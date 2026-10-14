"""Stage 1 cannot open media without consent or acquire exam authority."""
from dataclasses import replace
import json
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from proctoring.audio.monitor import AudioMonitor
from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.devices import InputDevice
from proctoring.desktop_bridge.protocol import BridgeError, MAX_REQUEST_BYTES, Protocol, parse_request
from proctoring.desktop_bridge.service import SetupBridge
from proctoring.vision.camera import CapturedFrame


class StubAudio(AudioMonitor):
    starts = 0
    def start(self):
        self.starts += 1
        self._thread = SimpleNamespace(is_alive=lambda: True)
        self._set_status('available')
    def stop(self, timeout=.5):
        self._thread = None
        super().stop(timeout)


class StubCamera:
    starts = 0
    def __init__(self, config, clock, device_id):
        self.device_id, self.clock = device_id, clock
        self.alive, self.stopped, self.latest = False, False, None
        self.fps = 12.
    def start(self):
        self.starts += 1
        self.alive = True
        self.latest = CapturedFrame(1, self.clock.monotonic(), np.zeros((480, 640, 3), np.uint8))
    def stop(self, timeout=.5):
        self.alive, self.stopped, self.latest = False, True, None


@pytest.fixture
def bridge(tmp_path):
    config = replace(load_config(), sessions_dir=tmp_path/'must-not-be-created')
    result = SetupBridge(config, clock=FakeClock(100.), camera_factory=StubCamera,
                         audio_factory=StubAudio, auto_scan=False)
    result._catalog = {'cameras': [InputDevice('camera-a', 'Camera A'), InputDevice('camera-b', 'Camera B')],
                       'microphones': [InputDevice('mic-a', 'Fifine', signature='A'),
                                       InputDevice('mic-b', 'Other microphone', signature='B')]}
    yield result
    result.close()
    assert not config.sessions_dir.exists()


def request(command, payload=None, request_id='one'):
    return json.dumps({'version': 1, 'id': request_id, 'command': command, 'payload': payload or {}}).encode()


def select(bridge):
    bridge.dispatch('camera.select', {'key': 'camera-a'})
    bridge.dispatch('microphone.select', {'key': 'mic-a'})


def test_constructor_selection_and_consent_alone_never_start_devices(bridge):
    select(bridge)
    assert bridge.camera is None and bridge.audio.starts == 0
    for command in ('camera.start', 'audio.start', 'audio.calibrate'):
        with pytest.raises(BridgeError, match='Accept local device access'):
            bridge.dispatch(command, {})
    bridge.dispatch('consent.set', {'accepted': True})
    assert bridge.camera is None and bridge.audio.starts == 0
    bridge.dispatch('camera.start', {})
    bridge.dispatch('audio.start', {})
    assert bridge.camera.device_id == 'camera-a'
    assert bridge.audio.selection.key == 'mic-a'
    assert bridge.state()['camera']['source_width'] == 640


def test_consent_revocation_stops_both_and_requires_explicit_restart(bridge):
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('camera.start', {})
    bridge.dispatch('audio.start', {})
    bridge.dispatch('consent.set', {'accepted': False})
    assert not bridge.camera.alive and not bridge._audio_alive()
    assert bridge.latest_frame() is None
    bridge.dispatch('consent.set', {'accepted': True})
    assert not bridge.camera.alive and not bridge._audio_alive()


def test_selected_camera_identity_is_exact_and_missing_is_not_replaced(bridge):
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('camera.start', {})
    previous = bridge.camera
    bridge.dispatch('camera.select', {'key': 'camera-b'})
    assert previous.stopped and bridge.camera is None
    bridge.dispatch('camera.start', {})
    assert bridge.camera.device_id == 'camera-b'
    bridge._catalog['cameras'] = [InputDevice('camera-a', 'Camera A')]
    assert bridge.state()['camera']['state'] == 'unavailable'
    with pytest.raises(BridgeError, match='unavailable'):
        bridge.dispatch('camera.start', {})
    assert bridge.camera_key == 'camera-b'


def test_stale_camera_and_audio_are_explicit_and_no_stale_meter(bridge):
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('camera.start', {})
    bridge.dispatch('audio.start', {})
    bridge.audio._detector.observe(np.full(800, .03), bridge.clock.monotonic(), 16000)
    assert bridge.state()['audio']['processed_level'] > 0
    bridge.clock.advance(3.)
    state = bridge.state()
    assert state['camera']['state'] == 'stale' and bridge.latest_frame() is None
    assert state['audio']['processed_level'] == 0 and state['audio']['check']['state'] == 'no_signal'


