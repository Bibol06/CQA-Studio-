"""Resolve the organizer's audio wrapper and serve bounded, verified media bytes."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import io
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import wave

ALLOWED_HOSTS = frozenset({
    'ec88f21f1accecf38e20095a9fe175.a5.environment.api.powerplatform.com',
    'freedomholdingcorporation.crm11.dynamics.com',
})
MAX_AUDIO_BYTES = 12_000_000  # Base64 plus JSON stays below the inline request limit.


def checked_url(address, allowed_hosts=ALLOWED_HOSTS):
    try:p=urlsplit(address)
    except (TypeError, ValueError):raise ValueError('Неверный адрес записи') from None
    if p.scheme!='https' or p.hostname not in allowed_hosts or p.username or p.password or p.port not in [None,443]:
        raise ValueError('Источник записи не входит в разрешённые источники организаторов')
    return address


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class AudioSource(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.sources=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower() in ['audio','source']:
            src=dict(attrs).get('src')
            if src:self.sources.append(src)


def mp3_info(data):
    """Read MPEG layer III frames without decoding speech or installing a codec."""
    def frame(pos):
        if pos+4>len(data):return None
        h=int.from_bytes(data[pos:pos+4],'big')
        version=(h>>19)&3;layer=(h>>17)&3;rate_index=(h>>10)&3;bit_index=(h>>12)&15
        if h>>21!=0x7ff or version==1 or layer!=1 or rate_index==3 or bit_index in [0,15]:return None
        bitrates=([0,32,40,48,56,64,80,96,112,128,160,192,224,256,320] if version==3
                  else [0,8,16,24,32,40,48,56,64,80,96,112,128,144,160])
        rate=[44100,48000,32000][rate_index]//(1 if version==3 else 2 if version==2 else 4)
        length=(144 if version==3 else 72)*bitrates[bit_index]*1000//rate+((h>>9)&1)
        return length,(1152 if version==3 else 576)/rate,rate,1 if (h>>6)&3==3 else 2
    pos=0
    if data[:3]==b'ID3' and len(data)>=10:
        if any(b&128 for b in data[6:10]):raise ValueError('Повреждён заголовок MP3')
        pos=10+sum(b<<(7*(3-i)) for i,b in enumerate(data[6:10]))+(10 if data[5]&16 else 0)
    first=None
    for candidate in range(pos,min(pos+4096,len(data)-8)):
        f=frame(candidate)
        if f and frame(candidate+f[0]):first=candidate;break
    if first is None:raise ValueError('Не удалось прочитать MP3: проверьте формат записи')
    pos=first;duration=0.;count=0;used=0;rate=0;channels=0
    while pos+4<=len(data):
        f=frame(pos)
        if not f or pos+f[0]>len(data):break
        length,seconds,rate,channels=f;duration+=seconds;used+=length;count+=1;pos+=length
    trailing=len(data)-pos
    if count<3 or duration<=0 or (trailing>4096 and used<.97*(len(data)-first)):
        raise ValueError('MP3 содержит повреждённые или неподдерживаемые участки')
    return round(duration,3),rate,channels


@dataclass(frozen=True)
class AudioClip:
    data: bytes
    mime_type: str
    duration_seconds: float
    sample_rate: int
    channels: int
    sha256: str

    def info(self):
        return {'mime_type':self.mime_type,'duration_seconds':self.duration_seconds,
                'sample_rate':self.sample_rate,'channels':self.channels,'size_bytes':len(self.data),'sha256':self.sha256}


def clip_from_bytes(data):
    if not data or len(data)>MAX_AUDIO_BYTES:raise ValueError('Для встроенного анализа нужна запись не более 12 МБ')
    if data[:4]==b'RIFF' and data[8:12]==b'WAVE':
        try:
            with wave.open(io.BytesIO(data),'rb') as w:
                rate=w.getframerate();channels=w.getnchannels();duration=round(w.getnframes()/rate,3)
        except (wave.Error,EOFError,ZeroDivisionError):raise ValueError('Не удалось прочитать WAV') from None
        mime='audio/wav'
    else:
        duration,rate,channels=mp3_info(data);mime='audio/mpeg'
    if duration<=0 or duration>1800:raise ValueError('Поддерживаются записи длительностью от долей секунды до 30 минут')
    return AudioClip(data,mime,duration,rate,channels,hashlib.sha256(data).hexdigest())


def byte_range(value,size):
    if not value:return 0,size-1,200
    m=re.fullmatch(r'bytes=(\d*)-(\d*)',value.strip())
    if not m or not any(m.groups()):raise ValueError('Неверный диапазон аудио')
    left,right=m.groups()
    if left:
        start=int(left);end=min(int(right),size-1) if right else size-1
    else:
        length=int(right)
        if length<=0:raise ValueError('Неверный диапазон аудио')
        start=max(0,size-length);end=size-1
    if start>=size or start>end:raise ValueError('Неверный диапазон аудио')
    return start,end,206


class AudioMedia:
    def __init__(self,record_for,fetch=None):
        self.record_for=record_for;self.fetch=fetch or self._fetch;self.cache=OrderedDict();self.lock=threading.Lock()

    @staticmethod
    def _fetch(address):
        checked_url(address)
        try:
            with build_opener(SafeRedirect()).open(Request(address),timeout=25) as response:
                content_type=response.headers.get_content_type()
                limit=512_000 if content_type in ['text/html','application/xhtml+xml'] else MAX_AUDIO_BYTES
                raw=response.read(limit+1)
                if len(raw)>limit:raise ValueError('Запись или страница источника превышает допустимый размер')
                return content_type,raw
        except HTTPError as error:
            code=error.code;error.close();raise ValueError(f'Источник аудио вернул HTTP {code}. Повторите проверку доступности позже.') from None
        except (URLError,TimeoutError):raise ValueError('Не удалось получить запись от организаторов. Повторите позже.') from None

    def get(self,cid):
        record=self.record_for(cid)
        if record.get('channel')!='voice call' or not record.get('audio_url'):
            raise ValueError('У этого диалога нет записи звонка')
        with self.lock:
            cached=self.cache.get(cid)
            if cached and time.monotonic()-cached[0]<1800:
                self.cache.move_to_end(cid);return cached[1]
            address=checked_url(record['audio_url'])
            mime,data=self.fetch(address)
            if mime in ['text/html','application/xhtml+xml']:
                parser=AudioSource();parser.feed(data.decode('utf-8',errors='replace'))
                if not parser.sources:raise ValueError('На странице источника не найдена запись')
                address=checked_url(urljoin(address,parser.sources[0]));mime,data=self.fetch(address)
            if not mime.startswith('audio/') and mime!='application/octet-stream':
                raise ValueError('Источник вернул страницу вместо аудиофайла')
            clip=clip_from_bytes(data);self.cache[cid]=(time.monotonic(),clip);self.cache.move_to_end(cid)
            while len(self.cache)>3 or sum(len(v[1].data) for v in self.cache.values())>24_000_000:
                self.cache.popitem(last=False)
            return clip
