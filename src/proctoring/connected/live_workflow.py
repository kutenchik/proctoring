"""Controller-thread authority for Stage 3 commands, consent and display gates."""
from collections import deque
import json
import math
from uuid import uuid4

from .live import LiveWorker
from .sync import canonical
from .sync import digest
from ..desktop_bridge.protocol import BridgeError


class LiveWorkflow:
    def __init__(self, bridge, *, worker=None, display_count_provider=None):
        self.b,self.c,self.client=bridge,bridge.controller,bridge.admission_client
        self.worker=worker or LiveWorker(self.client)
        self.display_count_provider=display_count_provider or self._display_count
        self.last_display=float('-inf')
        self.last_connection=None
        self.host_messages=deque(maxlen=32)
        self.viewer={'viewer_id':None,'state':'stopped','transport':None,'reason':None}
        self.screen_diagnostic=None
        self.last_stopped_viewer=None
        self.messages=[]
        self.consent_accepted=False;self.consent_acknowledged=False
        self.display={'count':None,'incident_id':None,'ready':False,'calibration_ready':False,'approval_required':False}
        self.display_baseline_id=None
        self.outage=None
        self.event_offset=0;self.event_sequence=0
        self.last_event_batch=float('-inf')
        self.ended_since=None
        self.started=False
        self.error=None

    @staticmethod
    def _display_count():
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.instance() is None:return None
        return len(QGuiApplication.screens())

    def row(self):
        return self.b.connected_sync.row()

    def start(self):
        if self.started:return
        row=self.row()
        if not row or row.get('phase') in ('terminal_pending','ended_locally') or row.get('cleanup'):return
        self.started=True
        self.consent_accepted=bool((row.get('screen_consent') or {}).get('accepted') is True and (row.get('screen_consent') or {}).get('version') == 3)
        self.display.update(row.get('display_incident') or {})
        self.display_baseline_id=row.get('display_calibration_id')
        self._restore_display_incident(row)
        self.messages=list(row.get('teacher_messages',[]))[-20:]
        self.worker.consent(self.consent_accepted)
        self.worker.start()

    def _restore_display_incident(self,row):
        # Existing restart reconciliation has already merged the durable
        # lifecycle tail. It may be newer than the encrypted incident metadata.
        checkpoint=row.get('checkpoint') or {}
        latest=next((record for record in reversed(checkpoint.get('lifecycle',[]))
            if record.get('event_type') in ('display_interrupted','teacher_display_recovered')),None)
        if latest is None:return
        pending=latest['event_type']=='display_interrupted' and 'display' in checkpoint.get('pause_reasons',[])
        if pending:
            incident=latest['incident_id']
            saved=row.get('display_incident') or {}
            baseline=latest.get('calibration_attempt_id') or (
                row.get('display_calibration_id') if saved.get('incident_id')==incident else None)
            # Legacy missing metadata refers to the prior process's baseline.
            # The new process still requires actual fresh samples and geometry;
            # this marker is not calibration readiness or teacher approval.
            self.display_baseline_id=baseline or 'prior-incident:'+incident
            self.display.update(incident_id=incident,approval_required=True,ready=False,calibration_ready=False,count=None)
        else:
            self.display.update(approval_required=False,ready=False,calibration_ready=False,count=None)
        self.client.persist(display_incident=dict(self.display),display_calibration_id=self.display_baseline_id)

    def consent(self, accepted):
        if self.c.session.started:raise BridgeError('wrong_state','Screen consent is fixed after start')
        self.consent_accepted=accepted;self.consent_acknowledged=False
        self.client.persist(screen_consent={'accepted':accepted,'version':3,'timestamp':self.b.clock.wall_time()})
        self.worker.consent(accepted)

    def prepare_start(self):
        self.require_display()
        if not self.consent_accepted or not self.consent_acknowledged:
            raise BridgeError('screen_consent_required','Screen-viewing consent must be recorded before start')
        self.c._ensure_store().update_metadata({'screen_viewing_consent':self.row().get('screen_consent')})

    def require_display(self):
        self.check_display(force=True)
        if not self.display['ready']:
            raise BridgeError('single_display_required','Exactly one active display is required. Disconnect additional displays in Windows or physically.')

    @property
    def recalibrating(self):
        return bool(self.c.session.started and not self.c.session.ended and 'display' in self.c.session.pause_reasons
                    and self.display['ready'] and not self.b._protected_requested)

    def check_display(self, force=False):
        now=self.b.clock.monotonic()
        if not force and now-self.last_display<1:return
        self.last_display=now
        try:count=self.display_count_provider()
        except Exception:count=None
        if type(count) is not int or count<0:count=None
        self.display.update(count=count,ready=count==1)
        session=self.c.session
        if not session.started and count!=1 and (self.b.flow.active or any(self.c.monitor.calibration.counts.values())):
            self.b.flow.reset()
            self.b.flow.message='Exactly one active display is required. Disconnect additional displays before calibration.'
        if session.started and not session.ended and count!=1 and not self.display['approval_required']:
            incident=uuid4().hex
            self.display.update(incident_id=incident,approval_required=True,calibration_ready=False)
            self.display_baseline_id=self.b.flow.attempt_id
            self.c.session.display_pause(incident_id=incident,screen_count=count,calibration_attempt_id=self.display_baseline_id)
            # The existing protected geometry terminal rule retains priority.
            # We do not change native geometry/containment or rearm protection.
            if not self.b._protected_requested:self.b.flow.reset()
            self.c._write_session_records()
            self.client.persist(display_incident=dict(self.display),display_calibration_id=self.display_baseline_id)
            self.b.connected_sync.checkpoint(force=True)
            self._stop_viewer('display_changed')
        self.display['calibration_ready']=bool(count==1 and self.c.monitor.calibration.ready and
            (not self.display['approval_required'] or self.b.flow.attempt_id!=self.display_baseline_id) and
            self.b._geometry is not None and self.b.flow.baseline_geometry_id==self.b._geometry.get('geometry_id'))

    def _outage(self):
        records=self.c.session.records
        last=next((r for r in reversed(records) if r['event_type']=='monitoring_failed'),None)
        if last is None:return None
        index=next(i for i in range(len(records)-1,-1,-1) if records[i]['event_type']=='monitoring_failed')
        identity=f'outage-{index}'
        if not self.outage or self.outage['outage_id']!=identity:
            self.outage={'outage_id':identity,'duration_seconds':0.,'healthy':False,'recovery_required':False}
        recovered=next((r for r in records[index+1:] if r['event_type'] in ('monitoring_recovered','monitoring_interruption_ended')),None)
        failure=self.c.session._failure_since
        duration=recovered.get('duration',0.) if recovered else max(0.,self.b.clock.monotonic()-(failure if failure is not None else self.b.clock.monotonic()))
        self.outage.update(duration_seconds=duration,healthy=self.c.session.monitoring_healthy,recovery_required=self.c.session.recovery_pin_required)
        return dict(self.outage)

    def status(self):
        s=self.c.session
        return {'state':'ended' if s.ended else 'preparation' if not s.started else 'running' if s.running else 'paused',
                'elapsed_seconds':s.elapsed_seconds,'remaining_seconds':s.remaining_seconds,'duration_seconds':s.duration_seconds,
                'answered':None if self.b.config.external_url else self.c.quiz.answered_count,
                'total':None if self.b.config.external_url else self.c.quiz.total,
                'monitoring_healthy':self.c.monitor.health(self.b.clock.monotonic()).healthy,'pause_reasons':sorted(s.pause_reasons),
                'monitoring_outage':self._outage(),'display':dict(self.display),'screen_consent':self.consent_accepted}

    def tick(self):
        self.start()
        if not self.started:return
        connection=self.worker.connection_id
        if connection!=self.last_connection:
            self.consent_acknowledged=False
            self._stop_viewer('control_disconnected')
            self.last_connection=connection
        self.check_display()
        for generation,message,deadline in self.worker.drain():
            if generation!=connection or connection is None:continue
            kind=message.get('type')
            if kind=='consent':
                self.consent_acknowledged=bool(message.get('accepted') is True and message.get('version')==3 and
                    message.get('session_id')==self.b._session_id() and self.consent_accepted)
                if self.consent_acknowledged:self.client.persist(screen_consent={'accepted':True,'version':3,'timestamp':message.get('recorded_at')})
            elif kind=='command':
                try:self.apply_command(message,generation,deadline)
                except Exception:
                    # A mutation may already have applied. Never forge rejection
                    # or success when its durable result cannot be confirmed.
                    self.error='command_result_unconfirmed';self.worker.close()
            elif kind=='view.start':self._start_viewer(message)
            elif kind in ('view.stop','view.expired') and message.get('viewer_id')==self.viewer['viewer_id']:
                self._stop_viewer(str(message.get('reason','view_stopped'))[:128])
        self.worker.publish(self.status())
        self._events()
        if self.c.session.ended:
            self._stop_viewer('session_ended')
            if self.ended_since is None:self.ended_since=self.b.clock.monotonic()
            if self.b.clock.monotonic()-self.ended_since>=1.5:self.worker.close()

    def _events(self):
        if self.worker.connection_id is None or self.c.store is None:return
        now=self.worker.clock()
        if now-self.last_event_batch<.25:return
        self.last_event_batch=now
        path=self.c.store.path/'events.jsonl'
        if not path.is_file():return
        try:stream=path.open('rb')
        except FileNotFoundError:return  # matching-receipt cleanup may finish
        with stream:
            stream.seek(self.event_offset)
            for _ in range(4):
                line=stream.readline(65537)
                if not line:break
                if not line.endswith(b'\n'):break
                record=json.loads(line)
                if len(canonical(record))>65536:break
                send=getattr(self.worker,'send_notification',self.worker.send)
                if not send({'type':'event','sequence':self.event_sequence,'record':record}):break
                self.event_offset=stream.tell();self.event_sequence+=1

    def _audit(self,command,outcome,code):
        self.c._append({'record_kind':'lifecycle','event_type':'teacher_command','timestamp':self.b.clock.wall_time(),
            'command_id':command['command_id'],'teacher_id':command['teacher_id'],'command_type':command['command_type'],
            'reason':command.get('payload',{}).get('reason'),'outcome':outcome,'code':code})

    def _ack(self,command,phase,result,reason=None):
        value={'type':'command_ack','command_id':command.get('command_id'),'phase':phase,'result':result}
        if reason:value['reason']=reason
        self.worker.send(value,command.get('connection_id'))

    def apply_command(self,command,generation,deadline):
        row=self.row();s=self.c.session
        if not row:return
        required=('command_id','teacher_id','exam_id','attempt_id','session_id','connection_id','command_type')
        if any(not isinstance(command.get(k),str) or not 1<=len(command[k])<=128 for k in required):return
        if (command['attempt_id']!=row['attempt_id'] or command['session_id']!=row['session_id'] or
                command['exam_id']!=self.client.admission['exam']['id'] or command['connection_id']!=generation or
                generation!=self.worker.connection_id or deadline is None or self.worker.clock()>=deadline):
            self._ack(command,'rejected',{'code':'stale_command'},'stale_command');return
        ledger=row.get('live_commands',{})
        prior=ledger.get(command['command_id'])
        if prior:
            if prior.get('fingerprint')!=digest({k:command.get(k) for k in (*required,'payload')}):
                self._ack(command,'rejected',{'code':'command_conflict'},'command_conflict');return
            self._ack(command,prior['phase'],prior['result'],prior.get('reason'));return
        if len(ledger)>=2048:
            self._ack(command,'rejected',{'code':'command_limit'},'command_limit');return
        self._ack(command,'received',{})
        s.tick();kind=command['command_type'];payload=command.get('payload');code='invalid_command';applied=False
        old_duration=s.duration_seconds
        if not s.started or s.ended:
            if s.ended and self.c.summary is None:self.c.end(s.end_reason)
            code='terminal_attempt' if s.ended else 'attempt_not_started'
            self._ack(command,'rejected',{'code':code},code)
            return
        if isinstance(payload,dict) and s.started and not s.ended:
            audit={'command_id':command['command_id'],'teacher_id':command['teacher_id']}
            reason=payload.get('reason')
            reason_valid=isinstance(reason,str) and 1<=len(reason.strip())<=1000 and not any(ord(c)<32 for c in reason)
            if kind=='warning' and set(payload)=={'text'} and isinstance(payload['text'],str) and 1<=len(payload['text'].strip())<=400 and not any(ord(c)<32 for c in payload['text']):
                self.messages=[*self.messages,{'command_id':command['command_id'],'teacher_id':command['teacher_id'],
                    'text':payload['text'],'timestamp':self.b.clock.wall_time()}][-20:]
                applied=True
            elif reason_valid:
                audit['reason']=reason
                if kind=='pause' and set(payload)=={'reason'}:applied=s.teacher_pause(**audit)
                elif kind=='resume' and set(payload)=={'reason'}:applied=s.teacher_resume(**audit)
                elif kind=='end' and set(payload)=={'reason','confirm'} and payload['confirm'] is True:
                    # Existing end releases protection before media/report work.
                    self._audit(command,'requested','teacher_end_requested')
                    self.c.end('teacher_ended');applied=True
                elif kind=='add_time' and set(payload)=={'reason','seconds'}:
                    applied=s.teacher_add_time(payload['seconds'],**audit)
                elif kind=='monitoring_recovery' and set(payload)=={'reason','outage_id'}:
                    outage=self._outage()
                    if (outage and outage['outage_id']==payload['outage_id'] and outage['duration_seconds']>=15 and
                            self.c.monitor.health(self.b.clock.monotonic()).healthy):
                        applied=s.teacher_monitoring_recovery(**audit)
                elif kind=='display_recovery' and set(payload)=={'reason','incident_id'}:
                    self.check_display(force=True)
                    if (payload['incident_id']==self.display['incident_id'] and self.display['approval_required'] and
                            self.display['ready'] and self.display['calibration_ready'] and
                            self.c.monitor.health(self.b.clock.monotonic()).healthy):
                        applied=s.teacher_display_recovery(**audit)
                        if applied:self.display.update(approval_required=False)
            code='applied' if applied else 'local_precondition_failed'
        elif s.ended:code='terminal_attempt'
        result={key:value for key,value in self.status().items() if key in ('state','pause_reasons','elapsed_seconds','remaining_seconds','duration_seconds')}
        result['code']=code
        if kind=='add_time' and applied:
            result.update(old_duration_seconds=old_duration,new_duration_seconds=s.duration_seconds,
                          delta_seconds=s.duration_seconds-old_duration)
        outcome={'phase':'applied' if applied else 'rejected','result':result,'reason':None if applied else code,
                 'fingerprint':digest({k:command.get(k) for k in (*required,'payload')})}
        if kind!='end' or not applied:self._audit(command,outcome['phase'],code)
        self.c._write_session_records()
        if self.c.store:self.c.store.flush_durable()
        ledger[command['command_id']]=outcome
        self.client.persist(live_commands=ledger,teacher_messages=list(self.messages),display_incident=dict(self.display),
                            checkpoint=self.b.connected_sync.make_checkpoint())
        self._ack(command,outcome['phase'],result,outcome['reason'])

    def _start_viewer(self,message):
        if (message.get('attempt_id')!=self.client.admission['attempt_id'] or message.get('session_id')!=self.b._session_id() or
                not self.c.session.started or self.c.session.ended or not self.consent_accepted or not self.display['ready'] or
                not isinstance(message.get('viewer_id'),str) or not isinstance(message.get('sender_token'),str)):
            return
        self._stop_viewer('viewer_replaced')
        if self._host_message({**message,'server_url':self.client.server}):
            self.viewer={'viewer_id':message['viewer_id'],'state':'starting','transport':None,'reason':None}

    def _host_message(self,message):
        if len(self.host_messages)>=31:
            self.error='live_queue_full';self.worker.close()
            self.host_messages.clear()
            if self.viewer['viewer_id']:
                self.host_messages.append({'type':'view.stop','viewer_id':self.viewer['viewer_id'],'reason':'live_queue_full'})
            self.viewer={'viewer_id':None,'state':'stopped','transport':None,'reason':'live_queue_full'}
            return False
        self.host_messages.append(message)
        return True

    def _stop_viewer(self,reason):
        if self.viewer['viewer_id']:
            self.last_stopped_viewer=self.viewer['viewer_id']
            self._host_message({'type':'view.stop','viewer_id':self.viewer['viewer_id'],'reason':reason})
        if self.screen_diagnostic and self.screen_diagnostic['viewer_id']==self.last_stopped_viewer:
            reason=self.screen_diagnostic['code']
        self.viewer={'viewer_id':None,'state':'stopped','transport':None,'reason':reason}

    def capture(self,payload):
        diagnostic=payload.get('diagnostic')
        current=payload['viewer_id']==self.viewer['viewer_id']
        # The server's close can beat this host RPC. Accept terminal evidence for
        # that one stopped identity without reviving it or altering a newer view.
        if not current and not (diagnostic and payload['viewer_id']==self.last_stopped_viewer and self.viewer['viewer_id'] is None):
            raise BridgeError('stale_viewer','Viewer lease is not current')
        if diagnostic:
            if self.screen_diagnostic and self.screen_diagnostic['viewer_id']==payload['viewer_id']:
                return
            self.screen_diagnostic=dict(diagnostic)
        if not current:
            self.viewer['reason']=self.screen_diagnostic['code'];return
        if self.screen_diagnostic and self.screen_diagnostic['viewer_id']==payload['viewer_id'] and not diagnostic:
            return  # Late starting/live reports cannot overwrite a terminal failure.
        if (payload['state'] in ('live','degraded','recovering') and
                (not self.worker.connection_id or not self.c.session.started or self.c.session.ended or not self.consent_accepted)):
            self._stop_viewer('session_unavailable');return
        self.viewer.update({k:v for k,v in payload.items() if k!='diagnostic'})
        if payload['state']=='stopped':
            self.last_stopped_viewer=self.viewer['viewer_id'];self.viewer['viewer_id']=None

    def poll_host(self):
        messages=list(self.host_messages);self.host_messages.clear()
        return {'messages':messages,'connection':self.worker.connection}

    def public(self):
        return {'connection':self.worker.connection,'error':self.error or self.worker.error,
                'consent':{'accepted':self.consent_accepted,'version':3,'acknowledged':self.consent_acknowledged},
                'viewing':dict(self.viewer),'messages':list(self.messages),'display':dict(self.display),
                'monitoring_outage':self._outage(),'screen_diagnostic':self.screen_diagnostic}

    def close(self):
        self._stop_viewer('application_shutdown');self.worker.close()
