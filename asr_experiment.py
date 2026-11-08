"""Run independent ASR on original and DSP copy, preserving previous results."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from cqa.store import Store
from cqa.media import AudioMedia
from cqa.asr import run


def main():
    p=argparse.ArgumentParser();p.add_argument('--ids',nargs='+',default=[f'p4-ru-{i:03}' for i in range(1,6)])
    p.add_argument('--seconds',type=float);args=p.parse_args()
    if len(args.ids)>1:
        # Native inference allocators can retain large buffers. One process per
        # recording releases them before the next call on constrained machines.
        for cid in args.ids:
            command=[sys.executable,str(Path(__file__).resolve()),'--ids',cid]
            if args.seconds is not None:command+=['--seconds',str(args.seconds)]
            subprocess.run(command,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return
    store=Store(Path(__file__).resolve().parent/'data/cqa.sqlite');media=AudioMedia(store.record)
    for cid in args.ids:
        result=run(media.get(cid),args.seconds,lambda n,t:print(cid,n,t,flush=True))
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT id,payload FROM audio_analyses WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
            if not row:raise ValueError('Сначала выполните аудиоанализ')
            payload=json.loads(row['payload'])
            if payload['result']['audio']['sha256']!=result['audio_sha256']:raise ValueError('Источник аудио изменился')
            if payload['result'].get('asr_comparison'):payload['result'].setdefault('asr_history',[]).append(payload['result']['asr_comparison'])
            payload['result']['asr_comparison']=result
            db.execute('UPDATE audio_analyses SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),row['id']))
        print('SAVED',cid,result['elapsed_seconds'],flush=True)


if __name__=='__main__':main()
