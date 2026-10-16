"""All runtime/native operations are mocked; no windows, capture or input injection."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from proctoring.security import packaged_startup as startup
from proctoring.security.electron_validation import MANDATORY_CHECKS


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path/'app'
    (root/'resources/backend').mkdir(parents=True)
    config = tmp_path/'config.toml'; config.write_bytes(b'trusted config')
    (root/'resources/default.example.toml').write_bytes(config.read_bytes())
    report = tmp_path/'audit.json'
    policy = SimpleNamespace(enabled=True, heartbeat_timeout_seconds=5, startup_timeout_seconds=5,
                             foreground_poll_ms=100, validation_report=report, validation_max_age_hours=24)
    monkeypatch.setattr(startup.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(startup.sys, 'executable', str(root/'resources/backend/ProctoringBackend.exe'))
    monkeypatch.setattr(startup, 'load_config', lambda _: SimpleNamespace(protection=policy, connected=SimpleNamespace(enabled=True), ui=SimpleNamespace(language='en')))
    monkeypatch.setattr(startup, 'runtime_identity', lambda *_: {'runtime': {'build_kind': 'packaged'}, 'machine': 'test', 'fingerprint': 'current'})
    runtime = {'build_kind': 'packaged'}; host = root/'LocalProctoring-Electron.exe'
    identity = startup.inspect(config, runtime, host)['identity']
    valid = dict(schema=2, frontend='electron', mode='audit_only', blocking_enabled=False, passed=True, status='completed',
                 generated_at=datetime.now(timezone.utc).isoformat(), identity=identity,
                 checks=[dict(name=n, passed=True, kind='native_audit') for n in MANDATORY_CHECKS])
    return config, report, runtime, host, valid, policy


def test_missing_and_valid_report(setup):
    config, report, runtime, host, valid, _ = setup
    assert not startup.inspect(config, runtime, host)['valid']
    report.write_text(json.dumps(valid), encoding='utf-8')
    assert startup.inspect(config, runtime, host)['valid']


@pytest.mark.parametrize('change', ['expired','different_build','incomplete','failed','missing_status','missing_check','duplicate_check','suppression'])
def test_invalid_reports_fail_closed(setup, change):
    config, report, runtime, host, valid, _ = setup
    bad = deepcopy(valid)
    if change == 'expired': bad['generated_at'] = (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    elif change == 'different_build': bad['identity']['fingerprint'] = 'old'
    elif change == 'incomplete': bad['status'] = 'pending_or_incomplete'
    elif change == 'failed': bad['passed'] = False
    elif change == 'missing_status': del bad['status']
    elif change == 'missing_check': bad['checks'].pop()
    elif change == 'duplicate_check': bad['checks'].append(bad['checks'][0])
    elif change == 'suppression': bad['blocking_enabled'] = True
    report.write_text(json.dumps(bad), encoding='utf-8')
    assert not startup.inspect(config, runtime, host)['valid']


def test_trusted_unprotected_edition_skips_audit_but_untrusted_config_fails_closed(setup,monkeypatch):
    config, _, runtime, host, _, policy = setup
    policy.enabled = False
    def forbidden(*args):raise AssertionError('Unprotected edition must not request native audit')
    monkeypatch.setattr(startup,'require_electron_validation',forbidden)
    result=startup.inspect(config,runtime,host)
    assert result['audit_required'] is False and result['valid'] is False
    policy.enabled = True; config.write_bytes(b'changed')
    with pytest.raises(ValueError, match='trusted defaults'): startup.inspect(config, runtime, host)


def test_disconnected_packaged_edition_is_rejected(setup,monkeypatch):
    config,_,runtime,host,_,policy=setup
    monkeypatch.setattr(startup,'load_config',lambda _:SimpleNamespace(protection=policy,connected=SimpleNamespace(enabled=False)))
    with pytest.raises(ValueError,match='requires Connected Mode'):startup.inspect(config,runtime,host)


def test_no_audit_edition_verifies_config_without_reading_or_minting_report(setup,monkeypatch):
    config,report,runtime,host,_,policy=setup
    policy.require_recovery_audit=False
    def forbidden(*args): raise AssertionError('Audit must not be requested')
    monkeypatch.setattr(startup,'require_electron_validation',forbidden)
    result=startup.inspect(config,runtime,host)
    assert result['audit_required'] is False and result['valid'] is False
    assert not report.exists()
    config.write_bytes(b'edited no-audit policy')
    with pytest.raises(ValueError,match='trusted defaults'):startup.inspect(config,runtime,host)
