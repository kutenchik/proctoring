"""Active evidence only: isolated DB/outbox, synthetic JPEG, no devices."""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import secrets
import threading
from uuid import uuid4

import pytest
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from proctoring.connected.client import ConnectedError
from proctoring.connected.durable import DurableJournal
from proctoring.connected.sync import SyncWorker, build_manifest, cleanup_received
from proctoring_server.live import LiveService, Peer
from proctoring_server.service import Problem, iso
from proctoring_server.sync import SyncService
from test_live_api import network, receive, send


class Vault:
    def encrypt(self, value): return bytes(b ^ 173 for b in value)
    def decrypt(self, value): return self.encrypt(value)


@pytest.fixture
def active(service, owner, exam_data, tmp_path, clock):
    exam = service.create_exam(owner, {**exam_data, 'save_snapshots': True})
    credential, device = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    admission = service.admit({'exam_code':exam['code'],'full_name':'Synthetic','group':'Test','student_id':'snap',
        'admission_id':uuid4().hex,'device_id':uuid4().hex,'credential':credential,'device_secret':device})
    sync = SyncService(service)
    live = LiveService(service, sync)
    session = 'session-'+uuid4().hex
    peer = live.student_connect(credential, device, {'type':'hello','protocol':1,'attempt_id':admission['attempt_id'],'session_id':session})
    live.consent(peer, {'version':3,'accepted':True})
    start = {'session_id':session,'start_key':uuid4().hex}
    sync.authorize_start(credential, device, start)
    sync.confirm_start(credential, device, {**start,'started_at':iso(clock())})
    root = tmp_path/'local'/session
    root.mkdir(parents=True)
    metadata = {'session_id':session,'connected_attempt':{'attempt_id':admission['attempt_id']}}
    (root/'session.json').write_text(json.dumps(metadata))
    event = {'session_id':session,'event_id':'event-1','event_type':'phone_visible','action':'activated',
        'start_timestamp':iso(clock()),'snapshot_path':'snapshots/event-1.jpg','snapshot_status':'pending','duration_seconds':1}
    (root/'events.jsonl').write_text(json.dumps(event)+'\n')
    journal = DurableJournal(tmp_path/'outbox.db',vault=Vault())
    row = {'attempt_id':admission['attempt_id'],'session_id':session,'server':'http://127.0.0.1:8000',
        'credential':credential,'device_secret':device,'checkpoint':{'elapsed_seconds':1},
        'phase':'locally_started','screen_consent':{'version':3,'accepted':True},'admission':admission,
        'identity_required':False,'report_filename':'report.pdf'}
    key = 'attempt:'+row['attempt_id']; journal.put(key,row)
    calls = []
    def transport(method, origin, endpoint, body, token):
        assert token == credential
        calls.append((endpoint,deepcopy(body)))
        if endpoint == '/student/sync/records': return sync.records_upload(token,device,body)
        if endpoint == '/student/sync/snapshots': return sync.snapshot_declare(token,device,body)
        if endpoint.startswith('/student/sync/snapshots/'):
            return sync.chunk(token,device,endpoint.split('/')[-2],body,provisional=True)
        if endpoint == '/student/sync/manifest': return sync.manifest_upload(token,device,body)
        if endpoint == '/student/sync/status': return sync.status(token,device)
        if endpoint.startswith('/student/sync/files/'): return sync.chunk(token,device,endpoint.split('/')[-2],body)
        if endpoint == '/student/sync/complete': return sync.complete(token,device,body)
        raise AssertionError(endpoint)
    worker = SyncWorker(journal,root.parent,transport)
    jpeg = BytesIO(); Image.new('RGB',(80,60),(30,120,50)).save(jpeg,format='JPEG')
    return locals()


def publish(a, data=None):
    path=a['root']/'snapshots/event-1.jpg';path.parent.mkdir(exist_ok=True)
    path.write_bytes(a['jpeg'].getvalue() if data is None else data)
    return path


def tick(a): a['worker'].once(a['journal'].get(a['key']))


