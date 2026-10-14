"""Stage 3 server contracts with controlled time and synthetic frames only."""
import base64
from copy import deepcopy
from io import BytesIO
import json
import secrets
from uuid import uuid4

import pytest

from proctoring_server.live import LiveService, effective_allowance
from proctoring_server.service import Problem, iso
from proctoring_server.sync import SyncService


def fail(code, call):
    with pytest.raises(Problem) as error:
        call()
    assert error.value.code == code


def status(sequence=0, **changes):
    return {'type':'status','sequence':sequence,'state':'running','elapsed_seconds':5.,'remaining_seconds':595.,
        'duration_seconds':600.,'answered':1,'total':2,'monitoring_healthy':True,'pause_reasons':[],
        'monitoring_outage':None,'display':{'count':1,'incident_id':None,'ready':True,'calibration_ready':True,
        'approval_required':False},'screen_consent':True,**changes}


@pytest.fixture
def live(service, clock):
    return LiveService(service, SyncService(service), monotonic=clock)


@pytest.fixture
def joined(live, service, admission_data, clock):
    data={**admission_data,'admission_id':uuid4().hex,'device_id':uuid4().hex,'device_secret':secrets.token_urlsafe(32),'credential':secrets.token_urlsafe(32)}
    attempt=service.admit(data)
    hello={'type':'hello','protocol':1,'attempt_id':attempt['attempt_id'],'session_id':'session-'+uuid4().hex}
    peer=live.student_connect(data['credential'],data['device_secret'],hello)
    return peer,data,attempt,hello


@pytest.fixture
def running(live, joined, clock):
    peer,data,attempt,hello=joined
    live.consent(peer,{'type':'consent','version':3,'accepted':True})
    start={'start_key':uuid4().hex,'session_id':hello['session_id']}
    live.sync.authorize_start(data['credential'],data['device_secret'],start)
    live.sync.confirm_start(data['credential'],data['device_secret'],{**start,'started_at':iso(clock())})
    live.status(peer,status())
    peer.control.clear()
    return joined


def test_live_hello_requires_device_and_same_session(live, joined):
    peer,data,attempt,hello=joined
    fail('wrong_device',lambda:live.student_connect(data['credential'],secrets.token_urlsafe(32),hello))
    fail('session_conflict',lambda:live.student_connect(data['credential'],data['device_secret'],{**hello,'session_id':'session-'+uuid4().hex}))


def test_consent_blocks_start_and_refusal_does_not_satisfy_gate(live, joined):
    peer,data,_,hello=joined
    start={'start_key':uuid4().hex,'session_id':hello['session_id']}
    fail('consent_required',lambda:live.sync.authorize_start(data['credential'],data['device_secret'],start))
    live.consent(peer,{'type':'consent','version':3,'accepted':False})
    fail('consent_required',lambda:live.sync.authorize_start(data['credential'],data['device_secret'],start))
    live.consent(peer,{'type':'consent','version':3,'accepted':True})
    assert live.sync.authorize_start(data['credential'],data['device_secret'],start)['lifecycle']=='start_authorized'


def test_fresh_presence_and_stale_snapshot(live, running, owner, clock):
    peer,_,attempt,_=running
    assert live.snapshot(owner,peer.exam_id)['students'][0]['presence']=='online'
    clock.advance(6)
    item=live.snapshot(owner,peer.exam_id)['students'][0]
    assert item['presence']=='offline' and item['status']['remaining_seconds']==595
    assert not item['capabilities']['commands']


def test_status_rejects_answer_keys_and_incorrect_types(live, running):
    peer,*_=running
    fail('invalid_live_status',lambda:live.status(peer,status(1,answers={'single':['two']})))
    fail('invalid_live_status',lambda:live.status(peer,status(1,remaining_seconds=float('nan'))))


def test_live_notifications_deduplicate_across_reconnect(live, running, owner):
    peer,data,attempt,hello=running
    event={'type':'event','sequence':9,'record':{'event_id':'event-1','event_type':'phone_visible','session_id':peer.session_id,'duration_seconds':1}}
    live.event(peer,event);live.event(peer,event)
    assert len(live.snapshot(owner,peer.exam_id)['students'][0]['events'])==1
    replacement=live.student_connect(data['credential'],data['device_secret'],hello)
    live.event(replacement,event)
    assert len(replacement.recent)==1
    fail('record_conflict',lambda:live.event(replacement,{**event,'record':{**event['record'],'duration_seconds':99}}))


