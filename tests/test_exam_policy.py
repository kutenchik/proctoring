from copy import deepcopy
from dataclasses import replace
import pytest
from proctoring.exam_policy import *
from proctoring.config import load_config
from proctoring.clock import FakeClock
from proctoring.domain import Observation
from proctoring.events import EventEngine
from proctoring.connected.client import frozen_policy, ConnectedError
from test_connected_client import ADMISSION


def test_catalog_complete_localized_and_defaults_from_python():
    c=catalog();assert len(c['fields'])==len(BY_KEY)==36
    assert c['default']['values']==values_from_config(load_config(__import__('pathlib').Path('config/default.example.toml')))
    for f in c['fields']:
        assert all(f['labels'][l] and f['descriptions'][l] for l in LANGUAGES)
        assert f['mapping'] and f['teacher_editable'] and f['component'] in ('toggle','number','select')
    for f in FIELDS:
        if f.depends_on:assert f.depends_on in BY_KEY

@pytest.mark.parametrize('value',[True,'2',None,float('nan'),float('inf'),-.1,61])
def test_reject_invalid_duration(value):
    with pytest.raises(ValueError):validate_values({'events.second_person.seconds':value},complete=False)

@pytest.mark.parametrize('key',['proctor_pin','protection.enabled','protection.heartbeat_timeout_seconds','vision.yolo_model','duration_seconds'])
def test_reject_host_and_deadline_override(key):
    p=default_policy();p['values'][key]=False
    with pytest.raises(ValueError):validate_policy(p)

def test_policy_versions_and_incomplete_saved_values_fail_closed():
    p=default_policy();p['schema_version']=999
    with pytest.raises(ValueError):validate_policy(p)
    p=default_policy();del p['values']['audio.enabled']
    with pytest.raises(ValueError):validate_policy(p)

def test_frozen_transfer_and_legacy_host_defaults():
    host=load_config();admission=deepcopy(ADMISSION);old,_=frozen_policy(host,admission)
    assert old.thresholds==host.thresholds
    p=default_policy();p['values'].update({'audio.enabled':False,'snapshots_enabled':False,'events.second_person.enabled':False,'events.phone_visible.seconds':.2})
    admission['exam']['monitoring_policy']=p;updated,_=frozen_policy(host,admission)
    assert updated.event_rules['second_person'] is False and updated.thresholds[EventType.PHONE_VISIBLE]==.2
    assert updated.protection==host.protection and updated.proctor_pin==host.proctor_pin and updated.vision.yolo_model==host.vision.yolo_model
    admission['exam']['audio_monitoring']=True
    with pytest.raises(ConnectedError):frozen_policy(host,admission)

def test_disabled_rule_and_timing_while_shared_phone_observation_still_works():
    clock=FakeClock();e=EventEngine({EventType.SECOND_PERSON:.2,EventType.PHONE_VISIBLE:.2},.2,clock)
    e.configure_policy(e.thresholds,.2,{EventType.SECOND_PERSON})
    for _ in range(5):
        e.observe(Observation(clock.monotonic(),{EventType.SECOND_PERSON:.9,EventType.PHONE_VISIBLE:.9},'synthetic'));clock.advance(.1)
    assert [v['event_type'] for v in e.events]==['phone_visible']
    old_id=e.events[0]['event_id'];changes=e.configure_policy({EventType.SECOND_PERSON:.2,EventType.PHONE_VISIBLE:1},.2)
    assert changes[0]['close_reason']=='policy_changed' and e.events[0]['event_id']==old_id
    for _ in range(5):
        e.observe(Observation(clock.monotonic(),{EventType.PHONE_VISIBLE:.9},'synthetic'));clock.advance(.1)
    assert len(e.events)==1
    for _ in range(8):
        e.observe(Observation(clock.monotonic(),{EventType.PHONE_VISIBLE:.9},'synthetic'));clock.advance(.1)
    assert len(e.events)==2 and e.events[1]['event_id']!=old_id

@pytest.mark.parametrize('key',['audio.enabled','snapshots_enabled'])
def test_capture_may_only_be_disabled_live(key):
    p=default_policy();new=live_patch(p,{key:False});assert not new['values'][key]
    with pytest.raises(ValueError):live_patch(new,{key:True})