def test_late_snapshot_active_upload_is_durable_owned_and_not_receipt(active, owner, other):
    a=active;tick(a)
    assert not any('/snapshots' in p for p,_ in a['calls'])
    path=publish(a);tick(a)
    row=a['journal'].get(a['key']);item=row['early_snapshots']['event-1']
    assert item['complete'] and path.exists() and not row.get('receipt') and not row.get('cleanup')
    assert a['sync'].status(row['credential'],row['device_secret'])['receipt'] is None
    assert a['sync'].evidence_file(owner,row['attempt_id'],item['item_id'])[0].read_bytes()==path.read_bytes()
    with pytest.raises(Problem) as error: a['sync'].evidence_file(other,row['attempt_id'],item['item_id'])
    assert error.value.code=='not_found'
    with pytest.raises(ValueError): cleanup_received(a['journal'],path.parent.parent.parent,row)
    # A new live service, without any student connection, reconstructs availability.
    fresh=LiveService(a['service'],a['sync']).snapshot(owner,a['exam']['id'])['students'][0]
    assert fresh['presence']=='offline' and fresh['events'][0]['snapshot']=={'status':'available','item_id':item['item_id'],'reason':None}
    with pytest.raises(Problem): a['sync'].snapshot_declare(row['credential'],row['device_secret'],
        {'session_id':row['session_id'],'event_id':'different','size':item['size'],'sha256':item['sha256']})


def test_duplicate_interrupted_upload_and_restart_reconcile_frontier(active):
    a=active
    # Valid JPEG plus trailing bytes exercises multiple bounded chunks.
    path=publish(a,a['jpeg'].getvalue()+b'\0'*(600*1024))
    original=a['worker'].transport;lost=[True]
    def drop_response(*args):
        reply=original(*args)
        if '/snapshots/' in args[2] and lost[0]:
            lost[0]=False;raise ConnectedError('connection_failed')
        return reply
    a['worker'].transport=drop_response
    with pytest.raises(ConnectedError):tick(a)
    assert path.exists()
    a['journal']=DurableJournal(a['journal'].path,vault=Vault())
    a['worker']=SyncWorker(a['journal'],a['root'].parent,original)
    for _ in range(4):tick(a)
    row=a['journal'].get(a['key']);item=row['early_snapshots']['event-1']
    assert item['complete']
    chunks=[b for p,b in a['calls'] if '/snapshots/' in p]
    assert [b['offset'] for b in chunks]==[0,262144,524288]
    response=a['sync'].chunk(row['credential'],row['device_secret'],item['item_id'],chunks[0],provisional=True)
    assert response['complete']
    with pytest.raises(Problem) as error:
        a['sync'].snapshot_declare(row['credential'],row['device_secret'],{'session_id':row['session_id'],
            'event_id':'event-1','size':item['size'],'sha256':'a'*64})
    assert error.value.code=='file_conflict'


def test_disabled_policy_and_old_consent_never_upload(active, owner):
    a=active;publish(a)
    row=a['journal'].get(a['key']);row['admission']['exam']['save_snapshots']=False
    a['journal'].put(a['key'],row);tick(a)
    assert not any('/snapshots' in p for p,_ in a['calls'])
    with a['service'].database.connect(write=True) as db:
        db.execute('UPDATE live_attempts SET consent_version=2 WHERE attempt_id=?',(row['attempt_id'],))
    with pytest.raises(Problem) as error:
        a['sync'].snapshot_declare(row['credential'],row['device_secret'],{'session_id':row['session_id'],
            'event_id':'event-1','size':len(a['jpeg'].getvalue()),'sha256':sha256(a['jpeg'].getvalue()).hexdigest()})
    assert error.value.code=='snapshot_consent_required'
    with a['service'].database.connect(write=True) as db:
        policy=json.loads(db.execute('SELECT policy_snapshot FROM attempts WHERE id=?',(row['attempt_id'],)).fetchone()[0]);policy['save_snapshots']=False
        db.execute('UPDATE attempts SET policy_snapshot=? WHERE id=?',(json.dumps(policy),row['attempt_id']))
    with pytest.raises(Problem) as error:
        a['sync'].snapshot_declare(row['credential'],row['device_secret'],{'session_id':row['session_id'],
            'event_id':'event-1','size':len(a['jpeg'].getvalue()),'sha256':sha256(a['jpeg'].getvalue()).hexdigest()})
    assert error.value.code=='policy_conflict'
    assert a['live'].snapshot(owner,a['exam']['id'])['students'][0]['events'][0]['snapshot']['status']=='disabled'


def test_invalid_partial_jpeg_is_not_uploaded_and_late_valid_file_recovers(active):
    a=active;path=publish(a,b'\xff\xd8\xffbroken');tick(a)
    assert not any('/snapshots' in p for p,_ in a['calls'])
    assert path.exists()
    publish(a);tick(a)
    assert a['journal'].get(a['key'])['early_snapshots']['event-1']['complete']


