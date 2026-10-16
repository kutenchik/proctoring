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
import wave
import struct
from reportlab.pdfgen.canvas import Canvas

from proctoring.connected.client import ConnectedError
from proctoring.domain import EventType
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
def audio_active(service, owner, exam_data, tmp_path, clock):
    from proctoring.exam_policy import default_policy
    policy=default_policy();policy['values'].update({'audio.enabled':True,'audio_evidence.enabled':True,'snapshots_enabled':False})
    exam = service.create_exam(owner, {**exam_data, 'audio_monitoring':True,'save_snapshots':False,'monitoring_policy':policy})
    credential, device = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    admission = service.admit({'exam_code':exam['code'],'full_name':'Synthetic','group':'Test','student_id':'snap',
        'admission_id':uuid4().hex,'device_id':uuid4().hex,'credential':credential,'device_secret':device})
    sync = SyncService(service)
    live = LiveService(service, sync)
    session = 'session-'+uuid4().hex
    peer = live.student_connect(credential, device, {'type':'hello','protocol':1,'attempt_id':admission['attempt_id'],'session_id':session})
    live.consent(peer, {'version':5,'accepted':True})
    start = {'session_id':session,'start_key':uuid4().hex}
    sync.authorize_start(credential, device, start)
    sync.confirm_start(credential, device, {**start,'started_at':iso(clock())})
    root = tmp_path/'local'/session
    root.mkdir(parents=True)
    metadata = {'session_id':session,'connected_attempt':{'attempt_id':admission['attempt_id']}}
    (root/'session.json').write_text(json.dumps(metadata))
    event = {'session_id':session,'event_id':'event-1','event_type':EventType.VOICE_DETECTED.value,'action':'activated','record_kind':'review_event',
        'start_timestamp':iso(clock()),'audio_path':'audio/event-1.wav','audio_status':'ready','duration_seconds':1}
    (root/'events.jsonl').write_text(json.dumps(event)+'\n')
    journal = DurableJournal(tmp_path/'outbox.db',vault=Vault())
    row = {'attempt_id':admission['attempt_id'],'session_id':session,'server':'http://127.0.0.1:8000',
        'credential':credential,'device_secret':device,'checkpoint':{'elapsed_seconds':1},
        'phase':'locally_started','screen_consent':{'version':5,'accepted':True},'admission':admission,
        'identity_required':False,'report_filename':'report.pdf'}
    key = 'attempt:'+row['attempt_id']; journal.put(key,row)
    calls = []
    def transport(method, origin, endpoint, body, token):
        assert token == credential
        calls.append((endpoint,deepcopy(body)))
        if endpoint == '/student/sync/records': return sync.records_upload(token,device,body)
        if endpoint == '/student/sync/audio': return sync.snapshot_declare(token,device,body,audio=True)
        if endpoint.startswith('/student/sync/audio/'):
            return sync.chunk(token,device,endpoint.split('/')[-2],body,provisional=True)
        if endpoint == '/student/sync/manifest': return sync.manifest_upload(token,device,body)
        if endpoint == '/student/sync/status': return sync.status(token,device)
        if endpoint.startswith('/student/sync/files/'): return sync.chunk(token,device,endpoint.split('/')[-2],body)
        if endpoint == '/student/sync/complete': return sync.complete(token,device,body)
        raise AssertionError(endpoint)
    worker = SyncWorker(journal,root.parent,transport)
    wav=BytesIO()
    with wave.open(wav,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(struct.pack('<h',1000)*160000)
    raw=wav.getvalue()
    return locals()


def tick(a): a['worker'].once(a['journal'].get(a['key']))

def publish(a):
    path=a['root']/'audio/event-1.wav';path.parent.mkdir(exist_ok=True);path.write_bytes(a['raw']);return path


def test_late_upload_retry_owner_live_review_and_final_receipt(audio_active, owner, other, clock):
    a=audio_active;tick(a)
    assert not any('/audio' in p for p,_ in a['calls'])
    path=publish(a);original=a['worker'].transport;lost=[True]
    def drop(*args):
        reply=original(*args)
        if '/audio/' in args[2] and lost[0]:lost[0]=False;raise ConnectedError('connection_failed')
        return reply
    a['worker'].transport=drop
    with pytest.raises(ConnectedError):tick(a)
    assert path.exists() and not a['journal'].get(a['key']).get('receipt')
    a['journal']=DurableJournal(a['journal'].path,vault=Vault())
    a['worker']=SyncWorker(a['journal'],a['root'].parent,original)
    tick(a)
    row=a['journal'].get(a['key']);item=row['early_audio']['event-1']
    assert item['complete'] and not row.get('receipt')
    server_path,media,_=a['sync'].evidence_file(owner,row['attempt_id'],item['item_id'])
    assert media=='audio/wav' and server_path.read_bytes()==path.read_bytes()==a['raw']
    with pytest.raises(Problem):a['sync'].evidence_file(other,row['attempt_id'],item['item_id'])
    with pytest.raises(ValueError):cleanup_received(a['journal'],a['root'].parent,row)
    events=LiveService(a['service'],a['sync']).snapshot(owner,a['exam']['id'])['students'][0]['events']
    assert len(events)==1 and events[0]['event_id']=='event-1' and events[0]['audio']['status']=='available'
    from proctoring_server.review import event_projection
    assert event_projection([a['event']],[{'id':item['item_id'],'kind':'audio','relative_path':item['path'],'complete':True}])[0]['audio']['status']=='available'
    chunks=[b for p,b in a['calls'] if '/audio/' in p]
    assert [b['offset'] for b in chunks]==[0,262144]
    assert a['sync'].chunk(row['credential'],row['device_secret'],item['item_id'],chunks[0],provisional=True)['complete']
    root=a['root']
    summary={'session_id':row['session_id'],'connected_attempt':{'attempt_id':row['attempt_id']},
        'started_at':iso(clock()),'ended_at':iso(clock()+20),'end_reason':'completed','elapsed_seconds':20,
        'remaining_seconds':580,'score':0,'total_questions':2,'events':[a['event']],'snapshot_errors':[],'storage_error':None}
    (root/'summary.json').write_text(json.dumps(summary))
    (root/'answers.json').write_text(json.dumps({'session_id':row['session_id'],'attempt_id':row['attempt_id'],'answers':{}}))
    pdf=Canvas(str(root/'report.pdf'));pdf.drawString(10,20,'Synthetic');pdf.save()
    row=a['journal'].update(a['key'],phase='ended_locally',media_released=True)
    manifest=build_manifest(root.parent,row)
    assert any(i['id']==item['item_id'] and i['required'] for i in manifest['items'])
    wrong=deepcopy(manifest);wrong['items']=[i for i in wrong['items'] if i['kind']!='audio']
    with pytest.raises(Problem):a['sync'].manifest_upload(row['credential'],row['device_secret'],{'manifest':wrong})
    for _ in range(15):
        tick(a)
        if a['journal'].get(a['key']).get('cleanup'):break
    row=a['journal'].get(a['key']);assert row['receipt']['complete'] and row['cleanup']
    assert not path.exists() and server_path.read_bytes()==a['raw']
    clock.advance(30*86400)
    assert not a['sync'].retain()['deleted']
    clock.advance(21)
    assert len(a['sync'].retain()['deleted'])==1 and not server_path.exists()
    with a['service'].database.connect() as db:
        assert not db.execute('SELECT 1 FROM event_audio WHERE attempt_id=?',(row['attempt_id'],)).fetchone()


@pytest.mark.parametrize('version',[3,4])
def test_recording_consent_required_at_start_and_upload(audio_active,version):
    a=audio_active;publish(a);row=a['row']
    with a['service'].database.connect(write=True) as db:db.execute('UPDATE live_attempts SET consent_version=? WHERE attempt_id=?',(version,row['attempt_id']))
    with pytest.raises(Problem):a['sync'].authorize_start(row['credential'],row['device_secret'],a['start'])
    with pytest.raises(Problem):tick(a)
    assert not a['sync'].status(row['credential'],row['device_secret'])['files']


@pytest.mark.parametrize('raw',[b'RIFF'+b'X'*60,b'X'*480045],ids=['malformed','oversize'])
def test_invalid_audio_never_available(audio_active,raw,owner):
    a=audio_active;tick(a);row=a['row']
    with pytest.raises(Problem):
        declared=a['sync'].snapshot_declare(row['credential'],row['device_secret'],{'session_id':row['session_id'],'event_id':'event-1','size':len(raw),'sha256':sha256(raw).hexdigest()},audio=True)
        a['sync'].chunk(row['credential'],row['device_secret'],declared['item_id'],{'session_id':row['session_id'],'offset':0,'data_base64':base64.b64encode(raw).decode()},provisional=True)
    assert a['live'].snapshot(owner,a['exam']['id'])['students'][0]['events'][0]['audio']['status']=='pending'


def test_wrong_event_and_changed_original_rejected(audio_active):
    a=audio_active;path=publish(a);tick(a);tick(a);row=a['journal'].get(a['key']);item=row['early_audio']['event-1']
    for event,sha in [('other',item['sha256']),('event-1','0'*64)]:
        with pytest.raises(Problem):a['sync'].snapshot_declare(row['credential'],row['device_secret'],{'session_id':row['session_id'],'event_id':event,'size':item['size'],'sha256':sha},audio=True)
    row['early_audio']['event-1']['complete']=False;a['journal'].put(a['key'],row)
    path.write_bytes(a['raw'][:-2]+b'xx')
    with pytest.raises(ValueError,match='local_evidence_changed'):tick(a)


def test_http_audio_notification_range_and_owner(audio_active,client,app,owner,other):
    a=audio_active;tick(a);row=a['row'];raw=a['raw']
    teacher=Peer('teacher',owner,a['exam']['id']);app.state.live.teachers.append(teacher)
    headers={'Authorization':'Bearer '+row['credential'],'X-Device-Secret':row['device_secret']}
    declared=client.post('/api/v1/student/sync/audio',headers=headers,json={'session_id':row['session_id'],'event_id':'event-1','size':len(raw),'sha256':sha256(raw).hexdigest()})
    assert declared.status_code==200;item=declared.json()['item_id']
    for offset in range(0,len(raw),262144):
        response=client.post('/api/v1/student/sync/audio/'+item+'/chunks',headers=headers,json={'session_id':row['session_id'],'offset':offset,'data_base64':base64.b64encode(raw[offset:offset+262144]).decode()})
        assert response.status_code==200
    assert teacher.pop()['student']['events'][0]['audio']['status']=='available'
    url='/api/v1/attempts/'+row['attempt_id']+'/evidence/'+item
    assert client.get(url).status_code==401
    origin={'Origin':'http://127.0.0.1:5174'}
    assert client.post('/api/v1/auth/login',headers=origin,json={'email':'teacher@example.com','password':'test password 12345'}).status_code==200
    response=client.get(url,headers={'Range':'bytes=44-1043'})
    assert response.status_code==206 and response.content==raw[44:1044]
    assert response.headers['content-type']=='audio/wav' and response.headers['cache-control']=='no-store'
    assert client.post('/api/v1/auth/login',headers=origin,json={'email':'other@example.com','password':'other password 12345'}).status_code==200
    assert client.get(url).status_code==404


def test_failed_clip_blocks_complete_receipt_and_retains_material(audio_active,clock):
    a=audio_active;root=a['root'];row=a['row']
    failure={**a['event'],'audio_path':None,'audio_status':'unavailable','audio_reason':'write_failed'}
    (root/'events.jsonl').write_text(json.dumps(failure)+'\n')
    (root/'summary.json').write_text(json.dumps({'session_id':row['session_id'],'connected_attempt':{'attempt_id':row['attempt_id']},'ended_at':iso(clock()+20),'end_reason':'completed','events':[failure]}))
    row=a['journal'].update(a['key'],phase='ended_locally',media_released=True)
    manifest=build_manifest(root.parent,row)
    item=next(i for i in manifest['items'] if i['kind']=='audio')
    assert item['required'] and item['status']=='missing_error'
    from proctoring.connected.sync import verify_receipt
    with pytest.raises(ValueError,match='required_material_missing'):verify_receipt({**row,'manifest':manifest},{'complete':True})
    assert (root/'events.jsonl').exists()
