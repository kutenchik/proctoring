"""Injected native adapter; these tests never install hooks or operate devices."""
from dataclasses import replace
import json

import pytest

from proctoring.desktop_bridge.protocol import BridgeError, parse_request
from proctoring.security.protection import EmergencyRelease, NoOpProtection
from test_desktop_workflow import make_workflow, make_ready


class ProtectionFixture(NoOpProtection):
    blocking_enabled = True

    def __init__(self):
        super().__init__()
        self.ready = self.media_allowed = True
        self.arm_count = 0
        self.progress = []
        self.phase = 'preparing'

    @property
    def status(self):
        return 'ACTIVE' if self.armed else 'INACTIVE'

    def binding_status(self):
        return {'ready': self.ready, 'media_allowed': self.media_allowed,
                'error': None if self.ready else 'awaiting_audit'}

    def public_state(self):
        return {'requested': True, 'enabled': self.armed, 'state': self.phase, 'reason': ''}

    def arm(self):
        if not self.ready:
            raise RuntimeError('Audit missing')
        self.arm_count += 1
        self.phase = 'active'
        super().arm()

    def release(self, reason):
        self.phase = 'released'
        super().release(reason)

    def accept_progress(self, payload):
        self.progress.append(payload)
        return True


@pytest.fixture
def protected(tmp_path):
    bridge = make_workflow(tmp_path)
    adapter = ProtectionFixture()
    bridge.config = replace(bridge.config, protection=replace(bridge.config.protection, enabled=True))
    bridge.controller.config = bridge.config
    bridge._protected_requested = True
    bridge.electron_protection = bridge.controller.protection = adapter
    bridge.controller.emergency = EmergencyRelease(adapter)
    bridge._geometry = {'geometry_id': 'test-display', 'fullscreen': True, 'settled': True}
    yield bridge, adapter
    bridge.close()


def test_missing_desktop_ownership_blocks_devices_before_capture(protected):
    bridge, adapter = protected
    adapter.media_allowed = False
    with pytest.raises(BridgeError, match='desktop owner'):
        bridge.dispatch('camera.select', {'key': 'camera-a'})
    assert not bridge.monitor.started
    assert not adapter.armed


def test_missing_audit_blocks_exam_but_not_owned_safe_setup(protected):
    bridge, adapter = protected
    make_ready(bridge)
    adapter.ready = False
    readiness = bridge.readiness()
    assert not readiness['ready']
    assert next(c for c in readiness['checks'] if c['id'] == 'protection')['status'] == 'blocked'
    with pytest.raises(BridgeError, match='readiness'):
        bridge.dispatch('exam.start', {})
    assert adapter.arm_count == 0
    assert not bridge.controller.session.started


@pytest.mark.parametrize('missing', ['fullscreen', 'settled'])
def test_final_geometry_required_without_resetting_existing_fit(protected, missing):
    bridge, adapter = protected
    make_ready(bridge)
    bridge._geometry[missing] = False
    with pytest.raises(BridgeError, match='fullscreen'):
        bridge.dispatch('exam.start', {})
    assert adapter.arm_count == 0
    assert bridge.monitor.calibration.ready


@pytest.mark.parametrize('outage,needs_pin', [(14.9, False), (15., True)])
def test_monitoring_pause_keeps_protection_and_control_chain(protected, outage, needs_pin):
    bridge, adapter = protected
    make_ready(bridge)
    bridge.dispatch('exam.start', {})
    session = bridge.controller.session
    bridge.monitor.healthy = False
    bridge.monitor.failure_since = bridge.clock.monotonic()
    bridge.tick()
    assert not session.running and adapter.armed
    payload = {'lease_id': 'a'*32, 'sequence': 1, 'nonce': 'b'*32, 'main_sequence': 1,
               'session_id': bridge._session_id(), 'snapshot_seq': bridge.state()['workflow']['snapshot_seq']}
    bridge.dispatch('host.progress', payload)
    assert len(adapter.progress) == 1
    assert 'session_id' not in adapter.progress[0]
    bridge.clock.advance(outage)
    bridge.monitor.healthy = True
    bridge.tick()
    assert adapter.armed and adapter.arm_count == 1
    assert session.recovery_pin_required is needs_pin
    assert session.running is not needs_pin


