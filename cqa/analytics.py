"""Explainable discovery on the supplied sample, not population/business metrics."""
from collections import Counter
from difflib import SequenceMatcher
import re

from .domain import config_hash
from .insights import underperformed


TOPICS = [
    ('access', 'Доступ и приложение', r'вход|войти|парол|приложен|авторизац|log\s?in|password|app\b|sign.?in|қосымша|құпиясөз|кіре алмай'),
    ('fees', 'Тарифы и комиссии', r'тариф|комисси|стоимост|fee\b|fees\b|tariff|commission|комиссия|ақы'),
    ('funding', 'Пополнение и переводы', r'пополн|перевод|зачисл|deposit|transfer|top.?up|толықтыр|аудар'),
    ('withdrawal', 'Вывод средств', r'вывод|вывести|withdraw|ақша шығ|қаражат.*шығар'),
    ('securities', 'Сделки и инструменты', r'акци[яиюй]|облигац|ценн.*бумаг|купить|продать|дивиденд|stock|bond|dividend|trade|сауда|бағалы қағаз'),
    ('documents', 'Документы и отчётность', r'отч[её]т|выписк|справк|документ|налог|statement|report|document|tax\b|құжат|есеп|салық'),
    ('other', 'Другие обращения', None),
]


def source(record, index):
    return {'message_index': index, 'end_message_index': index, 'quote': record['transcript'][index-1]['text']}


def topics(record):
    result=[]
    for tid,label,pattern in TOPICS:
        if not pattern: continue
        matches=[source(record,i) for i,t in enumerate(record['transcript'],1)
                 if t['speaker']=='client' and re.search(pattern,t['text'],re.I)]
        if matches:result.append({'id':tid,'label':label,'evidence':matches})
    return result or [{'id':'other','label':TOPICS[-1][1],'evidence':[]}]


def friction(record):
    """Conservative review signals; never penalize length or bot greetings."""
    result=[]; clients=[]; operator_seen=False
    explicit=r'ещ[её] раз|уже (?:спрашивал|писал)|я (?:же )?(?:спрашивал|спрашивала)|так и не|не ответили|не понял|не поняла|қайта сұра|түсінбедім|i (?:already )?asked|still (?:cannot|can.t|not)|didn.t answer|don.t understand'
    for i,t in enumerate(record['transcript'],1):
        if t['speaker']=='operator':operator_seen=True
        if t['speaker']!='client':continue
        normalized=' '.join(re.findall(r'\w+',t['text'].casefold()))
        if operator_seen and re.search(explicit,t['text'],re.I):
            result.append({'code':'explicit_friction','label':'Клиент сообщает о затруднении','evidence':[source(record,i)]})
        if len(normalized.split())>=5:
            match=next(((j,old) for j,old in clients
                        if any(x['speaker']=='operator' for x in record['transcript'][j:i-1])
                        and SequenceMatcher(None,normalized,old).ratio()>=.88),None)
            if match:
                result.append({'code':'repeated_request','label':'Похожая реплика повторена после ответа оператора',
                               'evidence':[source(record,match[0]),source(record,i)]})
            clients.append((i,normalized))
    return result


def group_key(meta, checklist_hash):
    return (meta.get('provider','unknown'),meta.get('model','unknown'),meta.get('prompt_version','legacy'),
            meta.get('variant','?'),meta.get('reasoning_effort'),checklist_hash)


def comparisons(evaluations, attempts):
    groups={}
    def get(meta,chash):
        key=group_key(meta,chash)
        if key not in groups:
            groups[key]={'id':len(groups),'provider':key[0],'model':key[1],'prompt_version':key[2],
                         'variant':key[3],'reasoning_effort':key[4],'checklist_hash':key[5],
                         'saved_evaluations':0,'legacy_saved':0,'traced_attempts':0,'completed':0,'failed':0,
                         'interrupted':0,'running':0,'latencies':[],'input_tokens':0,'output_tokens':0,
                         'usage_known':0,'cost_known':0,'known_cost_usd':0,'latest':{}}
        return groups[key]
    for e in evaluations:
        meta=e['meta']
        if meta.get('provider')=='rules':continue
        g=get(meta,e['checklist_hash']);g['saved_evaluations']+=1
        if not meta.get('attempt_id'):g['legacy_saved']+=1
        g['latest'][e['conversation_id']]=e
    for a in attempts:
        meta=a['meta'];g=get(meta,meta.get('checklist_hash'))
        g['traced_attempts']+=1;g[a['status']]+=1
        if a['status']!='running' and isinstance(meta.get('elapsed_seconds'),(int,float)):
            g['latencies'].append(meta['elapsed_seconds'])
        usage=meta.get('usage',{})
        if all(type(usage.get(k)) is int for k in ['input_tokens','output_tokens']):
            g['usage_known']+=1
            for k in ['input_tokens','output_tokens']:g[k]+=usage[k]
        if isinstance(meta.get('cost_usd'),(int,float)):
            g['cost_known']+=1;g['known_cost_usd']+=meta['cost_usd']
    paired=[]; values=list(groups.values())
    for i,a in enumerate(values):
        for b in values[i+1:]:
            if a['checklist_hash']!=b['checklist_hash']:continue
            shared=sorted(a['latest'].keys() & b['latest'].keys())
            if not shared:continue
            different=[];total=0;changed=0
            for cid in shared:
                left={r['criterion_id']:r['value'] for r in a['latest'][cid]['answers']}
                right={r['criterion_id']:r['value'] for r in b['latest'][cid]['answers']}
                ids=sorted(left.keys() & right.keys());diff=[k for k in ids if left[k]!=right[k]]
                total+=len(ids);changed+=len(diff)
                if diff:different.append({'conversation_id':cid,'criteria':diff,
                                         'left_evaluation_id':a['latest'][cid]['id'],'right_evaluation_id':b['latest'][cid]['id']})
            paired.append({'left':a['id'],'right':b['id'],'conversations':len(shared),'criteria':total,
                           'different':changed,'examples':different})
    for g in values:
        latency=g.pop('latencies');g['latency_known']=len(latency)
        g['mean_seconds']=round(sum(latency)/len(latency),2) if latency else None
        g['unique_conversations']=len(g.pop('latest'))
        g['known_cost_usd']=round(g['known_cost_usd'],6) if g['cost_known'] else None
    return {'groups':values,'paired':paired}


