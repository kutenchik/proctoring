from copy import deepcopy
import json
from uuid import uuid4
import pytest
from proctoring.exam_policy import default_policy
from proctoring_server.service import Service, Problem
from proctoring_server.configuration import effective
from proctoring_server.sync import checksum
from test_live import live, joined, running, status

def login(client,email='teacher@example.com',password='test password 12345'):
    client.headers['Origin']='http://127.0.0.1:5174'
    r=client.post('/api/v1/auth/login',json={'email':email,'password':password});assert r.status_code==200
    client.headers['X-CSRF-Token']=r.json()['csrf_token']

def test_profile_crud_ownership_restart_and_immutable_default(client,owner,other,settings,clock):
    login(client);p=default_policy()
    r=client.post('/api/v1/configuration/profiles',json={'name':'Classroom','policy':p});assert r.status_code==201,r.text
    item=r.json();id=item['id']
    assert client.put('/api/v1/configuration/profiles/default',json={'name':'bad','policy':p,'version':1}).status_code==404
    changed=deepcopy(p);changed['values']['events.second_person.enabled']=False
    r=client.put('/api/v1/configuration/profiles/'+id,json={'name':'Renamed','policy':changed,'version':1});assert r.status_code==200
    assert client.put('/api/v1/configuration/profiles/'+id,json={'name':'stale','policy':p,'version':1}).status_code==409
    Service(settings,clock=clock)
    assert client.get('/api/v1/configuration/profiles').json()['items'][1]['policy']==changed
    login(client,'other@example.com','other password 12345')
    assert len(client.get('/api/v1/configuration/profiles').json()['items'])==1
    assert client.get('/api/v1/configuration/profiles/'+id).status_code==404
    assert client.delete('/api/v1/configuration/profiles/'+id).status_code==404
    assert client.put('/api/v1/configuration/profiles/'+id,json={'name':'steal','policy':p,'version':2}).status_code==404
    login(client);assert client.delete('/api/v1/configuration/profiles/'+id).status_code==200

def test_exam_snapshot_backward_compatibility_and_unknown_safety_fields(service,owner,exam_data,admission_data):
    legacy=service.create_exam(owner,exam_data);assert 'monitoring_policy' not in legacy['policy']
    p=default_policy();p['values']['events.second_person.enabled']=False
    exam=service.create_exam(owner,{**exam_data,'monitoring_policy':p})
    admitted=service.admit({**admission_data,'exam_code':exam['code'],'student_id':'new'})
    assert admitted['exam']['monitoring_policy']==p
    p['values']['events.second_person.enabled']=True
    assert service.exam(owner,exam['id'])['policy']['monitoring_policy']['values']['events.second_person.enabled'] is False
    p['values']['protection.enabled']=False
    with pytest.raises(Problem):service.create_exam(owner,{**exam_data,'monitoring_policy':p})


def test_new_features_require_v4_and_frozen_settings(live,joined,owner):
    peer,data,attempt,hello=joined
    policy=default_policy()
    policy['values']['advanced.remote_enabled']=True
    policy['values']['advanced.liveness_enabled']=True
    policy['values']['advanced.identity_enabled']=True
    with live.database.connect(write=True) as db:
        old=json.loads(db.execute('SELECT policy_snapshot FROM attempts WHERE id=?',(attempt['attempt_id'],)).fetchone()[0])
        old['monitoring_policy']=policy
        db.execute('UPDATE attempts SET policy_snapshot=? WHERE id=?',(json.dumps(old),attempt['attempt_id']))
    with pytest.raises(Problem):live.consent(peer,{'version':3,'accepted':True})
    start={'start_key':uuid4().hex,'session_id':hello['session_id']}
    with pytest.raises(Problem):live.sync.authorize_start(data['credential'],data['device_secret'],start)
    live.consent(peer,{'version':4,'accepted':True})
    assert live.sync.authorize_start(data['credential'],data['device_secret'],start)['lifecycle']=='start_authorized'
    with live.database.connect() as db:
        row=db.execute('SELECT * FROM attempts WHERE id=?',(attempt['attempt_id'],)).fetchone()
        assert effective(db,row)['policy']==policy


