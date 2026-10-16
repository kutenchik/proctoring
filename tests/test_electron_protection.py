"""Deterministic safety tests; no hooks, keyboard input, processes, or devices."""
import copy
from datetime import datetime, timezone, timedelta
from itertools import product
import json
from types import SimpleNamespace
import pytest
from proctoring.security.control_lease import ControlLease
from proctoring.security.electron_binding import ElectronHostBinding, pointer
from proctoring.security.electron_helper import ElectronHelperRuntime
from proctoring.security.electron import ElectronProtection
from proctoring.security.electron_validation import require_electron_validation, MANDATORY_CHECKS, artifact_fingerprint
from proctoring.security.guardian import GuardianOwner
from proctoring.security.settings import ProtectionConfig


LAUNCH='a'*32


def payload():
    return {'launch_id':LAUNCH,'host_pid':123,'windows':[{'hwnd':'0xabc','role':'exam'}],
            'runtime':{'electron_version':'40','app_version':'1','build_kind':'source','build_id':'b'*64}}


class Native:
    def __init__(self):
        self.living=True; self.created='1234567'; self.owner=123; self.stamps={}; self.closed=[]; self.killed=[]; self.lock=False
    def open_process(self,pid,terminate=False): return ('retained',pid)
    def creation(self,handle): return self.created
    def alive(self,handle): return self.living
    def image(self,handle): return 'C:/owned/Electron.exe'
    def close(self,handle): self.closed.append(handle)
    def window_owner(self,hwnd): return self.owner
    def stamp(self,hwnd,name,value): self.stamps[(hwnd,name)]=value
    def stamped(self,hwnd,name): return self.stamps.get((hwnd,name),0)
    def unstamp(self,hwnd,name): self.stamps.pop((hwnd,name),None)
    def terminate(self,handle,timeout): self.killed.append(handle); self.living=False
    def desktop_mutex(self):
        if self.lock: raise RuntimeError('desktop in use')
        self.lock=True; return 99
    def release_mutex(self,handle): self.lock=False


def bind(native=None,**kwargs):
    return ElectronHostBinding(payload(),expected_launch_id=LAUNCH,backend_pid=456,native=native or Native(),parent_chain=lambda _: [456,123],**kwargs)


def test_retained_binding_exact_window_and_creation():
    native=Native(); binding=bind(native)
    assert binding.valid() and binding.allows(0xabc) and not binding.allows(0xabd)
    native.created='different'
    assert not binding.valid()
    binding.close(); assert native.closed and not native.stamps


def test_destroyed_recycled_hwnd_is_not_same_registration():
    native=Native(); binding=bind(native)
    native.stamps.clear()
    assert native.owner==123 and not binding.valid()
    binding.close()


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(host_pid=True),lambda p:p.update(launch_id='c'*32),
    lambda p:p['windows'][0].update(hwnd='123'),lambda p:p['windows'].append({'hwnd':'0xabc','role':'dialog'}),
    lambda p:p['runtime'].update(build_id=123),lambda p:p.update(extra='arbitrary'),
    lambda p:p['runtime'].update(build_kind=[]),lambda p:p['windows'][0].update(role=[]),
])
def test_bad_binding_rejected(mutation):
    data=payload(); mutation(data)
    with pytest.raises(ValueError): ElectronHostBinding(data,expected_launch_id=LAUNCH,native=Native(),parent_chain=lambda _:[123])


def test_foreign_owner_and_wrong_ancestor_rejected_cleanup():
    native=Native(); native.owner=789
    with pytest.raises(ValueError,match='HWND'): bind(native)
    assert native.closed
    native=Native()
    with pytest.raises(ValueError,match='ancestor'):
        ElectronHostBinding(payload(),expected_launch_id=LAUNCH,native=native,parent_chain=lambda _:[111])
    assert native.closed


def test_helper_verifies_stamped_binding_independently():
    native=Native(); parent=bind(native)
    child=ElectronHostBinding(parent.payload(),expected_launch_id=LAUNCH,backend_pid=456,native=native,parent_chain=lambda _:[123],attached=True)
    child.close(); assert parent.valid()
    altered=parent.payload(); altered['host_created']='old'
    with pytest.raises(ValueError,match='creation'): ElectronHostBinding(altered,expected_launch_id=LAUNCH,native=native,parent_chain=lambda _:[123],attached=True)
    parent.close()


@pytest.mark.parametrize('value',['0x0','-1','0x10000000000000000',42,None])
def test_pointer_rejects_truncation(value):
    with pytest.raises(ValueError): pointer(value)


def test_challenge_uses_independent_deadline_and_rejects_replay():
    lease=ControlLease(0.,1.)
    first={**lease.challenge,'main_sequence':1}
    lease.acknowledge(first,.2)
    with pytest.raises(ValueError,match='replayed'): lease.acknowledge(first,.3)
    assert lease.fresh(1.1999)
    with pytest.raises(ValueError,match='expired'): lease.acknowledge({**lease.challenge,'main_sequence':2},1.2)
    assert lease.stopped


