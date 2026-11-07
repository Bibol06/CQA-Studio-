import io
import math
import struct
import unittest
import wave
from cqa.media import clip_from_bytes
from cqa.acoustics import measure
from cqa.interaction import analyze


class SignalTests(unittest.TestCase):
    def test_tone_and_quiet_are_measured_not_guessed(self):
        out=io.BytesIO();rate=16000
        samples=[int(8000*math.sin(2*math.pi*200*i/rate)) if i<rate or i>=3*rate else 0 for i in range(4*rate)]
        with wave.open(out,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(struct.pack('<'+'h'*len(samples),*samples))
        result=measure(clip_from_bytes(out.getvalue()))
        if result['status']=='unavailable':self.skipTest('optional audio packages unavailable')
        self.assertEqual(result['quiet_segments'],[{'start_seconds':1.,'end_seconds':3.}])
        self.assertEqual(result['quiet_seconds'],2.)
        if result['pitch']['status']=='measured':self.assertAlmostEqual(result['pitch']['median_hz'],200,delta=3)
        self.assertNotIn('emotion',result)
    def test_mixed_ru_kz_cues_keep_source_evidence_and_ignore_bot(self):
        record={'transcript':[
            {'speaker':'bot','text':'Сізге жауап бермедім'},
            {'speaker':'client','text':'Я түсінбедім, маған жауап бермедіңіз.'},
            {'speaker':'operator','text':'Күте тұрыңыз, пожалуйста.'},
            {'speaker':'client','text':'Рақмет, спасибо.'}]}
        cues=analyze(record)['signals'];codes={s['code'] for s in cues}
        self.assertTrue({'reported_no_answer','clarification','announced_wait','thanks'}<=codes)
        self.assertFalse(any(e['message_index']==1 for s in cues for e in s['evidence']))
        for s in cues:
            for e in s['evidence']:self.assertEqual(e['quote'],record['transcript'][e['message_index']-1]['text'])