def command(live, owner, attempt, kind='warning', payload=None, request_id=None):
    return live.command(owner,attempt['attempt_id'],{'request_id':request_id or uuid4().hex,'type':kind,'payload':payload or {'text':'Please face the screen'}})['command']


def test_command_ownership_duplicate_request_and_offline_policy(live, running, owner, other, clock):
    peer,_,attempt,_=running
    fail('not_found',lambda:command(live,other,attempt))
    rid=uuid4().hex
    first=command(live,owner,attempt,request_id=rid)
    assert command(live,owner,attempt,request_id=rid)==first
    fail('command_conflict',lambda:command(live,owner,attempt,payload={'text':'Changed'},request_id=rid))
    clock.advance(6)
    fail('student_offline',lambda:command(live,owner,attempt))
    assert len(live.commands(owner,attempt['attempt_id'])['items'])==1


def test_connection_loss_marks_unconfirmed_and_never_requeues(live, running, owner):
    peer,data,attempt,hello=running
    original=command(live,owner,attempt)
    replacement=live.student_connect(data['credential'],data['device_secret'],hello)
    assert all(message['type']!='command' for message in replacement.control)
    assert live.commands(owner,attempt['attempt_id'])['items'][0]['status']=='execution_unconfirmed'
    fail('command_binding',lambda:live.acknowledge(replacement,{'command_id':original['command_id'],'phase':'applied','result':{}}))


def test_command_ack_idempotent_and_expiry_not_assumed_success(live, running, owner, clock):
    peer,_,attempt,_=running
    first=command(live,owner,attempt)
    live.acknowledge(peer,{'command_id':first['command_id'],'phase':'received','result':{}})
    assert live.commands(owner,attempt['attempt_id'])['items'][0]['status']=='delivered'
    clock.advance(10)
    assert live.commands(owner,attempt['attempt_id'])['items'][0]['status']=='execution_unconfirmed'
    fail('command_expired',lambda:live.acknowledge(peer,{'command_id':first['command_id'],'phase':'received','result':{}}))
    # Late actual-application acknowledgement is historical evidence, not an
    # instruction permitting Python to execute after its own deadline.
    ack={'command_id':first['command_id'],'phase':'applied','result':{'code':'notification_shown'}}
    live.acknowledge(peer,ack);live.acknowledge(peer,ack)
    assert live.commands(owner,attempt['attempt_id'])['items'][0]['status']=='applied'


def test_one_expired_command_does_not_expire_newer_command(live, running, owner, clock):
    peer,_,attempt,_=running
    old=command(live,owner,attempt)
    clock.advance(5);live.status(peer,status(1))
    new=command(live,owner,attempt)
    clock.advance(5)
    commands={c['command_id']:c for c in live.commands(owner,attempt['attempt_id'])['items']}
    assert commands[old['command_id']]['status']=='execution_unconfirmed'
    assert commands[new['command_id']]['status']=='sent'


def test_monitoring_and_display_recovery_require_current_healthy_gate(live,running,owner):
    peer,_,attempt,_=running
    fail('recovery_unavailable',lambda:command(live,owner,attempt,'monitoring_recovery',{'outage_id':'old','reason':'ready'}))
    outage={'outage_id':'outage-1','duration_seconds':20,'healthy':True,'recovery_required':True}
    display={'count':1,'incident_id':'display-1','ready':True,'calibration_ready':True,'approval_required':True}
    live.status(peer,status(1,state='paused',pause_reasons=['recovery_pin','display'],monitoring_outage=outage,display=display))
    assert command(live,owner,attempt,'monitoring_recovery',{'outage_id':'outage-1','reason':'ready'})['status']=='sent'
    assert command(live,owner,attempt,'display_recovery',{'incident_id':'display-1','reason':'ready'})['status']=='sent'
    live.status(peer,status(2,state='paused',display={**display,'count':2}))
    fail('recovery_unavailable',lambda:command(live,owner,attempt,'display_recovery',{'incident_id':'display-1','reason':'ready'}))