def test_same_device_retains_calibration_different_device_invalidates_only_audio(bridge):
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('camera.start', {})
    detector = bridge.audio._detector
    detector.processed_speech = .04
    detector._commit_threshold(.016, 'adaptive', .0001, .016)
    detector.gain = 8.
    detector._check_state = 'ready'
    bridge.dispatch('microphone.select', {'key': 'mic-a'})
    bridge.dispatch('audio.start', {})
    assert bridge.audio._detector is detector and bridge.audio.check_status['committed_threshold'] == .016
    bridge.dispatch('audio.stop', {})
    bridge.dispatch('audio.start', {})
    assert bridge.audio._detector is detector and detector.gain == 8.
    camera = bridge.camera
    bridge.dispatch('microphone.select', {'key': 'mic-b'})
    assert bridge.audio._detector is not detector and bridge.audio._detector.custom_threshold is None
    assert bridge.audio.starts == 0 and bridge.camera is camera and camera.alive


def test_calibration_uses_existing_gain_path_and_failed_retry_retains_reference(bridge):
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('audio.calibrate', {})
    detector = bridge.audio._detector
    now = 100.
    for index in range(170):
        # quiet for the actual configured window, then realistic numerical variation
        amplitude = .00002 if index < 32 else (.004 if index % 10 < 7 else .00002)
        detector.observe(np.full(800, amplitude), now, 16000)
        now += .05
    assert detector.check_status['state'] == 'ready'
    committed = detector.threshold
    assert committed < .05 and detector.gain == 8.
    bridge.dispatch('audio.calibrate', {})
    for index in range(170):
        detector.observe(np.zeros(800), now, 16000)
        now += .05
    assert detector.check_status['state'] == 'no_signal'
    assert detector.threshold == committed


def test_refresh_is_async_and_does_not_stop_or_restart_media(bridge):
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('audio.start', {})
    release = threading.Event()
    bridge.scanner = lambda: (release.wait(2.), bridge._catalog)[1]
    state = bridge.dispatch('devices.refresh', {})
    assert state['devices']['scanning'] and bridge._audio_alive()
    with pytest.raises(BridgeError, match='already running'):
        bridge.dispatch('devices.refresh', {})
    bridge.clock.advance(6.)
    assert 'scan_error' in bridge.state()['devices']['errors']
    release.set()
    for _ in range(100):
        if not bridge.state()['devices']['scanning']:
            break
        time.sleep(.005)
    assert not bridge.state()['devices']['scanning'] and bridge.audio.starts == 1


def wait_for_scan(bridge):
    for _ in range(200):
        if not bridge.state()['devices']['scanning']:
            return
        time.sleep(.005)
    pytest.fail('Device scan did not finish')


def test_idle_refresh_rebuilds_portaudio_catalog_without_losing_calibration(bridge, monkeypatch):
    from proctoring.desktop_bridge import service
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    detector = bridge.audio._detector
    detector.processed_speech = .04
    detector._commit_threshold(.016, 'adaptive', .0001, .016)
    detector.gain = 8.
    release = threading.Event()
    calls = []
    cameras = list(bridge._catalog['cameras'])
    microphones = list(bridge._catalog['microphones'])
    def refresh():
        calls.append('rebuild')
        assert not bridge._audio_alive()
        assert release.wait(2.)
        return [*microphones, InputDevice('new-mic', 'Newly connected microphone')]
    monkeypatch.setattr(service.devices, 'cameras', lambda: cameras)
    monkeypatch.setattr(service.devices, 'refresh_microphones', refresh)
    monkeypatch.setattr(service.devices, 'microphones', lambda: pytest.fail('Idle refresh used cached catalog'))
    bridge.dispatch('devices.refresh', {})
    try:
        for command in ('audio.start', 'audio.calibrate', 'camera.start'):
            with pytest.raises(BridgeError, match='catalog'):
                bridge.dispatch(command, {})
        assert bridge.audio.starts == 0
    finally:
        release.set()
    wait_for_scan(bridge)
    state = bridge.state()
    assert calls == ['rebuild']
    assert 'new-mic' in [row['key'] for row in state['devices']['microphones']]
    assert 'microphones_notice' not in state['devices']['errors']
    assert bridge.audio._detector is detector and detector.threshold == .016 and detector.gain == 8.
    assert bridge.audio.starts == 0


@pytest.mark.parametrize('releasing', [False, True])
def test_live_or_releasing_audio_refresh_uses_cached_catalog_with_notice(bridge, monkeypatch, releasing):
    from proctoring.desktop_bridge import service
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('audio.start', {})
    if releasing:
        # A bounded stop may return before a native read releases the input.
        bridge.audio._set_status('stopped')
    calls = []
    cameras = list(bridge._catalog['cameras'])
    microphones = list(bridge._catalog['microphones'])
    monkeypatch.setattr(service.devices, 'cameras', lambda: cameras)
    monkeypatch.setattr(service.devices, 'microphones', lambda: calls.append('cached') or microphones)
    monkeypatch.setattr(service.devices, 'refresh_microphones', lambda: pytest.fail('Catalog rebuilt while native audio thread alive'))
    bridge.dispatch('devices.refresh', {})
    wait_for_scan(bridge)
    assert calls == ['cached']
    assert 'Stop the microphone' in bridge.state()['devices']['errors']['microphones_notice']
    assert bridge.audio.starts == 1 and bridge._audio_alive()


