"""Bounded event-only PCM capture. No devices, transcription or network."""
from collections import deque
from dataclasses import dataclass
import os
import math
from pathlib import Path
import queue
import re
import struct
import threading
import wave

RATE=16000
MAX_SECONDS=15
MAX_BYTES=44+RATE*2*MAX_SECONDS


@dataclass(frozen=True)
class AudioEvidenceConfig:
    enabled: bool=False
    pre_seconds: float=3.
    post_seconds: float=5.


def validate_wav(path):
    """Accept our canonical mono PCM16 RIFF layout, rejecting trailing payloads."""
    with Path(path).open("rb") as source:
        data=source.read(MAX_BYTES+1)
    if not 46<=len(data)<=MAX_BYTES: raise ValueError('invalid_audio_size')
    if (data[:4]!=b'RIFF' or data[8:16]!=b'WAVEfmt ' or data[36:40]!=b'data' or
        struct.unpack_from('<I',data,4)[0]!=len(data)-8 or
        struct.unpack_from('<IHHIIHH',data,16)!=(16,1,1,RATE,RATE*2,2,16) or
        struct.unpack_from('<I',data,40)[0]!=len(data)-44 or (len(data)-44)%2):
        raise ValueError('invalid_audio_format')
    return (len(data)-44)/(RATE*2)


class AudioEvidence:
    def __init__(self,config,root, *, start_time=None):
        if not config.enabled or not 0 <= config.pre_seconds <= 5 or not 1 <= config.post_seconds <= 8:
            raise ValueError("invalid_audio_configuration")
        self.config,self.root=config,Path(root)
        self.start_time = start_time
        self.lock=threading.Lock();self.ring=deque(maxlen=256);self.pending={};self.seen=set()
        self.jobs=queue.Queue(maxsize=4);self.results=queue.Queue(maxsize=2000)
        self.last=None;self.closed=False
        self.thread=threading.Thread(target=self._write,daemon=True,name='audio-evidence-writer')
        self.thread.start()

    def feed(self,samples,end,rate,healthy=True):
        import numpy as np
        with self.lock:
            if self.closed or (self.start_time is not None and end <= self.start_time):return
            values=np.asarray(samples)
            if (not healthy or not math.isfinite(end) or not math.isfinite(rate) or (values.ndim == 2 and values.shape[1] not in (1,2)) or rate<8000 or rate>192000 or values.size==0 or values.ndim not in (1,2)
                    or len(values)/rate>.5 or not np.isfinite(values).all()):
                self._gap();return
            if np.issubdtype(values.dtype,np.integer):values=values.astype(np.float64)/max(abs(np.iinfo(values.dtype).min),np.iinfo(values.dtype).max)
            if values.ndim==2:values=values.mean(axis=1)
            if self.start_time is not None and end-len(values)/rate < self.start_time:
                values = values[max(0,math.ceil((self.start_time-(end-len(values)/rate))*rate)):]
                if not len(values):return
            duration=len(values)/rate;start=end-duration
            if self.last is not None and (start-self.last>.08 or end<=self.last):self._gap()
            # Each source block is at most 0.5 s. Linear interpolation preserves
            # duration; no detection threshold or capture gain is changed.
            count=round(duration*RATE)
            normalized=np.interp(np.arange(count)*rate/RATE,np.arange(len(values)),values)
            pcm=(np.clip(normalized,-1,1)*32767).astype('<i2').tobytes()
            self.ring.append((end-count/RATE,end,pcm));self.last=end
            while self.ring and self.ring[0][1]<end-self.config.pre_seconds-1:self.ring.popleft()
            for event,item in list(self.pending.items()):
                self._append(item,end-count/RATE,end,pcm)
                if end>=item['end']:self._finish(event)

    @staticmethod
    def _append(item,start,end,pcm):
        left=max(start,item['start'],item['cursor']);right=min(end,item['end'])
        if right<=left:return
        a=max(0,round((left-start)*RATE));b=min(len(pcm)//2,round((right-start)*RATE))
        item['pcm'].extend(pcm[a*2:b*2]);item['cursor']=right

    def trigger(self,event,stamp):
        with self.lock:
            if event in self.seen:return
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}',event):raise ValueError('invalid_event')
            if self.closed or len(self.seen)>=1900: return "capacity_or_closed"
            self.seen.add(event)
            if len(self.pending)>=4:
                return "capture_capacity"
            item={'start':stamp-self.config.pre_seconds,'end':stamp+self.config.post_seconds,
                  'cursor':stamp-self.config.pre_seconds,'pcm':bytearray()}
            for start,end,pcm in self.ring:self._append(item,start,end,pcm)
            item['partial'] = len(item['pcm']) < round(self.config.pre_seconds*RATE)*2
            self.pending[event]=item
            if self.last is not None and self.last>=item['end']:self._finish(event)

    def _finish(self,event,reason=None):
        item=self.pending.pop(event)
        reason = reason or ('insufficient_prebuffer' if item['partial'] else None)
        pcm=bytes(item['pcm'][:RATE*2*MAX_SECONDS])
        if not pcm:self.results.put_nowait((event,None,reason or 'insufficient_audio'));return
        try:self.jobs.put_nowait((event,pcm,reason))
        except queue.Full:self.results.put_nowait((event,None,'writer_capacity'))

    def _gap(self):
        self.ring.clear();self.last=None
        for event in list(self.pending):self._finish(event,'audio_interrupted')

    def interrupt(self):
        with self.lock:
            if not self.closed: self._gap()

    def close(self):
        with self.lock:
            if self.closed:return
            for event in list(self.pending):self._finish(event,'capture_ended_early')
            self.ring.clear()
            # Publish closure only after every final job is queued.
            self.closed=True

    @property
    def finished(self):return self.closed and not self.thread.is_alive()

    def _write(self):
        while True:
            try:event,pcm,reason=self.jobs.get(timeout=.05)
            except queue.Empty:
                if self.closed:return
                continue
            path=self.root/'audio'/f'{event}.wav';temporary=path.with_suffix('.partial')
            created=False
            try:
                path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():raise ValueError('audio_immutable')
                with temporary.open('xb') as handle:
                    created=True
                    with wave.open(handle,'wb') as wav:
                        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE);wav.writeframes(pcm)
                    handle.flush();os.fsync(handle.fileno())
                validate_wav(temporary)
                # Windows rename refuses an existing destination.
                temporary.rename(path)
                self.results.put_nowait((event,'audio/'+path.name,reason))
            except Exception:
                if created:
                    try: temporary.unlink(missing_ok=True)
                    except OSError: pass
                self.results.put_nowait((event,None,'write_failed'))
            finally:self.jobs.task_done()

    def drain(self):
        values=[]
        while True:
            try:values.append(self.results.get_nowait())
            except queue.Empty:return values
