import tempfile
import threading
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from cqa.asr import VERSION,enhance,metrics,windows,run_pipeline
from cqa.queue import Worker
from cqa.store import Store
from cqa.providers import EvaluationError
from test_audio import call_record,SETTINGS,wav_clip


class AsrTests(unittest.TestCase):
    def test_empty_provider_response_is_not_saved_as_a_transcript(self):
        clip=wav_clip()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'candidates':[{'finishReason':'SAFETY'}]}).encode()
        local={'version':VERSION,'full_recording':True,'audio_sha256':clip.sha256}
        with patch('urllib.request.urlopen',return_value=Response()) as request:
            with self.assertRaises(EvaluationError) as caught:
                run_pipeline(call_record(),SETTINGS,'unit-test-key',type('Media',(),{'get':lambda self,cid:clip})(),local)
        self.assertIn('SAFETY',str(caught.exception));self.assertEqual(request.call_count,1)
        self.assertEqual(caught.exception.meta['responses'][0]['finish_reason'],'SAFETY')
        self.assertNotIn('unit-test-key',str(caught.exception.meta))
    def test_stationary_noise_is_reduced_on_known_synthetic_signal(self):
        import numpy as np
        t=np.arange(16000*8)/16000
        clean=.15*np.sin(2*np.pi*220*t)*((t>1)&(t<6))
        noisy=(clean+np.random.default_rng(4).normal(0,.025,len(t))).astype(np.float32)
        filtered=enhance(noisy)
        def snr(x):
            gain=np.dot(x,clean)/np.dot(clean,clean)
            return float(10*np.log10(np.mean((gain*clean)**2)/np.mean((x-gain*clean)**2)))
        self.assertGreater(snr(filtered)-snr(noisy),1.)
    def test_cloud_asr_is_blind_to_source_and_compares_same_codec(self):
        clip=wav_clip();record=call_record();record['transcript'][0]['text']='SENTINEL_SOURCE'
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'candidates':[{'content':{'parts':[{'text':json.dumps({'transcript':'Сәлеметсіз бе! Здравствуйте.','limitations':None})}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':5}}).encode()
        local={'version':VERSION,'full_recording':True,'audio_sha256':clip.sha256}
        with patch('urllib.request.urlopen',return_value=Response()) as request:
            result,meta=run_pipeline(record,SETTINGS,'unit-test-key',type('Media',(),{'get':lambda self,cid:clip})(),local)
        self.assertEqual(request.call_count,2);self.assertFalse(result['source_transcript_sent'])
        for call in request.call_args_list:
            self.assertNotIn('SENTINEL_SOURCE',call.args[0].data.decode())
            self.assertEqual(json.loads(call.args[0].data)['contents'][0]['parts'][0]['inlineData']['mimeType'],'audio/wav')
        self.assertEqual(meta['usage']['input_tokens'],20)
        self.assertNotIn('unit-test-key',json.dumps(result))
    def test_metrics_preserve_kazakh_and_count_real_errors(self):
        self.assertEqual(metrics('Мен жұмысқа бардым.','Мен жұмысқа бардым')['wer'],0)
        self.assertAlmostEqual(metrics('Мен бүгін жұмысқа бардым','Мен жұмысқа бардым')['wer'],.25)
        self.assertIsNone(metrics('','что-то')['wer'])
    def test_dsp_is_bounded_and_does_not_mutate_source(self):
        import numpy as np
        x=np.random.default_rng(0).normal(0,.03,16000*25).astype(np.float32);original=x.copy()
        y=enhance(x)
        self.assertEqual(len(x),len(y));self.assertTrue(np.array_equal(x,original))
        self.assertTrue(np.isfinite(y).all());self.assertLessEqual(float(np.max(np.abs(y))),.971)
        self.assertTrue(np.array_equal(enhance(np.zeros(8000,dtype=np.float32)),np.zeros(8000)))
    def test_chunk_windows_cover_audio_without_gaps_and_stay_below_30_seconds(self):
        import numpy as np
        x=np.zeros(16000*65,dtype=np.float32);spans=list(windows(x))
        self.assertEqual(spans[0][0],0);self.assertEqual(spans[-1][1],len(x))
        self.assertTrue(all(b-a<=29*16000 for a,b in spans))
        self.assertTrue(all(spans[i][1]==spans[i+1][0] for i in range(len(spans)-1)))
    def test_asr_queue_saves_separately_without_replacing_readable_or_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Store(Path(folder)/'app.sqlite');r=call_record();s.import_records([r]);s.save_settings(SETTINGS)
            jid=s.enqueue([r['conversation_id']],kind='asr')['created'][0]
            worker=Worker(s,lambda settings:'unit-test-key',threading.Lock(),start=False)
            with patch('cqa.asr.run_pipeline',return_value=({'cloud':{},'local':{}},{'kind':'asr','calls':2})) as call:
                worker.run_once();call.assert_called_once()
            d=s.detail(r['conversation_id']);self.assertTrue(d['asr_analysis']);self.assertIsNone(d['audio_analysis']);self.assertIsNone(d['evaluation'])
            self.assertEqual(s.record(r['conversation_id']),r)
            self.assertEqual(s.jobs()['jobs'][0]['status'],'completed')
