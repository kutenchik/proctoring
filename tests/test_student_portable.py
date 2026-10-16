import hashlib,importlib.util,json,zipfile
from pathlib import Path
import pytest
from proctoring.config import load_config
from proctoring.security.pin import PinVerifier
from proctoring.connected.client import frozen_policy,ConnectedError
from test_connected_client import ADMISSION
from copy import deepcopy
from dataclasses import replace
spec=importlib.util.spec_from_file_location('portable',Path('packaging/portable_launcher.py'));portable=importlib.util.module_from_spec(spec);spec.loader.exec_module(portable)

def payload(tmp_path,unsafe=False):
 bundle=tmp_path/'bundle';bundle.mkdir();state=tmp_path/'state';state.mkdir()
 data=b'fake executable'
 inventory=json.dumps({'files':[{'path':'LocalProctoring-Electron.exe','sha256':hashlib.sha256(data).hexdigest()}]}).encode()
 with zipfile.ZipFile(bundle/'student.zip','w') as z:
  z.writestr('app/LocalProctoring-Electron.exe',data);z.writestr('app/PACKAGE-INVENTORY.json',inventory)
  if unsafe:z.writestr('../escape.txt','bad')
 (bundle/'payload.json').write_text(json.dumps({'sha256':portable.digest(bundle/'student.zip')}))
 return bundle,state


def test_explicit_edition_has_stable_separate_storage_and_preserves_old_profile(tmp_path):
 bundle,state=payload(tmp_path)
 old=tmp_path/'existing';old.mkdir();(old/'saved-attempt').write_bytes(b'preserve')
 env={'LOCALAPPDATA':str(old),'APPDATA':str(tmp_path/'roaming')}
 assert portable.edition_environment(bundle,env)==env
 metadata=json.loads((bundle/'payload.json').read_text())
 metadata['profile_name']='protected-no-audit'
 (bundle/'payload.json').write_text(json.dumps(metadata),encoding='utf-8')
 first=portable.edition_environment(bundle,env)
 assert first==portable.edition_environment(bundle,env)
 assert first['LOCALAPPDATA']!=env['LOCALAPPDATA'] and first['APPDATA']!=env['APPDATA']
 assert (old/'saved-attempt').read_bytes()==b'preserve'
 metadata['profile_name']='unprotected'
 (bundle/'payload.json').write_text(json.dumps(metadata),encoding='utf-8')
 unprotected=portable.edition_environment(bundle,env)
 assert unprotected==portable.edition_environment(bundle,env)
 assert unprotected['LOCALAPPDATA'] not in (env['LOCALAPPDATA'],first['LOCALAPPDATA'])
 assert unprotected['APPDATA'] not in (env['APPDATA'],first['APPDATA'])
 metadata['profile_name']='../other'
 (bundle/'payload.json').write_text(json.dumps(metadata),encoding='utf-8')
 with pytest.raises(RuntimeError):portable.edition_environment(bundle,env)

def test_verified_extraction_reuse_and_tamper_rejection(tmp_path):
 bundle,state=payload(tmp_path)
 (state/'pending-evidence').write_text('preserve')
 app=portable.materialize(bundle,state)
 assert portable.materialize(bundle,state)==app
 assert (state/'pending-evidence').read_text()=='preserve'
 (app/'LocalProctoring-Electron.exe').write_bytes(b'tampered')
 with pytest.raises(RuntimeError,match='integrity'):portable.materialize(bundle,state)

def test_changed_inventory_cannot_authorize_changed_resources(tmp_path):
 bundle,state=payload(tmp_path);app=portable.materialize(bundle,state)
 (app/'PACKAGE-INVENTORY.json').write_text('{"files":[]}')
 with pytest.raises(RuntimeError,match='inventory integrity'):portable.materialize(bundle,state)

def test_archive_traversal_is_rejected(tmp_path):
 bundle,state=payload(tmp_path,True)
 with pytest.raises(RuntimeError,match='Unsafe'):portable.materialize(bundle,state)
 assert not (state/'escape.txt').exists()

def test_duplicate_launcher_is_rejected_until_original_owner_exits(tmp_path):
 import msvcrt, subprocess, sys
 lock=portable.acquire_launch_lock(tmp_path)
 code="import importlib.util,sys;from pathlib import Path;s=importlib.util.spec_from_file_location('p','packaging/portable_launcher.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.acquire_launch_lock(Path(sys.argv[1]))"
 try:
  duplicate=subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,text=True)
  assert duplicate.returncode!=0 and 'already running' in duplicate.stderr
 finally:
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
 assert subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True).returncode==0

def test_empty_pin_only_for_connected_and_never_authorizes(tmp_path):
 text=Path('config/connected.example.toml').read_text().replace('proctor_pin = "739261"','proctor_pin = ""')
 path=tmp_path/'config.toml';path.write_text(text)
 assert load_config(path).proctor_pin==''
 assert not PinVerifier('').verify('')
 path.write_text(text.replace('[connected]\nenabled = true','[connected]\nenabled = false'))
 with pytest.raises(ValueError):load_config(path)

def test_host_permission_does_not_force_unprotected_exam_to_arm(monkeypatch):
 config=load_config(Path('config/connected.example.toml'))
 config=replace(config,protection=replace(config.protection,enabled=True))
 assert not frozen_policy(config,ADMISSION)[0].protection.enabled
 from proctoring.exam_policy import default_policy
 admission=deepcopy(ADMISSION);policy=default_policy();policy['values']['advanced.identity_enabled']=True
 policy['values']['audio.enabled']=False;policy['values']['snapshots_enabled']=False
 admission['exam']['monitoring_policy']=policy
 monkeypatch.setattr('proctoring.runtime.is_frozen',lambda:True)
 with pytest.raises(ConnectedError,match='packaged_requires_protected'):frozen_policy(config,admission)
 admission['exam']['protection_mode']='protected'
 with pytest.raises(ConnectedError,match='optional_face_unavailable'):frozen_policy(config,admission)