@pytest.mark.parametrize('raw,code',[(b'not JPEG','invalid_file_type'),(b'wrong digest','checksum_mismatch')])
def test_server_rejects_invalid_content_without_availability(active, owner, raw, code):
    a=active;tick(a);row=a['row']
    declared=a['sync'].snapshot_declare(row['credential'],row['device_secret'],{'session_id':row['session_id'],
        'event_id':'event-1','size':len(raw),'sha256':sha256(raw).hexdigest() if code=='invalid_file_type' else 'a'*64})
    with pytest.raises(Problem) as error:
        a['sync'].chunk(row['credential'],row['device_secret'],declared['item_id'],{'session_id':row['session_id'],
            'offset':0,'data_base64':base64.b64encode(raw).decode()},provisional=True)
    assert error.value.code==code
    assert a['live'].snapshot(owner,a['exam']['id'])['students'][0]['events'][0]['snapshot']['status']=='pending'


def test_production_failure_changes_status_without_duplicate_event(active, owner):
    a=active;tick(a)
    failure={**a['event'],'record_kind':'snapshot_result','snapshot_path':None,
             'snapshot_status':'unavailable','snapshot_reason':'production_failed'}
    with (a['root']/'events.jsonl').open('a') as f:f.write(json.dumps(failure)+'\n')
    tick(a)
    events=a['live'].snapshot(owner,a['exam']['id'])['students'][0]['events']
    assert len(events)==1 and events[0]['event_id']=='event-1'
    assert events[0]['snapshot']['status']=='unavailable'
    assert events[0]['snapshot']['reason']=='production_failed'


def test_snapshot_status_preserves_timeline_order(active, owner, clock):
    a=active
    second={**a['event'],'event_id':'event-2','start_timestamp':iso(clock()+1),
            'snapshot_path':None,'snapshot_status':'unavailable'}
    with (a['root']/'events.jsonl').open('a') as f:f.write(json.dumps(second)+'\n')
    tick(a)
    before=a['live'].snapshot(owner,a['exam']['id'])['students'][0]['events']
    result={**a['event'],'record_kind':'snapshot_result','snapshot_status':'ready'}
    with (a['root']/'events.jsonl').open('a') as f:f.write(json.dumps(result)+'\n')
    publish(a);tick(a)
    after=a['live'].snapshot(owner,a['exam']['id'])['students'][0]['events']
    assert [e['event_id'] for e in before]==[e['event_id'] for e in after]==['event-1','event-2']
    assert after[0]['snapshot']['status']=='available'


def test_queue_cap_defers_without_losing_local_evidence(active):
    a=active;path=publish(a)
    a['journal'].update(a['key'],early_snapshots={str(i):{'complete':True} for i in range(1900)})
    tick(a)
    row=a['journal'].get(a['key'])
    assert row['snapshot_cursor']==0 and row['snapshot_offset']==0
    assert path.exists() and not row.get('receipt')
    assert not any('/snapshots' in endpoint for endpoint,_ in a['calls'])


def test_final_manifest_reuses_early_file_and_only_complete_receipt_cleans(active, clock):
    a=active;publish(a);tick(a)
    row=a['journal'].get(a['key']);item=row['early_snapshots']['event-1'];root=a['root']
    assert not (root/'summary.json').exists()
    summary={'session_id':row['session_id'],'connected_attempt':{'attempt_id':row['attempt_id']},
        'started_at':iso(clock()),'ended_at':iso(clock()+20),'end_reason':'completed','elapsed_seconds':20,
        'remaining_seconds':580,'score':0,'total_questions':2,'events':[a['event']],'snapshot_errors':[],'storage_error':None}
    (root/'summary.json').write_text(json.dumps(summary))
    (root/'answers.json').write_text(json.dumps({'session_id':row['session_id'],'attempt_id':row['attempt_id'],'answers':{}}))
    pdf=Canvas(str(root/'report.pdf'));pdf.drawString(10,20,'Synthetic');pdf.save()
    row=a['journal'].update(a['key'],phase='ended_locally',media_released=True)
    manifest=build_manifest(root.parent,row)
    assert any(i['id']==item['item_id'] for i in manifest['items'])
    wrong=deepcopy(manifest);wrong['items']=[i for i in wrong['items'] if i['id']!=item['item_id']]
    with pytest.raises(Problem) as error: a['sync'].manifest_upload(row['credential'],row['device_secret'],{'manifest':wrong})
    assert error.value.code=='file_conflict'
    for _ in range(15):
        tick(a)
        if a['journal'].get(a['key']).get('cleanup'):break
    row=a['journal'].get(a['key'])
    assert row['receipt']['complete'] is True and row['cleanup'] is True
    assert not (root/'snapshots/event-1.jpg').exists()
    assert not any('/files/'+item['item_id']+'/' in p for p,_ in a['calls'])


