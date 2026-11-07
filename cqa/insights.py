"""Validate summaries and recommendations against the exact source transcript."""
def evidence(items, record):
    if not isinstance(items, list) or not 1 <= len(items) <= 10:
        raise ValueError('Для вывода нужны от 1 до 10 фрагментов-доказательств')
    clean = []
    for item in items:
        index = item.get('message_index')
        end = item.get('end_message_index', index)
        if type(index) is not int or not 1 <= index <= len(record['transcript']):
            raise ValueError('Неверная реплика в резюме или рекомендации')
        if type(end) is not int or not index <= end <= len(record['transcript']):
            raise ValueError('Неверный участок в резюме или рекомендации')
        # Insight citations can be IDs only. Copy text from the immutable source,
        # rather than asking the model to reproduce the same text a second time.
        quote = item.get('quote', record['transcript'][index-1]['text'])
        if not isinstance(quote, str) or not quote.strip() or quote not in record['transcript'][index-1]['text']:
            raise ValueError('Цитата резюме или рекомендации не найдена в транскрипте')
        clean.append({'message_index': index, 'end_message_index': end, 'quote': quote})
    return clean

def text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('Нужно содержательное поле: ' + name)
    return value.strip()

def underperformed(criterion, value):
    if value is None or value == 'N/A':
        return False
    if criterion.get('is_gross'):
        return value == 'Да'
    if criterion['scale_max']:
        return value < criterion['scale_max']
    return value == 'Нет'

def validate_insights(raw, record, config, answers):
    if not isinstance(raw, dict) or not isinstance(raw.get('summary'), dict):
        raise ValueError('Модель не вернула структурированное резюме')
    summary = raw['summary']
    if summary.get('status') not in ['resolved', 'follow_up', 'unresolved', 'not_enough_data']:
        raise ValueError('Неверный статус результата разговора')
    result = {'summary': {k: text(summary.get(k), k) for k in ['request', 'actions', 'outcome']}, 'recommendations': []}
    result['summary']['status'] = summary['status']
    result['summary']['evidence'] = evidence(summary.get('evidence'), record)
    criteria = {c['id']: c for c in config['criteria']}
    values = {a['criterion_id']: a['value'] for a in answers}
    expected = {cid for cid, c in criteria.items() if underperformed(c, values[cid])}
    recommendations = raw.get('recommendations')
    if not isinstance(recommendations, list) or len(recommendations) > len(criteria):
        raise ValueError('Неверный список рекомендаций')
    seen = set()
    for item in recommendations:
        cid = item.get('criterion_id')
        if type(cid) is not int or cid not in expected or cid in seen:
            raise ValueError('Рекомендация должна относиться к отдельному нарушенному критерию')
        seen.add(cid)
        result['recommendations'].append({'criterion_id': cid, 'issue': text(item.get('issue'), 'issue'),
                                         'action': text(item.get('action'), 'action'),
                                         'evidence': evidence(item.get('evidence'), record)})
    if seen != expected:
        raise ValueError('Не для всех нарушенных критериев предложены рекомендации')
    return result
