"""Real controller/session/storage with deterministic injected vision, no hardware."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.desktop_bridge.protocol import BridgeError, Protocol
from proctoring.desktop_bridge.workflow import WorkflowBridge
from proctoring.devices import InputDevice
from proctoring.settings import AudioConfig, IdentityConfig, RegistrationConfig, RemoteConfig, ReportingConfig, SystemChecksConfig
from proctoring.vision.calibration import Calibration, DIRECTIONS
from proctoring.vision.camera import CapturedFrame
from proctoring.vision.rules import to_observation
from proctoring.vision.types import HealthStatus
from test_desktop_calibration_flow import measurement


CANDIDATE = {'first_name': 'Test', 'last_name': 'Candidate', 'group_id': 'TEST-01'}


class FakeCamera:
    def __init__(self, clock):
        self.clock = clock
        self.latest = None
        self.alive = False
        self.stopped = False
        self.fps = 12.
    def start(self):
        self.alive, self.stopped = True, False
    def stop(self, timeout=.5):
        self.alive, self.stopped, self.latest = False, True, None


class FakeMonitor:
    def __init__(self, config, clock):
        self.config, self.clock = config, clock
        self.calibration = Calibration(config)
        self._camera = FakeCamera(clock)
        self._switching, self._thread = False, None
        self.selected_camera_id = None
        self.started, self.stopped, self.healthy = False, False, True
        self.failure_since = None
        self.conditions = {}
        self.latest_result = self.delivered_result = None
        self._last_delivered = None
        self.identity_baseline = None
        self.identity_ready = False
        self.identity_status = 'Reference face not captured'
        self.exam_active = False
    def configure_identity(self, config): self.identity_config = config
    @property
    def identity_can_capture(self): return self.started and not self.stopped and self.healthy
    def start(self):
        self.started, self.stopped = True, False
        self._camera.start()
        self.publish()
    def stop(self, timeout=.5):
        self.stopped, self.exam_active = True, False
        self._camera.stop(timeout)
    def set_exam_active(self, active): self.exam_active = active
    def select_camera(self, key, activate=False):
        self.stop()
        self.selected_camera_id = key
        self.calibration.reset()
        self.identity_baseline = None
        self.identity_ready = False
        self._camera = FakeCamera(self.clock)
        if activate: self.start()
        return True
    def publish(self, **changes):
        stamp = self.clock.monotonic()
        source = measurement(stamp)
        self.latest_result = replace(source, frame=np.zeros((720, 1280, 3), np.uint8), **self.conditions, **changes)
        self._camera.latest = CapturedFrame(round(stamp*1000), stamp, self.latest_result.frame)
        return self.latest_result
    @property
    def latest_calibration_result(self):
        return self.publish() if self.started and not self.stopped and self.healthy else None
    def health(self, now):
        healthy = self.healthy and self.started and not self.stopped
        return HealthStatus(healthy, '' if healthy else 'Injected monitoring unavailable', self.failure_since)
    @property
    def metrics(self): return {'monitoring_fps': 5.}
    def sample(self, now):
        if not self.health(now).healthy or self._last_delivered == now:
            return None
        self._last_delivered = now
        self.delivered_result = self.publish()
        return to_observation(self.delivered_result)
    def request_identity_baseline(self):
        ok, data = cv2.imencode('.jpg', np.zeros((40, 40, 3), np.uint8))
        assert ok
        self.identity_baseline = SimpleNamespace(jpeg_bytes=data.tobytes(), metadata={'captured_monotonic': self.clock.monotonic()})
        self.identity_ready = True
        self.identity_status = 'Reference captured; geometry only'
        return True


def make_workflow(tmp_path, *, audio_enabled=False, registration_enabled=False, identity_enabled=False, external_url=''):
    config = replace(load_config(), sessions_dir=tmp_path/'sessions', external_url=external_url,
                     allowed_domains=('exam.example',) if external_url else (),
                     registration=RegistrationConfig(enabled=registration_enabled),
                     identity=IdentityConfig(selfie_verification_enabled=identity_enabled),
                     audio=AudioConfig(enabled=audio_enabled), remote=RemoteConfig(enabled=False),
                     reporting=ReportingConfig(generate_pdf_report=False), system_checks=SystemChecksConfig(),
                     snapshots_enabled=False)
    clock = FakeClock(100.)
    monitor = FakeMonitor(config.vision, clock)
    controller = AppController(config, clock, mode='camera', monitor=monitor)
    bridge = WorkflowBridge(config, controller=controller, clock=clock, auto_scan=False)
    bridge._catalog = {'cameras': [InputDevice('camera-a', 'Camera A'), InputDevice('camera-b', 'Camera B')],
                       'microphones': [InputDevice('mic-a', 'Test microphone', signature='mic-a')]}
    return bridge


def make_ready(bridge):
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('camera.select', {'key': 'camera-a'})
    bridge.dispatch('camera.start', {})
    if bridge.config.registration.enabled:
        bridge.dispatch('registration.submit', CANDIDATE)
    if bridge.config.identity.selfie_verification_enabled:
        bridge.dispatch('reference.capture', {})
    calibration = bridge.monitor.calibration
    for direction, (x, y) in zip(DIRECTIONS, [(.5, .5), (.2, .5), (.8, .5), (.5, .8)]):
        for _ in range(bridge.config.vision.calibration_samples):
            bridge.clock.advance(.05)
            value = measurement(bridge.clock.monotonic(), x, y).face
            assert calibration.add_sample(direction, value.features, bridge.clock.monotonic(), value.quality,
                                          noise_floor=1/35., measurement=value, frame_size=value.frame_size)
    assert calibration.fit()[0]
    bridge.flow.phase = 'complete'
    bridge.flow.completed = list(DIRECTIONS)
    bridge._step = 'ready'
    bridge.monitor.publish()
    return bridge


@pytest.fixture
def workflow(tmp_path):
    bridge = make_workflow(tmp_path)
    yield bridge
    bridge.close()


def test_failed_fit_and_no_consent_cannot_start_or_create_session(workflow):
    assert workflow.state()['mode'] == 'exam_workflow'
    with pytest.raises(BridgeError): workflow.dispatch('exam.start', {})
    assert workflow.controller.store is None
    assert not workflow.config.sessions_dir.exists()
    workflow.dispatch('consent.set', {'accepted': True})
    workflow.dispatch('camera.select', {'key': 'camera-a'})
    workflow.dispatch('camera.start', {})
    with pytest.raises(BridgeError): workflow.dispatch('exam.start', {})
    assert not workflow.controller.session.started


@pytest.mark.parametrize('registration', [False, True])
@pytest.mark.parametrize('identity', [False, True])
def test_optional_registration_reference_variants(tmp_path, registration, identity):
    bridge = make_workflow(tmp_path, registration_enabled=registration, identity_enabled=identity)
    try:
        make_ready(bridge)
        assert bridge.readiness()['ready']
        assert bool(bridge.controller.candidate_info) is registration
        assert bridge.controller.identity_ready
        bridge.dispatch('exam.start', {})
        assert bridge.controller.session.running
        assert bridge.controller.store.path.joinpath('reference_face.jpg').exists() is identity
    finally:
        bridge.close()


def test_start_answers_submission_are_idempotent_and_hide_scoring_keys(workflow):
    make_ready(workflow)
    first = workflow.dispatch('exam.start', {})
    session_id = first['workflow']['session_id']
    assert 'correct_index' not in json.dumps(first['workflow']['quiz'])
    assert workflow.dispatch('exam.start', {})['workflow']['session_id'] == session_id
    workflow.dispatch('quiz.answer', {'question_index': 0, 'option_index': 1, 'revision': 0})
    workflow.dispatch('quiz.answer', {'question_index': 0, 'option_index': 1, 'revision': 0})
    with pytest.raises(BridgeError, match='Answers changed'):
        workflow.dispatch('quiz.answer', {'question_index': 0, 'option_index': 0, 'revision': 0})
    workflow.dispatch('quiz.navigate', {'question_index': 1})
    assert workflow.state()['workflow']['quiz']['answers'] == {0: 1}
    summary = workflow.dispatch('exam.submit', {})['workflow']['summary']
    assert summary['answered'] == 1 and summary['end_reason'] == 'completed'
    workflow.dispatch('exam.submit', {})
    assert workflow.controller.summary['session_id'] == session_id
    records = [json.loads(line) for line in (workflow.controller.store.path/'events.jsonl').read_text().splitlines()]
    assert sum(r.get('event_type') == 'session_started' for r in records) == 1
    assert sum(r.get('event_type') == 'session_ended' for r in records) == 1


def test_pin_pause_presentation_resync_and_monitoring_reasons_overlap(workflow):
    make_ready(workflow).dispatch('exam.start', {})
    with pytest.raises(BridgeError, match='Incorrect'): workflow.dispatch('proctor.pause', {'pin': 'wrong'})
    pin = workflow.config.proctor_pin
    workflow.clock.advance(1.)
    workflow.dispatch('proctor.pause', {'pin': pin})
    workflow.dispatch('presentation.lost', {})
    elapsed = workflow.controller.session.elapsed_seconds
    workflow.clock.advance(10.)
    workflow.monitor.publish()
    workflow.dispatch('presentation.sync', {'session_id': workflow._session_id(), 'event_cursor': workflow._event_cursor()})
    assert 'proctor' in workflow.controller.session.pause_reasons
    assert workflow.controller.session.elapsed_seconds == elapsed
    workflow.dispatch('proctor.resume', {'pin': pin})
    assert workflow.controller.session.running


@pytest.mark.parametrize('duration,needs_pin', [(14.9, False), (15., True)])
def test_monitoring_recovery_boundaries_keep_backend_policy(workflow, duration, needs_pin):
    make_ready(workflow).dispatch('exam.start', {})
    workflow.monitor.healthy = False
    workflow.monitor.failure_since = workflow.clock.monotonic()
    workflow.tick()
    elapsed = workflow.controller.session.elapsed_seconds
    workflow.clock.advance(duration)
    workflow.monitor.healthy = True
    workflow.monitor.publish()
    workflow.tick()
    assert workflow.controller.session.recovery_pin_required is needs_pin
    assert workflow.controller.session.running is not needs_pin
    assert workflow.controller.session.elapsed_seconds == elapsed
    if needs_pin:
        workflow.dispatch('proctor.resume', {'pin': workflow.config.proctor_pin})
        assert workflow.controller.session.running


def test_device_change_invalidates_reference_and_calibration_only(tmp_path):
    bridge = make_workflow(tmp_path, registration_enabled=True, identity_enabled=True)
    try:
        make_ready(bridge)
        bridge.dispatch('camera.select', {'key': 'camera-b'})
        assert bridge.controller.candidate_info == CANDIDATE
        assert not bridge.monitor.calibration.ready and not bridge.controller.identity_ready
    finally:
        bridge.close()


def test_same_requested_camera_can_retry_failed_asynchronous_switch(workflow, monkeypatch):
    make_ready(workflow)
    original = workflow.monitor.select_camera
    calls = []
    def failed_switch(key, activate=False):
        calls.append((key, activate))
        workflow.monitor._selection_error = 'Previous camera is still releasing'
        workflow.monitor.stop()
        # Matches RealMonitor: request accepted, then asynchronous switch fails;
        # actual selected_camera_id remains the old camera.
        return True
    monkeypatch.setattr(workflow.monitor, 'select_camera', failed_switch)
    failed = workflow.dispatch('camera.select', {'key': 'camera-b'})
    assert workflow.camera_key == 'camera-b'
    assert workflow.monitor.selected_camera_id == 'camera-a'
    assert failed['camera']['state'] == 'unavailable'
    assert failed['camera']['error'] == 'Previous camera is still releasing'
    assert not workflow.readiness()['ready']
    def completed_switch(key, activate=False):
        calls.append((key, activate))
        workflow.monitor._selection_error = None
        return original(key, activate=activate)
    monkeypatch.setattr(workflow.monitor, 'select_camera', completed_switch)
    workflow.dispatch('camera.select', {'key': 'camera-b'})
    assert calls == [('camera-b', False), ('camera-b', False)]
    assert workflow.monitor.selected_camera_id == 'camera-b'
    assert not workflow.monitor._camera.alive  # retry does not activate capture
    workflow.dispatch('camera.select', {'key': 'camera-b'})
    assert len(calls) == 2  # successful same-device selection remains a no-op


def test_camera_retry_waits_for_previous_switch_to_finish(workflow, monkeypatch):
    from unittest.mock import Mock
    make_ready(workflow)
    workflow.monitor._selection_error = 'Injected selection failure'
    workflow.monitor._switching = True
    select = Mock()
    monkeypatch.setattr(workflow.monitor, 'select_camera', select)
    with pytest.raises(BridgeError, match='still releasing'):
        workflow.dispatch('camera.select', {'key': 'camera-a'})
    select.assert_not_called()


def test_event_pages_are_durable_boundary_checked_and_not_reset_by_remount(workflow):
    make_ready(workflow).dispatch('exam.start', {})
    workflow.controller.record_security_event('TEST_REVIEW', 'Injected test observation')
    page = workflow.event_page(0, 100)
    assert any(item['record'].get('event_type') == 'TEST_REVIEW' for item in page['records'])
    assert page['cursor'] == workflow._event_cursor()
    assert not workflow.event_page(page['cursor'], 100)['records']
    with pytest.raises(BridgeError): workflow.event_page(1, 100)
    with pytest.raises(BridgeError): workflow.event_page(page['cursor']+1, 100)
    before = workflow.state()['workflow']['revision']
    assert workflow.state()['workflow']['revision'] > before


def test_external_exam_never_exposes_native_answers_or_invented_score(tmp_path):
    bridge = make_workflow(tmp_path, external_url='https://exam.example/test')
    try:
        make_ready(bridge).dispatch('exam.start', {})
        assert bridge.state()['workflow']['quiz']['questions'] == []
        with pytest.raises(BridgeError): bridge.dispatch('exam.submit', {})
        bridge.dispatch('proctor.end', {'pin': bridge.config.proctor_pin})
        assert bridge.controller.summary['score'] is None and bridge.controller.summary['answers'] == {}
    finally:
        bridge.close()


def test_evidence_rejects_wrong_ids_missing_files_and_escape(workflow, tmp_path):
    make_ready(workflow).dispatch('exam.start', {})
    with pytest.raises(BridgeError): workflow.evidence({'session_id': 'session-other', 'kind': 'report'})
    with pytest.raises(BridgeError): workflow.evidence({'session_id': workflow._session_id(), 'kind': 'snapshot', 'event_id': 'unknown'})
    workflow.controller.record_security_event('TEST', 'Injected')
    event = workflow.controller.review_events[-1]
    outside = tmp_path/'outside.jpg'
    outside.write_bytes(b'\xff\xd8private')
    workflow.controller._snapshots[event['event_id']] = str(outside)
    with pytest.raises(BridgeError): workflow.evidence({'session_id': workflow._session_id(), 'kind': 'snapshot', 'event_id': event['event_id']})


def test_backend_disconnect_finalizes_interrupted_once(workflow):
    make_ready(workflow).dispatch('exam.start', {})
    path = workflow.controller.store.path
    workflow.close()
    workflow.close()
    summary = json.loads((path/'summary.json').read_text())
    assert summary['end_reason'] == 'backend_disconnected'
    assert not workflow.monitor._camera.alive


def test_protected_mode_without_host_launch_refused_before_controller_or_devices(tmp_path, monkeypatch):
    config = load_config()
    monkeypatch.delenv('PROCTORING_HOST_LAUNCH_ID', raising=False)
    with pytest.raises(BridgeError, match='verified Electron host'):
        WorkflowBridge(replace(config, protection=replace(config.protection, enabled=True)), auto_scan=False)


def test_presentation_loss_during_setup_stops_media_and_revokes_capture_consent(workflow):
    make_ready(workflow)
    workflow.dispatch('presentation.lost', {})
    assert not workflow.consent and not workflow.monitor._camera.alive
    workflow.dispatch('presentation.sync', {'session_id': workflow._session_id(), 'event_cursor': workflow._event_cursor()})
    assert not workflow.consent and not workflow.monitor._camera.alive
    assert not workflow.controller.session.started


def test_expiry_and_emergency_ending_have_honest_persisted_reasons(workflow):
    make_ready(workflow).dispatch('exam.start', {})
    # Fresh observations on each tick; camera failure must not manufacture expiry.
    for _ in range(600):
        workflow.clock.advance(1.)
        workflow.tick()
    assert workflow.controller.summary['end_reason'] == 'time_expired'
    assert workflow.controller.summary['remaining_seconds'] == 0
    assert workflow.dispatch('emergency.end', {})['workflow']['summary']['end_reason'] == 'time_expired'


def test_live_emergency_end_and_event_summary_paging_preserve_complete_local_summary(workflow):
    make_ready(workflow).dispatch('exam.start', {})
    for index in range(40):
        workflow.controller.record_security_event('TEST_REVIEW', f'Injected observation {index}')
    state = workflow.dispatch('emergency.end', {})
    assert state['workflow']['summary']['end_reason'] == 'emergency_shortcut'
    assert state['workflow']['summary']['events_total'] == 40
    assert state['workflow']['summary']['events_truncated']
    assert len(state['workflow']['summary']['events']) == 30
    disk = json.loads((workflow.controller.store.path/'summary.json').read_text())
    assert len(disk['events']) == 40
    page = workflow.event_page(0, 100)
    assert sum(item['record'].get('event_type') == 'TEST_REVIEW' for item in page['records']) == 40


def test_reference_evidence_validated_and_source_path_never_in_regular_snapshot(tmp_path):
    bridge = make_workflow(tmp_path, identity_enabled=True)
    try:
        make_ready(bridge)
        result = bridge.dispatch('host.evidence', {'session_id': bridge._session_id(), 'kind': 'reference'})
        assert result.data['mime'] == 'image/jpeg'
        assert result.data['file_name'] == 'reference_face.jpg'
        assert result.data['path'] not in json.dumps(bridge.state())
        assert Path(result.data['path']).is_file()
    finally:
        bridge.close()


def test_ready_can_return_to_setup_without_losing_fit_and_reset_only_explicitly(workflow):
    make_ready(workflow)
    workflow._step = 'ready'
    ready = workflow.dispatch('setup.show', {})
    assert ready['workflow']['step'] == 'setup' and workflow.monitor.calibration.ready
    assert workflow.readiness()['ready']
    assert workflow.dispatch('calibration.start', {})['workflow']['step'] == 'ready'
    state = workflow.dispatch('calibration.retry', {'scope': 'baseline'})
    assert state['workflow']['step'] == 'calibration'
    assert not workflow.monitor.calibration.ready
    with pytest.raises(BridgeError): workflow.dispatch('exam.start', {})
    make_ready(workflow).dispatch('exam.start', {})
    with pytest.raises(BridgeError): workflow.dispatch('setup.show', {})


def test_preview_boxes_use_matching_processed_frame_not_newer_raw_frame(workflow):
    from proctoring.vision.types import Box
    make_ready(workflow)
    result = workflow.monitor.publish(phones=(Box(.2, .3, .4, .5, .9),))
    workflow.clock.advance(.1)
    newer = np.full((480, 640, 3), 255, np.uint8)
    workflow.monitor._camera.latest = CapturedFrame(999999, workflow.clock.monotonic(), newer)
    frame = workflow.latest_frame()
    assert frame.image is result.frame and frame.timestamp == result.timestamp
    phone = next(item for item in frame.overlays if item.get('label') == 'phone')
    assert (phone['x1'], phone['y1'], phone['x2'], phone['y2']) == (.2, .3, .4, .5)
    workflow.clock.advance(2.)
    workflow.monitor._camera.latest = CapturedFrame(9999999, workflow.clock.monotonic(), newer)
    fallback = workflow.latest_frame()
    assert fallback.image is newer and not any(item['kind'] == 'box' for item in fallback.overlays)


def test_failed_report_retry_uses_original_saved_session_once(workflow, monkeypatch):
    from unittest.mock import Mock
    workflow.controller.config = replace(workflow.controller.config, reporting=ReportingConfig(generate_pdf_report=True))
    factory = Mock(return_value=SimpleNamespace(status='failed', result=SimpleNamespace(error='Injected failure'),
                                                close=lambda timeout=2.: True))
    monkeypatch.setattr('proctoring.storage.report_generator.ReportJob', factory)
    make_ready(workflow).dispatch('exam.start', {})
    state = workflow.dispatch('exam.submit', {})
    assert state['workflow']['report']['status'] == 'failed' and factory.call_count == 1
    original = factory.call_args.args[:2]
    factory.return_value = SimpleNamespace(status='complete', result=SimpleNamespace(error=None), close=lambda timeout=2.: True)
    state = workflow.dispatch('report.retry', {})
    assert state['workflow']['report']['available']
    assert factory.call_count == 2 and factory.call_args.args[:2] == original
    with pytest.raises(BridgeError): workflow.dispatch('report.retry', {})
    assert factory.call_count == 2
