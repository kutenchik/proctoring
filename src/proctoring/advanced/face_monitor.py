"""Bounded optional process; camera publication and controller polling never wait."""
import base64
from dataclasses import asdict
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from uuid import uuid4
from ..domain import EventType, Observation
from ..events import EventEngine


class FaceMonitor:
    def __init__(self, config, clock, session=None):
        self.config,self.clock=config,clock
        self.session=session or str(uuid4())
        self.prefix=uuid4().hex+"-"
        self.inputs=queue.Queue(maxsize=1);self.outputs=queue.Queue(maxsize=1)
        self.stop_event=threading.Event();self.lock=threading.Lock()
        self.thread=None;self.process=None;self.busy=False
        self.state='awaiting_consent';self.identity='reference_required';self.liveness='inconclusive'
        self.generation=0;self.seen_generation=0;self.sequence=0;self.next_at=float('-inf');self.last_valid=None
        self.enroll_requested=False;self.enrolled=False;self.running=False
        self.last_sample=None;self.counts={};self.passed=0;self.next_identity=float('-inf');self.next_liveness=float('-inf')
        self.engines={}
        for key,enabled in [('liveness',config.liveness_enabled),('identity',config.identity_enabled)]:
            if enabled:
                kind=EventType.PRESENTATION_ATTACK_SUSPECTED if key=='liveness' else EventType.IDENTITY_MISMATCH_SUSPECTED
                self.engines[key]=EventEngine({kind:.001},self.interval,clock,
                    max_observation_gap=getattr(config,key+'_interval_seconds')*2.5,accumulate_sample_durations=True)

    @property
    def interval(self):
        return min([value for enabled,value in ((self.config.liveness_enabled,self.config.liveness_interval_seconds),
            (self.config.identity_enabled,self.config.identity_interval_seconds)) if enabled])

    def start(self):
        if self.thread is not None: return
        self.state='initializing'
        self.thread=threading.Thread(target=self._run,daemon=True,name='optional-face-pipe')
        self.thread.start()

    def request_enrollment(self):
        if self.running or self.enrolled: raise RuntimeError('Reference is fixed for this session')
        self.enroll_requested=True

    def offer(self,image,face,timestamp):
        if self.stop_event.is_set() or self.state!='ready': return
        from ..vision.identity import face_quality_reason
        reason=('low_quality' if image.ndim!=3 or image.shape[2]!=3 or image.nbytes>32_000_000 else 'multiple_faces' if face.detected_face_count>1 else 'face_missing' if not face.face_present
                else 'low_quality' if face_quality_reason(face) else None)
        with self.lock:
            if reason:
                self.generation+=1;self.identity=reason;self.liveness='inconclusive';self.last_valid=None
                return
            self.last_valid=timestamp
            if self.busy or timestamp<self.next_at: return
            self.sequence+=1
            request={'session':self.session,'sequence':self.sequence,'timestamp':timestamp,
                     'generation':self.generation,'enroll':self.enroll_requested and not self.running and
                     (not self.config.liveness_enabled or self.passed>=self.config.liveness_confirmations)}
            request['identity_due']=self.config.identity_enabled and timestamp>=self.next_identity
            request['liveness_due']=self.config.liveness_enabled and (timestamp>=self.next_liveness or request['identity_due'])
            if request['identity_due']: self.next_identity=timestamp+self.config.identity_interval_seconds
            if request['liveness_due']: self.next_liveness=timestamp+self.config.liveness_interval_seconds
            self.busy=True;self.next_at=timestamp+self.interval
            self.inputs.put_nowait((image.copy(),face.box,request))

    def _run(self):
        process=None
        try:
            executable=os.environ.get('PROCTOR_FACE_PYTHON','')
            root=os.environ.get('PROCTOR_FACE_RESOURCES','')
            if not Path(executable).is_file() or not Path(root).is_dir(): raise RuntimeError('resources_not_configured')
            flags=(subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name=='nt' else 0
            process=subprocess.Popen([executable,'-u',str(Path(__file__).with_name('face_worker.py'))],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                encoding='utf-8',creationflags=flags)
            self.process=process
            replies=queue.Queue(maxsize=4)
            def read():
                try:
                    while not self.stop_event.is_set():
                        line=process.stdout.readline(16385)
                        if not line or len(line)>16384: break
                        replies.put_nowait(json.loads(line))
                except Exception: pass
            def drain():
                # Do not log upstream exceptions/payloads. Keep the pipe drained until exit.
                while process.stderr.read(4096): pass
            threading.Thread(target=read,daemon=True).start()
            threading.Thread(target=drain,daemon=True).start()
            def send(value):
                process.stdin.write(json.dumps(value,allow_nan=False)+'\n');process.stdin.flush()
            def receive(timeout):
                deadline=time.monotonic()+timeout
                while not self.stop_event.is_set() and time.monotonic()<deadline:
                    try: return replies.get(timeout=.1)
                    except queue.Empty:
                        if process.poll() is not None: raise RuntimeError('worker_exited')
                raise RuntimeError('worker_timeout_or_stopped')
            send({'root':root,'config':asdict(self.config),'session':self.session,'parent_pid':os.getpid()})
            if receive(20).get('state')!='ready': raise RuntimeError('worker_not_ready')
            self.state='ready'
            while not self.stop_event.is_set():
                try: image,box,request=self.inputs.get(timeout=.1)
                except queue.Empty:
                    if process.poll() is not None: raise RuntimeError('worker_exited')
                    continue
                import cv2
                height,width=image.shape[:2]
                scale=min(640/width,480/height,1)
                resized=cv2.resize(image,(int(width*scale),int(height*scale)))
                h,w=resized.shape[:2]
                request['box']=[int(box.x1*w),int(box.y1*h),int(box.width*w),int(box.height*h)]
                ok,jpeg=cv2.imencode('.jpg',resized,[cv2.IMWRITE_JPEG_QUALITY,90])
                if not ok: raise RuntimeError('encoding_failed')
                request['jpeg']=base64.b64encode(jpeg).decode('ascii')
                send(request);result=receive(5)
                if result.get('session')!=self.session or result.get('sequence')!=request['sequence']:
                    raise RuntimeError('worker_protocol_mismatch')
                result["_snapshot_frame"]=image
                self.outputs.put_nowait(result)
                with self.lock: self.busy=False
        except Exception:
            self.state='unavailable'
        finally:
            if process is not None:
                try:
                    if process.stdin: process.stdin.close()
                    process.wait(timeout=.5)
                except (OSError,subprocess.TimeoutExpired):
                    process.kill();process.wait(timeout=2)
                for stream in (process.stdout,process.stderr):
                    if stream: stream.close()
            if self.stop_event.is_set(): self.state='stopped'

    def consume(self,result,active):
        stamp=result['timestamp']
        if (result.get('session')!=self.session or result.get('generation')!=self.generation or
                not 0<=self.clock.monotonic()-stamp<=5 or
                self.last_sample is not None and stamp<=self.last_sample):
            if result.get('identity')=='enrolled':
                # The worker may hold a reference that the controller cannot accept.
                # Fail closed; never overwrite it with an unannounced replacement.
                self.close();self.state='unavailable'
            return []
        if self.last_sample is not None and stamp-self.last_sample>self.interval*2.5:
            self.counts.clear();self.passed=0
        self.last_sample=stamp
        self.identity=result.get('identity',self.identity);self.liveness=result.get('liveness',self.liveness)
        if 'liveness' in result: self.passed=self.passed+1 if self.liveness=='passed' else 0
        if self.identity=='enrolled': self.enrolled=True;self.enroll_requested=False
        changes=[]
        for key,engine in self.engines.items():
            if key not in result: continue
            state=result.get(key,'inconclusive')
            self.counts[key]=self.counts.get(key,0)+1 if state=='suspected' and active else 0
            needed=getattr(self.config,key+'_confirmations')
            if not active: continue
            if state not in ('passed','match','suspected'):
                records=engine.interrupt(state)
            else:
                kind=next(iter(engine.thresholds))
                records=engine.observe(Observation(stamp,{kind:None} if self.counts[key]>=needed else {},'deepface_local',.001))
            safe={'confirmations':needed,'interval_seconds':getattr(self.config,key+'_interval_seconds'),'observed_monotonic':stamp}
            safe.update({k:v for k,v in result.items() if k in ('model','revision','resource_revision','metric','distance','threshold','antispoof_score','identity','liveness')})
            changes.extend({**r,'event_id':key+'-'+self.prefix+r['event_id'],'details':safe,
                **({'_snapshot_frame':result.get('_snapshot_frame')} if r.get('action')=='activated' else {})} for r in records)
        return changes

    def poll(self,active):
        if active and not self.running:
            self.running=True;self.counts.clear();self.generation+=1
        changes=[]
        if self.seen_generation!=self.generation:
            self.seen_generation=self.generation;self.counts.clear();self.passed=0
            for key,e in self.engines.items():
                changes.extend({**r,'event_id':key+'-'+self.prefix+r['event_id']} for r in e.interrupt('face_generation_changed'))
        while True:
            try: changes+=self.consume(self.outputs.get_nowait(),active)
            except queue.Empty: break
        if self.last_valid is None or self.clock.monotonic()-self.last_valid>2 or self.state!='ready':
            self.counts.clear();self.passed=0
            for key,engine in self.engines.items():
                changes.extend({**r,'event_id':key+'-'+self.prefix+r['event_id']} for r in engine.interrupt('face_observation_unavailable'))
        return changes

    @property
    def ready(self):
        return (self.state=='ready' and (not self.config.identity_enabled or self.enrolled) and
                (not self.config.liveness_enabled or self.passed>=self.config.liveness_confirmations))

    @property
    def events(self):
        return [{**r,'event_id':key+'-'+self.prefix+r['event_id']} for key,e in self.engines.items() for r in e.events]

    def close(self):
        self.stop_event.set();self.generation+=1;self.enrolled=False
        process=self.process
        if process is not None and process.poll() is None:
            # An independent reaper also handles a blocked writer. Never waits on Qt.
            def reap():
                try: process.wait(timeout=.75)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=2)
            threading.Thread(target=reap,daemon=True).start()
        changes=[]
        for key,e in self.engines.items():
            changes.extend({**r,'event_id':key+'-'+self.prefix+r['event_id']} for r in e.close_all('monitor_stopped'))
        return changes
