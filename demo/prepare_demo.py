"""Create an isolated public demo with synthetic chats and actual rule outputs."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cqa.store import Store
from cqa.engine import rules_review


def prepare(path=None):
    store=Store(path or ROOT/'data/public_demo.sqlite')
    payload=json.loads((ROOT/'demo/synthetic_chats.json').read_text(encoding='utf-8'))
    if store.overview()['records']:
        print('Demo database already contains data; existing results preserved.')
        return store
    store.import_records(payload)
    for record in payload['data']['records']:
        store.save_evaluation(record['conversation_id'],store.config(),rules_review(record,store.config()),
            {'provider':'rules','model':'Проверка правил','calls':0,'elapsed_seconds':0,'usage':{},'cost_usd':None})
    print('Created 3 SYNTHETIC chats. Rule outputs only; no AI calls and no official results.')
    return store


if __name__=='__main__':prepare()