def test_independent_safety_release_ends_session_and_cannot_resume(protected):
    bridge, adapter = protected
    make_ready(bridge)
    bridge.dispatch('exam.start', {})
    adapter.release('heartbeat_timeout')
    bridge.tick()
    assert bridge.controller.session.ended
    assert bridge.controller.summary['end_reason'] == 'heartbeat_timeout'
    bridge.dispatch('proctor.resume', {'pin': bridge.config.proctor_pin})
    assert not bridge.controller.session.running
    assert adapter.arm_count == 1


def test_geometry_change_is_terminal_after_protected_start(protected):
    bridge, adapter = protected
    make_ready(bridge)
    bridge.dispatch('exam.start', {})
    bridge.dispatch('geometry.changed', {'geometry': {'geometry_id': 'different', 'fullscreen': True, 'settled': True}})
    assert not adapter.armed
    assert bridge.controller.session.end_reason == 'display_geometry_changed'


def test_progress_rejects_other_session_and_unseen_snapshot(protected):
    bridge, adapter = protected
    payload = {'lease_id': 'a'*32, 'sequence': 1, 'nonce': 'b'*32, 'main_sequence': 1,
               'session_id': 'wrong-session', 'snapshot_seq': 1}
    with pytest.raises(BridgeError, match='presentation'):
        bridge.dispatch('host.progress', payload)
    payload.update(session_id=None, snapshot_seq=2**52)
    with pytest.raises(BridgeError, match='presentation'):
        bridge.dispatch('host.progress', payload)
    assert not adapter.progress


def test_protocol_rejects_native_pointer_precision_loss_and_unbounded_window_list():
    payload = {'launch_id': 'a'*32, 'host_pid': 42,
               'windows': [{'hwnd': 2**60, 'role': 'exam'}],
               'runtime': {'electron_version': '44', 'app_version': 'test', 'build_kind': 'source', 'build_id': 'a'*64}}
    def request():
        return json.dumps({'version': 1, 'id': 'test', 'command': 'host.bind', 'payload': payload}).encode()
    with pytest.raises(BridgeError, match='window'):
        parse_request(request())
    payload['windows'] = [{'hwnd': '0x1234', 'role': 'exam'}]*9
    with pytest.raises(BridgeError, match='window'):
        parse_request(request())


def test_controller_timer_stops_before_slow_cleanup(protected, monkeypatch):
    bridge, adapter = protected
    make_ready(bridge)
    bridge.dispatch('exam.start', {})
    bridge.clock.advance(1.)
    before = bridge.controller.session.elapsed_seconds
    original = bridge.monitor.stop
    def slow_stop(*args, **kwargs):
        assert not adapter.armed and bridge.controller.session.ended
        bridge.clock.advance(3.)
        return original(*args, **kwargs)
    monkeypatch.setattr(bridge.monitor, 'stop', slow_stop)
    bridge.dispatch('proctor.end', {'pin': bridge.config.proctor_pin})
    assert bridge.controller.summary['elapsed_seconds'] == before


@pytest.mark.parametrize('field', ['role', 'build_kind', 'reason'])
@pytest.mark.parametrize('value', [[], {}, None, True])
def test_native_protocol_malformed_enums_are_rejected_without_crashing(field, value):
    payload = {'launch_id': 'a'*32, 'host_pid': 42,
               'windows': [{'hwnd': '0x1234', 'role': 'exam'}],
               'runtime': {'electron_version': '44', 'app_version': 'test', 'build_kind': 'source', 'build_id': 'a'*64}}
    command = 'host.bind'
    if field == 'role':
        payload['windows'][0]['role'] = value
    elif field == 'build_kind':
        payload['runtime']['build_kind'] = value
    else:
        command, payload = 'host.safety_release', {'reason': value}
    raw = json.dumps({'version': 1, 'id': 'bad-enum', 'command': command, 'payload': payload}).encode()
    with pytest.raises(BridgeError):
        parse_request(raw)