def test_allowance_reconciles_only_this_attempt_addtime_ids(live,running,owner,service,clock):
    peer,_,attempt,_=running
    addition=command(live,owner,attempt,'add_time',{'seconds':60,'reason':'Technical adjustment'})
    with service.database.connect(write=True) as db:
        row=db.execute('SELECT * FROM attempts WHERE id=?',(attempt['attempt_id'],)).fetchone()
        assert effective_allowance(db,row,{'duration_seconds':660,'time_adjustment_ids':[addition['command_id']]},clock())==660
    fail('invalid_command',lambda:command(live,owner,attempt,'add_time',{'seconds':-5,'reason':'invalid'}))
    assert live.commands(owner,attempt['attempt_id'])['items'][0]['status']=='applied'
    with service.database.connect(write=True) as db:
        fail('invalid_allowance',lambda:effective_allowance(db,row,{'duration_seconds':999,'time_adjustment_ids':[]},clock()))


def test_allowance_accepts_client_2048_bound_and_rejects_2049(live,running,owner,service,clock):
    peer,_,attempt,hello=running
    identifiers=[uuid4().hex for _ in range(2048)]
    with service.database.connect(write=True) as db:
        row=db.execute('SELECT * FROM attempts WHERE id=?',(attempt['attempt_id'],)).fetchone()
        # Previously applied grants: no queue, networking or synthetic local timer.
        db.executemany('INSERT INTO live_commands VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',[
            (cid,uuid4().hex,owner,peer.exam_id,attempt['attempt_id'],hello['session_id'],peer.connection_id,
             'add_time',json.dumps({'seconds':1,'reason':'bounded grant'}),clock(),clock()+10,'applied','{}')
            for cid in identifiers])
        assert effective_allowance(db,row,{'duration_seconds':2648,'time_adjustment_ids':identifiers},clock())==2648
        fail('invalid_allowance',lambda:effective_allowance(db,row,
            {'duration_seconds':2649,'time_adjustment_ids':[*identifiers,uuid4().hex]},clock()))


def test_early_close_leaves_existing_start_and_evidence_credentials(live,joined,owner,service,admission_data):
    peer,data,attempt,hello=joined
    exam=live.close_admissions(owner,peer.exam_id,{'confirm':True,'reason':'Admission completed'})
    assert not exam['admission_open'] and exam['admissions_closed_at']
    fail('admission_closed',lambda:service.admit({**admission_data,'student_id':'Another'}))
    live.consent(peer,{'type':'consent','version':3,'accepted':True})
    assert live.sync.authorize_start(data['credential'],data['device_secret'],{'start_key':uuid4().hex,'session_id':hello['session_id']})['lifecycle']=='start_authorized'
    assert live.sync.attempt(data['credential'],data['device_secret'])['attempt_id']==attempt['attempt_id']


def open_view(live,running,owner,service):
    peer,_,attempt,_=running
    view=live.start_viewer(owner,attempt['attempt_id'])
    message=next(m for m in reversed(peer.control) if m['type']=='view.start')
    raw,login=service.login({'email':'teacher@example.com','password':'test password 12345'},'loopback')
    sender=live.stream_connect({'role':'student','viewer_id':view['viewer_id'],'token':message['sender_token']})
    teacher=live.stream_connect({'role':'teacher','viewer_id':view['viewer_id'],'csrf_token':login['csrf_token']},raw)
    return view,sender,teacher


def jpeg_frame(view,sequence=1):
    from PIL import Image
    pixels=BytesIO();Image.new('RGB',(80,60),'green').save(pixels,format='JPEG')
    return {'type':'frame','viewer_id':view['viewer_id'],'sequence':sequence,'captured_at':1800000000000.,
            'width':80,'height':60,'jpeg_base64':base64.b64encode(pixels.getvalue()).decode()}


def test_capture_recovery_preserves_only_authorized_viewer_and_deadline(live,running,owner,service):
    view,sender,teacher=open_view(live,running,owner,service)
    viewer=live.viewers[view['viewer_id']]
    deadline=viewer.deadline
    packet={'type':'capture.recovering','viewer_id':view['viewer_id'],'through_sequence':1}
    teacher.control.clear()
    live.stream(sender,packet)
    assert teacher.control[-1]==packet and viewer.deadline==deadline
    assert viewer.failure_reason is None
    live.stream(sender,jpeg_frame(view,2))
    assert viewer.last_sequence==2
    for change in [{'through_sequence':True},{'through_sequence':-1},{'through_sequence':2**53},{'private':'secret'}]:
        fail('invalid_stream_message',lambda:live.stream(sender,{**packet,**change}))
    fail('invalid_stream_message',lambda:live.stream(teacher,packet))
    fail('viewer_forbidden',lambda:live.stream(sender,{**packet,'viewer_id':uuid4().hex}))
    live.disconnect(sender)
    fail('viewer_expired',lambda:live.stream(sender,packet))


