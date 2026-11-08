import copy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import wave

from test_app import record, answers
from cqa.audio_analysis import EVENT_LABELS, validate_audio, call_audio, audio_attempt_meta
from cqa.media import AudioMedia, clip_from_bytes, byte_range, checked_url, AudioSource
from cqa.queue import Worker
from cqa.store import Store
from cqa.submission import build
from server import make_server

SETTINGS={'provider':'gemini','model':'fixture-audio-model','base_url':'https://generativelanguage.googleapis.com/v1beta/openai','input_price':1,'output_price':2}
WRAPPER='https://ec88f21f1accecf38e20095a9fe175.a5.environment.api.powerplatform.com/test'
SOURCE='https://freedomholdingcorporation.crm11.dynamics.com/test.mp3'


def call_record():
    r=record();r.update(conversation_id='test-call-001',channel='voice call',audio_url=WRAPPER)
    return r


def wav_clip():
    out=io.BytesIO()
    with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\x00\x00'*80000)
    return clip_from_bytes(out.getvalue())


def audio_result(r=None):
    r=r or call_record()
    return {'conversation_id':r['conversation_id'],'overview':'Речь в основном ровная, есть отдельный короткий звук.',
            'quality':{'audibility':'clear','limitations':['Один общий аудиоканал.']},
            'delivery':[{'speaker':'unknown','pace':'steady','intonation':'even','description':'Ровная мелодика речи.','start_seconds':0,'end_seconds':5}],
            'checks':[{'type':k,'status':'detected' if k=='cough' else 'not_detected','comment':'Кандидат для проверки.' if k=='cough' else 'Не замечено при прослушивании.'} for k in EVENT_LABELS],
            'events':[{'type':'cough','speaker':'unknown','start_seconds':2,'end_seconds':3,'description':'Короткий звук, похожий на кашель.','confidence':'medium'}]}


class MediaTests(unittest.TestCase):
    def test_mp3_frames_duration_without_codec(self):
        data=(bytes.fromhex('fff388c4')+bytes(284))*30
        c=clip_from_bytes(data)
        self.assertAlmostEqual(c.duration_seconds,1.08);self.assertEqual(c.sample_rate,16000);self.assertEqual(c.channels,1)
    def test_bad_audio_not_accepted_by_content_type_alone(self):
        with self.assertRaises(ValueError):clip_from_bytes(b'<html>not audio</html>')
    def test_private_untrusted_and_credentialed_urls_rejected(self):
        for url in ['https://127.0.0.1/x','http://'+SOURCE[8:],'https://example.org/audio.mp3','https://user:password@freedomholdingcorporation.crm11.dynamics.com/x']:
            with self.subTest(url=url),self.assertRaises(ValueError):checked_url(url)
    def test_wrapper_resolution_and_memory_cache(self):
        c=wav_clip();fetch=unittest.mock.Mock(side_effect=[('text/html',f'<audio controls src="{SOURCE}"></audio>'.encode()),('audio/wav',c.data)])
        media=AudioMedia(lambda cid:call_record(),fetch)
        self.assertEqual(media.get('test-call-001').sha256,c.sha256)
        self.assertEqual(media.get('test-call-001').sha256,c.sha256);self.assertEqual(fetch.call_count,2)
    def test_wrapper_script_is_not_a_media_source(self):
        parser=AudioSource();parser.feed('<script src="https://evil.invalid/test"></script>')
        self.assertEqual(parser.sources,[])
    def test_chat_cannot_be_fetched_as_audio(self):
        with self.assertRaises(ValueError):AudioMedia(lambda cid:record()).get('test')
    def test_ranges_include_suffix_and_reject_invalid_bounds(self):
        self.assertEqual(byte_range(None,100),(0,99,200));self.assertEqual(byte_range('bytes=5-9',100),(5,9,206))
        self.assertEqual(byte_range('bytes=-10',100),(90,99,206));self.assertEqual(byte_range('bytes=90-500',100),(90,99,206))
        for v in ['bytes=100-','bytes=9-5','bytes=0-1,4-5','bytes=-0','bytes=-']:
            with self.subTest(value=v),self.assertRaises(ValueError):byte_range(v,100)


