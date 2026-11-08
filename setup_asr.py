"""Explicit download of the pinned, public multilingual Whisper ONNX model."""
import hashlib
import json
from pathlib import Path
import shutil
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent/'data/models/whisper-tiny-int8'
REPO='csukuangfj/sherpa-onnx-whisper-tiny'
REVISION='65176e2deb88badc814a94058666cadccc29b61c'
FILES={'tiny-encoder.int8.onnx':12937772,'tiny-decoder.int8.onnx':89855401,'tiny-tokens.txt':816730}


def main():
    ROOT.mkdir(parents=True,exist_ok=True);manifest={'repository':REPO,'revision':REVISION,'files':{}}
    needed=sum(size for name,size in FILES.items() if not (ROOT/name).exists())
    if shutil.disk_usage(ROOT).free<needed+20_000_000:raise ValueError('Недостаточно места для модели и запаса 20 МБ')
    for name,size in FILES.items():
        dest=ROOT/name
        if not dest.exists():
            part=dest.with_suffix(dest.suffix+'.part')
            with urlopen(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}',timeout=90) as r,part.open('wb') as w:
                total=0
                while block:=r.read(1048576):
                    total+=len(block)
                    if total>size:raise ValueError('Модель превысила ожидаемый размер')
                    w.write(block)
            if total!=size:raise ValueError('Модель загружена не полностью')
            part.replace(dest)
        if dest.stat().st_size!=size:raise ValueError('Размер модели не совпадает')
        with dest.open('rb') as model_file:digest=hashlib.file_digest(model_file,'sha256').hexdigest()
        manifest['files'][name]={'size':size,'sha256':digest}
        print(name,size)
    (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')


if __name__=='__main__':main()
