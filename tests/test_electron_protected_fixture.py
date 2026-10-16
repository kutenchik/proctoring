"""Gate 3B preparation tests only; never install restrictions or inject keys."""
from types import SimpleNamespace
import pytest
from proctoring.security.electron_protected_test import ProtectedEndpoint, SHORTCUTS, main


def endpoint():
    result=ProtectedEndpoint.__new__(ProtectedEndpoint)
    result.client=SimpleNamespace(armed=False,_test_lease_seconds=None,binding=None)
    result.state=lambda:{'test':'state'}
    return result


def test_foreground_precondition_is_read_only_and_requires_exact_binding():
    fixture=endpoint(); armed=[]
    fixture.client.arm=lambda:armed.append(True)
    with pytest.raises(ValueError,match='Verified fixture'): fixture.command('test.foreground',{})
    current=[42]
    fixture.client.binding=SimpleNamespace(valid=lambda:True,allows=lambda hwnd:hwnd==42,
        native=SimpleNamespace(u=SimpleNamespace(GetForegroundWindow=lambda:current[0])))
    assert fixture.command('test.foreground',{})=={'owned_foreground':True}
    current[0]=999
    assert fixture.command('test.foreground',{})=={'owned_foreground':False}
    with pytest.raises(ValueError): fixture.command('test.foreground',{'arbitrary':True})
    assert not armed


@pytest.mark.parametrize('seconds',[None,True,0,.49,15.01,999,float('nan'),float('inf')])
def test_protected_fixture_never_arms_without_bounded_explicit_maximum(seconds):
    fixture=endpoint(); called=[]; fixture.client.arm=lambda:called.append(True)
    with pytest.raises(ValueError): fixture.command('test.enable',{'max_session_seconds':seconds})
    assert not called


def test_bounded_fixture_must_still_use_actual_adapter_audit_gate():
    fixture=endpoint()
    def refuse(): raise ValueError('current recovery audit missing')
    fixture.client.arm=refuse
    with pytest.raises(ValueError,match='audit missing'): fixture.command('test.enable',{'max_session_seconds':15})
    assert fixture.client._test_lease_seconds==15 and not fixture.client.armed


@pytest.mark.parametrize('command',['audit.enable','audit.record','audit.finish'])
def test_protected_fixture_cannot_mint_recovery_audit(command):
    with pytest.raises(ValueError,match='not available'): endpoint().command(command,{})


def test_shortcuts_require_actual_active_binding(monkeypatch):
    fixture=endpoint(); injected=[]
    monkeypatch.setattr('proctoring.security.electron_protected_test._inject_keys',lambda *a,**kw:injected.append(a))
    with pytest.raises(ValueError,match='actively protected'): fixture.command('test.shortcut',{'name':'copy'})
    assert not injected
    fixture.client.armed=True; fixture.client.binding=SimpleNamespace(valid=lambda:True)
    result=fixture.command('test.shortcut',{'name':'copy'})
    assert injected==[(SHORTCUTS['copy'][0],)] and result['expected_event']=='BLOCKED_COPY'
    with pytest.raises(ValueError): fixture.command('test.shortcut',{'name':'arbitrary text'})


def test_explicit_cli_opt_in_is_required_before_any_native_setup():
    with pytest.raises(SystemExit) as outcome: main(['--recovery-report','unused.json'])
    assert outcome.value.code==2


def test_unprotected_probe_never_arms_and_rejects_active_hooks(monkeypatch):
    fixture=endpoint(); injected=[]
    fixture.client.binding=SimpleNamespace(valid=lambda:True)
    fixture.client.diagnostics={'armed':False,'hook_installed':False,'hotkey_registered':False}
    monkeypatch.setattr('proctoring.security.electron_protected_test._inject_keys',lambda keys,**kw:injected.append(keys) or {'sent_events':2})
    assert fixture.command('test.unprotected_input',{'name':'insert'})['injection']=={'sent_events':2}
    assert injected==[[0x2d]]
    with pytest.raises(ValueError): fixture.command('test.unprotected_input',{'name':'paste'})
    fixture.client.diagnostics['hook_installed']=True
    with pytest.raises(ValueError,match='Confirmed native release'): fixture.command('test.unprotected_input',{'name':'a'})
    assert len(injected)==1


@pytest.mark.parametrize('value',[0,0xe11d,True,-1])
def test_audit_input_rejects_missing_or_unsupported_physical_scan(value):
    from proctoring.security.audit import _scan_key_fields
    with pytest.raises(RuntimeError): _scan_key_fields(0x41,value)


def test_named_print_screen_uses_physical_extended_key_not_legacy_sysrq():
    from proctoring.security.audit import _scan_key_fields
    assert _scan_key_fields(0x2c,0x54)=={'wVk':0,'wScan':0x37,'dwFlags':9}


