"""One local model lifetime per recording. No credentials accepted."""
import base64
import json
import sys
from .media import clip_from_bytes,MAX_AUDIO_BYTES
from .asr import run,recognizer,transcribe

if __name__=='__main__':
    if '--pair' in sys.argv:
        import struct,numpy as np
        packet=sys.stdin.buffer.read(4+29*16000*8+1)
        n=struct.unpack('<I',packet[:4])[0]
        if not 0<n<=29*16000 or len(packet)!=4+n*8:raise ValueError('Неверный размер ASR-фрагмента')
        raw=np.frombuffer(packet,dtype='<f4',count=n,offset=4)
        clean=np.frombuffer(packet,dtype='<f4',count=n,offset=4+n*4)
        model=recognizer();result=[transcribe(model,raw),transcribe(model,clean)]
        sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode('utf-8'))
        sys.exit(0)
    encoded=sys.stdin.buffer.read(MAX_AUDIO_BYTES*4//3+16)
    clip=clip_from_bytes(base64.b64decode(encoded,validate=True))
    result=run(clip)
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode('utf-8'))
