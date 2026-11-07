import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_app import record, answers, insights
from cqa.analytics import build_analytics, topics, friction
from cqa.domain import default_checklist
from cqa.insights import validate_requests, request_outcome
from cqa.providers import call_model, EvaluationError, attempt_meta
from cqa.queue import Worker
from cqa.store import Store


SETTINGS={'provider':'gemini','model':'fixture','base_url':'https://generativelanguage.googleapis.com/v1beta/openai','reasoning_effort':'low'}


class Response:
    def __init__(self, result):self.result=result
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,*args):
        return json.dumps({'choices':[{'message':{'content':json.dumps(self.result)}}],
                           'usage':{'prompt_tokens':120,'completion_tokens':40}}).encode()


class EnrichmentTests(unittest.TestCase):
    def result(self):return {'conversation_id':record()['conversation_id'],'criteria':answers(),'insights':insights()}
    def call(self,result):
        with patch('urllib.request.urlopen',return_value=Response(result)):
            return call_model(record(),default_checklist(),SETTINGS,'unit-test-key')
    def test_bad_optional_summary_preserves_all_official_answers(self):
        r=self.result();r['insights']['summary']['evidence']=[None]
        a,meta,summary=self.call(r)
        self.assertEqual(len(a),8);self.assertIsNone(summary);self.assertEqual(meta['insights_status'],'error')
        self.assertEqual(meta['usage']['output_tokens'],40)
    def test_bad_core_criteria_rejected_with_usage_and_stage(self):
        r=self.result();r['criteria'][0]['evidence'][0]['quote']='invented quote'
        with self.assertRaises(EvaluationError) as ctx:self.call(r)
        self.assertEqual(ctx.exception.meta['failure_stage'],'criteria')
        self.assertEqual(ctx.exception.meta['usage']['input_tokens'],120)
        self.assertEqual(ctx.exception.meta['calls'],1)
    def test_malformed_core_shape_has_safe_validation_error(self):
        r=self.result();r['criteria'][0]=[]
        with self.assertRaises(EvaluationError):self.call(r)
    def test_question_status_requires_operator_evidence(self):
        raw=[{'request':'Тариф','status':'answered','request_evidence':[{'message_index':1}], 'answer_evidence':[{'message_index':2}]}]
        with self.assertRaises(ValueError):validate_requests(raw,record())  # bot is not operator
        raw[0]['answer_evidence']=[{'message_index':3}]
        self.assertEqual(request_outcome(validate_requests(raw,record())),'resolved')
        raw.append({'request':'Другой вопрос','status':'unanswered','request_evidence':[{'message_index':1}], 'answer_evidence':[]})
        self.assertEqual(request_outcome(validate_requests(raw,record())),'unresolved')
    def test_summary_question_conflict_is_visible_not_silently_changed(self):
        r=self.result();r['request_analysis']=[{'request':'Тариф','status':'unanswered','request_evidence':[{'message_index':1}], 'answer_evidence':[]}]
        _,meta,summary=self.call(r)
        self.assertTrue(meta['outcome_conflict']);self.assertEqual(summary['summary']['status'],'resolved')


