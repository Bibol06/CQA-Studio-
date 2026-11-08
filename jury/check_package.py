"""Portable integrity and schema checks; no network or private database."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cqa.submission import validate

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON field: '+key)
        result[key]=value
    return result

def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=unique_object,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Non-finite JSON number')))

def check():
    manifest=load(ROOT/'jury/evidence/file_manifest.json');names=set()
    for row in manifest['files']:
        name=row['path'];path=(ROOT/name).resolve()
        if name in names or not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('Invalid manifest path: '+name)
        names.add(name)
        raw=path.read_bytes()
        if row.get('hash_mode')=='utf8-lf':raw=raw.replace(b'\r\n',b'\n')
        elif row.get('hash_mode','binary')!='binary':raise ValueError('Unknown hash mode')
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('File changed: '+name)
    index=load(ROOT/'jury/evidence/source_index.json')['records']
    if len(index)!=65 or any(type(r['turn_count']) is not int or not 1<=r['turn_count']<=10000 for r in index):raise ValueError('Invalid source index')
    stubs=[{'conversation_id':r['conversation_id'],'channel':r['channel'],'transcript':[None]*r['turn_count']} for r in index]
    document=load(ROOT/'results/dev/results.json');validate(document,stubs,'dev')
    summary={'verified_files':len(names),'dev_records':len(document['results']),
        'ok':sum(r['status']=='ok' for r in document['results']),'error':sum(r['status']=='error' for r in document['results']),
        'team_name':document['team_name'],'schema_version':document['schema_version'],
        'scope':'Integrity, recorded IDs and turn bounds, schema and arithmetic. Not semantic correctness or source authenticity.'}
    if (ROOT/'results/prod/results.json').exists():
        control_index=load(ROOT/'jury/evidence/prod_source_index.json')['records']
        if len(control_index)!=10 or any(type(r['turn_count']) is not int or not 1<=r['turn_count']<=10000 for r in control_index):raise ValueError('Invalid control index')
        control_records=[{'conversation_id':r['conversation_id'],'channel':r['channel'],'transcript':[None]*r['turn_count']} for r in control_index]
        control=load(ROOT/'results/prod/results.json');validate(control,control_records,'prod')
        summary.update({'prod_records':len(control['results']),'prod_ok':sum(r['status']=='ok' for r in control['results']),
            'prod_error':sum(r['status']=='error' for r in control['results'])})
    print(json.dumps(summary,ensure_ascii=False,indent=2));return summary

if __name__=='__main__':
    try:check()
    except (ValueError,KeyError,TypeError,OSError) as error:raise SystemExit('PACKAGE CHECK FAILED: '+str(error))