def test_slow_network_is_separate_from_controller_and_journal(active):
    a=active;publish(a);entered=threading.Event();release=threading.Event();original=a['worker'].transport
    def slow(*args):
        if '/snapshots/' in args[2]:entered.set();assert release.wait(3)
        return original(*args)
    a['worker'].transport=slow;a['worker'].start()
    try:
        assert entered.wait(3)
        # Controller/checkpoint writes use no upload lock; local work can proceed.
        for elapsed in range(20): a['journal'].update(a['key'],checkpoint={'elapsed_seconds':elapsed})
        assert a['journal'].get(a['key'])['checkpoint']['elapsed_seconds']==19
    finally:
        release.set();a['worker'].close(3)


def test_authenticated_http_upload_notification_thumbnail_and_full_access(active, client, app, owner, other):
    a=active;tick(a);row=a['journal'].get(a['key']);raw=a['jpeg'].getvalue()
    teacher=Peer('teacher',owner,a['exam']['id']);app.state.live.teachers.append(teacher)
    headers={'Authorization':'Bearer '+row['credential'],'X-Device-Secret':row['device_secret']}
    body={'session_id':row['session_id'],'event_id':'event-1','size':len(raw),'sha256':sha256(raw).hexdigest()}
    assert client.post('/api/v1/student/sync/snapshots',json=body).status_code==401
    declared=client.post('/api/v1/student/sync/snapshots',headers=headers,json=body)
    assert declared.status_code==200,declared.text
    item=declared.json()['item_id']
    reply=client.post('/api/v1/student/sync/snapshots/'+item+'/chunks',headers=headers,json={
        'session_id':row['session_id'],'offset':0,'data_base64':base64.b64encode(raw).decode()})
    assert reply.status_code==200,reply.text
    assert teacher.pop()['student']['events'][0]['snapshot']['status']=='available'
    url='/api/v1/attempts/'+row['attempt_id']+'/evidence/'+item
    assert client.get(url).status_code==401
    origin={'Origin':'http://127.0.0.1:5174'}
    assert client.post('/api/v1/auth/login',headers=origin,json={'email':'teacher@example.com','password':'test password 12345'}).status_code==200
    assert client.get(url).content==raw  # same authenticated resource for thumb/full
    assert client.get(url).headers['cache-control']=='no-store'
    assert client.post('/api/v1/auth/login',headers=origin,json={'email':'other@example.com','password':'other password 12345'}).status_code==200
    assert client.get(url).status_code==404


def test_real_loopback_http_notifies_authenticated_teacher_websocket(active, network):
    import httpx
    from websockets.sync.client import connect
    a=active;tick(a);http,websocket,_=network;row=a['row'];raw=a['jpeg'].getvalue()
    origin='http://127.0.0.1:5174'
    with httpx.Client(base_url=http,trust_env=False,timeout=5) as teacher:
        login=teacher.post('/api/v1/auth/login',headers={'Origin':origin},json={
            'email':'teacher@example.com','password':'test password 12345'})
        assert login.status_code==200
        cookie='; '.join(f'{key}={value}' for key,value in teacher.cookies.items())
        with connect(websocket+'/api/v1/live/teacher',origin=origin,additional_headers={'Cookie':cookie},proxy=None) as ws:
            send(ws,{'type':'auth','csrf_token':login.json()['csrf_token'],'exam_id':a['exam']['id']})
            assert receive(ws,'snapshot')['students'][0]['events'][0]['snapshot']['status']=='pending'
            headers={'Authorization':'Bearer '+row['credential'],'X-Device-Secret':row['device_secret']}
            declaration=teacher.post('/api/v1/student/sync/snapshots',headers=headers,json={
                'session_id':row['session_id'],'event_id':'event-1','size':len(raw),'sha256':sha256(raw).hexdigest()})
            item=declaration.json()['item_id']
            reply=teacher.post('/api/v1/student/sync/snapshots/'+item+'/chunks',headers=headers,json={
                'session_id':row['session_id'],'offset':0,'data_base64':base64.b64encode(raw).decode()})
            assert reply.status_code==200,reply.text
            assert receive(ws,'student')['student']['events'][0]['snapshot']['status']=='available'
            assert teacher.get('/api/v1/attempts/'+row['attempt_id']+'/evidence/'+item).content==raw