def test_capture_recovery_reconnect_requires_new_lease_and_consent(live,running,owner,service):
    view,sender,teacher=open_view(live,running,owner,service)
    live.disconnect(sender)
    fail('viewer_expired',lambda:live.stream_connect({'role':'student','viewer_id':view['viewer_id'],'token':'old'}))
    new,new_sender,new_teacher=open_view(live,running,owner,service)
    assert new['viewer_id']!=view['viewer_id']
    live.disconnect(new_sender)
    live.status(running[0],status(sequence=1,screen_consent=False))
    fail('consent_required',lambda:live.start_viewer(owner,running[2]['attempt_id']))


def test_viewer_one_per_teacher_switch_stops_previous(live,running,owner,service):
    view,sender,teacher=open_view(live,running,owner,service)
    newer=live.start_viewer(owner,running[2]['attempt_id'])
    assert newer['viewer_id']!=view['viewer_id'] and len(live.viewers)==1
    assert sender.closed and teacher.closed


def test_viewer_cross_teacher_and_bad_sender_token_rejected(live,running,owner,other,service):
    peer,_,attempt,_=running
    fail('not_found',lambda:live.start_viewer(other,attempt['attempt_id']))
    view=live.start_viewer(owner,attempt['attempt_id'])
    fail('viewer_forbidden',lambda:live.stream_connect({'role':'student','viewer_id':view['viewer_id'],'token':secrets.token_urlsafe(32)}))


def test_relay_latest_only_memory_buffer_and_no_frames_on_disk(live,running,owner,service,clock):
    view,sender,teacher=open_view(live,running,owner,service)
    live.stream(sender,jpeg_frame(view,1));clock.advance(.21);live.stream(sender,jpeg_frame(view,2))
    assert teacher.frame['sequence']==2
    assert len(teacher.control)==1  # Ready only; frames never become queued messages.
    assert list(live.sync.root.rglob('*'))==[]
    with service.database.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM sync_files').fetchone()[0]==0
    live.stream(teacher,{'type':'frame_ack','sequence':2})
    assert sender.control[-1]=={'type':'frame_ack','sequence':2}


def test_viewer_expiry_and_disconnect_clear_frames(live,running,owner,service,clock):
    view,sender,teacher=open_view(live,running,owner,service)
    live.stream(sender,jpeg_frame(view))
    clock.advance(31);live.sweep()
    assert not live.viewers and teacher.closed and teacher.frame is None
    assert running[0].control[-1]['type']=='view.stop'


def test_renew_requires_live_authorization_and_stops_on_teacher_disconnect(live,running,owner,service,clock):
    view,sender,teacher=open_view(live,running,owner,service)
    clock.advance(5);live.status(running[0],status(1));live.stream(teacher,{'type':'renew'})
    assert live.viewers[view['viewer_id']].deadline==clock()+30
    live.disconnect(teacher)
    assert not live.viewers and sender.closed


def test_screen_failure_classification_survives_generic_socket_cleanup(live,running,owner,service):
    view,sender,teacher=open_view(live,running,owner,service)
    for reason in ('privacy_mask_unavailable','capture_unavailable'):
        live.stream(sender,{'type':'transport','viewer_id':view['viewer_id'],'transport':'unavailable','reason':reason})
    live.disconnect(sender)
    assert running[0].control[-1]['reason']=='privacy_mask_unavailable'
    with service.database.connect() as db:
        row=db.execute("SELECT reason FROM audit_log WHERE action='screen_view_stopped' ORDER BY created_at DESC").fetchone()
        assert row[0]=='privacy_mask_unavailable'


def test_screen_progress_status_and_renewal_keep_existing_viewer(live,running,owner,service,clock):
    view,sender,teacher=open_view(live,running,owner,service)
    for i in range(1,25):
        clock.advance(1)
        live.status(running[0],status(i,answered=i%3,elapsed_seconds=5+i,remaining_seconds=595-i))
        if i%5==0:live.stream(teacher,{'type':'renew'})
        live.sweep()
        assert view['viewer_id'] in live.viewers and not sender.closed and not teacher.closed
    live.stop_viewer(view['viewer_id'],'teacher_stopped',owner)
    assert sender.closed and teacher.closed


