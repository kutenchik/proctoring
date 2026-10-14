import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from proctoring_server.app import create_app
from proctoring_server.demo import DemoGateway, quick_origin
from proctoring_server.settings import Settings

ORIGIN='https://demo-unit.trycloudflare.com'

@pytest.fixture
def demo(tmp_path):
    frontend=tmp_path/'dist';frontend.mkdir();(frontend/'index.html').write_text('<html>Teacher</html>')
    (frontend/'assets').mkdir();(frontend/'assets/app.js').write_text('export {}')
    (frontend/'assets/private.js.map').write_text('SECRET');(frontend/'secret.py').write_text('SECRET')
    settings=Settings(database=tmp_path/'db.sqlite3',public_url=ORIGIN,teacher_origin=ORIGIN)
    api=create_app(settings,public_errors=True)
    gateway=DemoGateway(api,ORIGIN,frontend)
    with TestClient(gateway,base_url=ORIGIN,client=('127.0.0.1',12345),headers={'X-Forwarded-Proto':'https'}) as client:
        yield gateway,api,client

@pytest.mark.parametrize('origin',['http://x.trycloudflare.com','https://*.trycloudflare.com','https://a.trycloudflare.com.evil','https://a.trycloudflare.com/','https://a.trycloudflare.com:443','https://user@a.trycloudflare.com'])
def test_exact_origin_configuration(origin):
    with pytest.raises(ValueError):quick_origin(origin)

def test_routes_headers_and_forwarded_spoof(demo):
    gateway,api,c=demo
    assert c.get('/').status_code==200
    assert "script-src 'self'" in c.get('/').headers['content-security-policy']
    assert c.get('/assets/app.js').status_code==200
    for path in ['/secret.py','/assets/private.js.map','/server/data/teacher.sqlite3','/evidence/x.jpg','/docs','/openapi.json','/.env','/assets/../secret.py']:
        assert c.get(path).status_code==404
    assert c.get('/api/v1/health',headers={'Host':'other.trycloudflare.com','X-Forwarded-Host':'demo-unit.trycloudflare.com'}).status_code==400
    assert c.get('/api/v1/health',headers={'X-Forwarded-Proto':'http'}).status_code==400
    assert c.get('/api/v1/health',headers={'Origin':'https://other.trycloudflare.com'}).status_code==403
    assert c.get('/api/v1/health',headers={'Forwarded':'host=evil;proto=http','X-Forwarded-For':'8.8.8.8'}).status_code==200
    assert c.get('/api/v1/health',headers=[('Host','demo-unit.trycloudflare.com'),('Host','evil')]).status_code==400

def test_cookie_csrf_invite_reset_and_private_routes(demo):
    gateway,api,c=demo;service=api.state.service
    token=service.issue_account_token('invite','demo@example.com')
    h={'Origin':ORIGIN};password='disposable demo password'
    assert c.post('/api/v1/auth/accept-invite',headers=h,json={'token':token,'name':'Demo','password':password}).status_code==200
    login=c.post('/api/v1/auth/login',headers=h,json={'email':'demo@example.com','password':password})
    assert login.status_code==200
    cookie=login.headers['set-cookie']
    assert all(s in cookie for s in ['Secure','HttpOnly','SameSite=strict','Path=/api/v1'])
    assert c.get('/api/v1/auth/me').status_code==200
    assert c.post('/api/v1/auth/logout',headers=h,json={}).status_code==403
    assert c.post('/api/v1/auth/logout',headers={**h,'X-CSRF-Token':login.json()['csrf_token']},json={}).status_code==200
    assert c.get('/api/v1/exams').status_code==401
    assert c.get('/api/v1/attempts/unknown/reports/original').status_code==401
    assert c.get('/api/v1/student/attempt').status_code==401
    reset=service.issue_account_token('reset','demo@example.com')
    assert c.post('/api/v1/auth/reset-password',headers=h,json={'token':reset,'password':password+'2'}).status_code==200

def test_websocket_origin_and_identity(demo):
    _,_,c=demo
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(ORIGIN.replace('https:','wss:')+'/api/v1/live/teacher',headers={'Origin':'https://other.trycloudflare.com'}):pass
    with c.websocket_connect(ORIGIN.replace('https:','wss:')+'/api/v1/live/student') as ws:
        ws.send_json({'type':'hello'})
        assert ws.receive_json()['code']=='invalid_credential'
    with c.websocket_connect(ORIGIN.replace('https:','wss:')+'/api/v1/live/teacher',headers={'Origin':ORIGIN}) as ws:
        ws.send_json({'type':'auth','csrf_token':'invalid','exam_id':'invalid'})
        assert ws.receive_json()['type']=='error'

def test_bounded_admission_and_connection_limits(demo):
    g,_,c=demo
    g.http_active=16;assert c.get('/api/v1/health').status_code==429;g.http_active=0
    for _ in range(30):assert c.post('/api/v1/student/admit',json={}).status_code!=429
    assert c.post('/api/v1/student/admit',json={}).status_code==429
    assert len(g.auth_requests)==30

def test_nonloopback_peer_rejected(demo):
    g,_,_=demo
    with TestClient(g,base_url=ORIGIN,client=('192.168.1.10',123),headers={'X-Forwarded-Proto':'https'}) as c:
        assert c.get('/api/v1/health').status_code==400

def test_public_errors_and_body_limit(demo):
    _,api,c=demo
    @api.get('/api/v1/test-error')
    def error():raise ValueError('C:/private/secret')
    result=c.get('/api/v1/test-error');assert result.status_code==400 and 'private' not in result.text
    assert c.post('/api/v1/student/admit',content=b'x'*(3*1024*1024+1)).status_code==413
