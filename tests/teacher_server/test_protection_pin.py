import json
import pytest
from proctoring_server.protection_pin import ProtectionPins
from proctoring_server.service import Problem

def test_pin_secret_rotation_rate_limit_and_ownership(service,owner,other,admitted,clock):
 pins=ProtectionPins(service)
 assert not pins.status(owner)['configured']
 assert pins.change(owner,{'pin':'836204','confirm_pin':'836204','revision':0})['revision']==1
 assert not pins.status(other)['configured']
 data={'pin':'836204','revision':1,'action':'proctor.pause','nonce':'a'*32}
 assert pins.verify(admitted['credential'],data)['authorized'] is True
 pins.change(owner,{'pin':'914827','confirm_pin':'914827','revision':1})
 with pytest.raises(Problem):pins.verify(admitted['credential'],data)
 for _ in range(8):
  with pytest.raises(Problem):pins.verify(admitted['credential'],{**data,'pin':'000000','revision':2})
 with pytest.raises(Problem) as failure:pins.verify(admitted['credential'],{**data,'pin':'914827','revision':2})
 assert failure.value.status==429
 clock.advance(901)
 assert pins.verify(admitted['credential'],{**data,'pin':'914827','revision':2})['authorized']
 with service.database.connect() as db:
  value=db.execute('SELECT verifier FROM protection_pins WHERE teacher_id=?',(owner,)).fetchone()[0]
  assert value.startswith('scrypt$') and '914827' not in value
  logs=json.dumps([dict(r) for r in db.execute('SELECT * FROM audit_log')])
  assert '836204' not in logs and '914827' not in logs
 assert 'verifier' not in json.dumps(pins.status(owner))
 assert '914827' not in json.dumps(service.student_attempt(admitted['credential']))

def test_pin_http_requires_session_csrf_origin(client,owner):
 assert client.get('/api/v1/settings/protection-pin').status_code==401
 login=client.post('/api/v1/auth/login',headers={'origin':'http://127.0.0.1:5174'},json={'email':'teacher@example.com','password':'test password 12345'})
 assert login.status_code==200
 payload={'pin':'836204','confirm_pin':'836204','revision':0}
 assert client.post('/api/v1/settings/protection-pin',json=payload).status_code==403
 headers={'origin':'http://127.0.0.1:5174','x-csrf-token':login.json()['csrf_token']}
 assert client.post('/api/v1/settings/protection-pin',headers=headers,json=payload).status_code==200
 assert client.post('/api/v1/settings/protection-pin',headers=headers,json=payload).status_code==409
 assert client.post('/api/v1/student/protection-pin/verify',json={}).status_code==401