def test_legacy_profile_migrates_without_overwriting_original(client,owner,service):
    from proctoring.exam_policy import LEGACY_KEYS
    login(client)
    legacy={'schema_version':1,'values':{k:v for k,v in default_policy()['values'].items() if k in LEGACY_KEYS}}
    legacy['values']['events.phone_visible.seconds']=2.7
    identity=uuid4().hex
    with service.database.connect(write=True) as db:
        db.execute('INSERT INTO configuration_profiles VALUES (?,?,?,?,?,?,?)',
                   (identity,owner,'Legacy',json.dumps(legacy),1,service.clock(),service.clock()))
    result=client.get('/api/v1/configuration/profiles/'+identity)
    assert result.status_code==200
    policy=result.json()['policy']
    assert policy['schema_version']==3 and policy['values']['events.phone_visible.seconds']==2.7
    assert not policy['values']['advanced.identity_enabled']
    with service.database.connect() as db:
        assert json.loads(db.execute('SELECT policy FROM configuration_profiles WHERE id=?',(identity,)).fetchone()[0])==legacy

def test_live_owned_revision_requires_ack_and_rejects_offline(live,running,owner,other):
    peer,data,attempt,hello=running;p=default_policy();id=attempt['attempt_id']
    # Fixture migration to a versioned initial snapshot before issuing commands.
    with live.database.connect(write=True) as db:
        old=json.loads(db.execute('SELECT policy_snapshot FROM attempts WHERE id=?',(id,)).fetchone()[0]);old['monitoring_policy']=p
        db.execute('UPDATE attempts SET policy_snapshot=? WHERE id=?',(json.dumps(old),id))
    def request(base=0,patch=None):return {'request_id':uuid4().hex,'type':'monitoring_policy','payload':{'reason':'Classroom','base_revision':base,'revision':base+1,'patch':patch or {'events.second_person.enabled':False}}}
    with pytest.raises(Problem):live.command(other,id,request())
    cmd=live.command(owner,id,request())['command']
    with live.database.connect() as db:
        a=live.service.owned_attempt(db,owner,id);assert effective(db,a)['revision']==0
    with pytest.raises(Problem):live.command(owner,id,request())
    new=deepcopy(p);new['values']['events.second_person.enabled']=False
    with pytest.raises(Problem):live.acknowledge(peer,{'command_id':cmd['command_id'],'phase':'applied','result':{'policy_revision':1,'policy_hash':'wrong'}})
    live.acknowledge(peer,{'command_id':cmd['command_id'],'phase':'applied','result':{'policy_revision':1,'policy_hash':checksum(new)}})
    with live.database.connect() as db:assert effective(db,a)['policy']==new
    with pytest.raises(Problem):live.command(owner,id,request())
    with pytest.raises(Problem):live.command(owner,id,request(1,{'audio.enabled':True}))
    second=live.command(owner,id,request(1,{'events.phone_visible.enabled':False}))['command']
    newer=deepcopy(new);newer['values']['events.phone_visible.enabled']=False
    live.acknowledge(peer,{'command_id':second['command_id'],'phase':'applied','result':{'policy_revision':2,'policy_hash':checksum(newer)}})
    with live.database.connect() as db:
        state=effective(db,a);assert state['revision']==2 and state['policy']==newer
    live.students.pop(id)
    with pytest.raises(Problem):live.command(owner,id,request(2))


def test_audio_profile_persistence_and_v2_migration(client,owner,service):
    from proctoring.exam_policy import V2_KEYS
    login(client)
    policy=default_policy();policy['values'].update({'audio.enabled':True,'audio_evidence.enabled':True,'audio_evidence.pre_seconds':2.5,'audio_evidence.post_seconds':4})
    saved=client.post('/api/v1/configuration/profiles',json={'name':'Audio evidence','policy':policy})
    assert saved.status_code==201
    assert client.get('/api/v1/configuration/profiles/'+saved.json()['id']).json()['policy']==policy
    legacy={'schema_version':2,'values':{k:v for k,v in policy['values'].items() if k in V2_KEYS}}
    identity=uuid4().hex
    with service.database.connect(write=True) as db:
        db.execute('INSERT INTO configuration_profiles VALUES (?,?,?,?,?,?,?)',(identity,owner,'V2 audio energy',json.dumps(legacy),1,service.clock(),service.clock()))
    migrated=client.get('/api/v1/configuration/profiles/'+identity).json()['policy']
    assert migrated['schema_version']==3 and not migrated['values']['audio_evidence.enabled']
    with service.database.connect() as db:assert json.loads(db.execute('SELECT policy FROM configuration_profiles WHERE id=?',(identity,)).fetchone()[0])==legacy
