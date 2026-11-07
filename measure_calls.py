"""Append local measurements without resending audio or changing readable editions."""
import json
from pathlib import Path
from cqa.store import Store
from cqa.media import AudioMedia
from cqa.acoustics import measure
from cqa.interaction import analyze


def main():
    store=Store(Path(__file__).resolve().parent/'data/cqa.sqlite');media=AudioMedia(store.record)
    for record in store.overview()['records']:
        if record['channel']!='voice call':continue
        cid=record['conversation_id'];clip=media.get(cid);signal=measure(clip);interaction=analyze(store.record(cid))
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT id,payload FROM audio_analyses WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
            if not row:raise ValueError('Сначала выполните аудиоанализ')
            payload=json.loads(row['payload'])
            if payload['result']['audio']['sha256']!=clip.sha256:raise ValueError('Аудиофайл изменился')
            payload['result']['signal_analysis']=signal;payload['result']['interaction_analysis']=interaction
            db.execute('UPDATE audio_analyses SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),row['id']))
        print(json.dumps({'id':cid,'status':signal['status'],'quiet_seconds':signal.get('quiet_seconds'),'segments':len(signal.get('quiet_segments',[])),'cues':len(interaction['signals'])},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
