"""A single durable worker. Page reloads do not own or interrupt model calls."""
import threading
from .engine import rules_review
from .providers import call_model

class Worker:
    def __init__(self,store,key_for,evaluate_lock):
        self.store=store;self.key_for=key_for;self.evaluate_lock=evaluate_lock
        self.wake=threading.Event();self.stop=threading.Event()
        store.recover_jobs()
        self.thread=threading.Thread(target=self.run,name='cqa-queue',daemon=True)
        self.thread.start()

    def run_once(self):
        for job in self.store.candidates():
            payload=job['payload'];settings=payload['settings'];key=self.key_for(settings)
            if settings['provider'] not in ['rules','ollama'] and not key:
                if job['status']!='waiting_key':self.store.job_state(job['id'],'waiting_key','Добавьте ключ для провайдера и адреса, сохранённых в этом задании.')
                continue
            # One global lock also serializes requests from the synchronous benchmark endpoint.
            with self.evaluate_lock:
                if self.stop.is_set():return False
                if not self.store.job_state(job['id'],'running'):continue
                try:
                    record=self.store.record(job['conversation_id']);config=payload['checklist']
                    if settings['provider']=='rules':
                        answers=rules_review(record,config);meta={'provider':'rules','model':'Проверка правил','calls':0,'elapsed_seconds':0,'usage':{},'cost_usd':None};insights=None
                    else:
                        answers,meta,insights=call_model(record,config,settings,key,payload['variant'])
                    self.store.save_evaluation(job['conversation_id'],config,answers,meta,insights,job['id'])
                except ValueError as error:
                    self.store.job_state(job['id'],'failed',str(error)[:1000])
                    if any(code in str(error) for code in ['HTTP 429','HTTP 401','HTTP 403']):
                        self.store.pause_pending('Провайдер отклонил запрос по ключу, доступу или квоте. Исправьте причину и возобновите очередь вручную.')
                except Exception:
                    self.store.job_state(job['id'],'failed','Не удалось выполнить обработку. Предыдущая оценка сохранена; повтор доступен вручную.')
            return True
        return False

    def run(self):
        while not self.stop.is_set():
            if not self.run_once():self.wake.wait(2);self.wake.clear()

    def close(self):
        self.stop.set();self.wake.set();self.thread.join(timeout=2)
