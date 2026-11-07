import copy
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from cqa.transcript import validate_edition,call_readable,source_hash,spoken_turns,save_editorial_edition
from cqa.store import Store
from cqa.audio_analysis import validate_audio
from test_audio import call_record,wav_clip,SETTINGS,audio_result


def fixture():
    r=call_record();r['transcript']=[
        {'speaker':'system','text':'Событие','timestamp':'source-time'},
        {'speaker':'operator','text':'Да компания федеброкер меня зовут [Имя скрыто].','timestamp':'original-time'},
        {'speaker':'client','text':'Купить 12 штук по 3,45.','timestamp':'unchanged-time'}]
    raw={'conversation_id':r['conversation_id'],'turns':[
        {'message_index':2,'text':'Да, компания «Фридом Брокер». Меня зовут [Имя скрыто].','uncertain':False},
        {'message_index':3,'text':'Купить 12 штук по 3,45.','uncertain':False}]}
    return r,raw


class TranscriptTests(unittest.TestCase):
    def test_mixed_ru_kz_turn_is_not_translated_or_transliterated(self):
        r,raw=fixture();text='Сәлеметсіз бе! Мен [Имя скрыто], как могу помочь?'
        raw['turns'][0]['text']=text
        self.assertEqual(validate_edition(raw,r,wav_clip())['turns'][0]['text'],text)
    def test_edition_does_not_mutate_original_roles_timestamps_or_text(self):
        r,raw=fixture();before=copy.deepcopy(r);result=validate_edition(raw,r,wav_clip())
        self.assertEqual(r,before);self.assertEqual(result['source_hash'],source_hash(r))
        self.assertEqual(result['changed_turns'],1);self.assertFalse(result['reviewed'])
        self.assertEqual([t['message_index'] for t in result['turns']],[2,3])
    def test_missing_duplicate_system_and_boolean_indices_are_rejected(self):
        for case in ['missing','duplicate','system','bool']:
            r,raw=fixture()
            if case=='missing':raw['turns'].pop()
            else:raw['turns'][0]['message_index']={'duplicate':3,'system':1,'bool':True}[case]
            with self.subTest(case=case),self.assertRaises(ValueError):validate_edition(raw,r,wav_clip())
    def test_hidden_names_and_numeric_facts_cannot_be_replaced(self):
        for index,text in [(0,'Меня зовут Иван.'),(1,'Купить 13 штук по 3,45.'),(1,'Купить 12 штук по 4,45.')]:
            r,raw=fixture();raw['turns'][index]['text']=text
            with self.subTest(text=text):
                result=validate_edition(raw,r,wav_clip())
                self.assertEqual(result['turns'][index]['text'],r['transcript'][index+1]['text'])
                self.assertEqual(result['validation']['status'],'partial')
                self.assertTrue(result['turns'][index]['warning'])
    def test_unintelligible_marker_is_visible_even_if_model_forgets_flag(self):
        r,raw=fixture();raw['turns'][0]['text']='[неразборчиво], меня зовут [Имя скрыто].'
        self.assertEqual(validate_edition(raw,r,wav_clip())['uncertain_turns'],1)
    def test_number_words_and_digits_are_equivalent_but_signs_and_codes_are_not(self):
        from cqa.transcript import number_signature
        self.assertEqual(number_signature('Нажмите один, затем 2.'),number_signature('Нажмите 1, затем два.'))
        self.assertEqual(number_signature('Екі / two'),number_signature('2 / 2'))
        self.assertNotEqual(number_signature('-5'),number_signature('5'))
        self.assertNotEqual(number_signature('0001'),number_signature('1'))
        self.assertNotEqual(number_signature('AB0001'),number_signature('AB0002'))
        self.assertEqual(number_signature('Он ответил'),number_signature('Ответил'))
    def test_native_editor_receives_audio_and_source_without_system_events(self):
        r,raw=fixture()
        envelope={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(raw)}]}}],
                  'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':50}}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(envelope).encode()
        with patch('cqa.transcript.urlopen',return_value=Response()) as request:
            edition,meta=call_readable(r,SETTINGS,'unit-test-key',wav_clip())
        wire=json.loads(request.call_args.args[0].data)
        source=json.loads(wire['contents'][0]['parts'][0]['text'])
        self.assertEqual(source['turns'],spoken_turns(r));self.assertEqual(len(source['turns']),2)
        self.assertIn('inlineData',wire['contents'][0]['parts'][1]);self.assertNotIn('unit-test-key',json.dumps(meta))
        self.assertEqual(edition['changed_turns'],1)
    def test_editorial_history_preserves_audio_reviews_and_original_source(self):
        r,raw=fixture();clip=wav_clip()
        with tempfile.TemporaryDirectory() as folder:
            s=Store(Path(folder)/'app.sqlite');s.import_records([r]);s.save_settings(SETTINGS)
            jid=s.enqueue([r['conversation_id']],kind='audio')['created'][0];s.job_state(jid,'running')
            result=validate_audio(audio_result(r),r,clip);previous=validate_edition(raw,r,clip)
            result['readable_transcript']=previous
            aid=s.save_audio_analysis(r['conversation_id'],result,{'kind':'audio','calls':2},jid)
            s.audio_review(aid,0,'confirmed')
            edited=save_editorial_edition(s,r['conversation_id'],{3:'Купить 12 штук. Цена — 3,45.'})
            saved=s.audio_history(r['conversation_id'])[0]
            self.assertEqual(s.record(r['conversation_id']),r)
            self.assertEqual(saved['result']['events'],result['events'])
            self.assertEqual(saved['result']['readable_transcript_history'],[previous])
            self.assertEqual(saved['event_reviews']['0']['verdict'],'confirmed')
            self.assertEqual(edited['editor'],'assistant');self.assertFalse(edited['reviewed'])


if __name__=='__main__':unittest.main()
