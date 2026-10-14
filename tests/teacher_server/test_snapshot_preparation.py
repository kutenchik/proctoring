"""Preparation-only real loopback transport; temporary synthetic data, no capture."""
import json
from pathlib import Path
import sys
import time
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/stage4b_synthetic'))
from snapshots import execute, operator_confirm
from test_live_api import network
from test_event_snapshots import Vault


def test_snapshot_public_harness_loopback(network, owner, other, tmp_path, clock):
    http,_,app=network
    accounts={'owner':{'email':'teacher@example.com','password':'test password 12345'},'other':{'email':'other@example.com','password':'other password 12345'}}
    observed=[]
    def confirm(stage,result,deadline,check):
        # Independent server projection checks at the same operator gates.
        student=app.state.live.snapshot(owner,result['exam_id'])['students'][0]
        assert student['status']['state']=='running'
        event=next(e for e in student['events'] if e['event_id']==result['event_id'])
        assert event['snapshot']['status']==('pending' if stage=='pending' else 'available')
        observed.append(stage)
    result=execute(tmp_path,http,accounts,time.time()+180,confirm,teacher_origin='http://127.0.0.1:5174',now=clock,vault=Vault())
    assert observed==['pending','image']
    assert result['local_cleanup'] and result['independent_receipt_before_cleanup']
    assert result['controlled_interruption_performed'] and result['no_early_receipt_or_cleanup']
    assert result['cross_teacher_http']==404 and not result['first_failure']
    with pytest.raises(FileExistsError):execute(tmp_path,http,accounts,time.time()+180,confirm,vault=Vault())
    assert json.loads((tmp_path/'snapshot-results.json').read_text())['phase']=='complete'


def test_operator_gate_requires_matching_explicit_confirmation(tmp_path):
    (tmp_path/'operator-pending.json').write_text(json.dumps({'attempt_id':'wrong','pending_visible':True}))
    with pytest.raises(ValueError,match='operator_confirmation_incomplete'):
        operator_confirm('pending',{'attempt_id':'expected'},time.time()+1,tmp_path)


def test_admission_failure_stops_before_snapshots(network, owner, other, tmp_path, monkeypatch, clock):
    from snapshots import ConnectedClient, ConnectedError
    original=ConnectedClient._request
    def fail(self,method,origin,endpoint,payload,credential):
        if endpoint=='/student/admit':
            error=ConnectedError('connection_failed');error.diagnostic={'operation':'admission','phase':'request','transport_failure':'dns_failed'}
            raise error
        return original(self,method,origin,endpoint,payload,credential)
    monkeypatch.setattr(ConnectedClient,'_request',fail)
    accounts={'owner':{'email':'teacher@example.com','password':'test password 12345'},'other':{'email':'other@example.com','password':'other password 12345'}}
    with pytest.raises(ConnectedError):
        execute(tmp_path,network[0],accounts,time.time()+180,lambda *args:pytest.fail('No operator gate should be reached'),teacher_origin='http://127.0.0.1:5174',now=clock,vault=Vault())
    result=json.loads((tmp_path/'snapshot-results.json').read_text())
    assert result['first_failure']['phase']=='admission'
    assert result['first_failure']['diagnostic']['transport_failure']=='dns_failed'
    assert 'early_upload' not in result and not (tmp_path/'synthetic-evidence').exists()