def test_real_admission_configures_mock_workers_before_capture(tmp_path):
    from test_connected_workflow import connected_workflow
    from test_connected_client import IDENTITY
    from proctoring.desktop_bridge.protocol import BridgeError
    b=connected_workflow(tmp_path)
    try:
        original=b.admission_client.transport
        p=default_policy();p['values'].update({'audio.enabled':False,'snapshots_enabled':False,'events.second_person.enabled':False,'vision.phone_confidence':.7})
        def transport(*args):
            result=original(*args)
            if isinstance(result,dict) and 'exam' in result:result['exam']['monitoring_policy']=p
            return result
        b.admission_client.transport=transport
        b.dispatch('connected.admit',IDENTITY);b.admission_client._thread.join(2);b.tick()
        assert b._admission_applied,b.admission_client.error
        assert b.monitor.config.phone_confidence==.7 and not b.monitor.started
        assert b.controller.audio is None and EventType.SECOND_PERSON in b.controller.events.disabled
        with pytest.raises(BridgeError):b.dispatch('audio.start',{})
    finally:b.close()

def test_live_backend_ack_revision_history_and_stale_rejection(tmp_path):
    from test_connected_stage3 import make_live, command
    from proctoring.connected.sync import digest
    b,t,j,w,count=make_live(tmp_path)
    try:
        b.effective_policy={'schema_version':VERSION,'values':values_from_config(b.config)};b.policy_revision=0
        original=b.effective_policy
        payload={'reason':'Crowded classroom','patch':{'events.second_person.enabled':False},'base_revision':0,'revision':1}
        command(b,w,'monitoring_policy',payload)
        assert b.policy_revision==1 and EventType.SECOND_PERSON in b.controller.events.disabled
        assert w.sent[-1]['phase']=='applied' and w.sent[-1]['result']['policy_hash']==digest(b.effective_policy)
        assert j.attempts()[0]['policy_revision']==1
        command(b,w,'monitoring_policy',payload)
        assert w.sent[-1]['phase']=='rejected' and b.policy_revision==1
        b.live_teacher.consent_acknowledged=False
        command(b,w,'monitoring_policy',{**payload,'base_revision':1,'revision':2})
        assert w.sent[-1]['phase']=='rejected'
        assert original['values']['events.second_person.enabled'] is True
    finally:b.close()


def test_live_capture_disable_and_expired_patch(tmp_path):
    from test_connected_stage3 import make_live, command
    from uuid import uuid4
    b,t,j,w,count=make_live(tmp_path)
    class Audio:
        stopped=False
        def stop(self):self.stopped=True
    audio=Audio()
    try:
        b.effective_policy={'schema_version':VERSION,'values':values_from_config(b.config)}
        b.controller.audio=audio
        payload={'reason':'Quiet classroom','patch':{'audio.enabled':False,'snapshots_enabled':False,'clearing_seconds':1.5},'base_revision':0,'revision':1}
        value=command(b,w,'monitoring_policy',payload)
        assert audio.stopped and b.controller.audio is None
        assert b.controller.config.snapshots_enabled is False and b.controller.events.clearing_seconds==1.5
        assert w.sent[-1]['phase']=='applied'
        value.update(command_id=uuid4().hex,payload={**payload,'base_revision':1,'revision':2})
        b.live_teacher.apply_command(value,w.connection_id,w.clock())
        assert w.sent[-1]['phase']=='rejected' and b.policy_revision==1
    finally:b.close()


def test_source_fingerprint_covers_policy_enforcement_without_running_native_code():
    from types import SimpleNamespace
    from proctoring.security.electron_validation import runtime_resources
    root,paths,_,_=runtime_resources(SimpleNamespace(runtime={'build_kind':'source'}))
    relative={p.relative_to(root).as_posix() for p in paths}
    assert {'src/proctoring/exam_policy.py','src/proctoring/events/engine.py',
            'src/proctoring/connected/client.py','src/proctoring/connected/live_workflow.py',
            'config/default.example.toml'}<=relative