def test_owned_audit_injection_uses_real_scan_and_extended_insert_with_matching_keyups(monkeypatch):
    import proctoring.security.audit as audit
    calls=[]
    def send(count, batch, size):
        calls.append([(row.ki.wVk,row.ki.wScan,row.ki.dwFlags) for row in batch])
        return count
    native=SimpleNamespace(
        GetAsyncKeyState=lambda vk:0,GetForegroundWindow=lambda:42,
        GetWindowThreadProcessId=lambda hwnd,pid:7,GetKeyboardLayout=lambda tid:123,
        MapVirtualKeyExW=lambda key,kind,layout:{0x41:0x1e,0x10:0x2a,0x2d:0x52,0x11:0x1d,0x12:0x38,0x51:0x10}[key],
        SendInput=send)
    monkeypatch.setattr(audit.ctypes,'WinDLL',lambda *a,**kw:native)
    monkeypatch.setattr(audit,'window_pid',lambda hwnd:audit.os.getpid())
    result=audit._inject_keys([0x41])
    assert result['sent_events']==2 and result['keys']==[{'virtual_key':0x41,'scan_code':0x1e,'flags':8}]
    assert calls[-1]==[(0,0x1e,8),(0,0x1e,10)]
    audit._inject_keys([0x10,0x2d])
    assert calls[-1]==[(0,0x2a,8),(0,0x52,9),(0,0x52,11),(0,0x2a,10)]
    audit.inject_emergency_chord()
    assert calls[-1]==[(0,0x1d,8),(0,0x2a,8),(0,0x38,8),(0,0x10,8),
                       (0,0x10,10),(0,0x38,10),(0,0x2a,10),(0,0x1d,10)]


def foreground_observer_fixture():
    from pathlib import Path
    now=[0.]; closed=[]
    image=str(Path('controlled-electron.exe').resolve())
    binding=SimpleNamespace(pid=100,image_path=image,valid=lambda:True,allows=lambda hwnd:hwnd==10)
    native=SimpleNamespace(open_process=lambda pid:999,creation=lambda handle:'1234',alive=lambda handle:True,
        window_owner=lambda hwnd:200 if hwnd==20 else 100,image=lambda handle:image,close=lambda handle:closed.append(handle),
        u=SimpleNamespace(GetForegroundWindow=lambda:10 if now[0]<.1 or now[0]>1.2 else 20))
    def sleep(seconds): now[0]+=seconds
    return binding,native,now,closed,sleep


def test_foreground_observer_retains_exact_sibling_and_records_actual_transitions():
    from proctoring.security.electron_protected_test import observe_owned_foreground
    binding,native,now,closed,sleep=foreground_observer_fixture()
    result=observe_owned_foreground(binding,{'pid':200,'hwnd':'0x14','duration_seconds':1.75},
        native=native,parent_chain=lambda pid:[300],clock=lambda:now[0],sleep=sleep)
    assert result['target']=={'pid':200,'created':'1234','hwnd':'0x14'}
    assert [row['kind'] for row in result['samples']]==['exam','foreign','exam']
    assert closed==[999] and 1.75<=result['ended_at']<=1.8


@pytest.mark.parametrize('duration',[1.5,2.6,3.0])
def test_foreground_observer_accepts_bounded_configured_poll_allowance(duration):
    from proctoring.security.electron_protected_test import observe_owned_foreground
    binding,native,now,closed,sleep=foreground_observer_fixture()
    result=observe_owned_foreground(binding,{'pid':200,'hwnd':'0x14','duration_seconds':duration},
        native=native,parent_chain=lambda pid:[300],clock=lambda:now[0],sleep=sleep)
    assert duration<=result['ended_at']<duration+.03
    assert closed==[999]


@pytest.mark.parametrize('duration',[1.49,3.01,True,float('nan'),float('inf')])
def test_foreground_observer_rejects_unbounded_duration_before_opening_process(duration):
    from proctoring.security.electron_protected_test import observe_owned_foreground
    binding,native,now,closed,sleep=foreground_observer_fixture()
    opened=[]
    native.open_process=lambda pid:opened.append(pid)
    with pytest.raises(ValueError,match='1.5–3 seconds'):
        observe_owned_foreground(binding,{'pid':200,'hwnd':'0x14','duration_seconds':duration},
            native=native,parent_chain=lambda pid:[300],clock=lambda:now[0],sleep=sleep)
    assert not opened and not closed


@pytest.mark.parametrize('mismatch',['parent','image','window','creation'])
def test_foreground_observer_rejects_unowned_or_replaced_process(mismatch):
    from proctoring.security.electron_protected_test import observe_owned_foreground
    binding,native,now,closed,sleep=foreground_observer_fixture()
    if mismatch=='image': native.image=lambda handle:'different.exe'
    if mismatch=='window': native.window_owner=lambda hwnd:900
    if mismatch=='creation': native.creation=lambda handle:'changed' if now[0]>.1 else '1234'
    parent=lambda pid:[pid if mismatch=='parent' else 300]
    with pytest.raises(ValueError,match='owned sibling|identity changed'):
        observe_owned_foreground(binding,{'pid':200,'hwnd':'0x14','duration_seconds':1.75},
            native=native,parent_chain=parent,clock=lambda:now[0],sleep=sleep)
    assert closed==[999]
