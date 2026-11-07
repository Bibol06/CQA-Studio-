import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cqa.domain import default_checklist,score,validate_checklist,validate_result,parse_dataset
from cqa.engine import rules_review
from cqa.store import Store
from cqa.providers import call_model,safe_endpoint
from server import make_server

def record():
    return {'conversation_id':'test-ru-001','language':'RU','channel':'agent chat','audio_url':None,'transcript':[
        {'timestamp':'00:00','speaker':'client','text':'Где посмотреть тариф?'},
        {'timestamp':'00:01','speaker':'bot','text':'Здравствуйте, я AIM.'},
        {'timestamp':'00:10','speaker':'operator','text':'Здравствуйте, я Алина. Откройте Кабинет.'},
        {'timestamp':'00:20','speaker':'client','text':'Нашёл, спасибо.'},
        {'timestamp':'00:30','speaker':'operator','text':'Если будут вопросы, напишите. До свидания!'}]}

def answers():
    return [{'criterion_id':c['id'],'value':20 if c['id']==4 else 10 if c['id']==6 else 'Нет' if c['is_gross'] else 'Да',
             'reason':'Тестовый ответ','evidence':[{'message_index':3,'quote':'Здравствуйте'}],'needs_review':False}
            for c in default_checklist()['criteria']]

def insights():
    return {'summary':{'request':'Клиент спросил, где тариф.','actions':'Оператор объяснил, где посмотреть.','outcome':'Клиент сообщил об успехе.','status':'resolved','evidence':[{'message_index':4,'quote':'Нашёл, спасибо.'}]},'recommendations':[]}

