"""Paired evaluation through the running app; API key stays in server memory."""
import argparse
import json
from pathlib import Path
import sys
import urllib.request
import urllib.error
from urllib.parse import urlparse
from cqa.domain import default_checklist

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--server',default='http://127.0.0.1:8765');parser.add_argument('--split',choices=['tuning','validation'],default='tuning');parser.add_argument('--limit',type=int,default=3);args=parser.parse_args()
    parsed=urlparse(args.server)
    if parsed.hostname not in ['localhost','127.0.0.1'] or parsed.scheme!='http':parser.error('Use the local CQA server')
    base=args.server.rstrip('/')
    def api(path,body=None):
        req=urllib.request.Request(base+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=180) as response:return json.load(response)
        except urllib.error.HTTPError as error:
            message=json.loads(error.read()).get('error','HTTP error');error.close();raise ValueError(message) from None
    health=api('health')
    if health.get('benchmark_variants')!=['A','B']:raise ValueError('Сервер запущен до обновления A/B. Для эксперимента нужен перезапуск; после него API-ключ вводится заново.')
    settings=api('settings')
    if settings['provider']=='rules':raise ValueError('Сначала подключите модель в настройках приложения. Правила не являются AI-бенчмарком.')
    if settings['provider']!='ollama' and not settings['key_configured']:raise ValueError('В настройках нет API-ключа.')
    state=api('state')
    if state['checklist']!=default_checklist():raise ValueError('Для этого эксперимента нужна исходная конфигурация v1; текущий чек-лист изменён.')
    manifest=json.loads((ROOT/'research/experiment/frozen_manifest.json').read_text(encoding='utf8'))
    ids=manifest[args.split][:max(1,min(args.limit,6))]
    out=ROOT/'data/benchmarks';out.mkdir(parents=True,exist_ok=True)
    from datetime import datetime,timezone
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');path=out/f'{stamp}-{args.split}.jsonl'
    completed=0
    with path.open('x',encoding='utf8') as file:
        for i,cid in enumerate(ids):
            for variant in (['A','B'] if i%2==0 else ['B','A']):
                print(f'{cid} / {variant}: запрос модели…',flush=True)
                result=api('evaluate/'+cid,{'variant':variant});meta=result['meta']
                row={'request_id':cid+'__'+variant,'model':meta['model'],'provider':meta['provider'],'elapsed_seconds':meta['elapsed_seconds'],'usage':meta['usage'],'cost_usd':meta['cost_usd'],
                     'response':{'conversation_id':cid,'criteria':result['original_answers']}}
                file.write(json.dumps(row,ensure_ascii=False)+'\n');file.flush();completed+=1
                print(f"Сохранено. {meta['elapsed_seconds']} с; итог {result['original_score']['total']}",flush=True)
    print(f'Готово: {completed} реальных ответов; файл {path}',flush=True)
    print(f'Сравнить: python research/experiment.py evaluate --responses "{path}"',flush=True)

if __name__=='__main__':
    try:main()
    except (ValueError,urllib.error.URLError,TimeoutError) as error:
        print('Эксперимент остановлен: '+str(error),file=sys.stderr);raise SystemExit(1)