def build_analytics(store, filters=None):
    filters=filters or {}
    all_records,all_evaluations,all_attempts,config=store.analytics_snapshot()
    records=[r for r in all_records if all(not filters.get(k) or r[k]==filters[k] for k in ['dataset_group','language','channel'])]
    ids={r['conversation_id'] for r in records}
    evaluations=[e for e in all_evaluations if e['conversation_id'] in ids]
    latest={e['conversation_id']:e for e in evaluations}
    chash=config_hash(config);rows=[];outcomes=Counter();matrix=[];valid_count=0;summary_count=0;requests_count=0;stale_count=0
    for r in records:
        e=latest.get(r['conversation_id'])
        valid=bool(e and e['meta'].get('provider')!='rules' and e['checklist_hash']==chash and e['original_score']['complete'])
        if e and e['checklist_hash']!=chash:stale_count+=1
        valid_count+=valid
        failed=[];applicable=[];status='not_analyzed';request_analysis=[];conflict=False
        if valid:
            values={a['criterion_id']:a for a in e['answers']}
            for c in config['criteria']:
                a=values[c['id']]
                if a['value'] not in [None,'N/A']:applicable.append(c['id'])
                if underperformed(c,a['value']):failed.append({'id':c['id'],'evidence':a['evidence']})
            if e.get('insights'):
                status=e['insights']['summary']['status'];summary_count+=1
            request_analysis=e['meta'].get('request_analysis',[])
            if request_analysis:requests_count+=1
            conflict=e['meta'].get('outcome_conflict',False)
        outcomes[status]+=1
        rows.append({'conversation_id':r['conversation_id'],'language':r['language'],'channel':r['channel'],
                     'topics':topics(r),'friction':friction(r),'evaluated':valid,'outcome':status,'outcome_conflict':conflict,
                     'request_analysis':request_analysis,'score':e['original_score']['total'] if valid else None,
                     'failed':failed,'applicable':applicable,
                     'preview':next((t['text'] for t in r['transcript'] if t['speaker']=='client'),'')[:180]})
    for tid,label,_ in TOPICS:
        members=[r for r in rows if tid in {t['id'] for t in r['topics']}]
        cells=[]
        for c in config['criteria']:
            applicable=[r for r in members if c['id'] in r['applicable']]
            failed=[r['conversation_id'] for r in applicable if c['id'] in {f['id'] for f in r['failed']}]
            cells.append({'criterion_id':c['id'],'applicable':len(applicable),'failed':len(failed),'ids':failed})
        matrix.append({'id':tid,'label':label,'total':len(members),'evaluated':sum(r['evaluated'] for r in members),'cells':cells})
    return {'filters':filters,'options':{'dataset_group':sorted({r['dataset_group'] for r in all_records}),
             'language':sorted({r['language'] for r in all_records}),'channel':sorted({r['channel'] for r in all_records})},
            'coverage':{'total':len(records),'evaluated':valid_count,'summaries':summary_count,'requests':requests_count,
                        'stale':stale_count,'friction':sum(bool(r['friction']) for r in rows)},
            'criteria':[{'id':c['id'],'name':c['name'],'is_gross':c.get('is_gross',False)} for c in config['criteria']],
            'topics':matrix,'rows':rows,'outcomes':dict(outcomes),
            'comparison':comparisons(evaluations,[a for a in all_attempts if a['conversation_id'] in ids])}