class DiscoveryTests(unittest.TestCase):
    def test_topics_only_use_clients_multilingual_and_multilabel(self):
        r=record();r['transcript'][0]['text']='What is the fee to withdraw funds?'
        r['transcript'][2]['text']='Документы и налоги'
        ids={t['id'] for t in topics(r)}
        self.assertIn('fees',ids);self.assertIn('withdrawal',ids);self.assertNotIn('documents',ids)
        r['transcript'][0]['text']='Қосымша құпиясөзін ұмыттым'
        self.assertIn('access',{t['id'] for t in topics(r)})
    def test_repetition_during_bot_phase_is_not_operator_friction(self):
        r=record();r['transcript']=[{'speaker':'client','text':'Как получить полную выписку по моему счёту?'},
            {'speaker':'bot','text':'Ждите'},{'speaker':'client','text':'Как получить полную выписку по моему счёту?'}]
        self.assertEqual(friction(r),[])
        r['transcript'][1]['speaker']='operator'
        f=friction(r);self.assertEqual(f[0]['code'],'repeated_request');self.assertEqual(f[0]['evidence'][1]['message_index'],3)


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=Store(Path(self.temp.name)/'test.sqlite');self.s.import_records([record()])
    def tearDown(self):self.temp.cleanup()
    def save(self,values=None,model='fixture',prompt='test-v1',meta=None):
        return self.s.save_evaluation(record()['conversation_id'],self.s.config(),values or answers(),
                                     {'provider':'gemini','model':model,'prompt_version':prompt,'variant':'B',**(meta or {})},insights())
    def test_na_not_denominator_and_unprocessed_not_zero(self):
        r=record();r['conversation_id']='untested';self.s.import_records([r])
        a=answers();a[1]['value']='N/A';a[6]['value']='Нет';self.save(a)
        d=build_analytics(self.s)
        self.assertEqual(d['coverage']['evaluated'],1);self.assertEqual(d['coverage']['total'],2)
        fees=next(t for t in d['topics'] if t['id']=='fees')
        self.assertEqual(fees['cells'][1]['applicable'],0)
        self.assertEqual(fees['cells'][6]['failed'],1);self.assertEqual(fees['cells'][6]['applicable'],1)
    def test_appeal_overlay_does_not_change_ai_problem_map(self):
        a=answers();a[6]['value']='Нет';e=self.save(a)
        aid=self.s.appeal(e['id'],7,'Есть прощание');self.s.resolve(aid,'Да','Проверено человеком')
        d=build_analytics(self.s)
        self.assertEqual(d['rows'][0]['failed'][0]['id'],7)
    def test_stale_results_and_filters(self):
        self.save();config=self.s.config();config['criteria'][0]['description']='Изменённое правило';self.s.save_config(config)
        d=build_analytics(self.s);self.assertEqual(d['coverage']['evaluated'],0);self.assertEqual(d['coverage']['stale'],1)
        self.assertEqual(build_analytics(self.s,{'language':'EN'})['coverage']['total'],0)
    def test_paired_comparison_uses_same_ids_and_last_per_configuration(self):
        a=answers();self.save(model='first');a[6]['value']='Нет';self.save(a,model='second');self.save(a,model='second')
        d=build_analytics(self.s)['comparison'];self.assertEqual(len(d['paired']),1)
        self.assertEqual(d['paired'][0]['conversations'],1);self.assertEqual(d['paired'][0]['different'],1)
        self.assertEqual(d['paired'][0]['criteria'],8)
        self.assertEqual(d['groups'][0]['traced_attempts'],0);self.assertIsNone(d['groups'][0]['mean_seconds'])
    def test_journal_failed_usage_and_success_atomic_no_second_call_on_db_recovery(self):
        self.s.save_settings(SETTINGS);self.s.enqueue([record()['conversation_id']])
        worker=Worker(self.s,lambda s:'unit-test-key',threading.Lock(),start=False)
        meta={**attempt_meta(self.s.config(),SETTINGS),'elapsed_seconds':2,'usage':{'input_tokens':100,'output_tokens':20},'calls':1}
        with patch('cqa.queue.call_model',side_effect=EvaluationError('Ошибка критериев',meta)):
            worker.run_once()
        d=build_analytics(self.s)['comparison']['groups'][0]
        self.assertEqual(d['failed'],1);self.assertEqual(d['usage_known'],1);self.assertEqual(d['mean_seconds'],2)
        self.assertIsNone(d['known_cost_usd']);self.assertEqual(len(self.s.export()['evaluations']),0)
    def test_successful_trace_and_result_committed_together(self):
        self.s.save_settings(SETTINGS);self.s.enqueue([record()['conversation_id']])
        worker=Worker(self.s,lambda s:'unit-test-key',threading.Lock(),start=False)
        with patch('cqa.queue.call_model',return_value=(answers(),{'provider':'gemini','model':'fixture'},insights())):worker.run_once()
        r,e,a,_=self.s.analytics_snapshot()
        self.assertEqual(a[0]['status'],'completed');self.assertEqual(a[0]['evaluation_id'],e[0]['id'])
        self.assertEqual(e[0]['meta']['attempt_id'],a[0]['id'])
    def test_restart_marks_uncertain_trace_without_made_up_usage(self):
        self.s.start_attempt(record()['conversation_id'],attempt_meta(self.s.config(),SETTINGS))
        self.s.recover_jobs();d=build_analytics(self.s)['comparison']['groups'][0]
        self.assertEqual(d['interrupted'],1);self.assertEqual(d['usage_known'],0);self.assertIsNone(d['mean_seconds'])


if __name__=='__main__':unittest.main()