@pytest.mark.parametrize('field,value',[('sequence',True),('sequence',0),('main_sequence',2**53),('nonce','bad'),('lease_id','c'*32)])
def test_malformed_progress_does_not_renew(field,value):
    lease=ControlLease(0.,1.); receipt={**lease.challenge,'main_sequence':1}; receipt[field]=value
    with pytest.raises(ValueError): lease.acknowledge(receipt,.5)
    assert lease.issued_at==0. and not lease.fresh(.5)


class Binding:
    pid=123; hwnd=456; launch_id=LAUNCH; image_path='C:/owned/electron.exe'; runtime=payload()['runtime']
    def __init__(self,*args,**kwargs): self.ok=True; self.closed=False
    def valid(self): return self.ok and not self.closed
    def payload(self): return payload()
    def close(self): self.closed=True


class Guardian:
    def __init__(self): self.owner=SimpleNamespace(pid=789); self.closed=False; self.fail=False
    def tick(self):
        if self.fail: raise RuntimeError('guardian died')
    def close(self): self.closed=True


class Backend:
    def __init__(self,*args,**kwargs): self.hook_installed=self.hotkey_registered=False; self.binding=kwargs['host_binding']
    def enable(self): self.hook_installed=self.hotkey_registered=True
    def release(self): self.hook_installed=self.hotkey_registered=False
    def pump(self): pass
    def poll_foreground(self): pass


@pytest.fixture
def helper():
    clock=SimpleNamespace(now=10.)
    native=Native(); events=[]
    runtime=ElectronHelperRuntime(555,events.append,clock=lambda:clock.now,backend_factory=Backend,
        binding_factory=Binding,native_factory=lambda:native,guardian_factory=Guardian)
    runtime.command({'command':'electron_prepare','binding':payload(),'heartbeat_timeout':1.})
    assert runtime.binding and native.lock and not runtime.backend
    yield runtime,clock,native,events
    runtime.release('shutdown'); runtime.finish_cleanup()


def progress(runtime,n=1):
    runtime.command({'command':'electron_progress','progress':{**runtime.control.challenge,'main_sequence':n}})


def arm(runtime):
    progress(runtime)
    runtime.command({'command':'electron_enable','blocking':True})
    assert runtime.lease.armed


def test_helper_cannot_arm_without_progress_or_generic_heartbeat(helper):
    runtime,clock,native,events=helper
    runtime.command({'command':'heartbeat','sent_at':clock.now})
    assert runtime.control.confirmed_at is None and events[-1]['kind']=='error'
    runtime.command({'command':'electron_enable','blocking':True})
    assert not runtime.lease.armed and runtime.terminal and not native.lock


def test_helper_polls_cannot_hide_renderer_stall(helper):
    runtime,clock,native,events=helper; arm(runtime)
    backend=runtime.backend
    delayed={**runtime.control.challenge,'main_sequence':2}
    for n in range(20): runtime.command({'command':'status'})
    clock.now+=1.
    runtime.tick()
    assert runtime.terminal and not backend.hook_installed and not native.lock
    assert runtime.lease.reason=='control_progress_lost'
    runtime.command({'command':'electron_progress','progress':delayed})
    assert runtime.control.stopped and not runtime.lease.armed


@pytest.mark.parametrize('kind',['host','guardian','eof','parent'])
def test_each_independent_failure_releases_exact_backend(helper,kind):
    runtime,clock,native,events=helper; arm(runtime); backend=runtime.backend; guardian=runtime.guardian
    if kind=='host': runtime.binding.ok=False
    if kind=='guardian': runtime.guardian.fail=True
    runtime.tick(parent_alive=kind!='parent',input_open=kind!='eof')
    assert not backend.hook_installed and not native.lock and runtime.terminal
    runtime.finish_cleanup(); assert guardian.closed


def test_camera_status_is_not_a_control_lease_input(helper):
    runtime,clock,native,events=helper; arm(runtime)
    for n in range(2,10):
        clock.now+=.5; progress(runtime,n); runtime.tick()
        assert runtime.lease.armed  # No CV/frame-health dependency exists.


@pytest.mark.parametrize('competing_reason',[None,'foreground_containment_failed'])
def test_short_maximum_lease_with_healthy_progress_preserves_first_release(helper,competing_reason):
    runtime,clock,native,events=helper
    progress(runtime)
    runtime.command({'command':'electron_enable','blocking':True,'max_session_seconds':2.})
    assert runtime.lease.armed
    for n in range(2,6):
        clock.now+=.5
        if not runtime.terminal: progress(runtime,n)
        if n==3 and competing_reason: runtime.release(competing_reason)
        runtime.tick()
    expected=competing_reason or 'lease_expired'
    assert runtime.terminal and not runtime.lease.armed and not native.lock
    assert runtime.lease.reason==expected
    for _ in range(3): runtime.command({'command':'status'})
    assert events[-1]['reason']==expected and events[-1]['hook_installed'] is False


def test_native_emergency_removes_hook_before_event_and_defers_child_join(helper):
    runtime,clock,native,events=helper; arm(runtime); backend=runtime.backend; guardian=runtime.guardian
    runtime.emit=lambda value: (events.append(value),pytest.fail('hook still installed') if backend.hook_installed else None)
    runtime.emergency()
    assert not backend.hook_installed and not guardian.closed
    runtime.finish_cleanup(); assert guardian.closed
    assert any(e.get('event_type')=='EMERGENCY_RELEASE' for e in events)


