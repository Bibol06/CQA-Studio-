import copy
import hashlib
import json
import math
from decimal import Decimal, ROUND_HALF_UP

RULES = [
    ('Установление контакта',10,None,['Да','Нет'],'Оператор поздоровался на языке клиента и представился в первом ответе.'),
    ('Выявление потребности',15,None,['Да','Нет','N/A'],'Учёл известные детали и уточнил недостающее до ответа. N/A: данных для ответа хватало с самого начала.'),
    ('Идентификация',20,None,['Да','Нет','N/A'],'Проверка личности подтверждена до раскрытия данных или защищённого действия. N/A: запрос не требовал идентификации.'),
    ('Корректная и полная консультация',20,20,[0,5,10,15,20,'N/A'],'20: все существенные вопросы закрыты или дан корректный следующий шаг. 15: пропущена второстепенная деталь. 10: существенный вопрос открыт. 5: общая подсказка без понятного действия. 0: нет ответа или ключевая рекомендация ошибочна. N/A: клиент не сформулировал запрос до конца чата.'),
    ('Эмпатия и клиентоориентированность',15,None,['Да','Нет'],'Оператор вежлив и отреагировал на конкретную проблему, если клиент выразил недовольство или описал неудобство.'),
    ('Управление диалогом, скорость и грамотность',15,10,[0,4,7,10],'10: ясно и связно, предупреждение при явном ожидании. 7: один заметный сбой. 4: клиент переспрашивает из-за формулировок или порядка. 0: ход диалога непонятен из-за бессвязности/противоречий. Порог первой реакции 3 минуты не учитывать.'),
    ('Завершение',5,None,['Да','Нет','N/A'],'Оператор подвёл итог или предложил дальнейшую помощь И попрощался. N/A: чат оборвался до возможности завершить.'),
    ('Грубые ошибки',0,None,['Да','Нет'],'Да: оскорбление клиента, предложение платной услуги в обход компании или раскрытие конфиденциальной информации. Самого предложения достаточно; согласие клиента не требуется. Отдельный флаг, без автоматического обнуления итога.'),
]

def default_checklist():
    return {'name':'Качество обслуживания','version':1,'criteria':[
        {'id':i,'name':n,'weight':w,'scale_max':m,'allowed_values':a,'description':d,
         'section': 'Начало и понимание запроса' if i<=2 else 'Безопасность и решение' if i<=4 else 'Ведение и завершение' if i<=7 else 'Грубые нарушения',
         'is_gross':i==8,'rule_key':f'official_{i}'}
        for i,(n,w,m,a,d) in enumerate(RULES,1)]}

def config_hash(config):
    return hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def validate_checklist(config):
    if not isinstance(config,dict) or not isinstance(config.get('name'),str) or not config['name'].strip():
        raise ValueError('Укажите название чек-листа')
    criteria=config.get('criteria')
    if not isinstance(criteria,list) or not 1<=len(criteria)<=30:
        raise ValueError('Чек-лист должен содержать от 1 до 30 критериев')
    ids=[]
    for c in criteria:
        if not isinstance(c,dict): raise ValueError('Неверный критерий')
        ids.append(c.get('id'))
        if not isinstance(c.get('id'),int) or isinstance(c['id'],bool): raise ValueError('ID критерия должен быть целым числом')
        if not c.get('name','').strip() or not c.get('description','').strip(): raise ValueError('Нужны название и правило каждого критерия')
        w=c.get('weight')
        if isinstance(w,bool) or not isinstance(w,(int,float)) or not math.isfinite(w) or not 0<=w<=100: raise ValueError('Вес должен быть числом от 0 до 100')
        a=c.get('allowed_values')
        if not isinstance(a,list) or not a or len(a)>30 or any(isinstance(v,bool) or not isinstance(v,(int,float,str)) for v in a): raise ValueError('Укажите допустимые ответы')
        if len(set(map(str,a)))!=len(a): raise ValueError('Ответы не должны повторяться')
        m=c.get('scale_max')
        numeric=[v for v in a if isinstance(v,(int,float))]
        if numeric:
            if isinstance(m,bool) or not isinstance(m,(int,float)) or not math.isfinite(m) or m<=0: raise ValueError('Нужен максимум числовой шкалы')
            if any(not math.isfinite(v) or not 0<=v<=m for v in numeric) or max(numeric)!=m or any(isinstance(v,str) and v!='N/A' for v in a): raise ValueError('Ступени должны лежать между 0 и максимумом шкалы')
        elif m is not None or any(v not in ['Да','Нет','N/A'] for v in a): raise ValueError('Для бинарных критериев используйте Да, Нет и при необходимости N/A')
        if c.get('is_gross') and w!=0: raise ValueError('Флаг грубой ошибки должен иметь нулевой вес')
    if len(ids)!=len(set(ids)): raise ValueError('ID критериев повторяются')
    return config

