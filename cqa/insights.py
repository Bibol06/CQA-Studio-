"""Validate summaries and recommendations against the exact source transcript."""
def evidence(items, record):
    if not isinstance(items, list) or not 1 <= len(items) <= 10:
        raise ValueError('Для вывода нужны от 1 до 10 фрагментов-доказательств')
    clean = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Неверная структура доказательства')
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
        if not isinstance(item, dict):
            raise ValueError('Неверная структура рекомендации')
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


def validate_requests(raw, record):
    """Validate question-level analysis independently of scores and summary."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
        raise ValueError('Нужны от 1 до 20 существенных вопросов клиента')
    clean = []
    for item in raw:
        if not isinstance(item, dict) or item.get('status') not in ['answered', 'follow_up', 'unanswered', 'not_enough_data']:
            raise ValueError('Неверный статус вопроса клиента')
        request = evidence(item.get('request_evidence'), record)
        if any(record['transcript'][ev['message_index']-1]['speaker'] != 'client' for ev in request):
            raise ValueError('Вопрос должен ссылаться на реплику клиента')
        response = item.get('answer_evidence')
        if not isinstance(response, list):
            raise ValueError('Неверный список ответов оператора')
        response = evidence(response, record) if response else []
        if any(record['transcript'][ev['message_index']-1]['speaker'] != 'operator' for ev in response):
            raise ValueError('Ответ должен ссылаться на реплику оператора')
        if item['status'] in ['answered', 'follow_up'] and not response:
            raise ValueError('Для ответа или обещания продолжения нужна реплика оператора')
        if any(ev['message_index'] < min(r['message_index'] for r in request) for ev in response):
            raise ValueError('Ответ не может предшествовать вопросу')
        clean.append({'request': text(item.get('request'), 'request'), 'status': item['status'],
                      'request_evidence': request, 'answer_evidence': response})
    return clean


def request_outcome(requests):
    statuses = {r['status'] for r in requests}
    if 'unanswered' in statuses:
        return 'unresolved'
    if 'not_enough_data' in statuses:
        return 'not_enough_data'
    if 'follow_up' in statuses:
        return 'follow_up'
    return 'resolved'