def test_second_helper_cannot_acquire_existing_desktop(helper):
    first,clock,native,events=helper
    second=ElectronHelperRuntime(555,events.append,clock=lambda:clock.now,backend_factory=Backend,
        binding_factory=Binding,native_factory=lambda:native,guardian_factory=Guardian)
    second.command({'command':'electron_prepare','binding':payload(),'heartbeat_timeout':1.})
    assert second.terminal and not second.backend
    assert native.lock and first.binding.valid()  # Failure never releases the first owner's mutex.


def test_guardian_terminates_retained_verified_ancestor_only():
    native=Native(); owner=GuardianOwner(123,native.created,native=native,parent_chain=lambda _:[456,123])
    owner.terminate(); assert native.killed==[('retained',123)]
    owner.close()
    native=Native()
    with pytest.raises(ValueError,match='ancestor'): GuardianOwner(123,native.created,native=native,parent_chain=lambda _:[999])
    assert not native.killed and native.closed


def report(identity):
    return {'schema':2,'frontend':'electron','mode':'audit_only','blocking_enabled':False,'passed':True,
        'generated_at':datetime.now(timezone.utc).isoformat(),'identity':identity,
        'checks':[{'name':n,'kind':'native_audit','passed':True} for n in MANDATORY_CHECKS]}


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(schema=1),lambda r:r.update(frontend='pyside6'),
    lambda r:r.update(blocking_enabled=True),lambda r:r.update(passed=False),
    lambda r:r.update(generated_at=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()),
    lambda r:r['checks'].pop(),lambda r:r['checks'].append(r['checks'][0]),
    lambda r:r['identity'].update(build='packaged'),
])
def test_incompatible_audit_rejected(tmp_path,mutation):
    identity={'build':'source'}; value=report(copy.deepcopy(identity)); mutation(value)
    path=tmp_path/'audit.json'; path.write_text(json.dumps(value))
    with pytest.raises(ValueError): require_electron_validation(path,identity)


def test_valid_exact_runtime_audit_accepted(tmp_path):
    identity={'build':'source'}; path=tmp_path/'audit.json'; path.write_text(json.dumps(report(identity)))
    assert require_electron_validation(path,identity)['passed']


def test_artifacts_fingerprint_matches_js_recipe(tmp_path):
    import hashlib
    (tmp_path/'build-electron').mkdir(); (tmp_path/'dist').mkdir()
    (tmp_path/'build-electron/main.js').write_bytes(b'main'); (tmp_path/'dist/index.html').write_bytes(b'html')
    expected=hashlib.sha256(b'proctoring-electron-artifacts-v1\0build-electron/main.js\0main\0dist/index.html\0html\0').hexdigest()
    assert artifact_fingerprint(tmp_path)==expected


def test_adapter_state_polls_cannot_refresh_confirmed_receipt(monkeypatch):
    now=[1.]; monkeypatch.setattr('proctoring.security.electron.time.monotonic',lambda:now[0])
    client=ElectronProtection(ProtectionConfig(enabled=True),binding_factory=Binding)
    client.binding=Binding(); client._audit_valid=True
    message={'kind':'status','prepared':True,'control_confirmed':True,'control_sequence':1,'status':'PREPARING'}
    client._consume(message)
    assert client.binding_status()['ready']
    now[0]=7.; client._consume(message)
    assert not client.binding_status()['ready']
    client._consume({**message,'control_sequence':2}); assert client.binding_status()['ready']


def test_adapter_generic_heartbeat_sends_nothing(monkeypatch):
    client=ElectronProtection(ProtectionConfig(enabled=True)); sent=[]
    monkeypatch.setattr(client,'_send',lambda *args,**kwargs:sent.append(args))
    client._armed=True; client.heartbeat(); assert not sent


def test_legacy_ownership_is_not_weakened():
    import os
    from proctoring.security.windows import WindowsProtection
    client=WindowsProtection(ProtectionConfig())
    with pytest.raises(ValueError): client.configure_window(123,os.getpid()+1)


def test_exact_window_policy_reports_unregistered_same_host_window():
    from proctoring.security.policy import WindowPolicy
    policy=WindowPolicy(123)
    assert not policy.should_report(10,123)  # Legacy PID behavior retained.
    assert policy.should_report(10,123,allowed=False)
    assert not policy.should_report(10,123,allowed=False)  # Repeat suppression.
    assert not policy.should_report(11,123,allowed=True)
    assert policy.should_report(10,123,allowed=False)


@pytest.fixture
def adapter(monkeypatch):
    messages=[]; native=Native()
    allowed=[True]
    def validator(*args):
        if not allowed[0]: raise ValueError('audit changed')
    client=ElectronProtection(ProtectionConfig(enabled=True),binding_factory=Binding,
        identity_factory=lambda *args:{'actual':'testidentity'},audit_validator=validator)
    runtime=ElectronHelperRuntime(555,client._consume,backend_factory=Backend,binding_factory=Binding,
        native_factory=lambda:native,guardian_factory=Guardian)
    monkeypatch.setattr(client,'_spawn',lambda:None)
    def request(command,timeout=1,**kwargs):
        messages.append(command)
        identifier=str(len(messages))
        runtime.command({'command':command,'request_id':identifier,**kwargs})
        response=client._responses.pop(identifier)
        if response['kind']=='error': raise RuntimeError(response['message'])
        return response
    monkeypatch.setattr(client,'_request',request)
    monkeypatch.setattr(client,'_send',lambda command,**kwargs:runtime.command({'command':command,**kwargs}))
    monkeypatch.setattr(client,'_terminate_owned_helper',lambda:runtime.release('helper_error'))
    yield client,runtime,allowed,messages
    runtime.release('shutdown'); runtime.finish_cleanup()


