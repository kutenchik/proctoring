"""Fake-clock foreground safety; no native hooks, windows, or input."""
from types import SimpleNamespace
import pytest
from proctoring.security.win32_backend import WindowsBackend
from proctoring.security.policy import WindowPolicy


def fixture(*,electron=True,blocking=True):
    state={'now':0.,'foreground':20,'restores':False,'result':False}
    owners={10:100,11:100,12:100,20:200,21:201,22:202}
    calls=[]; events=[]
    backend=WindowsBackend.__new__(WindowsBackend)
    backend.pid=100; backend.hwnd=10; backend.blocking=blocking
    backend._clock=lambda:state['now']; backend._foreign_since=None; backend._foreground_attempts=0
    backend._last_allowed=10; backend._desktop_lock=None; backend.hook=123; backend.hotkey_registered=True
    backend.windows=WindowPolicy(100); backend.window_pid=lambda hwnd:owners.get(hwnd,0)
    backend.host_binding=SimpleNamespace(allows=lambda hwnd:hwnd in {10,11} and owners.get(hwnd)==100) if electron else None
    def restore(target):
        calls.append(('restore',target))
        if state['restores']: state['foreground']=target
        return state['result']
    def unhook(handle): calls.append(('unhook',handle)); return True
    def unregister(*args): calls.append(('unregister',)); return True
    backend.user32=SimpleNamespace(GetForegroundWindow=lambda:state['foreground'],
        IsWindow=lambda hwnd:hwnd in owners,IsWindowVisible=lambda hwnd:True,IsIconic=lambda hwnd:False,
        ShowWindow=lambda *args:None,SetForegroundWindow=restore,
        UnhookWindowsHookEx=unhook,UnregisterHotKey=unregister)
    def event(kind,details):
        calls.append(('event',kind)); events.append((kind,details,backend.hook,backend.hotkey_registered))
    backend.on_event=event
    return backend,state,owners,calls,events


@pytest.mark.parametrize('electron',[False,True])
@pytest.mark.parametrize('returned',[False,True])
def test_foreign_foreground_failure_is_bounded_even_when_api_claims_success(electron,returned):
    backend,state,_,calls,events=fixture(electron=electron); state['result']=returned
    backend.poll_foreground(); state['now']=.999; backend.poll_foreground()
    assert backend.hook and len([e for e in events if e[0]=='PROTECTION_RECOVERY'])==0
    state['now']=1.; backend.poll_foreground()
    recovery=[e for e in events if e[0]=='PROTECTION_RECOVERY']
    assert len(recovery)==1 and recovery[0][1]['reason']=='foreground_containment_failed'
    assert recovery[0][1]['elapsed_seconds']==1. and recovery[0][1]['attempts']==3
    assert recovery[0][1]['set_foreground_returned']==returned
    assert recovery[0][2:]==(None,False)
    assert calls.index(('unhook',123))<calls.index(('event','PROTECTION_RECOVERY'))
    state['now']=10.; backend.poll_foreground()
    assert len([e for e in events if e[0]=='PROTECTION_RECOVERY'])==1


def test_actual_allowed_foreground_clears_deadline_even_if_api_returns_false():
    backend,state,_,_,events=fixture()
    backend.poll_foreground(); state.update(now=.8,restores=True,result=False); backend.poll_foreground()
    assert backend._foreign_since is None and backend.hook
    state.update(now=1.5,foreground=20,restores=False); backend.poll_foreground()
    state['now']=2.; backend.poll_foreground()
    assert backend.hook and not any(e[0]=='PROTECTION_RECOVERY' for e in events)


def test_switching_between_foreign_windows_never_resets_the_deadline():
    backend,state,_,_,events=fixture()
    for now,hwnd in [(0.,20),(.5,21),(.9,22),(1.,20)]:
        state.update(now=now,foreground=hwnd); backend.poll_foreground()
    assert not backend.hook and events[-1][1]['elapsed_seconds']==1.


def test_null_foreground_never_gets_reclaimed_and_does_not_reset_existing_loss():
    backend,state,_,calls,events=fixture(); state['foreground']=0
    backend.poll_foreground(); assert calls==[] and backend._foreign_since is None
    state.update(now=.1,foreground=20); backend.poll_foreground()
    count=len(calls); state.update(now=.5,foreground=0); backend.poll_foreground()
    state['now']=5.; backend.poll_foreground()
    assert len(calls)==count and backend.hook
    state.update(now=5.1,foreground=21); backend.poll_foreground()
    assert not backend.hook and events[-1][1]['elapsed_seconds']==5.


@pytest.mark.parametrize('mode',['no_hook','audit'])
def test_audit_or_unhooked_backend_never_contains_or_faults(mode):
    backend,state,_,calls,events=fixture(blocking=mode!='audit')
    if mode=='no_hook': backend.hook=None
    backend.poll_foreground(); state['now']=5.; backend.poll_foreground()
    assert not any(c[0]=='restore' for c in calls)
    assert not any(e[0]=='PROTECTION_RECOVERY' for e in events)


def test_registered_dialog_and_legacy_same_pid_are_allowed_but_unregistered_electron_is_not():
    for electron,hwnd,expected in [(True,11,True),(False,12,True),(True,12,False)]:
        backend,state,_,calls,_=fixture(electron=electron); state['foreground']=hwnd
        backend.poll_foreground()
        assert (not any(c[0]=='restore' for c in calls))==expected


def test_target_owner_is_revalidated_before_every_retry():
    backend,state,owners,calls,events=fixture(); backend.poll_foreground()
    owners[10]=999; state['now']=1.; backend.poll_foreground()
    assert [c for c in calls if c[0]=='restore']==[('restore',10)]
    assert not backend.hook and events[-1][1]['reason']=='foreground_containment_failed'


def test_emergency_release_before_poll_has_priority_over_foreground_fault():
    backend,state,_,_,events=fixture(); backend.poll_foreground()
    backend.release(); state['now']=2.; backend.poll_foreground()
    assert not any(e[0]=='PROTECTION_RECOVERY' for e in events)