@pytest.mark.parametrize('mutation,code',[
    (lambda f:f.update(width=1921),'frame_limit'),
    (lambda f:f.update(jpeg_base64='notbase64'),'invalid_frame'),
    (lambda f:f.update(width=79),'invalid_frame'),
    (lambda f:f.update(sequence=-1),'invalid_frame'),
])
def test_frame_bounds(live,running,owner,service,mutation,code):
    view,sender,teacher=open_view(live,running,owner,service)
    frame=jpeg_frame(view);mutation(frame)
    fail(code,lambda:live.stream(sender,frame))


def test_signaling_buffered_until_counterpart_and_fallback_forwarded(live,running,owner,service):
    peer,_,attempt,_=running
    view=live.start_viewer(owner,attempt['attempt_id'])
    token=next(m['sender_token'] for m in reversed(peer.control) if m['type']=='view.start')
    sender=live.stream_connect({'role':'student','viewer_id':view['viewer_id'],'token':token})
    signal={'type':'signal','viewer_id':view['viewer_id'],'signal':{'type':'offer','sdp':'synthetic SDP'}}
    live.stream(sender,signal)
    raw,login=service.login({'email':'teacher@example.com','password':'test password 12345'},'loopback')
    teacher=live.stream_connect({'role':'teacher','viewer_id':view['viewer_id'],'csrf_token':login['csrf_token']},raw)
    assert teacher.control[-1]==signal
    live.stream(teacher,{'type':'transport','viewer_id':view['viewer_id'],'transport':'relay','reason':'direct_timeout'})
    assert sender.control[-1]['transport']=='relay'


def test_quality_is_bounded_throttled_and_memory_only(live,running,owner,service,clock):
    view,sender,teacher=open_view(live,running,owner,service)
    packet={'type':'quality','viewer_id':view['viewer_id'],'ack_roundtrip_ms':25.,'send_fps':4.,'width':1280,'jpeg_quality':65,'degraded':False}
    live.stream(sender,packet)
    assert teacher.control[-1]==packet
    count=len(teacher.control)
    live.stream(sender,packet)
    assert len(teacher.control)==count
    clock.advance(1)
    live.stream(sender,{**packet,'ack_roundtrip_ms':None})
    assert teacher.control[-1]['ack_roundtrip_ms'] is None
    fail('invalid_quality',lambda:live.stream(sender,{**packet,'ack_roundtrip_ms':float('nan')}))
    fail('invalid_quality',lambda:live.stream(sender,{**packet,'send_fps':11}))
    fail('invalid_stream_message',lambda:live.stream(teacher,packet))


def test_running_consent_reassertion_cannot_be_changed(live,running):
    peer,data,_,hello=running
    newer=live.student_connect(data['credential'],data['device_secret'],hello)
    live.consent(newer,{'type':'consent','version':3,'accepted':True})
    assert newer.control[-1]['accepted'] is True
    fail('consent_locked',lambda:live.consent(newer,{'type':'consent','version':3,'accepted':False}))


def test_old_socket_cleanup_does_not_stop_new_viewer(live,running,owner,service):
    old,data,attempt,hello=running
    current=live.student_connect(data['credential'],data['device_secret'],hello)
    live.status(current,status())
    view=live.start_viewer(owner,attempt['attempt_id'])
    live.disconnect(old)
    assert view['viewer_id'] in live.viewers


def test_memory_capacity_refuses_active_then_evicts_only_closed(live,joined,service,admission_data,monkeypatch):
    import proctoring_server.live as module
    monkeypatch.setattr(module,'MAX_STUDENTS',1)
    first=joined[0]
    data={**admission_data,'student_id':'second','admission_id':uuid4().hex,'device_id':uuid4().hex,'device_secret':secrets.token_urlsafe(32),'credential':secrets.token_urlsafe(32)}
    attempt=service.admit(data)
    hello={'type':'hello','protocol':1,'attempt_id':attempt['attempt_id'],'session_id':'session-'+uuid4().hex}
    fail('live_capacity',lambda:live.student_connect(data['credential'],data['device_secret'],hello))
    assert live.students[first.identity] is first
    live.disconnect(first)
    second=live.student_connect(data['credential'],data['device_secret'],hello)
    assert list(live.students)==[second.identity]


def test_projection_exposes_restart_gate_without_checkpoint_answers(live,running,owner):
    peer,data,attempt,hello=running
    interruption={'interruption_id':uuid4().hex,'session_id':hello['session_id'],'reason':'unexpected interruption',
                  'checkpoint':{'elapsed_seconds':5,'remaining_seconds':595,'pause_reasons':[],'answers':{'single':['two']}}}
    live.sync.interrupted(data['credential'],data['device_secret'],interruption)
    snapshot=live.snapshot(owner,peer.exam_id)
    projected=snapshot['students'][0]
    assert projected['restart_recovery']['state']=='pending'
    assert projected['start_authorized'] and projected['lifecycle']=='interrupted'
    assert 'answers' not in json.dumps(projected)
    assert not snapshot['truncated'] and snapshot['total_students']==1