def test_no_audit_edition_keeps_resources_progress_and_emergency_gates(adapter):
    from dataclasses import replace
    client,runtime,allowed,messages=adapter
    client.config=replace(client.config,require_recovery_audit=False)
    def forbidden_audit(*args): raise AssertionError('No-audit edition must not read an audit')
    client.audit_validator=forbidden_audit
    client.configure_host(payload())
    assert not client._audit_valid
    assert client.public_state()['audit']['required'] is False
    with pytest.raises(RuntimeError,match='Fresh trusted'):client.arm()
    progress(runtime)
    client.arm()
    assert client.armed and runtime.lease.blocking_enabled
    runtime.emergency()
    assert not client.armed and runtime.terminal
    assert not runtime.backend


def test_no_audit_edition_still_rejects_changed_resources(adapter):
    from dataclasses import replace
    client,runtime,allowed,messages=adapter
    client.config=replace(client.config,require_recovery_audit=False)
    client.configure_host(payload());progress(runtime)
    def changed(*args): raise ValueError('resources changed')
    client.identity_factory=changed
    with pytest.raises(ValueError,match='resources changed'):client.arm()
    assert 'electron_enable' not in messages


def test_adapter_transaction_and_terminal_no_rearm(adapter):
    client,runtime,allowed,messages=adapter
    client.configure_host(payload())
    assert client.binding_status()['media_allowed'] and not client.binding_status()['ready']
    assert client.accept_progress({**client.challenge,'main_sequence':1})
    assert client.binding_status()['ready'] and not client.armed
    client.arm()
    assert client.armed and client.public_state()['state']=='active' and runtime.backend.binding.pid==123
    client._process=SimpleNamespace()  # Explicit fake acknowledgement path used on release.
    client.release('proctor_ended')
    assert not client.armed and client.public_state()['state']=='released'
    with pytest.raises(RuntimeError): client.arm()
    assert messages.count('electron_enable')==1


@pytest.mark.parametrize('reason',['completed','proctor_ended','normal_disable','application_exit'])
def test_normal_release_and_repeated_helper_status_are_idempotent(adapter,reason):
    client,runtime,_,messages=adapter
    client.configure_host(payload()); client.accept_progress({**client.challenge,'main_sequence':1}); client.arm()
    client._process=SimpleNamespace()
    client.release(reason)
    for _ in range(5):
        runtime.status()  # Actual helper emits RECOVERY for all terminal states.
        assert client.public_state()['state']=='released'
        assert client.public_state()['reason']==reason and not client.armed
    client.release(reason)
    assert messages.count('disable')==1
    with pytest.raises(RuntimeError): client.arm()


def terminal_status(reason):
    return {'kind':'status','status':'RECOVERY','reason':reason,'armed':False,
            'blocking_enabled':False,'hook_installed':False,'hotkey_registered':False}


@pytest.mark.parametrize('phase',['releasing','released'])
@pytest.mark.parametrize('reason',['emergency_shortcut','heartbeat_timeout','control_progress_lost','host_identity_lost','guardian_lost','lease_expired','foreground_containment_failed'])
def test_genuine_recovery_overrides_normal_release_and_late_normal_reply_cannot_erase_it(monkeypatch,phase,reason):
    import proctoring.security.helper as helper
    # Production backend need not import the separate Electron helper module.
    monkeypatch.setattr(helper,'RECOVERY_REASONS',helper.RECOVERY_REASONS-{'control_progress_lost','host_identity_lost','guardian_lost'})
    client=ElectronProtection(ProtectionConfig(enabled=True))
    client._requested_release_reason='completed'; client._phase=phase
    client._consume(terminal_status(reason))
    assert client.public_state()['state']=='fault' and client.public_state()['reason']==reason
    client._consume(terminal_status('completed'))
    assert client.public_state()['state']=='fault' and client.public_state()['reason']==reason
    assert client.release_reason==reason


def test_matching_normal_reply_stays_released_if_release_caller_already_finished():
    client=ElectronProtection(ProtectionConfig(enabled=True))
    client._requested_release_reason='completed'; client._phase='released'; client._terminal=True
    client._consume(terminal_status('completed'))
    assert client.public_state()['state']=='released'


def test_unsolicited_or_incompletely_disarmed_normal_status_is_not_success():
    client=ElectronProtection(ProtectionConfig(enabled=True)); client._phase='active'
    client._consume(terminal_status('completed'))
    assert client.public_state()['state']=='fault'
    client=ElectronProtection(ProtectionConfig(enabled=True)); client._phase='releasing'; client._requested_release_reason='completed'
    client._consume({**terminal_status('completed'),'hook_installed':True})
    assert client.public_state()['state']=='fault'


