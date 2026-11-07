"""Literal dialogue cues, not inferred intentions or employee emotions."""
import re
from .analytics import friction,source


def analyze(record):
    signals=[]
    patterns=[
        ('client','reported_no_answer','Слова об отсутствии ответа — проверить',r'не ответили|не отвечаете|меня не слышите|didn.t answer|not answering|жауап\s+берм|жауап\s+жоқ|мені\s+естім'),
        ('client','explicit_complaint','Слова о недовольстве — проверить',r'неприятн|отфутбол|навязываюсь|недовол|unacceptable|disappointed|наразымын|көңілім\s+толмай'),
        ('client','clarification','Клиент просит пояснить',r'не понял|не поняла|что значит|don.t understand|what do you mean|түсінбедім'),
        ('client','thanks','Благодарность клиента',r'спасибо|благодарю|thank|рақмет|рахмет'),
        ('operator','announced_wait','Оператор просит подождать',r'ожидать|подождите|ожидайте|please (?:wait|hold)|күте тұрыңыз'),
        ('operator','return_from_wait','Оператор благодарит за ожидание',r'за ожидание|for (?:holding|waiting)|күткеніңіз')]
    for i,t in enumerate(record['transcript'],1):
        for role,code,label,pattern in patterns:
            if t['speaker']==role and re.search(pattern,t['text'],re.I):
                signals.append({'code':code,'label':label,'evidence':[source(record,i)]})
    signals.extend({'code':f['code'],'label':f['label'],'evidence':f['evidence']} for f in friction(record) if f['code']=='repeated_request')
    return {'version':'interaction-cues-v1','basis':'original_transcript','requires_review':True,'signals':signals}
