"""Real loopback ASGI/WebSocket transport; synthetic JPEGs, no hardware capture."""
from contextlib import contextmanager
import json
import secrets
import socket
import threading
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn
from websockets.sync.client import connect

from proctoring_server.service import iso
from test_live import status, jpeg_frame


@pytest.fixture
def network(app):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error',
        access_log=False, proxy_headers=False, ws='websockets-sansio', ws_max_size=393216,
        ws_max_queue=8, ws_per_message_deflate=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic()+5
    while not server.started and thread.is_alive() and time.monotonic()<deadline:
        time.sleep(.01)
    assert server.started
    try:
        yield f'http://127.0.0.1:{port}', f'ws://127.0.0.1:{port}', app
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive(), 'Owned loopback server did not terminate'


def receive(ws, kind):
    for _ in range(40):
        data=json.loads(ws.recv(timeout=3))
        if data.get('type')=='error':
            pytest.fail('WebSocket error: '+data['code'])
        if data.get('type')==kind:
            return data
    pytest.fail('Expected WebSocket packet missing: '+kind)


def send(ws, data):
    ws.send(json.dumps(data, allow_nan=False))


@contextmanager
def connected(network, service, admission_data, clock):
    http, websocket, app = network
    identity={**admission_data,'admission_id':uuid4().hex,'device_id':uuid4().hex,
              'device_secret':secrets.token_urlsafe(32),'credential':secrets.token_urlsafe(32)}
    admitted=service.admit(identity)
    headers={'Authorization':'Bearer '+identity['credential'],'X-Device-Secret':identity['device_secret']}
    session='session-'+uuid4().hex
    hello={'type':'hello','protocol':1,'attempt_id':admitted['attempt_id'],'session_id':session}
    with connect(websocket+'/api/v1/live/student',additional_headers=headers,proxy=None) as student:
        send(student,hello); receive(student,'hello')
        send(student,{'type':'consent','accepted':True,'version':3})
        consent=receive(student,'consent')
        start={'start_key':uuid4().hex,'session_id':session}
        app.state.sync.authorize_start(identity['credential'],identity['device_secret'],start)
        app.state.sync.confirm_start(identity['credential'],identity['device_secret'],{**start,'started_at':iso(clock())})
        send(student,status())
        yield student, identity, admitted, hello, consent


def test_real_ws_running_reconnect_consent_and_command_ack(network,service,admission_data,clock):
    http,websocket,app=network
    with connected(network,service,admission_data,clock) as first:
        student,identity,attempt,hello,consent=first
        student.close()
    headers={'Authorization':'Bearer '+identity['credential'],'X-Device-Secret':identity['device_secret']}
    with connect(websocket+'/api/v1/live/student',additional_headers=headers,proxy=None) as student, httpx.Client(base_url=http) as teacher:
        send(student,hello); receive(student,'hello')
        send(student,{'type':'consent','version':3,'accepted':True})
        assert receive(student,'consent')==consent
        send(student,status())
        login=teacher.post('/api/v1/auth/login',headers={'Origin':'http://127.0.0.1:5174'},json={'email':'teacher@example.com','password':'test password 12345'})
        assert login.status_code==200
        auth={'Origin':'http://127.0.0.1:5174','X-CSRF-Token':login.json()['csrf_token']}
        response=teacher.post(f"/api/v1/attempts/{attempt['attempt_id']}/commands",headers=auth,json={'request_id':uuid4().hex,'type':'pause','payload':{'reason':'operator check'}})
        assert response.status_code==200, response.text
        command=receive(student,'command')
        assert command['command_type']=='pause'
        send(student,{'type':'command_ack','command_id':command['command_id'],'phase':'applied','result':{'state':'paused','pause_reasons':['teacher']}})
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=teacher.get(f"/api/v1/attempts/{attempt['attempt_id']}/commands").json()['items'][0]
            if result['status']=='applied':break
            time.sleep(.01)
        assert result['status']=='applied'
        send(student,{'type':'consent','version':3,'accepted':False})
        assert json.loads(student.recv(timeout=3))['code']=='consent_locked'