def test_consumer_keeps_base_notification_and_derived_state_in_one_transaction(monkeypatch):
    import threading
    from proctoring.security.windows import WindowsProtection
    client=ElectronProtection(ProtectionConfig(enabled=True)); client._phase='releasing'; client._requested_release_reason='completed'
    base_finished=threading.Event(); finish_reader=threading.Event(); waiter_finished=threading.Event()
    original=WindowsProtection._consume
    def pause_after_base(self,message):
        original(self,message); base_finished.set()
        assert finish_reader.wait(2)
    monkeypatch.setattr(WindowsProtection,'_consume',pause_after_base)
    reader=threading.Thread(target=lambda:client._consume(terminal_status('completed')))
    observed=[]
    def waiting_request():
        with client._condition: observed.append(client._phase)
        waiter_finished.set()
    reader.start(); assert base_finished.wait(2)
    waiter=threading.Thread(target=waiting_request); waiter.start()
    try: assert not waiter_finished.wait(.05)
    finally: finish_reader.set(); reader.join(2); waiter.join(2)
    assert observed==['released'] and not reader.is_alive() and not waiter.is_alive()


def test_start_revalidates_audit_and_never_installs_when_changed(adapter):
    client,runtime,allowed,messages=adapter; client.configure_host(payload())
    client.accept_progress({**client.challenge,'main_sequence':1})
    allowed[0]=False
    with pytest.raises(ValueError,match='audit changed'): client.arm()
    assert runtime.backend is None and not client.armed and 'electron_enable' not in messages


def test_adapter_audit_identity_binds_effective_policy(adapter):
    client,runtime,allowed,messages=adapter; observed=[]
    client.audit_validator=lambda path,identity,age:observed.append(identity)
    client.configure_host(payload())
    assert observed[-1]['protection_policy']=={'heartbeat_timeout_seconds':5.,'startup_timeout_seconds':5.,'foreground_poll_ms':100}


def test_missing_audit_allows_only_preexam_setup(adapter):
    client,runtime,allowed,messages=adapter; allowed[0]=False
    client.configure_host(payload()); client.accept_progress({**client.challenge,'main_sequence':1})
    assert client.binding_status()['media_allowed'] and not client.binding_status()['ready']
    assert client.public_state()['state']=='awaiting_audit'
    with pytest.raises(ValueError): client.arm()
    assert runtime.backend is None


def test_audit_fixture_never_enables_real_suppression(helper):
    runtime,clock,native,events=helper; runtime.audit_fixture=True; progress(runtime)
    runtime.command({'command':'electron_enable','blocking':True})
    assert runtime.backend is None and runtime.terminal
    assert any('cannot suppress' in e.get('message','') for e in events)


def test_package_fingerprint_covers_native_files_and_rejects_traversal(tmp_path):
    from proctoring.security.electron_validation import runtime_identity
    app=tmp_path/'resources/app'; (app/'build-electron').mkdir(parents=True); (app/'dist').mkdir()
    (app/'build-electron/main.js').write_bytes(b'main'); (app/'dist/index.html').write_bytes(b'html')
    backend=tmp_path/'resources/backend'; backend.mkdir(); (backend/'runtime.dll').write_bytes(b'native')
    manifest=tmp_path/'resources/package-build.json'
    files=['resources/app/build-electron/main.js','resources/app/dist/index.html','resources/backend/runtime.dll']
    manifest.write_text(json.dumps({'schema':1,'build_kind':'packaged','files':files}))
    binding=Binding(); binding.runtime={**binding.runtime,'build_kind':'packaged','build_id':artifact_fingerprint(app)}
    before=runtime_identity(binding,tmp_path)
    (backend/'runtime.dll').write_bytes(b'changed native')
    assert runtime_identity(binding,tmp_path)['fingerprint']!=before['fingerprint']
    manifest.write_text(json.dumps({'schema':1,'build_kind':'packaged','files':files+['../outside.dll']}))
    with pytest.raises(ValueError,match='Unsafe'): runtime_identity(binding,tmp_path)


class RetainedOwner:
    """Exact retained handle fake; pipes remain open independently of liveness."""
    def __init__(self):
        self.handle=object(); self.pid=9876; self.living=True
        self.query_error=False; self.termination_error=False; self.terminated=0
    def alive(self):
        if self.query_error: raise OSError('WaitForSingleObject failed')
        return self.living if self.handle else False
    def terminate_and_wait(self,timeout):
        self.terminated+=1
        if self.termination_error or not self.handle: raise RuntimeError('Owned cleanup could not be confirmed')
        self.living=False


def active_retained_client():
    client=ElectronProtection(ProtectionConfig(enabled=True),binding_factory=Binding)
    client.binding=Binding(); client._audit_valid=True
    owner=RetainedOwner(); client._helper_process=owner
    client._consume({'kind':'status','status':'ACTIVE','reason':None,'armed':True,
        'blocking_enabled':True,'hook_installed':True,'hotkey_registered':True,
        'prepared':True,'control_confirmed':True,'control_sequence':1,
        'challenge':{'lease_id':'a'*32,'sequence':2,'nonce':'b'*32}})
    return client,owner