def test_added_allowance_round_trips_interruption_with_lost_ack(live,running,owner):
    _,data,attempt,hello=running
    addition=command(live,owner,attempt,'add_time',{'seconds':60,'reason':'technical delay'})
    interruption={'interruption_id':uuid4().hex,'session_id':hello['session_id'],'reason':'unexpected interruption',
        'checkpoint':{'elapsed_seconds':5,'remaining_seconds':655,'duration_seconds':660,
            'time_adjustment_ids':[addition['command_id']],'pause_reasons':[],'answers':{}}}
    result=live.sync.interrupted(data['credential'],data['device_secret'],interruption)
    assert result['recovery']['checkpoint']['duration_seconds']==660
    row=live.commands(owner,attempt['attempt_id'])['items'][0]
    assert row['status']=='applied' and row['result']['old_duration_seconds']==600
    assert row['result']['new_duration_seconds']==660


def test_addtime_ack_requires_actual_issued_delta(live,running,owner):
    peer,_,attempt,_=running
    addition=command(live,owner,attempt,'add_time',{'seconds':60,'reason':'technical delay'})
    packet={'type':'command_ack','command_id':addition['command_id'],'phase':'applied','result':{'old_duration_seconds':600,'new_duration_seconds':700,'delta_seconds':100}}
    fail('invalid_command_ack',lambda:live.acknowledge(peer,packet))
    live.acknowledge(peer,{**packet,'result':{'old_duration_seconds':600,'new_duration_seconds':660,'delta_seconds':60}})
    assert live.commands(owner,attempt['attempt_id'])['items'][0]['status']=='applied'


def test_final_receipt_accepts_added_time_and_retention_purges_command_text(live,running,owner,service,clock):
    from hashlib import sha256
    from reportlab.pdfgen.canvas import Canvas
    peer,data,attempt,hello=running
    addition=command(live,owner,attempt,'add_time',{'seconds':60,'reason':'private technical reason'})
    warning=command(live,owner,attempt,'warning',{'text':'private warning text'})
    session=hello['session_id']; started=iso(clock()); ended=iso(clock()+5)
    records=[{'session_id':session,'event_type':'session_started','timestamp':started}]
    live.sync.records_upload(data['credential'],data['device_secret'],{'session_id':session,'records':[{'sequence':0,'record':records[0]}]})
    summary={'session_id':session,'connected_attempt':{'attempt_id':attempt['attempt_id']},'started_at':started,'ended_at':ended,
             'end_reason':'teacher_ended','elapsed_seconds':5,'remaining_seconds':655,'duration_seconds':660,
             'time_adjustment_ids':[addition['command_id']],'score':1,'total_questions':2,'events':[]}
    metadata={'session_id':session,'connected_attempt':{'attempt_id':attempt['attempt_id']}}
    answers={'session_id':session,'attempt_id':attempt['attempt_id'],'answers':{'single':['two']}}
    pdf=BytesIO(); writer=Canvas(pdf);writer.drawString(30,700,'Synthetic original report');writer.save()
    raw={'session':json.dumps(metadata).encode(),'summary':json.dumps(summary).encode(),'answers':json.dumps(answers).encode(),
         'events':json.dumps(records[0]).encode()+b'\n','original_pdf':pdf.getvalue()}
    paths={'session':'session.json','summary':'summary.json','answers':'answers.json','events':'events.jsonl','original_pdf':'report.pdf'}
    manifest={'version':1,'attempt_id':attempt['attempt_id'],'session_id':session,'ended_at':ended,'end_reason':'teacher_ended',
              'record_count':1,'identity_required':False,'items':[{'id':kind,'kind':kind,'relative_path':paths[kind],
              'required':True,'status':'present','size':len(value),'sha256':sha256(value).hexdigest(),'error':None} for kind,value in raw.items()]}
    manifest['items'].append({'id':'disabled_snapshot','kind':'snapshot','relative_path':'snapshots/disabled.jpg',
        'required':False,'status':'disabled','size':None,'sha256':None,'error':None})
    digest=live.sync.manifest_upload(data['credential'],data['device_secret'],{'manifest':manifest})['manifest_sha256']
    for kind,value in raw.items():
        live.sync.chunk(data['credential'],data['device_secret'],kind,{'manifest_sha256':digest,'offset':0,'data_base64':base64.b64encode(value).decode()})
    receipt=live.sync.complete(data['credential'],data['device_secret'],{'manifest_sha256':digest})
    assert receipt['receipt']['manifest_sha256']==digest
    assert next(row for row in live.commands(owner,attempt['attempt_id'])['items'] if row['command_id']==addition['command_id'])['status']=='applied'
    live.sync.delete_materials(owner,attempt['attempt_id'],{'confirm':True,'reason':'operator requested early deletion'})
    with service.database.connect() as db:
        command_rows=[dict(r) for r in db.execute('SELECT payload,result FROM live_commands WHERE attempt_id=?',(attempt['attempt_id'],))]
        assert all(r['payload']=='{}' and r['result'] is None for r in command_rows)
    assert live.snapshot(owner,peer.exam_id)['students'][0]['events']==[]