class AudioValidationTests(unittest.TestCase):
    def test_valid_observations_keep_audio_identity_and_review_requirement(self):
        c=wav_clip();r=validate_audio(audio_result(),call_record(),c)
        self.assertTrue(r['requires_review']);self.assertEqual(r['audio']['sha256'],c.sha256)
        self.assertEqual(r['events'][0]['speaker'],'unknown')
        raw=audio_result();raw['delivery'][0]['speaker']='bot'
        self.assertEqual(validate_audio(raw,call_record(),c)['delivery'][0]['speaker'],'bot')
    def test_invalid_timing_is_excluded_and_explicitly_marks_partial_result(self):
        for start,end in [(9,11),(True,3),(-1,3),(3,2),(None,3)]:
            r=audio_result();r['events'][0].update(start_seconds=start,end_seconds=end)
            with self.subTest(start=start,end=end):
                result=validate_audio(r,call_record(),wav_clip())
                self.assertEqual(result['events'],[])
                self.assertEqual(result['validation']['status'],'partial')
                self.assertEqual(result['validation']['discarded_events'],1)
                self.assertTrue(next(c for c in result['checks'] if c['type']=='cough')['timing_warning'])
    def test_point_events_and_standard_timestamp_formats_are_supported(self):
        r=audio_result();r['events'][0].update(start_seconds='00:02.5',end_seconds='2.5')
        result=validate_audio(r,call_record(),wav_clip())
        self.assertEqual(result['events'][0]['start_seconds'],2.5)
        self.assertEqual(result['events'][0]['end_seconds'],2.5)
        self.assertEqual(result['validation']['status'],'complete')
    def test_invalid_delivery_does_not_discard_valid_events(self):
        r=audio_result();r['delivery'][0]['end_seconds']=99
        result=validate_audio(r,call_record(),wav_clip())
        self.assertEqual(len(result['events']),1);self.assertEqual(result['delivery'],[])
        self.assertEqual(result['validation']['discarded_delivery'],1)
    def test_optional_negative_category_comment_can_be_empty(self):
        r=audio_result()
        for check in r['checks']:
            if check['status']=='not_detected':check.pop('comment',None)
        result=validate_audio(r,call_record(),wav_clip())
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['validation']['status'],'complete')
        self.assertEqual(next(c for c in result['checks'] if c['type']=='laugh')['comment'],'')
    def test_medical_conclusions_rejected(self):
        r=audio_result();r['events'][0]['description']='Это патологическое заикание.'
        with self.assertRaises(ValueError):validate_audio(r,call_record(),wav_clip())
    def test_contradictions_stay_visible_without_rewriting_the_model(self):
        for status,events in [('detected',[]),('not_detected',audio_result()['events'])]:
            r=audio_result();r['events']=events;r['checks'][0]['status']=status
            with self.subTest(status=status):
                result=validate_audio(r,call_record(),wav_clip())
                self.assertEqual(result['validation']['status'],'partial')
                self.assertEqual(result['validation']['contradictory_checks'],1)
                self.assertEqual(result['checks'][0]['status'],status)
                self.assertTrue(result['checks'][0]['consistency_warning'])
                self.assertEqual(result['events'],events)
    def test_unknown_categories_roles_and_wrong_shapes_rejected(self):
        for alteration in ['unknown_type','bad_role','bad_shape']:
            r=audio_result()
            if alteration=='unknown_type':r['events'][0]['type']='disease'
            if alteration=='bad_role':r['events'][0]['speaker']='named-person'
            if alteration=='bad_shape':r['events'][0]['type']=[]
            with self.subTest(case=alteration),self.assertRaises(ValueError):validate_audio(r,call_record(),wav_clip())
    def test_native_request_contains_audio_bytes_not_transcript(self):
        c=wav_clip();r=call_record();r['transcript'][0]['text']='SENTINEL_TRANSCRIPT_DO_NOT_SEND'
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(audio_result())}]}}],
                  'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':30}}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(response).encode()
        media=unittest.mock.Mock();media.get.return_value=c
        with patch('cqa.audio_analysis.urlopen',return_value=Response()) as request,patch('cqa.transcript.call_readable',return_value=({'turns':[]},{'calls':1,'usage':{'input_tokens':40,'output_tokens':20}})):
            result,meta=call_audio(r,SETTINGS,'unit-test-key',media)
        wire=request.call_args.args[0];payload=json.loads(wire.data)
        self.assertIn(':generateContent',wire.full_url)
        self.assertEqual(payload['contents'][0]['parts'][1]['inlineData']['mimeType'],'audio/wav')
        self.assertNotIn('SENTINEL_TRANSCRIPT_DO_NOT_SEND',wire.data.decode())
        self.assertNotIn('unit-test-key',json.dumps(meta));self.assertIsNone(meta['cost_usd'])
        self.assertEqual(meta['kind'],'audio');self.assertEqual(len(result['checks']),len(EVENT_LABELS))
        self.assertEqual(meta['calls'],2);self.assertEqual(meta['usage']['input_tokens'],140)
    def test_editor_failure_keeps_audio_observations(self):
        c=wav_clip();r=call_record()
        response={'candidates':[{'content':{'parts':[{'text':json.dumps(audio_result())}]}}]}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(response).encode()
        from cqa.providers import EvaluationError
        with patch('cqa.audio_analysis.urlopen',return_value=Response()),patch('cqa.transcript.call_readable',side_effect=EvaluationError('Редакция не прошла проверку',{'calls':1,'usage':{}})):
            result,meta=call_audio(r,SETTINGS,'unit-test-key',unittest.mock.Mock(get=lambda cid:c))
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['readable_transcript_error'],'Редакция не прошла проверку')
        self.assertEqual(meta['calls'],2)


class AudioStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=Store(Path(self.temp.name)/'app.sqlite');self.s.import_records([call_record()]);self.s.save_settings(SETTINGS)
    def tearDown(self):self.temp.cleanup()
    def run_audio(self):
        jid=self.s.enqueue([call_record()['conversation_id']],kind='audio')['created'][0]
        worker=Worker(self.s,lambda s:'unit-test-key',threading.Lock(),start=False)
        result=validate_audio(audio_result(),call_record(),wav_clip())
        with patch('cqa.queue.call_audio',return_value=(result,audio_attempt_meta(SETTINGS))) as call:
            worker.run_once();self.assertEqual(call.call_count,1)
        return jid
    def test_audio_does_not_overwrite_core_score_and_dedup_is_per_kind(self):
        e=self.s.save_evaluation(call_record()['conversation_id'],self.s.config(),answers(),{'provider':'gemini','model':'fixture'})
        text=self.s.enqueue([call_record()['conversation_id']])
        audio=self.s.enqueue([call_record()['conversation_id']],kind='audio')
        self.assertTrue(text['created']);self.assertTrue(audio['created'])
        self.assertEqual(self.s.enqueue([call_record()['conversation_id']],kind='audio')['existing'],audio['created'])
        self.assertEqual(self.s.evaluation(e['id'])['original_score']['total'],100)
    def test_audio_completion_and_review_history_are_separate(self):
        jid=self.run_audio();detail=self.s.detail(call_record()['conversation_id']);a=detail['audio_analysis']
        self.assertIsNone(detail['evaluation']);self.assertTrue(a)
        job=next(j for j in self.s.jobs()['jobs'] if j['id']==jid)
        self.assertIsNone(job['evaluation_id']);self.assertEqual(job['audio_analysis_id'],a['id'])
        self.s.audio_review(a['id'],0,'confirmed');self.s.audio_review(a['id'],0,'rejected','Повторно прослушано')
        final=self.s.audio_history(call_record()['conversation_id'])[0]
        self.assertEqual(len(final['reviews']),2);self.assertEqual(final['event_reviews']['0']['verdict'],'rejected')
        self.assertEqual(final['result'],a['result'])
    def test_audio_storage_recovery_does_not_repeat_model(self):
        self.s.enqueue([call_record()['conversation_id']],kind='audio');worker=Worker(self.s,lambda s:'unit-test-key',threading.Lock(),start=False)
        result=validate_audio(audio_result(),call_record(),wav_clip());original=self.s.save_audio_analysis;fail=[True]
        def save_once(*args):
            if fail.pop() if fail else False:raise sqlite3.OperationalError('disk I/O error')
            return original(*args)
        with patch('cqa.queue.call_audio',return_value=(result,audio_attempt_meta(SETTINGS))) as call,patch.object(self.s,'save_audio_analysis',side_effect=save_once):
            with self.assertRaises(sqlite3.Error):worker.run_once()
            worker.run_once();self.assertEqual(call.call_count,1)
        self.assertEqual(len(self.s.audio_history()),1)
    def test_bad_review_reference_rejected(self):
        self.run_audio();aid=self.s.audio_history()[0]['id']
        for index in [99,True,-1]:
            with self.assertRaises(ValueError):self.s.audio_review(aid,index,'confirmed')
    def test_development_reload_failure_leaves_job_unstarted(self):
        jid=self.s.enqueue([call_record()['conversation_id']],kind='audio')['created'][0]
        worker=Worker(self.s,lambda s:'unit-test-key',threading.Lock(),start=False,reload_audio=True)
        with patch('cqa.queue.importlib.reload',side_effect=SyntaxError('unfinished edit')),patch('cqa.queue.call_audio') as call:
            with self.assertRaises(SyntaxError):worker.run_once()
            call.assert_not_called()
        job=next(j for j in self.s.jobs()['jobs'] if j['id']==jid)
        self.assertEqual(job['status'],'queued');self.assertEqual(job['attempts'],0)
    def test_official_export_ignores_pending_and_completed_audio(self):
        rows=[]
        for i in range(65):
            r=record();r['conversation_id']=f'dev-{i}'
            if i>=60:r.update(channel='voice call',audio_url=WRAPPER)
            rows.append(r)
        other=Store(Path(self.temp.name)/'official.sqlite');other.import_records({'data':{'dataset_group_id':'DEV','records':rows}})
        other.save_settings(SETTINGS);other.save_evaluation('dev-0',other.config(),answers(),{'provider':'gemini','model':'text-fixture'})
        before,_=build(other,'dev','DEV','Fantastic Four')
        jid=other.enqueue(['dev-60'],kind='audio')['created'][0]
        pending,_=build(other,'dev','DEV','Fantastic Four');self.assertEqual(before,pending)
        other.job_state(jid,'running')
        other.save_audio_analysis('dev-60',validate_audio(audio_result(rows[60]),rows[60],wav_clip()),audio_attempt_meta(SETTINGS),jid)
        after,_=build(other,'dev','DEV','Fantastic Four');self.assertEqual(before,after)
        asr_job=other.enqueue(['dev-60'],kind='asr')['created'][0]
        pending_asr,_=build(other,'dev','DEV','Fantastic Four');self.assertEqual(before,pending_asr)
        other.job_state(asr_job,'running');other.save_asr_result('dev-60',{'test':True},{'kind':'asr'},asr_job)
        completed_asr,_=build(other,'dev','DEV','Fantastic Four');self.assertEqual(before,completed_asr)


class AudioHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.server=make_server(0,Path(cls.temp.name)/'http.sqlite');cls.server.store.import_records([call_record()])
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.base=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.temp.cleanup()
    def test_actual_range_and_head_protocol(self):
        clip=wav_clip()
        with patch.object(self.server.media,'get',return_value=clip):
            with urlopen(Request(self.base+'/api/audio/test-call-001',headers={'Range':'bytes=4-12'})) as r:
                self.assertEqual(r.status,206);self.assertEqual(r.read(),clip.data[4:13]);self.assertEqual(r.headers['Content-Type'],'audio/wav')
                self.assertTrue(r.headers['Content-Range'].startswith('bytes 4-12/'))
            with urlopen(Request(self.base+'/api/audio/test-call-001',method='HEAD')) as r:self.assertEqual(int(r.headers['Content-Length']),len(clip.data));self.assertEqual(r.read(),b'')
            with self.assertRaises(HTTPError) as ctx:urlopen(Request(self.base+'/api/audio/test-call-001',headers={'Range':'bytes=9999999-'}))
            self.assertEqual(ctx.exception.code,416);ctx.exception.close()


if __name__=='__main__':unittest.main()
