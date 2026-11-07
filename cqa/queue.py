"""One durable worker; storage recovery never resends an uncertain model request."""
from datetime import datetime, timezone
import sqlite3
import threading

from .engine import rules_review
from .providers import call_model


class Worker:
    def __init__(self, store, key_for, evaluate_lock, start=True):
        self.store = store
        self.key_for = key_for
        self.evaluate_lock = evaluate_lock
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.pending = None
        self.state_lock = threading.Lock()
        self.state = {'state': 'starting', 'error': None, 'job_id': None, 'updated_at': None}
        self.thread = None
        store.recover_jobs()
        if start:
            self.thread = threading.Thread(target=self.run, name='cqa-queue', daemon=True)
            self.thread.start()

    def status(self, state, error=None, job_id=None):
        with self.state_lock:
            self.state = {'state': state, 'error': error, 'job_id': job_id,
                          'updated_at': datetime.now(timezone.utc).isoformat()}

    def health(self):
        with self.state_lock:
            return {**self.state, 'alive': bool(self.thread and self.thread.is_alive())}

    def finish_pending(self):
        item = self.pending
        self.status('saving', job_id=item['id'])
        if item['kind'] == 'result':
            # COMMIT can have succeeded even if an I/O error was reported afterwards.
            checkpoint = self.store.job_checkpoint(item['id'])
            if checkpoint['status'] != 'completed':
                self.store.save_evaluation(item['cid'], item['config'], item['answers'],
                                           item['meta'], item['insights'], item['id'])
        else:
            self.store.finish_job_error(item['id'], item['error'], item.get('pause', False))
        self.pending = None
        self.status('idle')
        return True

    def run_once(self):
        if self.pending is not None:
            return self.finish_pending()
        for job in self.store.candidates():
            payload = job['payload']
            settings = payload['settings']
            key = self.key_for(settings)
            if settings['provider'] not in ['rules', 'ollama'] and not key:
                if job['status'] != 'waiting_key':
                    self.store.job_state(job['id'], 'waiting_key', 'Добавьте ключ для провайдера и адреса, сохранённых в этом задании.')
                continue
            with self.evaluate_lock:
                if self.stop.is_set():
                    return False
                # A failed read leaves an unstarted job queued, without a model call.
                record = self.store.record(job['conversation_id'])
                config = payload['checklist']
                try:
                    claimed = self.store.job_state(job['id'], 'running')
                except sqlite3.Error:
                    self.pending = {'kind': 'error', 'id': job['id'],
                                    'error': 'Не удалось подтвердить запуск задания в базе. Запрос модели не отправлен; доступен ручной повтор.'}
                    raise
                if not claimed:
                    continue
                self.status('processing', job_id=job['id'])
                try:
                    if settings['provider'] == 'rules':
                        answers = rules_review(record, config)
                        meta = {'provider': 'rules', 'model': 'Проверка правил', 'calls': 0,
                                'elapsed_seconds': 0, 'usage': {}, 'cost_usd': None}
                        insights = None
                    else:
                        answers, meta, insights = call_model(record, config, settings, key, payload['variant'])
                    self.pending = {'kind': 'result', 'id': job['id'], 'cid': job['conversation_id'],
                                    'config': config, 'answers': answers, 'meta': meta, 'insights': insights}
                except ValueError as error:
                    message = str(error)[:1000]
                    self.pending = {'kind': 'error', 'id': job['id'], 'error': message,
                                    'pause': any(code in message for code in ['HTTP 429', 'HTTP 401', 'HTTP 403'])}
                except Exception:
                    self.pending = {'kind': 'error', 'id': job['id'],
                                    'error': 'Не удалось выполнить обработку. Предыдущая оценка сохранена; повтор доступен вручную.'}
                return self.finish_pending()
        self.status('idle')
        return False

    def run(self):
        while not self.stop.is_set():
            try:
                worked = self.run_once()
            except sqlite3.Error:
                self.status('storage_error', 'Локальная база временно недоступна. Повторяется доступ к базе; готовый ответ модели сохраняется в памяти без нового запроса.',
                            self.pending['id'] if self.pending else None)
                worked = False
            except Exception:
                self.status('error', 'Сбой обработчика очереди. Повторяется проверка состояния; отправленный запрос модели автоматически не дублируется.',
                            self.pending['id'] if self.pending else None)
                worked = False
            if not worked:
                self.wake.wait(2)
                self.wake.clear()
        self.status('stopped')

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=2)
