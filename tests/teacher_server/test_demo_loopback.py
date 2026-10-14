"""Actual loopback TCP and sockets through the deployment boundary; no TLS edge,
public DNS, tunnel, device, Electron or physical pixels are involved."""
import json
import secrets
import socket
from uuid import uuid4
import httpx
import pytest
from websockets.sync.client import connect
from proctoring_server.settings import Settings
from proctoring_server.app import create_app
from proctoring_server.demo import DemoGateway
from proctoring_server.service import iso
from test_live import status,jpeg_frame
from test_live_api import network,send,receive

ORIGIN='https://loopback-fixture.trycloudflare.com'
HOST='loopback-fixture.trycloudflare.com'

@pytest.fixture
def settings(tmp_path):return Settings(database=tmp_path/'isolated.sqlite3',public_url=ORIGIN,teacher_origin=ORIGIN)

@pytest.fixture
def app(settings,clock,tmp_path):
    dist=tmp_path/'dist';dist.mkdir();(dist/'index.html').write_text('<html>synthetic teacher</html>')
    api=create_app(settings,clock=clock,public_errors=True)
    gateway=DemoGateway(api,ORIGIN,dist);gateway.state=api.state
    return gateway

def test_actual_boundary_authenticated_relay_and_stop(network,service,admission_data,clock):
    http,_,app=network;port=int(http.rsplit(':',1)[1])
    def ws(path,origin=None,extra=None):
        transport=socket.create_connection(('127.0.0.1',port),timeout=3)
        return connect('ws://'+HOST+path,sock=transport,origin=origin,
                       additional_headers={'X-Forwarded-Proto':'https',**(extra or {})},proxy=None)
    with httpx.Client(base_url=http,headers={'Host':HOST,'X-Forwarded-Proto':'https'},trust_env=False) as c:
        assert c.get('/').status_code==200
        identity={**admission_data,'admission_id':uuid4().hex,'device_id':uuid4().hex,
                  'device_secret':secrets.token_urlsafe(32),'credential':secrets.token_urlsafe(32)}
        response=c.post('/api/v1/student/admit',json=identity);assert response.status_code==201
        attempt=response.json();session='session-'+uuid4().hex
        headers={'Authorization':'Bearer '+identity['credential'],'X-Device-Secret':identity['device_secret']}
        with ws('/api/v1/live/student',extra=headers) as control:
            send(control,{'type':'hello','protocol':1,'attempt_id':attempt['attempt_id'],'session_id':session});receive(control,'hello')
            send(control,{'type':'consent','accepted':True,'version':2});assert receive(control,'consent')['version']==2
            start={'start_key':uuid4().hex,'session_id':session}
            app.state.sync.authorize_start(identity['credential'],identity['device_secret'],start)
            app.state.sync.confirm_start(identity['credential'],identity['device_secret'],{**start,'started_at':iso(clock())})
            send(control,status())
            login=c.post('/api/v1/auth/login',headers={'Origin':ORIGIN},json={'email':'teacher@example.com','password':'test password 12345'})
            assert login.status_code==200
            cookie='proctor_teacher_session='+c.cookies.get('proctor_teacher_session')
            auth={'Origin':ORIGIN,'X-CSRF-Token':login.json()['csrf_token'],'Cookie':cookie}
            view=c.post('/api/v1/attempts/'+attempt['attempt_id']+'/view',headers=auth,json={})
            assert view.status_code==200,view.text
            view=view.json();command=receive(control,'view.start')
            with ws('/api/v1/live/stream') as sender, ws('/api/v1/live/stream',ORIGIN,{'Cookie':cookie}) as receiver:
                send(sender,{'role':'student','viewer_id':view['viewer_id'],'token':command['sender_token']});receive(sender,'stream.ready')
                send(receiver,{'role':'teacher','viewer_id':view['viewer_id'],'csrf_token':login.json()['csrf_token']});receive(receiver,'stream.ready');receive(sender,'peer.ready')
                send(receiver,{'type':'transport','transport':'relay','reason':'direct_timeout','viewer_id':view['viewer_id']})
                assert receive(sender,'transport')['transport']=='relay'
                send(sender,jpeg_frame(view));assert receive(receiver,'frame')['sequence']==1
                send(receiver,{'type':'frame_ack','sequence':1});assert receive(sender,'frame_ack')['sequence']==1
                send(receiver,{'type':'renew'});assert receive(receiver,'renewed')['viewer_id']==view['viewer_id']
                assert c.post('/api/v1/live/view/stop',headers=auth,json={'viewer_id':view['viewer_id']}).status_code==200
                assert receive(sender,'view.stop')['reason']=='teacher_stopped'