def test_legacy_admission_projection_has_preparation_state(live,service,admitted,owner,exam):
    item=live.snapshot(owner,exam['id'])['students'][0]
    assert item['lifecycle']=='admitted' and item['start_authorized'] is False


def test_teacher_socket_auth_origin_and_student_ws_handshake(client,service,admission_data):
    from starlette.websockets import WebSocketDisconnect
    data={**admission_data,'admission_id':uuid4().hex,'device_id':uuid4().hex,'device_secret':secrets.token_urlsafe(32),'credential':secrets.token_urlsafe(32)}
    attempt=service.admit(data)
    with client.websocket_connect('ws://127.0.0.1:8000/api/v1/live/student',headers={'Authorization':'Bearer '+data['credential'],'X-Device-Secret':data['device_secret']}) as ws:
        ws.send_json({'type':'hello','protocol':1,'attempt_id':attempt['attempt_id'],'session_id':'session-'+uuid4().hex})
        assert ws.receive_json()['type']=='hello'
        ws.send_json({'type':'consent','version':3,'accepted':True})
        assert ws.receive_json()['accepted'] is True
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('ws://127.0.0.1:8000/api/v1/live/teacher',headers={'Origin':'https://evil.example'}):
            pass


def test_teacher_websocket_requires_cookie_csrf_and_exam_owner(client,service,exam):
    login=client.post('/api/v1/auth/login',headers={'Origin':'http://127.0.0.1:5174'},json={'email':'teacher@example.com','password':'test password 12345'}).json()
    with client.websocket_connect('ws://127.0.0.1:8000/api/v1/live/teacher',headers={'Origin':'http://127.0.0.1:5174'}) as ws:
        ws.send_json({'type':'auth','csrf_token':login['csrf_token'],'exam_id':exam['id']})
        assert ws.receive_json()['type']=='snapshot'
        ws.send_json({'type':'ping'})
        assert ws.receive_json()['exam_id']==exam['id']


def test_old_masked_consent_never_authorizes_unmasked_start_or_view(live,joined,owner):
    peer,data,attempt,hello=joined
    fail('invalid_consent',lambda:live.consent(peer,{'type':'consent','version':1,'accepted':True}))
    fail('invalid_consent',lambda:live.consent(peer,{'type':'consent','version':2,'accepted':True}))
    with live.database.connect(write=True) as db:
        db.execute('UPDATE live_attempts SET consent_version=1,consent_accepted_at=? WHERE attempt_id=?',(live.clock(),peer.identity))
    fail('consent_required',lambda:live.sync.authorize_start(data['credential'],data['device_secret'],{'start_key':uuid4().hex,'session_id':hello['session_id']}))
    live.status(peer,status())
    fail('consent_required',lambda:live.start_viewer(owner,attempt['attempt_id']))


def test_intentional_stream_stop_preserves_reason_for_both_sockets(live,running,owner,service):
    view,sender,teacher=open_view(live,running,owner,service)
    live.stream(teacher,{'type':'view.stop','viewer_id':view['viewer_id']})
    assert sender.closed and teacher.closed and view['viewer_id'] not in live.viewers
    assert sender.stop_message=={'type':'view.stop','viewer_id':view['viewer_id'],'reason':'teacher_stopped'}
    live.disconnect(teacher,'disconnected')
    assert sender.stop_message['reason']=='teacher_stopped'


