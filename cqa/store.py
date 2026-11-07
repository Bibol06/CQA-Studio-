import copy
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
from .domain import default_checklist,score,validate_checklist,parse_dataset,config_hash

def now(): return datetime.now(timezone.utc).isoformat()
def dumps(v): return json.dumps(v,ensure_ascii=False)

class Store:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, payload TEXT NOT NULL, dataset TEXT NOT NULL DEFAULT 'DEV');
            CREATE TABLE IF NOT EXISTS checklists(version INTEGER PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evaluations(id INTEGER PRIMARY KEY AUTOINCREMENT,conversation_id TEXT NOT NULL,checklist_version INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS appeals(id INTEGER PRIMARY KEY AUTOINCREMENT,evaluation_id INTEGER NOT NULL,criterion_id INTEGER NOT NULL,comment TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',value TEXT,reason TEXT,created_at TEXT NOT NULL,resolved_at TEXT);
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
            ''')
            if 'dataset' not in [r['name'] for r in db.execute('PRAGMA table_info(conversations)')]:
                db.execute("ALTER TABLE conversations ADD COLUMN dataset TEXT NOT NULL DEFAULT 'DEV'")
            if not db.execute('SELECT 1 FROM checklists LIMIT 1').fetchone():
                db.execute('INSERT INTO checklists VALUES(?,?,?)',(1,dumps(default_checklist()),now()))
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=20); db.row_factory=sqlite3.Row
        try:
            yield db; db.commit()
        except Exception: db.rollback(); raise
        finally: db.close()
    def config(self,version=None):
        with self.db() as db:
            row=db.execute('SELECT payload FROM checklists WHERE version=?',(version,)).fetchone() if version else db.execute('SELECT payload FROM checklists ORDER BY version DESC LIMIT 1').fetchone()
        if not row: raise ValueError('Версия чек-листа не найдена')
        return json.loads(row[0])
    def save_config(self,config):
        validate_checklist(config)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT MAX(version) FROM checklists').fetchone()[0]
            if config.get('version')!=current: raise ValueError('Чек-лист уже изменён в другой вкладке. Обновите страницу.')
            new=copy.deepcopy(config); new['version']=current+1
            db.execute('INSERT INTO checklists VALUES(?,?,?)',(new['version'],dumps(new),now()))
        return new
    def import_records(self,payload):
        records=parse_dataset(payload)
        group=(payload.get('data',payload).get('dataset_group_id','IMPORT') if isinstance(payload,dict) else 'IMPORT')
        if not isinstance(group,str) or len(group)>80: raise ValueError('Неверная группа данных')
        with self.db() as db:
            for r in records:
                old=db.execute('SELECT payload FROM conversations WHERE id=?',(r['conversation_id'],)).fetchone()
                if old and json.loads(old[0])!=r:
                    raise ValueError('Диалог с тем же ID имеет другое содержимое. Используйте новый ID, чтобы сохранить связь с прежними доказательствами.')
                db.execute('INSERT OR IGNORE INTO conversations(id,payload,dataset) VALUES(?,?,?)',(r['conversation_id'],dumps(r),group))
        return len(records)
    def record(self,cid):
        with self.db() as db: row=db.execute('SELECT payload FROM conversations WHERE id=?',(cid,)).fetchone()
        if not row: raise ValueError('Диалог не найден')
        return json.loads(row[0])
    def save_evaluation(self,cid,config,answers,meta):
        result=score(config,answers)
        payload={'checklist':config,'answers':answers,'original_score':result,'meta':meta,
                 'checklist_hash':config_hash(config)}
        with self.db() as db:
            cursor=db.execute('INSERT INTO evaluations(conversation_id,checklist_version,payload,created_at) VALUES(?,?,?,?)',(cid,config['version'],dumps(payload),now()))
            eid=cursor.lastrowid
        return self.evaluation(eid)
    def evaluation(self,eid):
        with self.db() as db:
            row=db.execute('SELECT * FROM evaluations WHERE id=?',(eid,)).fetchone()
            appeals=[dict(r) for r in db.execute('SELECT * FROM appeals WHERE evaluation_id=? ORDER BY id',(eid,))]
        if not row: raise ValueError('Оценка не найдена')
        result=json.loads(row['payload']); original=copy.deepcopy(result['answers']); final=copy.deepcopy(original)
        for a in appeals:
            if a['status']=='resolved':
                for item in final:
                    if item['criterion_id']==a['criterion_id']:
                        item['value']=json.loads(a['value']); item['review_reason']=a['reason']; item['needs_review']=False
        result.update({'id':row['id'],'conversation_id':row['conversation_id'],'created_at':row['created_at'],
                       'original_answers':original,'answers':final,'final_score':score(result['checklist'],final),'appeals':appeals})
        return result
    def detail(self,cid):
        record=self.record(cid)
        with self.db() as db:
            ids=[r[0] for r in db.execute('SELECT id FROM evaluations WHERE conversation_id=? ORDER BY id DESC',(cid,))]
            group=db.execute('SELECT dataset FROM conversations WHERE id=?',(cid,)).fetchone()[0]
        return {'record':record,'dataset_group':group,'evaluation':self.evaluation(ids[0]) if ids else None,'history':[self.evaluation(e) for e in ids[1:]],'current_version':self.config()['version']}
    def overview(self):
        with self.db() as db:
            rows=[(json.loads(r['payload']),r['dataset']) for r in db.execute('SELECT payload,dataset FROM conversations ORDER BY id')]
            latest={r['conversation_id']:r['id'] for r in db.execute('SELECT conversation_id,MAX(id) id FROM evaluations GROUP BY conversation_id')}
            open_count=db.execute("SELECT COUNT(*) FROM appeals WHERE status='open'").fetchone()[0]
        summaries=[]; version=self.config()['version']
        for r,group in rows:
            e=self.evaluation(latest[r['conversation_id']]) if r['conversation_id'] in latest else None
            summaries.append({'conversation_id':r['conversation_id'],'dataset_group':group,'language':r['language'],'channel':r['channel'],
                'preview':next((t['text'] for t in r['transcript'] if t['speaker']=='client'),'Нет реплик клиента')[:180],
                'messages':len(r['transcript']),'score':e['final_score']['total'] if e else None,'evaluated':bool(e),
                'gross_error':e['final_score']['gross_error'] if e else False,'provider':e['meta']['provider'] if e else None,
                'needs_review':sum(a.get('needs_review',False) or a['value'] is None for a in e['answers']) if e else 0,
                'stale':bool(e and e['checklist']['version']!=version),'evaluation_id':e['id'] if e else None})
        return {'records':summaries,'open_appeals':open_count,'checklist':self.config()}
    def appeal(self,eid,cid,comment):
        e=self.evaluation(eid)
        if cid not in {c['id'] for c in e['checklist']['criteria']}: raise ValueError('Критерий не найден')
        if not isinstance(comment,str) or not comment.strip() or len(comment)>5000: raise ValueError('Добавьте комментарий до 5000 символов')
        with self.db() as db:
            cur=db.execute('INSERT INTO appeals(evaluation_id,criterion_id,comment,created_at) VALUES(?,?,?,?)',(eid,cid,comment.strip(),now()))
            return cur.lastrowid
    def resolve(self,aid,value,reason):
        if not isinstance(reason,str) or not reason.strip() or len(reason)>5000: raise ValueError('Нужна причина решения до 5000 символов')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            a=db.execute('SELECT * FROM appeals WHERE id=?',(aid,)).fetchone()
            if not a or a['status']!='open': raise ValueError('Апелляция уже рассмотрена или не найдена')
            evaluation=db.execute('SELECT payload FROM evaluations WHERE id=?',(a['evaluation_id'],)).fetchone()
            config=json.loads(evaluation[0])['checklist']; c=next(x for x in config['criteria'] if x['id']==a['criterion_id'])
            if isinstance(value,bool) or value not in c['allowed_values']: raise ValueError('Недопустимая оценка')
            db.execute("UPDATE appeals SET status='resolved',value=?,reason=?,resolved_at=? WHERE id=?",(dumps(value),reason.strip(),now(),aid))
        return self.evaluation(a['evaluation_id'])
    def settings(self):
        with self.db() as db: r=db.execute('SELECT payload FROM settings WHERE id=1').fetchone()
        return json.loads(r[0]) if r else {'provider':'rules','base_url':'https://api.openai.com/v1','model':'','input_price':None,'output_price':None}
    def save_settings(self,settings):
        with self.db() as db: db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(dumps(settings),))
    def export(self):
        with self.db() as db: ids=[r[0] for r in db.execute('SELECT id FROM evaluations ORDER BY id')]
        return {'exported_at':now(),'checklist':self.config(),'evaluations':[self.evaluation(i) for i in ids]}
