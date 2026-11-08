"""Export aggregate evidence, without exporting transcripts or credentials."""
import csv
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cqa.store import Store
from cqa.domain import parse_dataset
from cqa.submission import validate
from research.full_dev_report import report

def write(name,value):
    dest=ROOT/'jury/evidence'/name;dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def main():
    db_path=ROOT/'data/cqa.sqlite'
    if not db_path.exists():raise SystemExit('Local database required to refresh evidence. Use check_package.py to inspect the snapshot.')
    store=Store(db_path)
    records=parse_dataset(json.loads((ROOT/'research/dev.json').read_text(encoding='utf-8')))
    unchanged=all(store.record(r['conversation_id'])==r for r in records)
    assert unchanged,'Original records changed'
    doc=json.loads((ROOT/'results/dev/results.json').read_text(encoding='utf-8'));validate(doc,records,'dev')
    summary=report(store)
    summary.update({'participant':'Бибол Жайлыбаев','team_name':'Fantastic Four','app_version':'0.7.0',
        'source_transcripts_unchanged':unchanged,'submission_ok':sum(r['status']=='ok' for r in doc['results']),
        'submission_error':sum(r['status']=='error' for r in doc['results']),
        'submission_sha256':hashlib.sha256((ROOT/'results/dev/results.json').read_bytes()).hexdigest(),
        'independent_human_reference_available':False,'model_accuracy':None,'real_call_wer':None,'real_call_cer':None,
        'prod_file_present':(ROOT/'results/prod/results.json').exists()})
    write('project_summary.json',summary)
    write('source_index.json',{'description':'ID channel language and turn counts only. No text. Not a semantic reference.',
        'records':[{'conversation_id':r['conversation_id'],'channel':r['channel'],'language':r['language'],'turn_count':len(r['transcript'])} for r in records]})
    reference={r['conversation_id']:r for r in json.loads((ROOT/'research/reference_draft.json').read_text(encoding='utf-8'))['records']}
    rows=[]
    with sqlite3.connect(db_path) as db:
        for eid,cid,payload in db.execute('SELECT id,conversation_id,payload FROM evaluations ORDER BY id'):
            item=json.loads(payload)
            if item['meta'].get('model')!='gemini-3.8-flash' or item['checklist']['version']!=1:continue
            refs={a['criterion_id']:a for a in reference[cid]['criteria']}
            for a in item['answers']:
                ref=refs[a['criterion_id']]
                rows.append({'conversation_id':cid,'evaluation_id':eid,'criterion_id':a['criterion_id'],
                    'reference_value':ref['value'],'model_value':a['value'],'match':ref['value']==a['value'],
                    'reference_flagged_for_review':ref['needs_review'],'reference_source':'assistant_draft_not_human','model':'gemini-3.8-flash'})
    assert len(rows)==48 and sum(r['match'] for r in rows)==45
    with (ROOT/'jury/evidence/preliminary_agreement.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    asr=[]
    for record in records:
        if record['channel']!='voice call':continue
        a=store.detail(record['conversation_id']).get('asr_analysis')
        if not a:continue
        result=a['result'];local=result['local']
        asr.append({'conversation_id':record['conversation_id'],'audio_sha256':result['audio_sha256'],
            'processed_seconds':local['processed_seconds'],'full_input':local['full_recording'],'whisper_chunk_pairs':len(local['chunks']),
            'local_engine':local['engine'],'cloud_engine':result['cloud_engine'],'source_transcript_sent':result['source_transcript_sent'],
            'cloud_variant_characters':{k:len(v['text']) for k,v in result['cloud'].items()},
            'provider_generation_completed':{k:v['complete'] for k,v in result['cloud'].items()},
            'cloud_calls_in_successful_run':a['meta']['calls'],'elapsed_seconds':a['meta']['elapsed_seconds'],'accuracy':result['accuracy']})
    write('asr_summary.json',{'generated_at_utc':datetime.now(timezone.utc).isoformat(),'calls':asr,
        'note':'Completed generation is not proof of accuracy. Manual audio reference is required.'})
    print(json.dumps({'dev_total':summary['total'],'ok':summary['submission_ok'],'source_unchanged':unchanged,
        'preliminary_agreement':[sum(r['match'] for r in rows),len(rows)],'asr_calls_saved':len(asr)},ensure_ascii=False))

if __name__=='__main__':main()
