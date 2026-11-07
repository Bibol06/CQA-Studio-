"""CQA Results JSON 1.0: source-aware export and independent file validation."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

from .domain import default_checklist, validate_result

CODES = ('contact', 'discovery', 'identification', 'consultation', 'empathy', 'dialogue', 'closure', 'critical')
WEIGHTS = (10, 15, 20, 20, 15, 15, 5, 0)
NULLABLE = {'discovery', 'identification', 'consultation', 'closure'}
SCALES = {'consultation': (0, 5, 10, 15, 20), 'dialogue': (0, 4, 7, 10)}
ACTIVE = {'queued', 'running', 'waiting_key', 'paused'}
PROVIDERS = {'openai', 'gemini', 'compatible', 'ollama'}


def dataset_check(records, kind):
    if kind not in ('dev', 'prod'):
        raise ValueError('Набор должен быть dev или prod')
    expected = 65 if kind == 'dev' else 10
    if len(records) != expected:
        raise ValueError(f'Для {kind.upper()} нужно ровно {expected} диалогов; в выбранной группе {len(records)}')
    ids = [r['conversation_id'] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError('Повторяющиеся ID исходных диалогов')
    chats = sum(r['channel'] == 'agent chat' for r in records)
    calls = sum(r['channel'] == 'voice call' for r in records)
    if (kind == 'dev' and (chats, calls) != (60, 5)) or (kind == 'prod' and (chats, calls) != (10, 0)):
        raise ValueError('DEV должен содержать 60 чатов и 5 звонков; контроль — 10 чатов')


def canonical_check(config):
    """Do not silently squeeze a different checklist into the fixed eight-code schema."""
    reference = default_checklist()['criteria']
    criteria = config.get('criteria', [])
    if len(criteria) != 8 or {c['id'] for c in criteria} != set(range(1, 9)):
        raise ValueError('Формат 1.0 требует официальные 8 критериев с исходными ID 1–8')
    for expected in reference:
        actual = next(c for c in criteria if c['id'] == expected['id'])
        if any(actual.get(k) != expected.get(k) for k in ('weight', 'scale_max', 'is_gross')) or set(actual['allowed_values']) != set(expected['allowed_values']):
            raise ValueError('Веса, шкалы или N/A отличаются от формата 1.0. Выберите официальный чек-лист и выполните новую оценку')


def snapshot(store, group):
    # A single read transaction pins the input, latest saved answers and jobs together.
    with store.db() as db:
        db.execute('BEGIN')
        config = json.loads(db.execute('SELECT payload FROM checklists ORDER BY version DESC LIMIT 1').fetchone()[0])
        rows = db.execute('SELECT payload FROM conversations WHERE dataset=? ORDER BY id', (group,)).fetchall()
        evaluations = db.execute('''SELECT e.* FROM evaluations e
            JOIN conversations c ON c.id=e.conversation_id
            WHERE c.dataset=? AND e.id=(SELECT MAX(x.id) FROM evaluations x WHERE x.conversation_id=e.conversation_id)''', (group,)).fetchall()
        jobs = db.execute('''SELECT j.* FROM jobs j JOIN conversations c ON c.id=j.conversation_id
            WHERE c.dataset=? ORDER BY j.id''', (group,)).fetchall()
    return {'records': [json.loads(r['payload']) for r in rows], 'config': config,
            'evaluations': {r['conversation_id']: json.loads(r['payload']) for r in evaluations},
            'jobs': [{**dict(r), 'payload': json.loads(r['payload'])} for r in jobs]}


def catalog(store):
    with store.db() as db:
        rows = db.execute('SELECT dataset,payload FROM conversations ORDER BY dataset,id').fetchall()
    groups = {}
    for row in rows:
        record = json.loads(row['payload'])
        group = groups.setdefault(row['dataset'], {'id': row['dataset'], 'total': 0, 'chats': 0, 'calls': 0})
        group['total'] += 1
        group['chats' if record['channel'] == 'agent chat' else 'calls'] += 1
    return list(groups.values())


def model_info(data):
    used = set()
    for evaluation in data['evaluations'].values():
        meta = evaluation.get('meta', {})
        if meta.get('provider') in PROVIDERS and meta.get('model'):
            used.add((meta['provider'], meta['model']))
    for job in data['jobs']:
        settings = job['payload']['settings']
        if job['attempts'] and settings['provider'] in PROVIDERS and settings.get('model'):
            used.add((settings['provider'], settings['model']))
    if not used:
        raise ValueError('В выбранной группе ещё не было попыток AI-оценки. Запустите модель; режим правил не выдаётся за LLM')
    locations = {'local' if provider == 'ollama' else 'external_api' for provider, _ in used}
    return {'mode': next(iter(locations)) if len(locations) == 1 else 'hybrid',
            'name': '; '.join(sorted({name for _, name in used}))}


def numeric_score(criteria):
    earned = Decimal(0)
    denominator = Decimal(0)
    values = {c['criterion_id']: c['value'] for c in criteria}
    for code, weight in zip(CODES, WEIGHTS):
        value = values[code]
        if value is None or not weight:
            continue
        w = Decimal(weight)
        fraction = Decimal(str(value)) / Decimal(max(SCALES[code])) if code in SCALES else Decimal(value)
        earned += w * fraction
        denominator += w
    if not denominator:
        raise ValueError('Нет применимых весов')
    return float((100 * earned / denominator).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def error_result(cid, reason):
    return {'conversation_id': cid, 'status': 'error', 'criteria': [], 'score': None, 'error': reason}


def build(store, kind, group, team_name):
    if not isinstance(team_name, str) or not team_name.strip() or len(team_name.strip()) > 100:
        raise ValueError('Укажите название команды до 100 символов')
    if not isinstance(group, str) or not group or (kind == 'prod' and group.upper() == 'DEV'):
        raise ValueError('Выберите отдельную группу контрольного набора; DEV нельзя сдать как PROD')
    data = snapshot(store, group)
    dataset_check(data['records'], kind)
    canonical_check(data['config'])
    if any(j['status'] in ACTIVE for j in data['jobs']):
        raise ValueError('В выбранной группе есть незавершённые задания. Дождитесь результата либо отмените ожидающие задания')
    model = model_info(data)
    latest_jobs = {j['conversation_id']: j for j in data['jobs']}
    results = []
    review_count = 0
    for record in data['records']:
        cid = record['conversation_id']
        evaluation = data['evaluations'].get(cid)
        if not evaluation:
            job = latest_jobs.get(cid)
            reason = job.get('error') if job else None
            results.append(error_result(cid, reason or 'AI-оценка диалога ещё не выполнена.'))
            continue
        if evaluation['checklist']['version'] != data['config']['version']:
            results.append(error_result(cid, 'Оценка выполнена по прежней версии чек-листа. Требуется новая проверка.'))
            continue
        if evaluation.get('meta', {}).get('provider') not in PROVIDERS:
            results.append(error_result(cid, 'Есть только проверка правил; полная AI-оценка не выполнена.'))
            continue
        try:
            # Stored payload contains the original AI answers; appeals are deliberately separate.
            answers = validate_result(data['config'], record, {'conversation_id': cid, 'criteria': evaluation['answers']})
            exported = []
            for answer in answers:
                value = answer['value']
                converted = {'Да': True, 'Нет': False, 'N/A': None}.get(value, value)
                if type(converted) in (int, float):
                    converted = int(converted)
                turns = sorted({turn for ev in answer['evidence'] for turn in range(ev['message_index'], ev['end_message_index'] + 1)})
                exported.append({'criterion_id': CODES[answer['criterion_id'] - 1], 'value': converted,
                                 'rationale': answer['reason'], 'evidence_turns': turns})
            results.append({'conversation_id': cid, 'status': 'ok', 'criteria': exported,
                            'score': {'final_score': numeric_score(exported), 'critical_flag': exported[7]['value']}})
            review_count += sum(a.get('needs_review', False) for a in answers)
        except (ValueError, TypeError, KeyError, AttributeError):
            results.append(error_result(cid, 'Сохранённая оценка неполная или не прошла проверку формата и доказательств.'))
    document = {'schema_version': '1.0', 'team_name': team_name.strip(), 'model': model, 'results': results}
    validate(document, data['records'], kind)
    report = {'set': kind, 'group': group, 'relative_path': f'results/{kind}/results.json',
              'total': len(results), 'ok': sum(r['status'] == 'ok' for r in results),
              'errors': [{'conversation_id': r['conversation_id'], 'error': r['error']} for r in results if r['status'] == 'error'],
              'needs_review_criteria': review_count, 'checklist_version': data['config']['version'],
              'model': model, 'basis': 'original_ai'}
    return document, report


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError('Неверные поля: ' + label)


def validate(document, records, kind):
    """Validate a generated OR supplied JSON independently of the exporter."""
    dataset_check(records, kind)
    fields(document, ('schema_version', 'team_name', 'model', 'results'), 'корень файла')
    if document['schema_version'] != '1.0' or not isinstance(document['team_name'], str) or not document['team_name'].strip():
        raise ValueError('Нужны schema_version 1.0 и название команды')
    model = document['model']
    fields(model, ('mode', 'name'), 'model')
    if model['mode'] not in ('local', 'external_api', 'hybrid') or not isinstance(model['name'], str) or not model['name'].strip():
        raise ValueError('Неверная модель или режим')
    results = document['results']
    if not isinstance(results, list) or len(results) != len(records):
        raise ValueError('Пропущены диалоги или добавлены лишние записи')
    source = {r['conversation_id']: r for r in records}
    seen = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError('Запись диалога должна быть объектом')
        cid = result.get('conversation_id')
        if not isinstance(cid, str) or cid not in source or cid in seen:
            raise ValueError('Неизвестный или повторный ID диалога')
        seen.add(cid)
        if result.get('status') == 'error':
            fields(result, ('conversation_id', 'status', 'criteria', 'score', 'error'), cid)
            if result['criteria'] != [] or result['score'] is not None or not isinstance(result['error'], str) or not result['error'].strip():
                raise ValueError('При error нужны пустые criteria, score=null и причина')
            continue
        fields(result, ('conversation_id', 'status', 'criteria', 'score'), cid)
        criteria = result['criteria']
        if result['status'] != 'ok' or not isinstance(criteria, list) or len(criteria) != 8:
            raise ValueError('При ok нужны ровно 8 критериев')
        criterion_ids = set()
        for criterion in criteria:
            fields(criterion, ('criterion_id', 'value', 'rationale', 'evidence_turns'), cid + ' / критерий')
            code, value = criterion['criterion_id'], criterion['value']
            if not isinstance(code, str) or code not in CODES or code in criterion_ids:
                raise ValueError('Неизвестный или повторный код критерия')
            criterion_ids.add(code)
            if value is None:
                valid = code in NULLABLE
            elif code in SCALES:
                valid = type(value) in (int, float) and math.isfinite(value) and value in SCALES[code]
            else:
                valid = type(value) is bool
            if not valid:
                raise ValueError('Недопустимый тип или значение критерия ' + code)
            if not isinstance(criterion['rationale'], str) or not criterion['rationale'].strip():
                raise ValueError('Нет rationale для ' + code)
            turns = criterion['evidence_turns']
            if not isinstance(turns, list) or not turns or any(type(t) is not int or not 1 <= t <= len(source[cid]['transcript']) for t in turns) or len(set(turns)) != len(turns):
                raise ValueError('Неверные evidence_turns для ' + code)
        score = result['score']
        fields(score, ('final_score', 'critical_flag'), cid + ' / score')
        final = score['final_score']
        if type(final) not in (int, float) or not math.isfinite(final) or not 0 <= final <= 100 or final != numeric_score(criteria):
            raise ValueError('Неверный final_score: проверьте веса, N/A и округление')
        critical = next(c['value'] for c in criteria if c['criterion_id'] == 'critical')
        if type(score['critical_flag']) is not bool or score['critical_flag'] != critical:
            raise ValueError('critical_flag не совпадает с критерием critical')
    if seen != set(source):
        raise ValueError('ID не совпадают с исходным набором')
    return document


def write_document(document, records, kind, destination, backup_dir):
    validate(document, records, kind)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        backups = Path(backup_dir)
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        shutil.copy2(destination, backups / f'{kind}-{stamp}.json')
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=destination.parent, prefix='.results-', suffix='.tmp', delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        os.replace(temp_path, destination)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return str(destination.resolve())
