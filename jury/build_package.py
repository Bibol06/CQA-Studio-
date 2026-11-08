"""Create a source package from Git-visible files with an explicit allowlist."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
MANIFEST='jury/evidence/file_manifest.json'

def fingerprint(name):
    path=ROOT/name;raw=path.read_bytes()
    text=path.suffix.lower() in ['.py','.md','.js','.css','.html','.json','.txt','.csv','.cmd'] or path.name=='.gitignore'
    canonical=raw.replace(b'\r\n',b'\n') if text else raw
    return {'path':name,'size_bytes':len(raw),'hash_mode':'utf8-lf' if text else 'binary','sha256':hashlib.sha256(canonical).hexdigest()}

def main():
    result=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',check=True)
    names=[]
    public_dirs={'cqa','static','tests','docs','jury','demo','results','research'}
    for name in sorted(set(result.stdout.splitlines())):
        p=Path(name);source=(ROOT/p).resolve()
        if name==MANIFEST or not source.is_file():continue
        if not source.is_relative_to(ROOT):raise ValueError('File outside repository')
        if len(p.parts)>1 and p.parts[0] not in public_dirs:continue
        if len(p.parts)==1 and not (p.suffix in ['.py','.md','.cmd','.txt'] or name=='.gitignore'):continue
        if p.parts[0]=='research' and name not in ['research/checklist_clarified_v2.json','research/build_reference.py','research/experiment.py','research/live_report.py','research/full_dev_report.py','research/experiment/README.md','research/experiment/response_template.json']:continue
        if any(part in ['__pycache__','.git','data','.venv'] for part in p.parts) or p.suffix in ['.sqlite','.db','.pyc','.rar','.zip'] or p.name=='.env':raise ValueError('Private file selected: '+name)
        if p.suffix.lower() in ['.py','.md','.txt','.json','.csv','.html','.js','.css','.cmd']:
            raw=source.read_text(encoding='utf-8-sig')
            if re.search(r'AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9]{24,}',raw):raise ValueError('Credential-like value detected in '+name)
        names.append(name)
    required={'jury/overview.pdf','jury/evidence/project_summary.json','demo/synthetic_chats.json','START_DEMO.cmd','results/dev/results.json','jury/check_package.py','README.md'}
    if not required.issubset(names):raise ValueError('Missing package files: '+str(required-set(names)))
    manifest={'schema_version':'file-manifest-1','generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'note':'Self excluded. Text SHA-256 normalizes CRLF to LF for Git checkout portability; binary files use original bytes. Private data excluded.',
        'files':[fingerprint(name) for name in names]}
    (ROOT/MANIFEST).write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    subprocess.run([sys.executable,'jury/check_package.py'],cwd=ROOT,check=True)
    dest=ROOT/'output/jury/CQA-Studio-Fantastic-Four-Bibol.zip';dest.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(dest,'w',ZIP_DEFLATED) as archive:
        for name in names+[MANIFEST]:archive.write(ROOT/name,'CQA-Studio-Fantastic-Four/'+name)
    print(json.dumps({'archive':str(dest),'files':len(names)+1,'bytes':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