def score(config,answers):
    by_id={a['criterion_id']:a for a in answers}
    earned=Decimal(0); denominator=Decimal(0); complete=True; sections={}; gross=False
    for c in config['criteria']:
        a=by_id.get(c['id']); value=a.get('value') if a else None
        if value is None:
            complete=False
            continue
        if isinstance(value,bool) or value not in c['allowed_values']: raise ValueError(f"Недопустимый ответ для «{c['name']}»")
        if c.get('is_gross') and value=='Да': gross=True
        if value=='N/A' or c['weight']==0: continue
        w=Decimal(str(c['weight'])); maximum=c['scale_max']
        fraction=Decimal(str(value))/Decimal(str(maximum)) if maximum else Decimal(value=='Да')
        e=w*fraction; earned+=e; denominator+=w
        s=sections.setdefault(c.get('section','Общее'),[Decimal(0),Decimal(0)])
        s[0]+=e; s[1]+=w
    def normalize(e,w):
        return float((100*e/w).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if w else None
    return {'total':normalize(earned,denominator) if complete else None,'complete':complete,
            'earned':float(earned),'applicable_weight':float(denominator),'gross_error':gross,
            'sections':{n:normalize(e,w) if complete else None for n,(e,w) in sections.items()}}

def validate_result(config,record,result,require_evidence=True):
    if not isinstance(result,dict) or result.get('conversation_id')!=record['conversation_id']: raise ValueError('Модель вернула неверный ID диалога')
    raw=result.get('criteria')
    if not isinstance(raw,list) or len(raw)!=len(config['criteria']): raise ValueError('Модель вернула не все критерии')
    expected={c['id']:c for c in config['criteria']}; seen=set(); answers=[]
    for item in raw:
        if not isinstance(item,dict): raise ValueError('Неверная структура критерия')
        cid=item.get('criterion_id')
        if type(cid) is not int or cid not in expected or cid in seen: raise ValueError('Неверные или повторные ID критериев')
        seen.add(cid); c=expected[cid]; value=item.get('value')
        if isinstance(value,bool) or value not in c['allowed_values']: raise ValueError(f'Недопустимая ступень критерия {cid}')
        reason=item.get('reason')
        if not isinstance(reason,str) or not reason.strip(): raise ValueError(f'Нет объяснения критерия {cid}')
        evidence=item.get('evidence')
        if not isinstance(evidence,list) or (require_evidence and not evidence): raise ValueError(f'Нет доказательства критерия {cid}')
        clean=[]
        for ev in evidence:
            if not isinstance(ev,dict): raise ValueError('Неверная структура доказательства')
            index=ev.get('message_index'); end=ev.get('end_message_index',index); quote=ev.get('quote')
            if isinstance(index,bool) or not isinstance(index,int) or not 1<=index<=len(record['transcript']): raise ValueError('Ссылка на несуществующую реплику')
            if isinstance(end,bool) or not isinstance(end,int) or not index<=end<=len(record['transcript']): raise ValueError('Неверный участок доказательства')
            if not isinstance(quote,str) or not quote.strip() or quote not in record['transcript'][index-1]['text']: raise ValueError('Цитата не найдена в исходной реплике')
            clean.append({'message_index':index,'end_message_index':end,'quote':quote})
        answers.append({'criterion_id':cid,'value':value,'reason':reason[:5000],'evidence':clean,'needs_review':bool(item.get('needs_review',False)) or not clean})
    score(config,answers)
    return sorted(answers,key=lambda a:a['criterion_id'])

def parse_dataset(payload):
    if isinstance(payload,list): records=payload
    elif isinstance(payload,dict):
        if payload.get('isSuccess') is False: raise ValueError('API вернул ошибку')
        records=payload.get('data',payload).get('records')
    else: records=None
    if not isinstance(records,list) or not records or len(records)>10000: raise ValueError('Ожидается непустой массив records')
    seen=set(); clean=[]
    for r in records:
        cid=r.get('conversation_id'); transcript=r.get('transcript')
        if not isinstance(cid,str) or not cid or len(cid)>150 or cid in seen: raise ValueError('Пустой или повторный ID диалога')
        seen.add(cid)
        if r.get('language') not in ['RU','KZ','EN'] or r.get('channel') not in ['agent chat','voice call']: raise ValueError('Неизвестный язык или канал')
        if not isinstance(transcript,list) or not transcript or len(transcript)>10000: raise ValueError('Пустой или слишком длинный транскрипт')
        for t in transcript:
            if t.get('speaker') not in ['operator','client','bot','system'] or not isinstance(t.get('text'),str) or not isinstance(t.get('timestamp'),str): raise ValueError('Неверная структура реплики')
        clean.append(copy.deepcopy(r))
    return clean
