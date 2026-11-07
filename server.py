"""Run with Python 3.11+: python server.py. No external dependencies."""
import argparse
import json
import mimetypes
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,unquote,parse_qsl,urlencode,urlunparse
import urllib.request
from cqa.domain import score
from cqa.engine import rules_review
from cqa.providers import call_model,safe_endpoint
from cqa.store import Store
from cqa.queue import Worker
from cqa.submission import catalog,build,snapshot,write_document

ROOT=Path(__file__).resolve().parent
STATIC=ROOT/'static'

def make_server(port=8765,db_path=None):
    store=Store(db_path or ROOT/'data/cqa.sqlite')
    if not store.overview()['records']:
        seed=ROOT/'research/dev.json'
        if seed.exists(): store.import_records(json.loads(seed.read_text(encoding='utf-8')))
    initial=store.settings();keys={}
    if os.environ.get('CQA_API_KEY'):keys[(initial['provider'],initial['base_url'])]=os.environ['CQA_API_KEY']
    if os.environ.get('OPENAI_API_KEY'):keys[('openai','https://api.openai.com/v1')]=os.environ['OPENAI_API_KEY']
    def key_for(settings):return keys.get((settings['provider'],settings['base_url']),'')
    busy=set()
    import threading
    lock=threading.Lock()
    evaluate_lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,fmt,*args): pass
        def write_json(self,obj,status=200):
            raw=json.dumps(obj,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(raw)
        def body(self):
            if self.headers.get_content_type()!='application/json': raise ValueError('Ожидается application/json')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=15_000_000: raise ValueError('Размер запроса должен быть до 15 МБ')
            return json.loads(self.rfile.read(length))
        def trusted(self):
            allowed=[f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']
            if self.headers.get('Host') not in allowed: return False
            origin=self.headers.get('Origin')
            return not origin or origin in ['http://'+host for host in allowed]
        def do_GET(self):
            if not self.trusted(): return self.write_json({'error':'Неверный источник запроса'},403)
            path=unquote(urlparse(self.path).path)
            try:
                if path=='/api/state': return self.write_json({**store.overview(),'queue_counts':store.jobs()['counts']})
                if path=='/api/jobs': return self.write_json(store.jobs())
                if path.startswith('/api/conversations/'): return self.write_json(store.detail(path.split('/')[-1]))
                if path=='/api/settings': return self.write_json({**store.settings(),'key_configured':bool(key_for(store.settings()))})
                if path=='/api/export': return self.write_json(store.export())
                if path=='/api/submission/catalog':return self.write_json({'groups':catalog(store),'team_name':store.submission_team()})
                if path=='/api/health': return self.write_json({'ok':True,'version':'0.4.0','benchmark_variants':['A','B'],'background_queue':True,'insights':True,'submission_schema':'1.0'})
                if path.startswith('/api/'): return self.write_json({'error':'Не найдено'},404)
                target=STATIC/('index.html' if path=='/' else path.lstrip('/'))
                if not target.resolve().is_relative_to(STATIC.resolve()) or not target.is_file(): return self.write_json({'error':'Не найдено'},404)
                raw=target.read_bytes(); self.send_response(200)
                self.send_header('Content-Type',(mimetypes.guess_type(str(target))[0] or 'application/octet-stream')+'; charset=utf-8')
                self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-cache')
                self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src https: http://localhost:* http://127.0.0.1:*; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
                self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(raw)
            except (ValueError,KeyError,json.JSONDecodeError) as e: self.write_json({'error':str(e)},400)
        def do_POST(self):
            if not self.trusted(): return self.write_json({'error':'Неверный источник запроса'},403)
            path=unquote(urlparse(self.path).path)
            try:
                body=self.body()
                if path in ['/api/submission/preview','/api/submission/export']:
                    kind=body.get('set');group=body.get('group')
                    document,report=build(store,kind,group,body.get('team_name'))
                    if path.endswith('/preview'):return self.write_json({'report':report})
                    destination=ROOT/report['relative_path']
                    saved=write_document(document,snapshot(store,group)['records'],kind,destination,ROOT/'data/submission_backups')
                    store.submission_team(document['team_name'])
                    return self.write_json({'report':report,'path':saved,'document':document})
                if path=='/api/jobs':
                    result=store.enqueue(body.get('conversation_ids'),body.get('variant','B'));worker.wake.set();return self.write_json(result,202)
                if path=='/api/jobs/resume':store.resume_jobs();worker.wake.set();return self.write_json(store.jobs())
                if path.startswith('/api/jobs/'):
                    parts=path.split('/');jid=int(parts[-2]);action=parts[-1]
                    if action=='retry':store.retry_job(jid)
                    elif action=='cancel':store.cancel_job(jid)
                    else:raise ValueError('Неизвестное действие очереди')
                    worker.wake.set();return self.write_json(store.jobs())
                if path=='/api/checklist': return self.write_json(store.save_config(body))
                if path=='/api/import': return self.write_json({'imported':store.import_records(body)})
                if path=='/api/sync':
                    source=ROOT/'data/dev_source.txt'
                    url=os.environ.get('CQA_DEV_URL','') or (source.read_text().strip() if source.exists() else '')
                    if not url: raise ValueError('Задайте CQA_DEV_URL или импортируйте JSON из API организаторов')
                    parsed=urlparse(url)
                    if parsed.scheme!='https': raise ValueError('API данных должен использовать HTTPS')
                    group=body.get('group_id','DEV')
                    import re
                    if not isinstance(group,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',group): raise ValueError('Неверный group_id')
                    query=dict(parse_qsl(parsed.query));query['group_id']=group
                    url=urlunparse(parsed._replace(query=urlencode(query)))
                    with urllib.request.urlopen(url,timeout=40) as response: payload=json.loads(response.read(15_000_000))
                    return self.write_json({'imported':store.import_records(payload)})
                if path=='/api/settings':
                    provider=body.get('provider')
                    if provider not in ['rules','openai','gemini','compatible','ollama']: raise ValueError('Неизвестный провайдер')
                    settings={k:body.get(k) for k in ['provider','base_url','model','input_price','output_price']}
                    settings['reasoning_effort']=body.get('reasoning_effort','low')
                    if settings['reasoning_effort'] not in ['low','medium','high','default']:raise ValueError('Неверный режим рассуждения')
                    if provider!='rules': safe_endpoint(settings['base_url'],provider)
                    if not isinstance(settings.get('model'),str) or len(settings['model'])>150: raise ValueError('Неверное название модели')
                    for k in ['input_price','output_price']:
                        if settings[k] is not None and (isinstance(settings[k],bool) or not isinstance(settings[k],(int,float)) or not 0<=settings[k]<=10000): raise ValueError('Неверная стоимость токенов')
                    if 'api_key' in body:
                        if not isinstance(body['api_key'],str): raise ValueError('Неверный ключ')
                        keys[(provider,settings['base_url'])]=body['api_key'].strip()
                    store.save_settings(settings)
                    worker.wake.set()
                    return self.write_json({**settings,'key_configured':bool(key_for(settings))})
                if path.startswith('/api/evaluate/'):
                    cid=path.split('/')[-1]
                    with lock:
                        if cid in busy: raise ValueError('Этот диалог уже оценивается')
                        busy.add(cid)
                    try:
                        record=store.record(cid); config=store.config(); settings=store.settings()
                        if not evaluate_lock.acquire(blocking=False):raise ValueError('Модель занята фоновой задачей. Используйте очередь или дождитесь завершения.')
                        try:
                            if settings['provider']=='rules':
                                answers=rules_review(record,config); meta={'provider':'rules','model':'Проверка правил','calls':0,'elapsed_seconds':0,'usage':{},'cost_usd':None};insights=None
                            else: answers,meta,insights=call_model(record,config,settings,key_for(settings),body.get('variant','B'))
                            return self.write_json(store.save_evaluation(cid,config,answers,meta,insights))
                        finally:evaluate_lock.release()
                    finally:
                        with lock: busy.discard(cid)
                if path=='/api/appeals': return self.write_json({'id':store.appeal(int(body['evaluation_id']),int(body['criterion_id']),body['comment'])})
                if path.startswith('/api/appeals/') and path.endswith('/resolve'):
                    return self.write_json(store.resolve(int(path.split('/')[-2]),body.get('value'),body.get('reason')))
                return self.write_json({'error':'Не найдено'},404)
            except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e: self.write_json({'error':str(e)},400)
            except (urllib.error.URLError,TimeoutError): self.write_json({'error':'Сервис данных недоступен. Локальные данные сохранены.'},502)
            except Exception:
                self.write_json({'error':'Не удалось выполнить операцию. Предыдущий результат сохранён.'},500)
    class Server(ThreadingHTTPServer):
        def server_close(self):
            if hasattr(self,'worker'):self.worker.close()
            super().server_close()
    server=Server(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    worker=Worker(store,key_for,evaluate_lock);server.worker=worker;server.store=store
    return server

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); parser.add_argument('--db',type=Path); args=parser.parse_args()
    server=make_server(args.port,args.db)
    print(f'CQA Studio: http://127.0.0.1:{server.server_port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
