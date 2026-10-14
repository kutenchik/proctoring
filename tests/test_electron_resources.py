"""File-only resource verification; never installs hooks or starts a native helper."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from proctoring.security.electron import ElectronProtection
from proctoring.security.electron_resources import VerifiedResources
from proctoring.security.electron_validation import artifact_fingerprint, runtime_identity
from proctoring.security.settings import ProtectionConfig


@pytest.fixture
def package(tmp_path):
    root=tmp_path/'Package с пробелами'
    app=root/'resources/app'
    (app/'build-electron').mkdir(parents=True); (app/'dist').mkdir()
    (app/'build-electron/main.js').write_bytes(b'main')
    (app/'dist/index.html').write_bytes(b'html')
    native=root/'resources/backend/runtime.dll'; native.parent.mkdir(); native.write_bytes(b'native')
    files=['resources/app/build-electron/main.js','resources/app/dist/index.html','resources/backend/runtime.dll']
    (root/'resources/package-build.json').write_text(json.dumps({'schema':1,'build_kind':'packaged','files':files}))
    binding=SimpleNamespace(runtime={'build_kind':'packaged','build_id':artifact_fingerprint(app)},
                            image_path=str(root/'Electron.exe'))
    return root,binding,native


class FakeLocks:
    """Injectable native surface; file identities still model the actual paths."""
    def __init__(self): self.opened={}; self.next=0; self.fail=None; self.replaced=None
    def open(self,path,directory=False):
        if path==self.fail: raise OSError('sharing violation')
        self.next+=1; self.opened[self.next]=(path,directory)
        return self.next
    def identity(self,handle):
        path,directory=self.opened[handle]
        if path==self.replaced: return (999,999,999,0,0,0,0,0)
        info=path.stat()
        return (info.st_dev,info.st_ino,0,0 if directory else info.st_size,0,0,
                0 if directory else info.st_mtime_ns,0)
    def close(self,handle): del self.opened[handle]


def test_full_hash_matches_existing_identity_and_arm_check_reads_no_bytes(package,monkeypatch):
    root,binding,_=package; native=FakeLocks()
    expected=runtime_identity(binding,root)
    retained=VerifiedResources(binding,root,native=native)
    try:
        assert retained.identity==expected
        monkeypatch.setattr('proctoring.security.electron_resources.runtime_identity',lambda *args:pytest.fail('rehash'))
        # The manifest is read to re-enumerate the exact resource set; no resource
        # content is rehashed in validate(). The original immutable locks remain.
        retained.validate()
        assert native.opened
    finally: retained.close()
    assert not native.opened


def test_new_artifact_invalidates_exact_enumeration(package):
    root,binding,_=package; retained=VerifiedResources(binding,root,native=FakeLocks())
    try:
        (root/'resources/app/dist/new.js').write_bytes(b'new')
        with pytest.raises(ValueError,match='resource set changed'): retained.validate()
    finally: retained.close()


def test_changed_retained_identity_is_rejected_not_mtime_cached(package):
    root,binding,path=package; native=FakeLocks(); retained=VerifiedResources(binding,root,native=native)
    try:
        native.replaced=path
        with pytest.raises(ValueError,match='resource changed'): retained.validate()
    finally: retained.close()


def test_partial_open_failure_closes_all_previous_locks(package):
    root,binding,path=package; native=FakeLocks(); native.fail=path
    with pytest.raises(OSError,match='sharing violation'): VerifiedResources(binding,root,native=native)
    assert not native.opened


def test_hash_failure_closes_complete_lock_set(package,monkeypatch):
    root,binding,_=package; native=FakeLocks()
    def fail(*args): raise ValueError('wrong build')
    monkeypatch.setattr('proctoring.security.electron_resources.runtime_identity',fail)
    with pytest.raises(ValueError,match='wrong build'): VerifiedResources(binding,root,native=native)
    assert not native.opened


def test_full_hash_runs_only_with_complete_lock_set(package,monkeypatch):
    root,binding,_=package; native=FakeLocks()
    original=runtime_identity
    def observed(*args):
        locked={path for path,directory in native.opened.values() if not directory}
        assert locked=={root/'resources/package-build.json',root/'resources/backend/runtime.dll',
                        root/'resources/app/build-electron/main.js',root/'resources/app/dist/index.html'}
        return original(*args)
    monkeypatch.setattr('proctoring.security.electron_resources.runtime_identity',observed)
    retained=VerifiedResources(binding,root,native=native)
    retained.close(); assert not native.opened


def test_new_source_file_invalidates_exact_enumeration(tmp_path,monkeypatch):
    root=tmp_path/'source'
    security=root/'src/proctoring/security'; security.mkdir(parents=True)
    (security/'guard.py').write_text('source')
    for name in ('controller.py','session.py','config.py'): (security.parent/name).write_text('source')
    app=root/'desktop'; (app/'build-electron').mkdir(parents=True); (app/'dist').mkdir()
    (app/'build-electron/main.js').write_text('main'); (app/'dist/index.html').write_text('html')
    monkeypatch.setattr('proctoring.security.electron_validation.__file__',str(security/'electron_validation.py'))
    binding=SimpleNamespace(runtime={'build_kind':'source','build_id':artifact_fingerprint(app)},image_path=str(root/'electron.exe'))
    retained=VerifiedResources(binding,native=FakeLocks())
    try:
        (security/'new.py').write_text('new')
        with pytest.raises(ValueError,match='resource set changed'): retained.validate()
    finally: retained.close()


def test_enumeration_change_during_lock_acquisition_fails_before_hash(package,monkeypatch):
    root,binding,_=package; native=FakeLocks(); opening=native.open
    def race(path,directory=False):
        handle=opening(path,directory)
        if directory and path==root: (root/'resources/app/dist/new.js').write_bytes(b'new')
        return handle
    native.open=race
    monkeypatch.setattr('proctoring.security.electron_resources.runtime_identity',lambda *args:pytest.fail('hashed raced set'))
    with pytest.raises(ValueError,match='resource set changed'): VerifiedResources(binding,root,native=native)
    assert not native.opened


def test_closed_snapshot_or_changed_host_never_validates(package):
    root,binding,_=package; retained=VerifiedResources(binding,root,native=FakeLocks())
    binding.runtime['build_id']='changed'
    with pytest.raises(ValueError,match='runtime changed'): retained.validate()
    retained.close(); retained.close()
    with pytest.raises(ValueError,match='no longer retained'): retained.validate()


@pytest.mark.skipif(os.name!='nt',reason='Windows sharing semantics')
def test_native_read_locks_prevent_write_delete_and_allow_edit_only_after_close(package):
    root,binding,path=package; retained=VerifiedResources(binding,root)
    try:
        assert path.read_bytes()==b'native'
        with pytest.raises(OSError): path.write_bytes(b'edit!!')
        with pytest.raises(OSError): path.unlink()
        retained.validate()
    finally: retained.close()
    path.write_bytes(b'edit!!'); assert path.read_bytes()==b'edit!!'


@pytest.mark.skipif(os.name!='nt',reason='Windows sharing semantics')
def test_native_existing_writer_is_rejected_and_partial_handles_cleaned(package):
    root,binding,path=package
    with path.open('r+b'):
        with pytest.raises(OSError,match='Cannot retain'): VerifiedResources(binding,root)
    path.unlink()  # No leaked handle after partial acquisition.


def test_adapter_checks_retained_build_and_audit_at_start_without_rehash(monkeypatch):
    calls=[]
    class Resources:
        identity={'build':'current'}
        def __init__(self,*args): calls.append('full_hash')
        def validate(self): calls.append('identity_check')
        def close(self): calls.append('close_locks')
    monkeypatch.setattr('proctoring.security.electron.VerifiedResources',Resources)
    client=ElectronProtection(ProtectionConfig(enabled=True),audit_validator=lambda *args:calls.append('audit'))
    client.binding=SimpleNamespace(valid=lambda:True,close=lambda:None,launch_id='test')
    client._validate_audit(initial=True)
    client._last_status={'prepared':True}; client._confirmed_received=__import__('time').monotonic()
    def active_reply(*args,**kwargs):
        response={'kind':'status','status':'ACTIVE','armed':True,'blocking_enabled':True}
        client._consume(response)  # Real replies update the adapter before request() returns.
        return response
    monkeypatch.setattr(client,'_request',active_reply)
    client.arm()
    assert calls==['full_hash','audit','identity_check','audit']
    client.close()
    assert calls[-1]=='close_locks'


def test_failed_initial_verification_cannot_start_slow_hash_under_lease(monkeypatch):
    calls=[]
    def fail(*args): calls.append('initial'); raise OSError('sharing violation')
    monkeypatch.setattr('proctoring.security.electron.VerifiedResources',fail)
    client=ElectronProtection(ProtectionConfig(enabled=True))
    client.binding=SimpleNamespace(valid=lambda:True,close=lambda:None)
    client._validate_audit(initial=True)
    with pytest.raises(ValueError,match='not verified before native preparation'): client.arm()
    assert calls==['initial']
    client.close()


def test_configure_failure_releases_locks_even_when_helper_cleanup_raises(monkeypatch):
    closed=[]
    class Binding:
        hwnd=1
        def __init__(self,*args,**kwargs): pass
        def close(self): closed.append('binding')
    class Resources:
        identity={'build':'current'}
        def __init__(self,*args): pass
        def close(self): closed.append('resources')
    monkeypatch.setattr('proctoring.security.electron.VerifiedResources',Resources)
    client=ElectronProtection(ProtectionConfig(enabled=True),binding_factory=Binding,audit_validator=lambda *args:None)
    def failed_spawn(): raise RuntimeError('spawn failure')
    def failed_cleanup(): raise RuntimeError('cleanup failure')
    monkeypatch.setattr(client,'_spawn',failed_spawn)
    monkeypatch.setattr(client,'_terminate_owned_helper',failed_cleanup)
    with pytest.raises(RuntimeError,match='cleanup failure'): client.configure_host({})
    assert closed==['binding','resources'] and client._resources is None


def test_close_releases_locks_even_when_binding_cleanup_raises(monkeypatch):
    from proctoring.security.windows import WindowsProtection
    closed=[]
    client=ElectronProtection(ProtectionConfig(enabled=True))
    monkeypatch.setattr(WindowsProtection,'close',lambda _:None)
    def fail(): raise OSError('binding cleanup')
    client.binding=SimpleNamespace(close=fail)
    client._resources=SimpleNamespace(close=lambda:closed.append(True))
    with pytest.raises(OSError,match='binding cleanup'): client.close()
    assert closed and client._resources is None
