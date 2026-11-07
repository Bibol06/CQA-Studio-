import copy
import json
import sqlite3
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from test_app import record,answers,insights
from cqa.domain import default_checklist
from cqa.insights import validate_insights
from cqa.store import Store
from cqa.queue import Worker

class InsightTests(unittest.TestCase):
    def test_id_only_citation_copies_exact_source(self):
        raw=insights();raw['summary']['evidence']=[{'message_index':4}]
        clean=validate_insights(raw,record(),default_checklist(),answers())
        self.assertEqual(clean['summary']['evidence'][0]['quote'],record()['transcript'][3]['text'])
    def test_integer_optional_reference_is_canonicalized_but_boolean_rejected(self):
        raw=insights();raw['summary']['evidence']=[4]
        clean=validate_insights(raw,record(),default_checklist(),answers())
        self.assertEqual(clean['summary']['evidence'][0]['message_index'],4)
        self.assertEqual(clean['summary']['evidence'][0]['quote'],record()['transcript'][3]['text'])
        raw['summary']['evidence']=[True]
        with self.assertRaises(ValueError):validate_insights(raw,record(),default_checklist(),answers())
    def test_valid_summary(self):
        clean=validate_insights(insights(),record(),default_checklist(),answers())
        self.assertEqual(clean['summary']['status'],'resolved')
    def test_cannot_recommend_for_successful_criterion(self):
        raw=insights();raw['recommendations']=[{'criterion_id':1,'issue':'x','action':'y','evidence':[{'message_index':3,'quote':'Здравствуйте'}]}]
        with self.assertRaises(ValueError):validate_insights(raw,record(),default_checklist(),answers())
    def test_every_failed_criterion_needs_advice(self):
        a=answers();a[6]['value']='Нет'
        with self.assertRaises(ValueError):validate_insights(insights(),record(),default_checklist(),a)
    def test_advice_is_tied_to_source(self):
        raw=insights();a=answers();a[6]['value']='Нет'
        raw['recommendations']=[{'criterion_id':7,'issue':'Нет корректного завершения','action':'Подвести итог и попрощаться.','evidence':[{'message_index':5,'quote':'До свидания!'}]}]
        self.assertEqual(validate_insights(raw,record(),default_checklist(),a)['recommendations'][0]['criterion_id'],7)
        raw['recommendations'][0]['evidence'][0]['quote']='Выдуманная цитата'
        with self.assertRaises(ValueError):validate_insights(raw,record(),default_checklist(),a)
    def test_summary_quote_must_exist(self):
        raw=insights();raw['summary']['evidence'][0]['message_index']=999
        with self.assertRaises(ValueError):validate_insights(raw,record(),default_checklist(),answers())
    def test_follow_up_distinct_from_resolved(self):
        raw=insights();raw['summary']['status']='follow_up'
        self.assertEqual(validate_insights(raw,record(),default_checklist(),answers())['summary']['status'],'follow_up')
    def test_unknown_outcome_status_rejected(self):
        raw=insights();raw['summary']['status']='perfect'
        with self.assertRaises(ValueError):validate_insights(raw,record(),default_checklist(),answers())

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=Store(Path(self.temp.name)/'test.sqlite');self.s.import_records([record()])
    def tearDown(self):self.temp.cleanup()
    def worker(self,key=''):
        # Deterministic single iteration, using the actual worker implementation and SQLite transactions.
        return Worker(self.s,lambda settings:key,threading.Lock(),start=False)
    def test_double_enqueue_does_not_duplicate_model_call(self):
        first=self.s.enqueue([record()['conversation_id']]);second=self.s.enqueue([record()['conversation_id']])
        self.assertEqual(len(first['created']),1);self.assertEqual(second['created'],[]);self.assertEqual(second['existing'],first['created'])
    def test_jobs_survive_new_store_instance(self):
        self.s.enqueue([record()['conversation_id']]);other=Store(self.s.path)
        self.assertEqual(other.jobs()['counts']['queued'],1)
    def test_paused_job_prevents_duplicate_and_can_be_cancelled(self):
        first=self.s.enqueue([record()['conversation_id']])['created']
        self.s.pause_pending('Квота')
        self.assertEqual(self.s.enqueue([record()['conversation_id']])['existing'],first)
        self.s.cancel_job(first[0]);self.s.resume_jobs()
        self.assertEqual(self.s.jobs()['counts'],{'cancelled':1})
    def test_checklist_snapshot_preserved(self):
        self.s.enqueue([record()['conversation_id']]);config=self.s.config();config['criteria'][0]['description']='Другое правило';self.s.save_config(config)
        self.assertEqual(self.s.candidates()[0]['payload']['checklist']['version'],1)
    def test_missing_key_waits_without_calling_model(self):
        self.s.save_settings({'provider':'gemini','model':'test-model','base_url':'https://generativelanguage.googleapis.com/v1beta/openai'})
        self.s.enqueue([record()['conversation_id']])
        with patch('cqa.queue.call_model') as call:
            self.assertFalse(self.worker().run_once());call.assert_not_called()
        job=self.s.jobs()['jobs'][0];self.assertEqual(job['status'],'waiting_key');self.assertEqual(job['attempts'],0)
    def test_completion_and_evaluation_committed_together(self):
        jid=self.s.enqueue([record()['conversation_id']])['created'][0];self.s.job_state(jid,'running')
        e=self.s.save_evaluation(record()['conversation_id'],self.s.config(),answers(),{'provider':'test'},insights(),jid)
        self.assertEqual(self.s.jobs()['jobs'][0]['evaluation_id'],e['id'])
        with self.assertRaises(ValueError):self.s.save_evaluation(record()['conversation_id'],self.s.config(),answers(),{'provider':'test'},insights(),jid)
        self.assertEqual(len(self.s.export()['evaluations']),1)
    def test_restart_does_not_automatically_repeat_uncertain_call(self):
        jid=self.s.enqueue([record()['conversation_id']])['created'][0];self.s.job_state(jid,'running');self.s.recover_jobs()
        self.assertEqual(self.s.jobs()['jobs'][0]['status'],'interrupted');self.assertEqual(self.s.candidates(),[])
        self.s.retry_job(jid);self.assertEqual(self.s.jobs()['jobs'][0]['status'],'queued')
    def test_running_call_cannot_be_cancelled(self):
        jid=self.s.enqueue([record()['conversation_id']])['created'][0];self.s.job_state(jid,'running')
        with self.assertRaises(ValueError):self.s.cancel_job(jid)
    def test_cancelled_job_not_run(self):
        jid=self.s.enqueue([record()['conversation_id']])['created'][0];self.s.cancel_job(jid)
        self.assertFalse(self.worker().run_once());self.assertEqual(self.s.export()['evaluations'],[])
    def test_worker_saves_rules_as_partial(self):
        self.s.enqueue([record()['conversation_id']]);self.assertTrue(self.worker().run_once())
        self.assertEqual(self.s.jobs()['counts']['completed'],1)
        self.assertIsNone(self.s.export()['evaluations'][0]['original_score']['total'])
    def test_model_failure_keeps_previous_result(self):
        self.s.save_evaluation(record()['conversation_id'],self.s.config(),answers(),{'provider':'test'})
        self.s.save_settings({'provider':'gemini','model':'test-model','base_url':'https://generativelanguage.googleapis.com/v1beta/openai'})
        self.s.enqueue([record()['conversation_id']])
        with patch('cqa.queue.call_model',side_effect=ValueError('Сбой ответа модели')):self.worker('unit-test-key').run_once()
        self.assertEqual(len(self.s.export()['evaluations']),1);self.assertEqual(self.s.jobs()['counts']['failed'],1)
    def test_rate_limit_pauses_remaining_jobs(self):
        second=record();second['conversation_id']='test-ru-002';self.s.import_records([second])
        self.s.save_settings({'provider':'gemini','model':'test-model','base_url':'https://generativelanguage.googleapis.com/v1beta/openai'})
        self.s.enqueue([record()['conversation_id'],second['conversation_id']])
        with patch('cqa.queue.call_model',side_effect=ValueError('Сервис модели вернул HTTP 429.')):self.worker('unit-test-key').run_once()
        self.assertEqual(self.s.jobs()['counts'],{'failed':1,'paused':1})
        self.s.resume_jobs();self.assertEqual(self.s.jobs()['counts']['queued'],1)
    def test_real_thread_can_complete_after_client_returns(self):
        self.s.enqueue([record()['conversation_id']]);worker=Worker(self.s,lambda s:'',threading.Lock())
        try:
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and not self.s.jobs()['counts'].get('completed'):time.sleep(.02)
            self.assertEqual(self.s.jobs()['counts']['completed'],1)
        finally:worker.close()

    def test_worker_survives_temporary_candidate_read_failure(self):
        self.s.enqueue([record()['conversation_id']])
        original=self.s.candidates; failures=[True]
        def temporarily_unavailable():
            if failures.pop() if failures else False:raise sqlite3.OperationalError('disk I/O error')
            return original()
        with patch.object(self.s,'candidates',side_effect=temporarily_unavailable):
            worker=Worker(self.s,lambda s:'',threading.Lock())
            try:
                deadline=time.monotonic()+1
                while time.monotonic()<deadline and worker.health()['state']!='storage_error':time.sleep(.01)
                self.assertTrue(worker.health()['alive'])
                self.assertEqual(worker.health()['state'],'storage_error')
                worker.wake.set()
                deadline=time.monotonic()+2
                while time.monotonic()<deadline and not self.s.jobs()['counts'].get('completed'):time.sleep(.02)
                self.assertEqual(self.s.jobs()['counts']['completed'],1)
                self.assertTrue(worker.health()['alive'])
            finally:worker.close()

    def model_job(self):
        self.s.save_settings({'provider':'gemini','model':'test-model','base_url':'https://generativelanguage.googleapis.com/v1beta/openai'})
        return self.s.enqueue([record()['conversation_id']])['created'][0]

    def test_save_recovery_keeps_response_without_second_model_call(self):
        self.model_job();worker=self.worker('unit-test-key')
        original=self.s.save_evaluation;failures=[True]
        def save_with_temporary_error(*args):
            if failures.pop() if failures else False:raise sqlite3.OperationalError('disk I/O error')
            return original(*args)
        with patch('cqa.queue.call_model',return_value=(answers(),{'provider':'gemini','model':'test-model'},insights())) as call,patch.object(self.s,'save_evaluation',side_effect=save_with_temporary_error):
            with self.assertRaises(sqlite3.Error):worker.run_once()
            self.assertIsNotNone(worker.pending)
            self.assertEqual(self.s.jobs()['counts'],{'running':1})
            self.assertTrue(worker.run_once())
            self.assertEqual(call.call_count,1)
        self.assertEqual(self.s.jobs()['counts'],{'completed':1})
        self.assertEqual(len(self.s.export()['evaluations']),1)

    def test_uncertain_commit_does_not_duplicate_saved_evaluation(self):
        self.model_job();worker=self.worker('unit-test-key');original=self.s.save_evaluation
        def save_then_report_error(*args):
            original(*args)
            raise sqlite3.OperationalError('disk I/O error after COMMIT')
        with patch('cqa.queue.call_model',return_value=(answers(),{'provider':'gemini','model':'test-model'},insights())) as call,patch.object(self.s,'save_evaluation',side_effect=save_then_report_error):
            with self.assertRaises(sqlite3.Error):worker.run_once()
            self.assertTrue(worker.run_once())
            self.assertEqual(call.call_count,1)
        self.assertEqual(len(self.s.export()['evaluations']),1)

    def test_claim_commit_error_never_sends_model_request(self):
        self.model_job();worker=self.worker('unit-test-key');original=self.s.job_state
        def claim_then_report_error(*args):
            original(*args)
            raise sqlite3.OperationalError('disk I/O error after claim')
        with patch('cqa.queue.call_model') as call,patch.object(self.s,'job_state',side_effect=claim_then_report_error):
            with self.assertRaises(sqlite3.Error):worker.run_once()
            self.assertTrue(worker.run_once());call.assert_not_called()
        self.assertEqual(self.s.jobs()['counts'],{'failed':1})

    def test_error_finalization_retries_database_without_model_retry(self):
        self.model_job();worker=self.worker('unit-test-key');original=self.s.finish_job_error;failures=[True]
        def fail_once(*args):
            if failures.pop() if failures else False:raise sqlite3.OperationalError('disk I/O error')
            return original(*args)
        with patch('cqa.queue.call_model',side_effect=ValueError('Сервис модели вернул HTTP 429.')) as call,patch.object(self.s,'finish_job_error',side_effect=fail_once):
            with self.assertRaises(sqlite3.Error):worker.run_once()
            self.assertTrue(worker.run_once())
            self.assertEqual(call.call_count,1)
        self.assertEqual(self.s.jobs()['counts'],{'failed':1})