def test_setup_only_discloses_destinations_without_credentials_or_protection(bridge):
    bridge.config = replace(bridge.config,
                            protection=replace(bridge.config.protection, enabled=True),
                            remote=replace(bridge.config.remote, enabled=True, telegram_enabled=True,
                                           telegram_bot_token='DO-NOT-LEAK', telegram_chat_id='PRIVATE',
                                           webhook_url='https://example.invalid/PRIVATE', webhook_token='SECRET'))
    state = bridge.state()
    assert not state['protection']['enabled']
    assert state['config']['remote_destinations'] == ['telegram', 'webhook']
    assert state['config']['audio_exam_enabled'] is False
    assert bridge.audio.config.enabled is True
    encoded = json.dumps(state)
    assert not any(secret in encoded for secret in ('DO-NOT-LEAK', 'PRIVATE', 'SECRET', bridge.config.proctor_pin))
    for command in ('exam.start', 'registration.submit', 'protect', 'shell.execute'):
        with pytest.raises(BridgeError):
            bridge.dispatch(command, {})


def test_shutdown_idempotent_and_cannot_resume(bridge):
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('camera.start', {})
    bridge.dispatch('audio.start', {})
    assert not bridge.dispatch('shutdown', {})['connected']
    bridge.dispatch('shutdown', {})
    assert not bridge.camera.alive and not bridge._audio_alive()
    with pytest.raises(BridgeError):
        bridge.dispatch('audio.start', {})


def test_start_retry_never_creates_second_live_device_worker(bridge):
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('camera.start', {})
    first = bridge.camera
    bridge.dispatch('camera.start', {})
    assert bridge.camera is first and first.starts == 1
    # A partially released driver blocks replacement rather than opening again.
    first.stop = lambda timeout=.5: setattr(first, 'stopped', True)
    bridge.dispatch('camera.stop', {})
    with pytest.raises(BridgeError, match='still releasing'):
        bridge.dispatch('camera.start', {})
    with pytest.raises(BridgeError, match='still releasing'):
        bridge.dispatch('camera.select', {'key': 'camera-b'})
    assert bridge.camera is first and bridge.camera_key == 'camera-a'
    first.alive = False


def test_fresh_bridge_does_not_reuse_consent_or_reopen_previous_streams(bridge):
    select(bridge)
    bridge.dispatch('consent.set', {'accepted': True})
    bridge.dispatch('camera.start', {})
    bridge.close()
    fresh = SetupBridge(bridge.config, clock=bridge.clock, camera_factory=StubCamera,
                        audio_factory=StubAudio, auto_scan=False)
    try:
        state = fresh.state()
        assert not state['consent_accepted'] and state['camera']['selected_key'] is None
        assert not state['audio']['running'] and fresh.camera is None
    finally:
        fresh.close()


@pytest.mark.parametrize('raw', [b'NaN', b'[]', b'{}', b'\xff', b'x'*(MAX_REQUEST_BYTES+1),
    b'{"version":1,"version":1,"id":"x","command":"state.get","payload":{}}',
    request('shell.execute'), request('state.get', {'extra': 1}), request('camera.select', {'key': 1}),
    request('consent.set', {'accepted': 1}), request('consent.set', {'accepted': True, 'other': False}),
    b'{"version":true,"id":"x","command":"state.get","payload":{}}'])
def test_protocol_rejects_unknown_extra_unbounded_and_invalid_values(raw):
    with pytest.raises(BridgeError):
        parse_request(raw)


def test_duplicate_ids_do_not_repeat_mutations_and_conflicting_reuse_rejected(bridge):
    calls = []
    protocol = Protocol(lambda command, payload: calls.append(command) or {'n': len(calls)})
    first = protocol.handle(request('state.get'))
    assert protocol.handle(request('state.get')) == first and calls == ['state.get']
    assert protocol.handle(request('shutdown'))['error']['code'] == 'duplicate_id'
    assert calls == ['state.get']
    for index in range(200):
        protocol.handle(request('state.get', request_id=str(index)))
    assert len(protocol.cache) == 128


def test_internal_exception_details_never_cross_control_boundary():
    def fail(*_):
        raise RuntimeError('credentials=TOP_SECRET')
    response = Protocol(fail).handle(request('state.get'))
    assert response['error']['code'] == 'backend_error' and 'TOP_SECRET' not in json.dumps(response)