@pytest.mark.parametrize('read',['status','armed','diagnostics','drain_events','heartbeat','public_state','binding_status','challenge'])
def test_confirmed_retained_death_is_reconciled_without_pipe_eof(read):
    client,owner=active_retained_client(); owner.living=False
    # No reader/EOF callback or terminate/join is involved in these read paths.
    value=getattr(client,read)
    result=value() if callable(value) else value
    assert not client.armed and client.status=='RECOVERY'
    assert client.public_state()['state']=='fault' and client.release_reason=='helper_exited'
    native=client.diagnostics
    assert native['status']=='RECOVERY' and native['reason'] is None  # Parent observation is not a native reason.
    assert native['termination_confirmed'] is True and native['helper_pid']==owner.pid
    assert all(native[key] is False for key in ('armed','blocking_enabled','hook_installed','hotkey_registered','prepared','control_confirmed'))
    assert client.challenge is None and not client.binding_status()['media_allowed']
    events=result if read=='drain_events' else client.drain_events()
    assert len(events)==1 and events[0]['details']['reason']=='helper_exited'
    for _ in range(5): client.heartbeat(); client.public_state()
    assert not client.drain_events() and owner.terminated==0
    with pytest.raises(RuntimeError,match='binding'): client.arm()
    with pytest.raises(ValueError,match='binding'): client.accept_progress({})


def test_live_retained_owner_does_not_change_progress_or_status():
    client,owner=active_retained_client(); before=client.diagnostics; receipt=client._confirmed_received
    for _ in range(5):
        assert client.status=='ACTIVE' and client.armed and client.public_state()['enabled']
        assert client.binding_status()['ready']; client.heartbeat()
    assert client.diagnostics==before and client._confirmed_received==receipt
    assert not client.drain_events() and not client._writer_stop.is_set() and not owner.terminated


def test_actual_retained_handle_class_observes_signaled_process_while_pipe_remains_open():
    import io
    from unittest.mock import Mock
    from proctoring.security.helper_process import OwnedHelperProcess
    kernel=SimpleNamespace(OpenProcess=Mock(return_value=987),WaitForSingleObject=Mock(return_value=0x102),
        TerminateProcess=Mock(return_value=True),CloseHandle=Mock(return_value=True))
    launcher=SimpleNamespace(pid=123450,poll=Mock(return_value=None),stdout=io.StringIO(),stdin=io.StringIO())
    owner=OwnedHelperProcess(launcher.pid,launcher,kernel32=kernel)
    client,_=active_retained_client(); client._helper_process=owner; client._process=launcher
    try:
        kernel.WaitForSingleObject.reset_mock(); kernel.WaitForSingleObject.return_value=0
        assert client.public_state()['reason']=='helper_exited'
        kernel.WaitForSingleObject.assert_called_once_with(987,0)
        assert client.diagnostics['termination_confirmed'] and not launcher.stdout.closed
        assert launcher.poll() is None  # Launcher/pipe state is not helper identity.
        kernel.TerminateProcess.assert_not_called()
    finally: owner.close(); launcher.stdout.close(); launcher.stdin.close()


@pytest.mark.parametrize('unknown',['closed_handle','zero_handle','query_failed','replaced_handle'])
def test_unknown_owner_does_not_claim_death_or_release(unknown):
    client,owner=active_retained_client()
    if unknown=='closed_handle': owner.handle=None
    elif unknown=='zero_handle': owner.handle=0
    elif unknown=='query_failed': owner.query_error=True
    else:
        def replaced(): owner.handle=object(); return False
        owner.alive=replaced
    state=client.public_state()
    assert state['state']=='releasing' and state['reason']=='helper_identity_unavailable' and not state['enabled']
    assert client.status=='RECOVERY' and client._owner_cleanup_required and client._writer_stop.is_set()
    assert 'termination_confirmed' not in client.diagnostics
    assert all(client.diagnostics[key] is True for key in ('armed','blocking_enabled','hook_installed','hotkey_registered'))
    assert not client.binding_status()['ready'] and client.challenge is None
    events=client.drain_events()
    assert len(events)==1 and events[0]['details']['release_confirmed'] is False
    assert 'unconfirmed' in events[0]['description'] and 'released' not in events[0]['description']
    assert not client.drain_events()


def test_unknown_owner_cleanup_is_attempted_and_only_confirmation_finishes_pending_state():
    client,owner=active_retained_client(); owner.query_error=True
    assert client.public_state()['state']=='releasing'
    owner.termination_error=True
    with pytest.raises(RuntimeError,match='could not be confirmed'): client.release('helper_identity_unavailable')
    assert owner.terminated==1 and client.public_state()['state']=='releasing'
    assert client._owner_cleanup_required and 'termination_confirmed' not in client.diagnostics
    owner.termination_error=False
    client.release('helper_identity_unavailable')
    assert owner.terminated==2 and client.public_state()['state']=='fault'
    assert not client._owner_cleanup_required and client.diagnostics['termination_confirmed']
    assert client.public_state()['reason']=='helper_identity_unavailable'
    assert len(client.drain_events())==1
    client.release('application_exit'); assert owner.terminated==2


def test_unknown_cleanup_without_confirmed_death_stays_pending(monkeypatch):
    client,owner=active_retained_client(); owner.query_error=True; client.public_state()
    monkeypatch.setattr(client,'_terminate_owned_helper',lambda:None)
    with pytest.raises(RuntimeError,match='remains unconfirmed'): client.release('application_exit')
    assert client.public_state()['state']=='releasing' and client._owner_cleanup_required


