import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

from test_app import record, answers
from cqa.store import Store
from cqa.submission import build, validate, numeric_score, write_document
from server import make_server
from submission import reject_constant, unique_fields


def import_group(store, group='CONTROL', kind='prod'):
    records = []
    for i in range(65 if kind == 'dev' else 10):
        row = record()
        row['conversation_id'] = f'{group.lower()}-{i+1:03}'
        if kind == 'dev' and i >= 60:
            row['channel'] = 'voice call'
        records.append(row)
    store.import_records({'data': {'dataset_group_id': group, 'records': records}})
    return records


def save_ai(store, cid, provider='gemini', model='test-model', custom_answers=None):
    return store.save_evaluation(cid, store.config(), custom_answers or answers(), {'provider': provider, 'model': model})


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'app.sqlite')
        self.records = import_group(self.store)
        self.cid = self.records[0]['conversation_id']
        self.evaluation = save_ai(self.store, self.cid)

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        return build(self.store, 'prod', 'CONTROL', 'Fantastic Four')

    def test_all_source_ids_including_unprocessed_are_preserved(self):
        document, report = self.build()
        self.assertEqual({r['conversation_id'] for r in document['results']}, {r['conversation_id'] for r in self.records})
        self.assertEqual(report['ok'], 1)
        self.assertEqual(len(report['errors']), 9)
        self.assertEqual(document['results'][1]['criteria'], [])
        self.assertIsNone(document['results'][1]['score'])

    def test_actual_json_boolean_types_and_stable_codes(self):
        document, _ = self.build()
        criteria = document['results'][0]['criteria']
        self.assertIs(criteria[0]['value'], True)
        self.assertIs(criteria[-1]['value'], False)
        self.assertEqual(criteria[3]['value'], 20)
        self.assertEqual(document['model'], {'mode': 'external_api', 'name': 'test-model'})

    def test_pdf_example_recalculates_85_38(self):
        a = answers()
        a[1]['value'] = a[2]['value'] = 'N/A'
        a[3]['value'] = 15
        a[5]['value'] = 7
        save_ai(self.store, self.cid, custom_answers=a)
        document, _ = self.build()
        result = document['results'][0]
        self.assertIsNone(result['criteria'][1]['value'])
        self.assertEqual(result['score']['final_score'], 85.38)

    def test_critical_flag_does_not_zero_score(self):
        a = answers(); a[-1]['value'] = 'Да'
        save_ai(self.store, self.cid, custom_answers=a)
        result = self.build()[0]['results'][0]
        self.assertEqual(result['score'], {'final_score': 100.0, 'critical_flag': True})

    def test_range_keeps_original_bot_client_and_operator_numbering(self):
        a = answers()
        a[0]['evidence'] = [{'message_index': 1, 'end_message_index': 3, 'quote': self.records[0]['transcript'][0]['text']}]
        save_ai(self.store, self.cid, custom_answers=a)
        self.assertEqual(self.build()[0]['results'][0]['criteria'][0]['evidence_turns'], [1, 2, 3])

    def test_appeal_does_not_change_jury_ai_answer(self):
        aid = self.store.appeal(self.evaluation['id'], 1, 'Пересмотреть')
        self.store.resolve(aid, 'Нет', 'Ручное решение')
        self.assertEqual(self.store.evaluation(self.evaluation['id'])['final_score']['total'], 90)
        result = self.build()[0]['results'][0]
        self.assertIs(result['criteria'][0]['value'], True)
        self.assertEqual(result['score']['final_score'], 100)

    def test_partial_rules_result_is_error_not_na(self):
        a = answers(); a[3]['value'] = None
        self.store.save_evaluation(self.cid, self.store.config(), a, {'provider': 'rules'})
        # A recorded cloud attempt supplies truthful model provenance for this all-error snapshot.
        self.store.save_settings({'provider': 'gemini', 'model': 'attempted-model', 'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai'})
        jid = self.store.enqueue([self.cid])['created'][0]
        self.store.job_state(jid, 'running'); self.store.job_state(jid, 'failed', 'Квота')
        result = self.build()[0]['results'][0]
        self.assertEqual(result['status'], 'error')
        self.assertIsNone(result['score'])

    def test_stale_result_is_explicit_error(self):
        config = self.store.config(); config['criteria'][0]['description'] += ' Уточнение.'
        self.store.save_config(config)
        self.assertEqual(self.build()[0]['results'][0]['status'], 'error')

    def test_different_checklist_not_silently_mapped(self):
        config = self.store.config(); config['criteria'][0]['weight'] = 11
        self.store.save_config(config)
        with self.assertRaisesRegex(ValueError, 'Веса'):
            self.build()

    def test_active_jobs_block_outdated_snapshot(self):
        self.store.enqueue([self.cid])
        with self.assertRaisesRegex(ValueError, 'незавершённые'):
            self.build()

    def test_dev_cannot_be_relabeled_as_prod(self):
        import_group(self.store, 'DEV', 'dev')
        with self.assertRaisesRegex(ValueError, 'DEV нельзя'):
            build(self.store, 'prod', 'DEV', 'Fantastic Four')

    def test_dev_requires_all_65_and_channel_split(self):
        records = import_group(self.store, 'DEV', 'dev')
        save_ai(self.store, records[0]['conversation_id'])
        document, report = build(self.store, 'dev', 'DEV', 'Fantastic Four')
        self.assertEqual(report['total'], 65)
        with self.assertRaises(ValueError):
            validate(document, records[:-1], 'dev')
        wrong = copy.deepcopy(records); wrong[-1]['channel'] = 'agent chat'
        with self.assertRaises(ValueError):
            validate(document, wrong, 'dev')

    def test_mixed_actual_models_are_reported_as_hybrid(self):
        save_ai(self.store, self.records[1]['conversation_id'], provider='ollama', model='local-model')
        model = self.build()[0]['model']
        self.assertEqual(model['mode'], 'hybrid')
        self.assertIn('local-model', model['name'])
        self.assertIn('test-model', model['name'])

    def test_missing_team_name_rejected(self):
        with self.assertRaises(ValueError):
            build(self.store, 'prod', 'CONTROL', '')

    def test_json_reader_rejects_duplicate_fields(self):
        with self.assertRaisesRegex(ValueError, 'Повторяющееся'):
            json.loads('{"status":"ok","status":"error"}', object_pairs_hook=unique_fields)

    def test_json_reader_rejects_nonfinite_numbers(self):
        for literal in ('NaN', 'Infinity', '-Infinity'):
            with self.assertRaises(ValueError):
                json.loads('{"value":' + literal + '}', parse_constant=reject_constant)

    def test_unknown_duplicate_or_missing_ids_rejected(self):
        document, _ = self.build()
        for mutation in ('unknown', 'duplicate', 'missing'):
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(document)
                if mutation == 'unknown': bad['results'][0]['conversation_id'] = 'other'
                if mutation == 'duplicate': bad['results'][1]['conversation_id'] = self.cid
                if mutation == 'missing': bad['results'].pop()
                with self.assertRaises(ValueError): validate(bad, self.records, 'prod')

    def test_disallowed_values_and_python_boolean_number_trap_rejected(self):
        document, _ = self.build()
        for index, value in [(0, 1), (0, None), (3, True), (3, 7), (5, None), (5, 15), (4, 'Да')]:
            with self.subTest(index=index, value=value):
                bad = copy.deepcopy(document); bad['results'][0]['criteria'][index]['value'] = value
                with self.assertRaises(ValueError): validate(bad, self.records, 'prod')

    def test_wrong_score_flag_and_turn_bounds_rejected(self):
        document, _ = self.build()
        mutations = [('score', 'final_score', 99), ('score', 'critical_flag', True), ('criteria', 'evidence_turns', [0]), ('criteria', 'evidence_turns', [999]), ('criteria', 'evidence_turns', [True])]
        for target, key, value in mutations:
            with self.subTest(key=key, value=value):
                bad = copy.deepcopy(document)
                item = bad['results'][0][target]
                if target == 'criteria': item = item[0]
                item[key] = value
                with self.assertRaises(ValueError): validate(bad, self.records, 'prod')

    def test_missing_duplicate_criterion_and_extra_secret_field_rejected(self):
        document, _ = self.build()
        for mutation in ('missing', 'duplicate', 'secret'):
            bad = copy.deepcopy(document)
            if mutation == 'missing': bad['results'][0]['criteria'].pop()
            if mutation == 'duplicate': bad['results'][0]['criteria'][1]['criterion_id'] = 'contact'
            if mutation == 'secret': bad['api_key'] = 'unit-test-placeholder'
            with self.assertRaises(ValueError): validate(bad, self.records, 'prod')

    def test_atomic_utf8_file_and_previous_version_backup(self):
        document, _ = self.build()
        target = Path(self.temp.name) / 'results/prod/results.json'
        backups = Path(self.temp.name) / 'backups'
        write_document(document, self.records, 'prod', target, backups)
        original = target.read_bytes()
        self.assertFalse(original.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(json.loads(original.decode('utf-8')), document)
        bad = copy.deepcopy(document); bad['results'].pop()
        with self.assertRaises(ValueError): write_document(bad, self.records, 'prod', target, backups)
        self.assertEqual(target.read_bytes(), original)
        write_document(document, self.records, 'prod', target, backups)
        self.assertEqual(len(list(backups.glob('*.json'))), 1)


class SubmissionHttpTests(unittest.TestCase):
    def test_preview_and_export_use_exact_group_and_fixed_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); store = Store(root / 'test.sqlite')
            records = import_group(store)
            save_ai(store, records[0]['conversation_id'])
            with patch('server.ROOT', root):
                server = make_server(0, store.path)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                try:
                    body = {'set': 'prod', 'group': 'CONTROL', 'team_name': 'Fantastic Four'}
                    def post(action):
                        request = urllib.request.Request(base + '/api/submission/' + action, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
                        with urllib.request.urlopen(request) as response: return json.load(response)
                    preview = post('preview')
                    self.assertEqual(preview['report']['total'], 10)
                    self.assertFalse((root / 'results/prod/results.json').exists())
                    response = post('export')
                    self.assertEqual(Path(response['path']), root / 'results/prod/results.json')
                    saved = json.loads((root / 'results/prod/results.json').read_text(encoding='utf-8'))
                    validate(saved, records, 'prod')
                    self.assertEqual(store.submission_team(), 'Fantastic Four')
                finally:
                    server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