class DomainTests(unittest.TestCase):
    def setUp(self): self.c=default_checklist()
    def test_default_valid(self): self.assertEqual(validate_checklist(self.c)['version'],1)
    def test_maximum_and_gross_independent(self):
        a=answers(); self.assertEqual(score(self.c,a)['total'],100)
        a[-1]['value']='Да'; self.assertEqual(score(self.c,a)['total'],100);self.assertTrue(score(self.c,a)['gross_error'])
    def test_na_redistribution_and_rounding(self):
        a=answers();a[1]['value']='N/A';a[2]['value']='N/A';a[6]['value']='Нет'
        self.assertEqual(score(self.c,a)['total'],92.31)
    def test_scale_is_weighted(self):
        a=answers();a[5]['value']=7;self.assertEqual(score(self.c,a)['total'],95.5)
    def test_partial_never_claims_full_score(self):
        a=answers();a[3]['value']=None;self.assertIsNone(score(self.c,a)['total'])
    def test_forbidden_na(self):
        a=answers();a[0]['value']='N/A'
        with self.assertRaises(ValueError):score(self.c,a)
    def test_rejects_boolean_in_scale(self):
        a=answers();a[3]['value']=False
        with self.assertRaises(ValueError):score(self.c,a)
    def test_invalid_scale(self):
        a=answers();a[5]['value']=9
        with self.assertRaises(ValueError):score(self.c,a)
    def test_custom_weight_scale(self):
        custom={'criteria':[{'id':31,'weight':70,'scale_max':4,'allowed_values':[0,2,4]}]}
        self.assertEqual(score(custom,[{'criterion_id':31,'value':2}])['total'],50)
    def test_zero_applicable_no_score(self):
        custom={'criteria':[{'id':31,'weight':10,'scale_max':None,'allowed_values':['N/A']}]}
        self.assertIsNone(score(custom,[{'criterion_id':31,'value':'N/A'}])['total'])
    def test_duplicate_criterion_rejected(self):
        self.c['criteria'][1]['id']=1
        with self.assertRaises(ValueError):validate_checklist(self.c)
    def test_evidence_exactness(self):
        r=record();a=answers();a[0]['evidence'][0]['quote']='Этой цитаты нет'
        with self.assertRaisesRegex(ValueError,'Цитата'):validate_result(self.c,r,{'conversation_id':r['conversation_id'],'criteria':a})
    def test_duplicate_model_answers_rejected(self):
        a=answers();a[1]['criterion_id']=1
        with self.assertRaises(ValueError):validate_result(self.c,record(),{'conversation_id':record()['conversation_id'],'criteria':a})
    def test_a_allows_missing_evidence_b_rejects(self):
        a=answers()
        for item in a:item['evidence']=[]
        result={'conversation_id':record()['conversation_id'],'criteria':a}
        self.assertEqual(len(validate_result(self.c,record(),result,require_evidence=False)),8)
        with self.assertRaises(ValueError):validate_result(self.c,record(),result,require_evidence=True)
    def test_out_of_bounds_evidence_rejected(self):
        a=answers();a[0]['evidence'][0]['message_index']=100
        with self.assertRaises(ValueError):validate_result(self.c,record(),{'conversation_id':record()['conversation_id'],'criteria':a})
    def test_bot_cannot_supply_operator_greeting(self):
        r=record();r['transcript'][2]['text']='Откройте Кабинет.'
        a=rules_review(r,self.c);self.assertEqual(a[0]['value'],'Нет')
    def test_changed_criterion_does_not_use_old_rule(self):
        self.c['criteria'][0]['description']='Проверить наличие благодарности клиенту.'
        self.assertIsNone(rules_review(record(),self.c)[0]['value'])
    def test_rules_leave_semantic_uncertainty_visible(self):
        a=rules_review(record(),self.c);self.assertIsNone(a[3]['value']);self.assertIsNone(score(self.c,a)['total'])
    def test_dataset_duplicate_id(self):
        with self.assertRaises(ValueError):parse_dataset([record(),record()])
    def test_endpoint_credentials_rejected(self):
        with self.assertRaises(ValueError):safe_endpoint('https://secret@example.com/v1','compatible')
    def test_endpoint_insecure_external_rejected(self):
        with self.assertRaises(ValueError):safe_endpoint('http://example.com/v1','compatible')

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=Store(Path(self.temp.name)/'app.sqlite');self.s.import_records([record()])
    def tearDown(self):self.temp.cleanup()
    def test_repeat_import_is_idempotent(self):
        self.s.import_records([record()]);self.assertEqual(len(self.s.overview()['records']),1)
    def test_changed_transcript_rejected(self):
        r=record();r['transcript'][0]['text']='Другой текст'
        with self.assertRaises(ValueError):self.s.import_records([r])
        self.assertEqual(self.s.record(r['conversation_id'])['transcript'][0]['text'],'Где посмотреть тариф?')
    def test_appeal_preserves_original_and_recalculates(self):
        e=self.s.save_evaluation(record()['conversation_id'],self.s.config(),answers(),{'provider':'test'})
        aid=self.s.appeal(e['id'],1,'Нет корректного представления')
        final=self.s.resolve(aid,'Нет','Проверен первый ответ')
        self.assertEqual(final['original_score']['total'],100);self.assertEqual(final['final_score']['total'],90)
        self.assertEqual(final['original_answers'][0]['value'],'Да');self.assertEqual(final['answers'][0]['value'],'Нет')
        with self.assertRaises(ValueError):self.s.resolve(aid,'Да','Повтор')
    def test_new_config_does_not_mutate_past_evaluation(self):
        e=self.s.save_evaluation(record()['conversation_id'],self.s.config(),answers(),{'provider':'test'})
        c=self.s.config();c['criteria'][0]['name']='Новый критерий';self.s.save_config(c)
        self.assertEqual(self.s.evaluation(e['id'])['checklist']['criteria'][0]['name'],'Установление контакта')
        self.assertTrue(self.s.overview()['records'][0]['stale'])
    def test_stale_config_save_rejected(self):
        c=self.s.config();self.s.save_config(c)
        with self.assertRaises(ValueError):self.s.save_config(c)
    def test_invalid_appeal_value_does_not_change_result(self):
        e=self.s.save_evaluation(record()['conversation_id'],self.s.config(),answers(),{'provider':'test'})
        aid=self.s.appeal(e['id'],1,'Проверить')
        with self.assertRaises(ValueError):self.s.resolve(aid,'N/A','Недопустимое значение')
        self.assertEqual(self.s.evaluation(e['id'])['final_score']['total'],100)

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.server=make_server(0,Path(cls.temp.name)/'http.sqlite')
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.temp.cleanup()
    def test_health_and_static(self):
        with urllib.request.urlopen(self.base+'/api/health') as r:self.assertTrue(json.load(r)['ok'])
        with urllib.request.urlopen(self.base) as r:
            self.assertIn('CQA Studio',r.read().decode());self.assertIn("script-src 'self'",r.headers['Content-Security-Policy'])
    def test_cross_origin_write_blocked(self):
        req=urllib.request.Request(self.base+'/api/evaluate/p1-ru-001',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://example.com'})
        with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code,403)
        ctx.exception.close()
    def test_unknown_api_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(self.base+'/api/missing')
        self.assertEqual(ctx.exception.code,404)
        ctx.exception.close()
    def test_local_rules_flow(self):
        req=urllib.request.Request(self.base+'/api/evaluate/p1-ru-022',data=b'{}',headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as r:e=json.load(r)
        self.assertEqual(e['meta']['calls'],0);self.assertIsNone(e['final_score']['total']);self.assertTrue(e['final_score']['gross_error'])
    def test_background_http_returns_before_model_and_deduplicates(self):
        self.server.store.import_records([record()])
        release=threading.Event();started=threading.Event()
        def slow_model(*args):
            started.set();release.wait(3)
            return answers(),{'provider':'test','model':'fixture'},insights()
        def post(path,body):
            req=urllib.request.Request(self.base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=2) as response:return response.status,json.load(response)
        settings={'provider':'gemini','model':'test-model','base_url':'https://generativelanguage.googleapis.com/v1beta/openai','api_key':'unit-test-key'}
        with patch('cqa.queue.call_model',side_effect=slow_model):
            try:
                post('/api/settings',settings)
                status,first=post('/api/jobs',{'conversation_ids':[record()['conversation_id']]})
                self.assertEqual(status,202);self.assertTrue(started.wait(1))
                _,second=post('/api/jobs',{'conversation_ids':[record()['conversation_id']]})
                self.assertEqual(second['existing'],first['created'])
                with urllib.request.urlopen(self.base+'/api/jobs') as r:
                    jobs=json.load(r);self.assertEqual(jobs['counts']['running'],1)
                    self.assertNotIn('unit-test-key',json.dumps(jobs))
                release.set();deadline=time.monotonic()+2
                while time.monotonic()<deadline and not self.server.store.jobs()['counts'].get('completed'):time.sleep(.02)
                self.assertEqual(self.server.store.jobs()['counts']['completed'],1)
                self.assertTrue(self.server.store.detail(record()['conversation_id'])['evaluation']['insights'])
            finally:
                release.set();post('/api/settings',{'provider':'rules','model':'','base_url':''})

class AdapterTests(unittest.TestCase):
    def test_openai_request_and_validation_without_network(self):
        r=record();data={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps({'conversation_id':r['conversation_id'],'criteria':answers(),'insights':insights()})}]}],'usage':{'input_tokens':100,'output_tokens':20}}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(data).encode()
        with patch('urllib.request.urlopen',return_value=Response()) as mock:
            result,meta,summary=call_model(r,default_checklist(),{'provider':'openai','model':'test-model','base_url':'https://api.openai.com/v1','input_price':1,'output_price':2},'test-not-a-real-key')
            sent=json.loads(mock.call_args.args[0].data)
            self.assertFalse(sent['store']);self.assertEqual(len(result),8);self.assertEqual(meta['usage']['input_tokens'],100)

if __name__=='__main__':unittest.main(verbosity=2)
