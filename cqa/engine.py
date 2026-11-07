"""Conservative rules for review assistance, never a substitute for an LLM."""
import re
from .domain import default_checklist

def match(pattern,text): return bool(re.search(pattern,text,re.I))

def rules_review(record,config):
    ts=record['transcript']; ops=[(i,t) for i,t in enumerate(ts,1) if t['speaker']=='operator']
    official={c['rule_key']:c for c in default_checklist()['criteria']}; answers=[]
    def ev(i,end=None):
        return [{'message_index':i,'end_message_index':end or i,'quote':ts[i-1]['text']}]
    for c in config['criteria']:
        value=None; evidence=[]; review=True
        reason='Нужна содержательная оценка по правилу. Подключите модель или заполните при пересмотре.'
        standard=official.get(c.get('rule_key'))
        unchanged=standard and all(c.get(k)==standard.get(k) for k in ['name','description','allowed_values','scale_max'])
        key=c.get('rule_key') if unchanged else None
        if not unchanged:
            reason='Изменённый критерий требует новой оценки. Старое правило к нему не применяется.'
        elif ops:
            first_i,first=ops[0]; last_i,last=ops[-1]
            if key=='official_1':
                text=first['text']
                hello=match(r'здравств|добрый|доброе|добрая|привет|сәлем|hello|\bhi\b|good (morning|afternoon|evening)',text)
                named=match(r'меня зовут|\bя\s+[А-ЯA-ZЁ]|\bмен\s+\S+|менің атым|\bi am\s+|\bi.m\s+',text)
                value='Да' if hello and named else 'Нет'
                reason='В первом ответе оператора найдены приветствие и представление.' if value=='Да' else 'В первом ответе оператора не найдены одновременно приветствие и представление. Приветствие бота не засчитывается.'
                reason+=' Соответствие языка и формулировку нужно подтвердить.'
                evidence=ev(first_i)
            if key=='official_3':
                verified=[i for i,t in enumerate(ts,1) if t['speaker']=='system' and match(r'личность.*подтверждена|жеке басы расталды|identity verified',t['text'])]
                disclosure=[i for i,t in ops if match(r'на вашем сч[её]те.*огранич|сіздің шотыңызда.*шектеу|restriction on your account',t['text'])]
                if disclosure and (not verified or min(disclosure)<min(verified)):
                    value='Нет'; evidence=ev(disclosure[0]); reason='Оператор сообщил ограничение конкретного счёта до системного подтверждения личности.'
                elif verified:
                    value='Да'; evidence=ev(verified[0]); reason='В транскрипте есть системное подтверждение личности. Проверить, что защищённые действия не выполнялись раньше.'
            if key=='official_7':
                broken=[i for i,t in enumerate(ts,1) if i>last_i and t['speaker']=='system' and match(r'соединение.*прервано|клиент покинул|байланыс үзілді|connection.*lost',t['text'])]
                if broken:
                    value='N/A'; evidence=ev(broken[-1]); reason='После ответа оператора зафиксирован явный выход клиента или обрыв связи.'
                else:
                    goodbye=match(r'до свидания|хорошего|всего доброго|сау бол|сәтті|goodbye|\bbye\b|take care|good (day|evening)',last['text'])
                    summary=match(r'если.*вопрос|обращайтесь|вопрос.*передан|начните|сверк|сообщим|ответ.*чат|ответ.*осында|follow.up|anything else|дальнейш|тексеруге|for review|that.s where',last['text'])
                    value='Да' if goodbye and summary else 'Нет'; evidence=ev(last_i,len(ts))
                    reason='Проверка последнего участка: нужны итог или предложение помощи вместе с прощанием. Требуется смысловой пересмотр.'
            if key=='official_8':
                bad=[(i,t) for i,t in ops if match(r'скиньте деньги мне|деньги.*мне на карту|частн.*консультац|ақылы.*айтып берем|i charge for private|вы вообще читать умеете',t['text'])]
                if bad:
                    value='Да'; evidence=ev(bad[0][0]); reason='Найдена реплика с признаком оскорбления или частной платной услуги. Самого предложения достаточно.'
                else: reason='Явный шаблон грубой ошибки не найден. Это не доказывает отсутствие нарушения — нужна проверка модели или человека.'
        else:
            reason='В транскрипте нет реплик оператора. Проверьте применимость критерия вручную.'
        if value is not None and value not in c['allowed_values']: value=None; evidence=[]
        answers.append({'criterion_id':c['id'],'value':value,'reason':reason,'evidence':evidence,'needs_review':review})
    return answers