def test_terminal_failure_precedes_later_explicit_stop(live,running,owner,service):
    view,sender,teacher=open_view(live,running,owner,service)
    live.stream(sender,{'type':'transport','viewer_id':view['viewer_id'],'transport':'unavailable','reason':'monitor_capture_unavailable'})
    live.stream(teacher,{'type':'view.stop','viewer_id':view['viewer_id']})
    assert sender.stop_message['reason']=='monitor_capture_unavailable'


@pytest.mark.parametrize('via',['http','stream'])
def test_stop_reason_sent_on_actual_stream_before_socket_close(client,service,admission_data,owner,clock,via):
    from starlette.websockets import WebSocketDisconnect
    live=client.app.state.live
    data={**admission_data,'admission_id':uuid4().hex,'device_id':uuid4().hex,'device_secret':secrets.token_urlsafe(32),'credential':secrets.token_urlsafe(32)}
    attempt=service.admit(data);sid='session-'+uuid4().hex
    peer=live.student_connect(data['credential'],data['device_secret'],{'type':'hello','protocol':1,'attempt_id':attempt['attempt_id'],'session_id':sid})
    live.consent(peer,{'type':'consent','version':3,'accepted':True})
    start={'start_key':uuid4().hex,'session_id':sid}
    live.sync.authorize_start(data['credential'],data['device_secret'],start)
    live.sync.confirm_start(data['credential'],data['device_secret'],{**start,'started_at':iso(clock())})
    live.status(peer,status())
    origin={'Origin':'http://127.0.0.1:5174'}
    login=client.post('/api/v1/auth/login',headers=origin,json={'email':'teacher@example.com','password':'test password 12345'}).json()
    view=live.start_viewer(owner,attempt['attempt_id'])
    token=next(m['sender_token'] for m in reversed(peer.control) if m['type']=='view.start')
    with client.websocket_connect('ws://127.0.0.1:8000/api/v1/live/stream') as sender:
        sender.send_json({'role':'student','viewer_id':view['viewer_id'],'token':token})
        assert sender.receive_json()['type']=='stream.ready'
        with client.websocket_connect('ws://127.0.0.1:8000/api/v1/live/stream',headers=origin) as teacher:
            teacher.send_json({'role':'teacher','viewer_id':view['viewer_id'],'csrf_token':login['csrf_token']})
            assert teacher.receive_json()['type']=='stream.ready'
            assert sender.receive_json()['type']=='peer.ready'
            if via=='stream':teacher.send_json({'type':'view.stop','viewer_id':view['viewer_id']})
            else:
                response=client.post('/api/v1/live/view/stop',headers={**origin,'X-CSRF-Token':login['csrf_token']},json={'viewer_id':view['viewer_id']})
                assert response.status_code==200
            assert sender.receive_json()=={'type':'view.stop','viewer_id':view['viewer_id'],'reason':'teacher_stopped'}
            with pytest.raises(WebSocketDisconnect):sender.receive_json()

def test_relay_trace_is_bounded_owned_and_survives_stop(live,running,owner,service,clock):
    view,sender,teacher=open_view(live,running,owner,service)
    for seq in range(1,80):
        clock.advance(.2)
        live.status(running[0],status(sequence=seq))
        live.frame(live.viewers[view['viewer_id']],jpeg_frame(view,seq))
    live.stream(teacher,{'type':'frame_ack','sequence':79})
    trace=live.diagnostics(owner,view['viewer_id'])['trace']
    assert trace['counts']['received']==79 and trace['counts']['replaced']==78
    assert trace['counts']['accepted']==79
    assert trace['counts']['ack_received']==1 and trace['counts']['ack_forwarded']==1
    assert len(trace['records'])<=128
    assert all(set(r)=={'stage','sequence','at_ms','value'} for r in trace['records'])
    fail('not_found',lambda:live.diagnostics('another-owner',view['viewer_id']))
    live.stop_viewer(view['viewer_id'],'teacher_stopped')
    assert live.diagnostics(owner,view['viewer_id'])['trace']['counts']['closed']==1


def test_relay_rejection_trace_never_copies_invalid_frame_payload(live,running,owner,service,clock):
    view,sender,teacher=open_view(live,running,owner,service)
    packet=jpeg_frame(view);packet['sequence']='private-invalid-field'
    fail('invalid_frame',lambda:live.stream(sender,packet))
    trace=live.diagnostics(owner,view['viewer_id'])['trace']
    assert trace['counts']['rejected']==1
    assert trace['records'][-1]['sequence']==-1
    assert 'private-invalid-field' not in json.dumps(trace)
