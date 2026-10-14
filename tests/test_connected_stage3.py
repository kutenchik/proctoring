"""Focused authority/IPC regressions with controlled clocks and fake devices."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from proctoring.connected.live_workflow import LiveWorkflow
from proctoring.desktop_bridge.protocol import BridgeError,parse_request
from proctoring.session import SessionController
from proctoring.clock import FakeClock
from test_connected_stage2 import workflow
from test_connected_workflow import prepare,start


class Worker:
    def __init__(self,clock):
        self.clock=clock;self.connection_id='connection-a';self.connection='online';self.error=None
        self.incoming=[];self.sent=[];self.latest=None;self.started=False;self.closed=False
    def start(self):self.started=True
    def close(self):self.closed=True;self.connection_id=None;self.connection='offline'
    def publish(self,status):self.latest=deepcopy(status)
    def consent(self,accepted):self.accepted=accepted
    def send(self,message,connection_id=None):
        if not self.connection_id:return False
        self.sent.append(deepcopy(message));return True
    def drain(self):
        items,self.incoming=self.incoming,[];return items


def make_live(tmp_path,started=True):
    b,t,j=workflow(tmp_path);count=[1];w=Worker(b.clock.monotonic)
    live=LiveWorkflow(b,worker=w,display_count_provider=lambda:count[0]);b.live_teacher=live
    b.tick();b.dispatch('screen.consent',{'accepted':True})
    w.incoming.append((w.connection_id,{'type':'consent','accepted':True,'version':3,'session_id':b._session_id(),'recorded_at':b.clock.wall_time()},None))
    b.tick();prepare(b)
    b._geometry={'geometry_id':'geometry-a'};b.flow.baseline_geometry_id='geometry-a'
    if started:start(b)
    return b,t,j,w,count


def command(b,w,kind,payload,**changes):
    row=b.connected_sync.row()
    value={'type':'command','command_id':uuid4().hex,'teacher_id':'teacher-a','exam_id':b.admission_client.admission['exam']['id'],
           'attempt_id':row['attempt_id'],'session_id':row['session_id'],'connection_id':w.connection_id,
           'command_type':kind,'payload':payload,**changes}
    b.live_teacher.apply_command(value,w.connection_id,w.clock()+10)
    return value


def test_warning_is_nonblocking_durable_and_not_answer_disclosure(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        before=b.controller.session.elapsed_seconds
        command(b,w,'warning',{'text':'Please keep your work visible.'})
        b.clock.advance(1);b.tick()
        assert b.controller.session.running and b.controller.session.elapsed_seconds==before+1
        assert b.state()['live_teacher']['messages'][0]['text']=='Please keep your work visible.'
        assert j.attempts()[0]['teacher_messages']
        assert 'answers' not in json.dumps(w.latest) and 'score' not in json.dumps(w.latest)
    finally:b.close()


def test_teacher_pause_resume_preserve_monitoring_proctor_and_offline_state(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        command(b,w,'pause',{'reason':'Clarification'})
        b.dispatch('proctor.pause',{'pin':'2468'})
        b.controller.session.monitoring_failed('camera unavailable')
        command(b,w,'resume',{'reason':'Continue when local checks allow'})
        assert b.controller.session.pause_reasons=={'proctor','monitoring'}
        command(b,w,'pause',{'reason':'Wait'})
        w.connection_id=None;w.connection='offline';b.clock.advance(2);b.tick()
        assert 'teacher' in b.controller.session.pause_reasons and not b.controller.session.running
        assert 'teacher' in j.attempts()[0]['checkpoint']['pause_reasons']
    finally:b.close()


def test_add_time_is_idempotent_and_checkpoint_restores_effective_allowance(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        s=b.controller.session;old=s.duration_seconds;elapsed=s.elapsed_seconds
        value=command(b,w,'add_time',{'seconds':60,'reason':'Compensate interruption'})
        b.live_teacher.apply_command(value,w.connection_id,w.clock()+10)
        assert s.duration_seconds==old+60 and s.elapsed_seconds==elapsed
        restored=SessionController(FakeClock(),old)
        restored.restore_connected_checkpoint(j.attempts()[0]['checkpoint'])
        assert restored.duration_seconds==old+60 and restored.time_adjustment_ids==[value['command_id']]
        assert b.state()['workflow']['session']['duration_seconds']==old+60
        conflict={**value,'payload':{'seconds':120,'reason':'Altered'}}
        b.live_teacher.apply_command(conflict,w.connection_id,w.clock()+10)
        assert w.sent[-1]['result']['code']=='command_conflict'
    finally:b.close()


@pytest.mark.parametrize('change',[{'attempt_id':'other'},{'session_id':'other'},{'exam_id':'other'},{'connection_id':'old'}])
def test_old_binding_never_affects_current_exam(tmp_path,change):
    b,t,j,w,count=make_live(tmp_path)
    try:
        command(b,w,'pause',{'reason':'No'},**change)
        assert b.controller.session.running and w.sent[-1]['result']['code']=='stale_command'
    finally:b.close()


def test_expired_or_offline_generation_command_is_not_replayed(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        value=command(b,w,'warning',{'text':'Initial'})
        value.update(command_id=uuid4().hex,command_type='pause',payload={'reason':'Expired'})
        b.live_teacher.apply_command(value,w.connection_id,w.clock())
        assert b.controller.session.running
        w.incoming.append(('connection-a',value,w.clock()+10));w.connection_id='connection-b'
        b.tick();assert b.controller.session.running
    finally:b.close()


def test_monitoring_recovery_clears_only_matching_healthy_long_outage(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        b.monitor.healthy=False;b.tick();b.clock.advance(16);b.tick()
        outage=b.live_teacher.public()['monitoring_outage'];assert outage['recovery_required']
        command(b,w,'monitoring_recovery',{'outage_id':outage['outage_id'],'reason':'Ready'})
        assert b.controller.session.recovery_pin_required
        b.monitor.healthy=True;b.monitor.publish();b.tick()
        command(b,w,'pause',{'reason':'Independent pause'})
        command(b,w,'monitoring_recovery',{'outage_id':outage['outage_id'],'reason':'Camera recovered'})
        assert not b.controller.session.recovery_pin_required
        assert b.controller.session.pause_reasons=={'teacher'}
    finally:b.close()


def test_display_change_requires_one_display_new_fit_and_teacher_grant(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        count[0]=2;b.clock.advance(1);b.tick()
        assert b.controller.session.pause_reasons=={'display'} and not b.monitor.calibration.ready
        incident=b.live_teacher.display['incident_id']
        command(b,w,'display_recovery',{'incident_id':incident,'reason':'Try too early'})
        assert 'display' in b.controller.session.pause_reasons
        count[0]=1;b.clock.advance(1);b.tick()
        assert b._step=='calibration'
        command(b,w,'display_recovery',{'incident_id':incident,'reason':'Still no fresh fit'})
        assert 'display' in b.controller.session.pause_reasons
        # Synthetic accepted fit only; hardware calibration is not bypassed in app.
        from test_desktop_workflow import make_ready
        b.controller.session.started=False
        make_ready(b)
        b.controller.session.started=True
        b.flow.baseline_geometry_id=b._geometry['geometry_id']
        command(b,w,'pause',{'reason':'Independent teacher pause'})
        command(b,w,'display_recovery',{'incident_id':incident,'reason':'Fresh fit checked'})
        assert b.controller.session.pause_reasons=={'teacher'}
    finally:b.close()


def test_missing_display_or_screen_consent_blocks_preparation_and_start(tmp_path):
    b,t,j,w,count=make_live(tmp_path,started=False)
    try:
        count[0]=2
        with pytest.raises(BridgeError,match='Exactly one'):b.dispatch('calibration.start',{})
        assert not b.monitor.calibration.ready
        count[0]=1;b.live_teacher.require_display()
        b.dispatch('screen.consent',{'accepted':False})
        assert not b.readiness()['ready']
        with pytest.raises(BridgeError):b.dispatch('exam.start',{})
    finally:b.close()


def test_teacher_end_and_emergency_are_terminal_and_trigger_normal_sync(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    value=command(b,w,'end',{'reason':'Exam concluded','confirm':True})
    try:
        b.tick();assert b.controller.session.ended and b.controller.summary['end_reason']=='teacher_ended'
        b.live_teacher.apply_command(value,w.connection_id,w.clock()+10)
        assert w.sent[-1]['phase']=='applied' and j.attempts()[0]['phase']=='ended_locally'
        command(b,w,'add_time',{'seconds':60,'reason':'Too late'})
        assert w.sent[-1]['result']['code']=='terminal_attempt'
    finally:b.close()


def test_viewer_token_only_in_host_poll_actual_capture_status_controls_indicator(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        row=j.attempts()[0]
        msg={'type':'view.start','viewer_id':'view-a','attempt_id':row['attempt_id'],'session_id':row['session_id'],
             'sender_token':'viewer-secret','lease_seconds':30,'expires_at':b.clock.wall_time(),'limits':{}}
        w.incoming.append((w.connection_id,msg,None));b.tick()
        assert b.state()['live_teacher']['viewing']['state']=='starting'
        assert 'viewer-secret' not in json.dumps(b.state())
        poll=b.dispatch('live.poll',{}).data
        assert poll['messages'][-1]['sender_token']=='viewer-secret' and poll['messages'][-1]['server_url']==b.admission_client.server
        b.dispatch('live.capture',{'viewer_id':'view-a','state':'live','transport':'relay','reason':None})
        assert b.state()['live_teacher']['viewing']['state']=='live'
        w.connection_id=None;b.tick()
        assert b.state()['live_teacher']['viewing']['state']=='stopped'
        assert b.dispatch('live.poll',{}).data['messages'][0]['type']=='view.stop'
    finally:b.close()


def test_capture_ipc_rejects_unbounded_or_extra_fields():
    def parse(payload):return parse_request(json.dumps({'version':1,'id':'x','command':'live.capture','payload':payload}).encode())
    valid={'viewer_id':'view-a','state':'live','transport':'relay','reason':None}
    assert parse(valid)
    assert parse({**valid,'state':'recovering','reason':'capture_geometry_changed'})
    with pytest.raises(BridgeError):parse({**valid,'secret':'bad'})
    with pytest.raises(BridgeError):parse({**valid,'reason':'x'*129})


def screen_diagnostic(viewer):
    return {'timestamp':'2026-10-14T10:00:00.000Z','generation':1,'viewer_id':viewer,
        'component':'capture','phase':'capture','code':'privacy_mask_unavailable','description':'privacy mask unavailable',
        'transport':'direct','capture_state':'in_flight','viewer_state':'attached','requested':False,
        'ws_close_code':None,'ws_close_reason':None,'transition':'lease_revoked','fallback':None,'secondary':[]}


@pytest.mark.parametrize('server_first',[False,True])
def test_screen_first_failure_survives_disconnect_and_late_reports(tmp_path,server_first):
    b,t,j,w,count=make_live(tmp_path)
    try:
        viewer=uuid4().hex;live=b.live_teacher
        live._start_viewer({'type':'view.start','viewer_id':viewer,'attempt_id':j.attempts()[0]['attempt_id'],
            'session_id':b._session_id(),'sender_token':'private-capability'})
        if server_first:live._stop_viewer('disconnected')
        diagnostic={**screen_diagnostic(viewer),'geometry':geometry_diagnostic()}
        payload={'viewer_id':viewer,'state':'unavailable','transport':'direct','reason':diagnostic['code'],'diagnostic':diagnostic}
        parse_request(json.dumps({'version':1,'id':'x','command':'live.capture','payload':payload}).encode())
        b.dispatch('live.capture',payload)
        duplicate={**diagnostic,'code':'disconnected','description':'disconnected'}
        b.dispatch('live.capture',{**payload,'reason':'disconnected','diagnostic':duplicate})
        assert live.public()['screen_diagnostic']==diagnostic
        if not server_first:
            b.dispatch('live.capture',{'viewer_id':viewer,'state':'starting','transport':None,'reason':'waiting_for_verified_frame'})
            assert live.viewer['state']=='unavailable'
        live._stop_viewer('disconnected');live._stop_viewer('session_ended')
        assert live.public()['screen_diagnostic']==diagnostic
        assert live.viewer['reason']=='privacy_mask_unavailable'
        assert 'private-capability' not in json.dumps(live.public())
        new=uuid4().hex
        live._start_viewer({'type':'view.start','viewer_id':new,'attempt_id':j.attempts()[0]['attempt_id'],
            'session_id':b._session_id(),'sender_token':'new-private-capability'})
        with pytest.raises(BridgeError):live.capture(payload)
        assert live.viewer['viewer_id']==new and live.viewer['state']=='starting'
    finally:b.close()


def test_screen_diagnostic_schema_rejects_private_text_and_matches_typescript():
    from pathlib import Path
    import re
    from proctoring.connected.screen_diagnostic import SCREEN_CODES, valid_diagnostic
    source=(Path(__file__).parents[1]/'shared/screen-diagnostic.ts').read_text().split('] as const')[0]
    assert SCREEN_CODES==set(re.findall(r"'([a-z_]+)'",source))
    d=screen_diagnostic(uuid4().hex);assert valid_diagnostic(d)
    for patch in ({'description':'secret'}, {'code':'secret'}, {'ws_close_reason':'https://secret'},
                  {'secondary':['socket_cleanup_failed']*5}, {'answers':{}}, {'generation':True}):
        assert not valid_diagnostic({**d,**patch})


def geometry_diagnostic():
    snapshot={'sampled_at':1791956303049,'window_destroyed':False,'web_contents_destroyed':False,'display_count':1,'display_id':1,
        'content':[0,0,800,600],'display_bounds':[0,0,1920,1080],'display_size':[1920,1080],
        'display_scale':1,'zoom':1,'focused':True,'maximized':False}
    return {'stage':'after_sources','failed':['content_x'],'before':snapshot,'after':{**snapshot,'content':[1,0,800,600]},
        'events':[{'event':'focus','at':1791956303049,'content':[0,0,800,600],'zoom':1,'focused':True}],
        'source':{'matches':1,'width':1280,'height':720,'empty':False}}


def test_screen_geometry_diagnostic_closed_numeric_schema_and_typescript_parity():
    from copy import deepcopy
    from pathlib import Path
    import re
    from proctoring.connected.screen_geometry import STAGES, CHECKS, EVENTS
    from proctoring.connected.screen_diagnostic import valid_diagnostic
    source=(Path(__file__).parents[1]/'shared/screen-geometry.ts').read_text()
    for name,values in [('STAGES',STAGES),('CHECKS',CHECKS),('EVENTS',EVENTS)]:
        block=source.split('GEOMETRY_'+name+' = [')[1].split('] as const')[0]
        assert set(values)==set(re.findall(r"'([a-z_-]+)'",block))
    d={**screen_diagnostic(uuid4().hex),'geometry':geometry_diagnostic()}
    assert valid_diagnostic(d)
    for patch in ({'stage':'private-url'}, {'failed':['content_x','content_x']}, {'events':d['geometry']['events']*17},
                  {'answers':{}}, {'source':{'matches':True,'width':1,'height':1,'empty':False}},
                  {'before':{**d['geometry']['before'],'zoom':float('nan')}},
                  {'before':{**d['geometry']['before'],'content':['secret',0,1,1]}}):
        bad=deepcopy(d);bad['geometry'].update(patch);assert not valid_diagnostic(bad)


def test_quiz_commands_and_progress_do_not_revoke_screen_viewer(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        live=b.live_teacher;viewer=uuid4().hex
        live._start_viewer({'type':'view.start','viewer_id':viewer,'attempt_id':j.attempts()[0]['attempt_id'],
            'session_id':b._session_id(),'sender_token':'private-capability'})
        live.poll_host()
        b.dispatch('live.capture',{'viewer_id':viewer,'state':'live','transport':'direct','reason':None})
        for i in range(12):
            quiz=b.state()['workflow']['quiz']
            b.dispatch('quiz.answer',{'question_index':0,'option_indices':[i%2],'revision':quiz['revision']})
            b.dispatch('quiz.navigate',{'question_index':i%quiz['total']})
            b.tick()
            assert live.viewer['viewer_id']==viewer and live.viewer['state']=='live'
            assert not live.poll_host()['messages']
        assert 'answers' not in json.dumps(live.status())
    finally:b.close()


@pytest.mark.parametrize('kind,payload',[
    ('pause',{'reason':'Durable pause'}),('add_time',{'seconds':60,'reason':'Durable extension'})])
def test_journal_recovers_command_when_encrypted_checkpoint_commit_fails(tmp_path,monkeypatch,kind,payload):
    b,t,j,w,count=make_live(tmp_path)
    old=b.controller.session.duration_seconds
    original=b.admission_client.persist
    def fail_result(**values):
        if 'live_commands' in values:raise OSError('injected durable commit failure')
        return original(**values)
    monkeypatch.setattr(b.admission_client,'persist',fail_result)
    value={'type':'command','command_id':uuid4().hex,'teacher_id':'teacher-a','exam_id':b.admission_client.admission['exam']['id'],
           'attempt_id':j.attempts()[0]['attempt_id'],'session_id':b._session_id(),'connection_id':w.connection_id,
           'command_type':kind,'payload':payload}
    w.incoming.append((w.connection_id,value,w.clock()+10))
    # tick isolates the ambiguous outcome; no successful ACK may be invented.
    b.live_teacher.tick()
    assert b.live_teacher.error=='command_result_unconfirmed' and w.closed
    assert not any(m.get('phase')=='applied' for m in w.sent)
    assert not j.attempts()[0].get('live_commands')
    b.controller.store.close();b.monitor.stop();b.audio.stop()
    b2,_,_=workflow(tmp_path,t,j)
    try:
        b2.admission_client._thread.join(2);b2.tick()
        b2.admission_client._thread.join(2);b2.tick()
        saved=j.attempts()[0]['checkpoint']
        if kind=='pause':assert 'teacher' in saved['pause_reasons']
        else:
            assert saved['duration_seconds']==old+60
            assert saved['time_adjustment_ids']==[value['command_id']]
        t.reply['recovery'].update(state='granted',grant_id='test-new-grant')
        b2.dispatch('connected.refresh',{});b2.admission_client._thread.join(2);b2.tick()
        prepare(b2);start(b2)
        w2=Worker(b2.clock.monotonic);w2.connection_id='connection-b'
        b2.live_teacher=LiveWorkflow(b2,worker=w2,display_count_provider=lambda:1)
        b2.live_teacher.apply_command(value,w2.connection_id,w2.clock()+10)
        assert w2.sent[-1]['result']['code']=='stale_command'
        assert b2.controller.session.duration_seconds==old+(60 if kind=='add_time' else 0)
        if kind=='pause':assert 'teacher' in b2.controller.session.pause_reasons
    finally:b2.close()


def test_event_catchup_throttles_and_retries_same_sequence_under_backpressure(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        for i in range(20):b.controller._append({'record_kind':'lifecycle','event_type':'test_notice','number':i})
        b.controller.store.flush_durable();live=b.live_teacher
        w.sent.clear();live.event_offset=live.event_sequence=0;live.last_event_batch=float('-inf')
        live._events();live._events()
        assert len(w.sent)==4 and live.event_sequence==4
        w.send_notification=lambda _:False
        b.clock.advance(.25);live._events();assert live.event_sequence==4
        w.send_notification=w.send
        b.clock.advance(.25);live._events()
        assert w.sent[-4]['sequence']==4 and len(w.sent)==8
    finally:b.close()


def test_protected_display_incident_does_not_accept_unchanged_old_fit(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        b._protected_requested=True  # no native adapter or hook is armed
        count[0]=2;b.clock.advance(1);b.live_teacher.tick()
        count[0]=1;b.clock.advance(1);b.live_teacher.tick()
        assert b.monitor.calibration.ready  # retained, but no longer sufficient
        assert not b.live_teacher.display['calibration_ready']
        command(b,w,'display_recovery',{'incident_id':b.live_teacher.display['incident_id'],'reason':'Old fit'})
        assert 'display' in b.controller.session.pause_reasons
    finally:b._protected_requested=False;b.close()


def test_notification_queue_reserves_ack_capacity_without_closing():
    from proctoring.connected.live import LiveWorker
    w=LiveWorker(None);w.connection_id='a'
    for i in range(16):assert w.send_notification({'type':'event','sequence':i})
    assert not w.send_notification({'type':'event','sequence':16})
    assert not w.stop_event.is_set()
    assert w.send({'type':'command_ack','command_id':'a'})


def test_host_queue_overflow_stops_capture_and_control_instead_of_eviction(tmp_path):
    b,t,j,w,count=make_live(tmp_path)
    try:
        live=b.live_teacher;live.viewer.update(viewer_id='active',state='live')
        for i in range(31):live.host_messages.append({'type':'view.start','viewer_id':str(i)})
        assert not live._host_message({'type':'view.start','viewer_id':'overflow'})
        assert w.closed and live.public()['viewing']['state']=='stopped'
        assert live.poll_host()['messages']==[{'type':'view.stop','viewer_id':'active','reason':'live_queue_full'}]
    finally:b.close()


@pytest.mark.parametrize('after_teacher_recovery',[False,True])
def test_display_incident_crash_tail_restores_matching_teacher_gate(tmp_path,monkeypatch,after_teacher_recovery):
    b,t,j,w,count=make_live(tmp_path)
    original=b.admission_client.persist
    def fail_metadata(**values):
        if ('live_commands' in values if after_teacher_recovery else 'display_incident' in values):
            raise OSError('incident metadata commit failed')
        return original(**values)
    if not after_teacher_recovery:monkeypatch.setattr(b.admission_client,'persist',fail_metadata)
    count[0]=2;b.clock.advance(1)
    if after_teacher_recovery:b.live_teacher.check_display(force=True)
    else:
        with pytest.raises(OSError):b.live_teacher.check_display(force=True)
    incident=b.live_teacher.display['incident_id']
    if after_teacher_recovery:
        count[0]=1
        from test_desktop_workflow import make_ready
        b.controller.session.started=False;make_ready(b);b.controller.session.started=True
        b.flow.baseline_geometry_id=b._geometry['geometry_id']
        monkeypatch.setattr(b.admission_client,'persist',fail_metadata)
        with pytest.raises(OSError):command(b,w,'display_recovery',{'incident_id':incident,'reason':'Fresh fit checked'})
        assert 'display' not in b.controller.session.pause_reasons
        assert j.attempts()[0]['display_incident']['approval_required']
    else:assert not j.attempts()[0].get('display_incident')
    b.controller.store.flush_durable();b.controller.store.close();b.monitor.stop();b.audio.stop();w.close()
    b2,_,_=workflow(tmp_path,t,j)
    w2=Worker(b2.clock.monotonic);w2.connection_id='new-connection'
    b2.live_teacher=LiveWorkflow(b2,worker=w2,display_count_provider=lambda:1)
    try:
        b2.tick();b2.admission_client._thread.join(2);b2.tick()
        b2.admission_client._thread.join(2);b2.tick()
        live=b2.live_teacher
        assert live.display['approval_required']==(not after_teacher_recovery)
        assert not live.display['calibration_ready']
        if not after_teacher_recovery:assert live.display['incident_id']==incident
        t.reply['recovery'].update(state='granted',grant_id='new-restart-grant')
        b2.dispatch('connected.refresh',{});b2.admission_client._thread.join(2);b2.tick()
        w2.incoming.append((w2.connection_id,{'type':'consent','accepted':True,'version':3,'session_id':b2._session_id(),'recorded_at':b2.clock.wall_time()},None))
        b2.tick();prepare(b2)
        b2._geometry={'geometry_id':'new-geometry'};b2.flow.baseline_geometry_id='new-geometry'
        start(b2)
        if not after_teacher_recovery:
            assert b2.controller.session.pause_reasons=={'display'}
            command(b2,w2,'display_recovery',{'incident_id':incident,'reason':'Fresh restart calibration and one display'})
        assert b2.controller.session.running
    finally:b2.close()


def test_restored_masked_consent_requires_new_explicit_opt_in(tmp_path):
    b,t,j=workflow(tmp_path)
    try:
        b.admission_client.persist(screen_consent={'accepted':True,'version':1})
        w=Worker(b.clock.monotonic)
        live=LiveWorkflow(b,worker=w,display_count_provider=lambda:1);b.live_teacher=live
        live.start()
        assert not live.consent_accepted and not w.accepted
        live.consent(True)
        assert j.attempts()[0]['screen_consent']['version']==3
        assert not live.consent_acknowledged
        w.incoming.append((w.connection_id,{'type':'consent','accepted':True,'version':1,'session_id':b._session_id()},None))
        b.tick();assert not live.consent_acknowledged
    finally:b.close()