def test_real_ws_relay_authenticated_peer_ready_and_cleanup(network,service,admission_data,clock):
    http,websocket,app=network
    with connected(network,service,admission_data,clock) as running, httpx.Client(base_url=http) as teacher:
        control,_,attempt,_,_=running
        login=teacher.post('/api/v1/auth/login',headers={'Origin':'http://127.0.0.1:5174'},json={'email':'teacher@example.com','password':'test password 12345'}).json()
        auth={'Origin':'http://127.0.0.1:5174','X-CSRF-Token':login['csrf_token']}
        result=teacher.post(f"/api/v1/attempts/{attempt['attempt_id']}/view",headers=auth,json={})
        assert result.status_code==200,result.text
        view=result.json(); command=receive(control,'view.start')
        with connect(websocket+'/api/v1/live/stream',proxy=None) as sender:
            send(sender,{'role':'student','viewer_id':view['viewer_id'],'token':command['sender_token']})
            assert receive(sender,'stream.ready')['peer_connected'] is False
            send(sender,jpeg_frame(view))  # safely discarded before receiver attaches
            cookie='proctor_teacher_session='+teacher.cookies.get('proctor_teacher_session')
            with connect(websocket+'/api/v1/live/stream',origin=auth['Origin'],additional_headers={'Cookie':cookie},proxy=None) as receiver:
                send(receiver,{'role':'teacher','viewer_id':view['viewer_id'],'csrf_token':login['csrf_token']})
                assert receive(receiver,'stream.ready')['peer_connected'] is True
                assert receive(sender,'peer.ready')['viewer_id']==view['viewer_id']
                send(sender,jpeg_frame(view,2))
                frame=receive(receiver,'frame')
                assert frame['sequence']==2 and frame['server_received_at']
                send(receiver,{'type':'frame_ack','sequence':2})
                assert receive(sender,'frame_ack')['sequence']==2
                send(receiver,{'type':'renew'})
                assert receive(receiver,'renewed')['viewer_id']==view['viewer_id']
            assert receive(control,'view.stop')['reason']=='disconnected'
        assert not app.state.live.viewers
        assert not list(service.settings.evidence_root.rglob('*'))
        with service.database.connect() as db:
            actions=[r[0] for r in db.execute('SELECT action FROM audit_log WHERE resource_id=?',(attempt['attempt_id'],))]
        assert 'screen_view_presented' in actions


def test_real_ws_origin_and_device_rejected(network,service,admission_data):
    _,websocket,_=network
    from websockets.exceptions import InvalidStatus
    with pytest.raises(InvalidStatus):
        with connect(websocket+'/api/v1/live/teacher',origin='https://evil.example',proxy=None):
            pass
    with connect(websocket+'/api/v1/live/student',additional_headers={'Authorization':'Bearer '+secrets.token_urlsafe(32),'X-Device-Secret':secrets.token_urlsafe(32)},proxy=None) as ws:
        send(ws,{'type':'hello','protocol':1,'attempt_id':uuid4().hex,'session_id':'session-'+uuid4().hex})
        assert json.loads(ws.recv(timeout=3))['type']=='error'


@pytest.mark.parametrize('failure',['sender_close','server_rejection'])
def test_real_ws_first_stop_reason_survives_finally(network,service,admission_data,clock,failure):
    http,websocket,app=network
    with connected(network,service,admission_data,clock) as running, httpx.Client(base_url=http) as teacher:
        control,_,attempt,_,_=running
        login=teacher.post('/api/v1/auth/login',headers={'Origin':'http://127.0.0.1:5174'},json={'email':'teacher@example.com','password':'test password 12345'}).json()
        auth={'Origin':'http://127.0.0.1:5174','X-CSRF-Token':login['csrf_token']}
        view=teacher.post(f"/api/v1/attempts/{attempt['attempt_id']}/view",headers=auth,json={}).json()
        command=receive(control,'view.start')
        with connect(websocket+'/api/v1/live/stream',proxy=None) as sender:
            send(sender,{'role':'student','viewer_id':view['viewer_id'],'token':command['sender_token']})
            receive(sender,'stream.ready')
            if failure=='sender_close':
                sender.close(1000,'privacy_mask_unavailable');expected='privacy_mask_unavailable'
            else:
                send(sender,{'type':'quality','width':0});expected='invalid_quality'
                assert json.loads(sender.recv(timeout=3))=={'type':'error','code':expected}
            assert receive(control,'view.stop')['reason']==expected
        assert not app.state.live.viewers

