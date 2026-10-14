"""Audit-only ownership observations; no native processes, hooks or devices."""
import threading
from types import SimpleNamespace
import pytest
from proctoring.security.electron_audit import AuditEndpoint, observe_stalled_helper
from proctoring.security.settings import ProtectionConfig
from proctoring.security.windows import WindowsProtection


def fixture(*, dies_at=2.56, request_error='Protection helper exited', return_at=2.51):
    now=[0.]; requests=[]; sleeps=[]
    owner=SimpleNamespace(pid=7001,handle=42,alive=lambda:now[0]<dies_at)
    client=SimpleNamespace(_helper_process=owner)
    def request(command,**kwargs):
        requests.append((command,kwargs['timeout']))
        if command=='status':
            now[0]=.1
            return {'armed':True,'blocking_enabled':False}
        now[0]=return_at
        if request_error is not None: raise RuntimeError(request_error)
        return {'armed':True}
    def sleep(seconds): sleeps.append(seconds); now[0]+=seconds
    client._request=request
    return client,now,requests,sleeps,sleep


def test_eof_before_handle_death_is_observed_without_extending_total_deadline():
    client,now,requests,sleeps,sleep=fixture()
    result=observe_stalled_helper(client,clock=lambda:now[0],sleep=sleep)
    assert result['request_error']=='Protection helper exited'
    assert result['alive_at_request_return'] is True
    assert result['request_return_seconds']==2.51
    assert 2.56<=result['death_confirmed_seconds']<2.58
    assert result['termination_confirmed'] and result['observation_only']
    assert requests==[('status',1.),('electron_audit_stall',5.9)]
    assert all(0<seconds<=.01 for seconds in sleeps)


def test_never_dying_owner_fails_at_original_six_second_deadline():
    client,now,requests,sleeps,sleep=fixture(dies_at=float('inf'),return_at=5.95)
    with pytest.raises(RuntimeError,match='within six seconds'):
        observe_stalled_helper(client,clock=lambda:now[0],sleep=sleep)
    assert now[0]==6.
    assert sum(sleeps)==pytest.approx(.05)
    assert requests[-1][1]==5.9


@pytest.mark.parametrize('error',[
    'Stall injection is available only to a nonsuppressing audit fixture',
    'Protection helper is unavailable',
    'Protection electron_audit_stall acknowledgement timed out',
    'Protection status channel failed: invalid data',
])
def test_rejected_or_unobserved_fault_never_passes_even_if_owner_dies(error):
    client,now,_,sleeps,sleep=fixture(request_error=error,dies_at=2.5)
    with pytest.raises(RuntimeError) as caught:
        observe_stalled_helper(client,clock=lambda:now[0],sleep=sleep)
    assert str(caught.value)==error
    assert not sleeps


def test_normal_stall_acknowledgement_is_not_independent_recovery():
    client,now,_,_,sleep=fixture(request_error=None,dies_at=4.1,return_at=4.)
    with pytest.raises(RuntimeError,match='returned without independent'):
        observe_stalled_helper(client,clock=lambda:now[0],sleep=sleep)


def test_death_observed_after_original_deadline_is_still_failure():
    client,now,_,_,sleep=fixture(dies_at=6.001,return_at=6.002)
    with pytest.raises(RuntimeError,match='within six seconds'):
        observe_stalled_helper(client,clock=lambda:now[0],sleep=sleep)


@pytest.mark.parametrize('change',['unarmed','blocking','dead','closed_handle','replaced_owner'])
def test_precondition_rejects_wrong_or_unsupported_owner_before_fault(change):
    client,now,requests,_,sleep=fixture()
    if change=='dead': client._helper_process.alive=lambda:False
    elif change=='closed_handle': client._helper_process.handle=None
    else:
        def status(command,**kwargs):
            requests.append((command,kwargs['timeout']))
            if change=='replaced_owner': client._helper_process=SimpleNamespace(handle=42,alive=lambda:True)
            return {'armed':change!='unarmed','blocking_enabled':change=='blocking'}
        client._request=status
    with pytest.raises(RuntimeError,match='requires'):
        observe_stalled_helper(client,clock=lambda:now[0],sleep=sleep)
    assert all(command=='status' for command,_ in requests)


def test_changed_retained_handle_during_eof_cannot_confirm_original_death():
    client,now,_,_,sleep=fixture()
    original=client._request
    def request(command,**kwargs):
        try: return original(command,**kwargs)
        finally:
            if command=='electron_audit_stall': client._helper_process.handle=None
    client._request=request
    with pytest.raises(RuntimeError,match='identity changed'):
        observe_stalled_helper(client,clock=lambda:now[0],sleep=sleep)


def test_actual_client_eof_notification_precedes_retained_cleanup_but_audit_waits():
    client=WindowsProtection(ProtectionConfig())
    owner=SimpleNamespace(pid=7001,handle=42,live=True)
    owner.alive=lambda:owner.live
    client._helper_process=owner; client._process=SimpleNamespace(stdout=[])
    permit_cleanup=threading.Event(); reader=[]
    def terminate():
        assert permit_cleanup.wait(2)
        owner.live=False
    client._terminate_owned_helper=terminate
    def send(command,**fields):
        if command=='status':
            client._consume({'kind':'status','request_id':fields['request_id'],'armed':True,'blocking_enabled':False})
        else:
            thread=threading.Thread(target=client._read)
            reader.append(thread); thread.start()
    client._send=send
    def sleep(_seconds):
        permit_cleanup.set(); reader[0].join(1)
    try:
        result=observe_stalled_helper(client,sleep=sleep)
        assert result['alive_at_request_return'] is True
        assert result['request_error']=='Protection helper exited'
        assert result['termination_confirmed'] and not owner.alive()
    finally:
        permit_cleanup.set()
        for thread in reader: thread.join(2)
    assert all(not thread.is_alive() for thread in reader)


def test_existing_audit_result_exposes_observation_and_keeps_exact_error(monkeypatch):
    endpoint=AuditEndpoint.__new__(AuditEndpoint)
    endpoint.client=object(); endpoint.state=lambda:{'helper_alive':False}
    observation={'request_error':'Protection helper exited','death_confirmed_seconds':2.56,'budget_seconds':6.}
    monkeypatch.setattr('proctoring.security.electron_audit.observe_stalled_helper',lambda client:observation)
    result=endpoint.command('audit.loop_failure',{})
    assert result=={'helper_alive':False,'loop_failure_observation':observation}