@pytest.mark.parametrize('phase',['fault','released'])
@pytest.mark.parametrize('late',[{'armed':True,'status':'ACTIVE'}, {'prepared':True,'status':'PREPARING'}])
def test_late_active_or_prepared_reply_cannot_resurrect_terminal_owner(phase,late):
    client,owner=active_retained_client()
    if phase=='fault': owner.living=False; client.public_state()
    else:
        client._requested_release_reason='completed'; client._phase='releasing'
        client._consume(terminal_status('completed'))
    before=client.public_state(); native=client.diagnostics
    client._consume({'kind':'status','request_id':'pending',**late})
    assert client._responses['pending']['kind']=='error'
    assert client.public_state()==before and client.diagnostics==native and not client.armed
    client._consume({**terminal_status('completed'),'request_id':'disable'})
    assert client._responses['disable']['kind']=='status'
    assert client.public_state()==before and client.diagnostics==native


def test_genuine_disarmed_failure_after_terminal_normal_release_remains_visible():
    client,owner=active_retained_client()
    client._requested_release_reason='completed'; client._phase='releasing'
    client._consume(terminal_status('completed')); assert client._terminal
    client._consume(terminal_status('foreground_containment_failed'))
    assert client.public_state()['state']=='fault'
    assert client.release_reason=='foreground_containment_failed'
    client._consume(terminal_status('completed'))
    assert client.release_reason=='foreground_containment_failed'


def test_later_natural_death_preserves_legitimate_release_reason():
    client,owner=active_retained_client()
    client._requested_release_reason='completed'; client._phase='releasing'
    client._consume(terminal_status('completed')); owner.living=False
    client._recovery('helper_exited')
    assert client.public_state()['state']=='released' and client.release_reason=='completed'
    assert not client.drain_events()


def test_pending_request_is_woken_by_retained_death_with_pipe_still_open(monkeypatch):
    import threading
    client,owner=active_retained_client(); sent=threading.Event(); errors=[]
    monkeypatch.setattr(client,'_send',lambda *args,**kwargs:sent.set())
    def request():
        try: client._request('status',timeout=2)
        except RuntimeError as error: errors.append(str(error))
    thread=threading.Thread(target=request); thread.start()
    assert sent.wait(1)
    owner.living=False; client.heartbeat(); thread.join(1)
    assert not thread.is_alive() and errors==['Protection helper exited']


def test_status_reader_skips_busy_cleanup_without_lock_inversion():
    import threading
    client,owner=active_retained_client(); acquired=threading.Event(); finish=threading.Event()
    def cleanup():
        with client._termination_lock: acquired.set(); finish.wait(2)
    thread=threading.Thread(target=cleanup); thread.start(); assert acquired.wait(1)
    try:
        owner.living=False
        # This would deadlock/timeout if a status read waited on cleanup's lock.
        with client._condition: assert client.status=='ACTIVE'
    finally: finish.set(); thread.join(1)
    assert not thread.is_alive() and client.status=='RECOVERY'


def test_pending_arm_ack_cannot_succeed_after_recovery(adapter,monkeypatch):
    client,runtime,_,messages=adapter
    client.configure_host(payload()); client.accept_progress({**client.challenge,'main_sequence':1})
    request=client._request
    def recovered_after_ack(command,**kwargs):
        response=request(command,**kwargs)
        if command=='electron_enable': client._recovery('control_progress_lost')
        return response
    monkeypatch.setattr(client,'_request',recovered_after_ack)
    with pytest.raises(RuntimeError,match='current protection'): client.arm()
    assert not client.armed and client.public_state()['reason']=='control_progress_lost'
    assert len([event for event in client.drain_events() if event['details'].get('reason')=='control_progress_lost'])==1
    with pytest.raises(RuntimeError,match='binding'): client.arm()
    assert messages.count('electron_enable')==1


def test_pending_prepare_ack_cannot_restore_binding_after_recovery(adapter,monkeypatch):
    client,runtime,_,_=adapter; request=client._request
    def recovered_after_ack(command,**kwargs):
        response=request(command,**kwargs)
        if command=='electron_prepare': client._recovery('helper_exited')
        return response
    monkeypatch.setattr(client,'_request',recovered_after_ack)
    with pytest.raises(RuntimeError,match='preparation'): client.configure_host(payload())
    assert client.public_state()['reason']=='helper_exited'
    assert not client.binding_status()['media_allowed'] and client.challenge is None


def test_recovery_and_terminal_flag_are_atomic_against_buffered_active(monkeypatch):
    import threading
    from proctoring.security.windows import WindowsProtection
    client,owner=active_retained_client()
    base_finished=threading.Event(); finish_recovery=threading.Event(); consume_finished=threading.Event()
    original=WindowsProtection._recovery
    def pause_after_base(self,reason):
        original(self,reason); base_finished.set()
        assert finish_recovery.wait(2)
    monkeypatch.setattr(WindowsProtection,'_recovery',pause_after_base)
    recovery=threading.Thread(target=lambda:client._recovery('control_progress_lost'))
    def late_message():
        client._consume({'kind':'status','status':'ACTIVE','armed':True,'prepared':True})
        consume_finished.set()
    recovery.start(); assert base_finished.wait(1)
    consumer=threading.Thread(target=late_message); consumer.start()
    try: assert not consume_finished.wait(.05)
    finally: finish_recovery.set(); recovery.join(1); consumer.join(1)
    assert not recovery.is_alive() and not consumer.is_alive()
    assert not client.armed and client.public_state()['reason']=='control_progress_lost'
    assert len(client.drain_events())==1