def test_packaged_update_refuses_unfinished_attempt_without_mutating_journal(tmp_path,monkeypatch):
    from proctoring.connected.client import ConnectedClient
    from proctoring.connected.settings import ConnectedConfig
    class Journal:
        def get(self,key):return {'device_id':'fake','device_secret':'fake'}
        def attempts(self):return [{'cleanup':False,'distribution_identity':'older-build'}]
        def update(self,*args,**kwargs):raise AssertionError('Old evidence must not be modified')
    monkeypatch.setattr('proctoring.runtime.is_frozen',lambda:True)
    monkeypatch.setattr('proctoring.runtime.distribution_identity',lambda:'new-build')
    with pytest.raises(ConnectedError,match='unfinished_attempt_from_different_build'):
        ConnectedClient(ConnectedConfig(enabled=True,allow_loopback_http=True),journal=Journal(),remember_path=tmp_path/'server.json')


@pytest.mark.parametrize('host_protected',[False,True])
@pytest.mark.parametrize('exam_protected',[False,True])
def test_packaged_editions_require_matching_teacher_mode(monkeypatch,host_protected,exam_protected):
    config=load_config(Path('config/connected.example.toml'))
    config=replace(config,protection=replace(config.protection,enabled=host_protected,require_recovery_audit=False))
    admission=deepcopy(ADMISSION)
    admission['exam']['protection_mode']='protected' if exam_protected else 'unprotected'
    monkeypatch.setattr('proctoring.runtime.is_frozen',lambda:True)
    if host_protected!=exam_protected:
        with pytest.raises(ConnectedError,match='packaged_requires_protected' if host_protected else 'packaged_requires_unprotected'):
            frozen_policy(config,admission)
    else:
        updated,_=frozen_policy(config,admission)
        assert updated.protection.enabled is host_protected
        assert updated.protection.require_recovery_audit is False


def test_unprotected_workflow_never_constructs_native_protection(tmp_path,monkeypatch):
    from test_desktop_workflow import make_workflow,make_ready
    def forbidden(*args,**kwargs):raise AssertionError('Unprotected workflow must not construct native protection')
    monkeypatch.setattr('proctoring.security.electron.ElectronProtection',forbidden)
    bridge=make_workflow(tmp_path)
    try:
        assert not bridge.config.protection.enabled and bridge.electron_protection is None
        make_ready(bridge)
        bridge.dispatch('exam.start',{})
        assert bridge.controller.session.started
        assert bridge.electron_protection is None
        bridge.dispatch('exam.submit',{})
        assert bridge.controller.session.ended
    finally:bridge.close()

def test_connected_pin_action_waits_for_server_and_wrong_pin_cannot_pause(tmp_path):
    from test_desktop_workflow import make_workflow,make_ready
    from test_connected_client import ready_client,settle,IDENTITY
    bridge=make_workflow(tmp_path)
    make_ready(bridge);bridge.dispatch('exam.start',{})
    client,clock=ready_client(tmp_path)
    client.submit('admit',IDENTITY);settle(client)
    bridge.admission_client=client
    bridge._admission_applied=True
    def rejected(*args):raise ConnectedError('invalid_pin')
    client.transport=rejected
    bridge.dispatch('proctor.pause',{'pin':'000000'})
    client._thread.join(2);bridge._poll_admission()
    assert 'proctor' not in bridge.controller.session.pause_reasons
    def allowed(method,origin,endpoint,body,credential):
        if method=='GET':return {'configured':True,'revision':1}
        return {'authorized':True,'revision':body['revision'],'action':body['action'],'nonce':body['nonce']}
    client.transport=allowed
    bridge.dispatch('proctor.pause',{'pin':'836204'})
    client._thread.join(2)
    assert 'proctor' not in bridge.controller.session.pause_reasons
    bridge._poll_admission()
    assert 'proctor' in bridge.controller.session.pause_reasons
    bridge.close()


def test_old_attempt_is_not_misreported_as_encryption_failure(tmp_path,monkeypatch):
    import test_desktop_workflow as helpers
    import proctoring.desktop_bridge.workflow as workflow_module
    from proctoring.connected.settings import ConnectedConfig
    original_config=helpers.load_config()
    monkeypatch.setattr(helpers,'load_config',lambda:replace(original_config,connected=ConnectedConfig(enabled=True,allow_loopback_http=True)))
    monkeypatch.setattr('proctoring.connected.durable.DurableJournal',lambda *_:object())
    original_client=workflow_module.ConnectedClient
    def client(settings,**kwargs):
        if kwargs.get('journal') is not None:raise ConnectedError('unfinished_attempt_from_different_build')
        return original_client(settings,remember_path=tmp_path/'server.json',**kwargs)
    monkeypatch.setattr(workflow_module,'ConnectedClient',client)
    bridge=helpers.make_workflow(tmp_path)
    try:
        assert bridge._secure_storage_error=='unfinished_attempt_from_different_build'
        assert bridge.admission_client.error=='unfinished_attempt_from_different_build'
        assert not bridge.controller.session.started and not bridge.monitor.started
    finally:bridge.close()