@pytest.mark.parametrize('late_statuses',[
    sequence for length in range(4) for sequence in product(('ACTIVE','PREPARING'),repeat=length)
])
def test_buffered_pre_release_status_preserves_intent_until_matching_ack(monkeypatch,late_statuses):
    client,owner=active_retained_client(); client._process=SimpleNamespace()
    receipt=client._confirmed_received
    def request(command,**kwargs):
        assert command=='disable' and client._phase=='releasing'
        for index,status in enumerate(late_statuses):
            active=status=='ACTIVE'
            late={'status':status,'armed':active,'prepared':True,'blocking_enabled':active,
                'hook_installed':active,'hotkey_registered':True}
            identifier=f'earlier-poll-{index}'
            client._consume({'kind':'status','request_id':identifier,'control_confirmed':True,'control_sequence':3+index,**late})
            assert client.public_state()['state']=='releasing' and not client._terminal
            assert client.armed is active  # No premature native-release claim.
            assert client.diagnostics['hook_installed'] is active
            assert client._responses[identifier]['status']==status
            assert client._confirmed_received==receipt
        response={**terminal_status('normal_disable'),'request_id':'disable-ack'}
        client._consume(response)
        return response
    monkeypatch.setattr(client,'_request',request)
    client.release('normal_disable')
    assert client.public_state()['state']=='released' and client.release_reason=='normal_disable'
    assert not client.armed and not owner.terminated
    assert not client.drain_events()


def test_delayed_normal_ack_keeps_release_pending_with_actual_native_flags(monkeypatch):
    import threading
    client,owner=active_retained_client(); client._process=SimpleNamespace()
    awaiting=threading.Event(); reply=threading.Event(); errors=[]
    def request(command,**kwargs):
        awaiting.set(); assert reply.wait(2)
        response=terminal_status('normal_disable'); client._consume(response); return response
    monkeypatch.setattr(client,'_request',request)
    def release():
        try: client.release('normal_disable')
        except BaseException as error: errors.append(error)
    thread=threading.Thread(target=release); thread.start(); assert awaiting.wait(1)
    try:
        client._consume({**client.diagnostics,'kind':'status','request_id':'pending-poll'})
        assert client.public_state()['state']=='releasing' and client.armed
        assert not client._terminal and not owner.terminated
        assert client.diagnostics['hook_installed'] is True
    finally: reply.set(); thread.join(1)
    assert not thread.is_alive() and not errors
    assert client.public_state()['state']=='released' and not client.armed


@pytest.mark.parametrize('failure_first',[True,False])
@pytest.mark.parametrize('reason',['control_progress_lost','emergency_shortcut','foreground_containment_failed'])
def test_genuine_recovery_wins_before_or_after_pending_normal_ack(monkeypatch,failure_first,reason):
    client,owner=active_retained_client(); client._process=SimpleNamespace()
    def request(command,**kwargs):
        client._consume({**client.diagnostics,'kind':'status'})  # Buffered ACTIVE.
        normal=terminal_status('normal_disable'); failure=terminal_status(reason)
        for message in ([failure,normal] if failure_first else [normal,failure]): client._consume(message)
        return normal
    monkeypatch.setattr(client,'_request',request)
    client.release('normal_disable')
    assert client.public_state()['state']=='fault' and client.release_reason==reason
    assert not client.armed and not owner.terminated


def test_retained_death_during_release_cannot_be_erased_by_delayed_normal_ack(monkeypatch):
    client,owner=active_retained_client(); client._process=SimpleNamespace()
    def request(command,**kwargs):
        client._consume({**client.diagnostics,'kind':'status'})
        owner.living=False; client.heartbeat()
        assert client.public_state()['reason']=='helper_exited'
        normal=terminal_status('normal_disable'); client._consume(normal); return normal
    monkeypatch.setattr(client,'_request',request)
    client.release('normal_disable')
    assert client.public_state()['state']=='fault' and client.release_reason=='helper_exited'
    assert client.diagnostics['termination_confirmed'] and not client.armed
    assert len(client.drain_events())==1 and not owner.terminated


def test_missing_release_ack_after_buffered_active_uses_owned_fallback_not_success(monkeypatch):
    client,owner=active_retained_client()
    client._process=SimpleNamespace(poll=lambda:0)  # Launcher exit does not establish owner death.
    def request(command,**kwargs):
        client._consume({**client.diagnostics,'kind':'status'})
        assert client.public_state()['state']=='releasing' and client.armed
        raise RuntimeError('Protection disable acknowledgement timed out')
    monkeypatch.setattr(client,'_request',request)
    client.release('normal_disable')
    assert owner.terminated==1 and client.diagnostics['termination_confirmed']
    assert client.public_state()['state']=='fault' and not client.armed
    assert client.release_reason=='release_fallback:normal_disable'
    assert len(client.drain_events())==1
