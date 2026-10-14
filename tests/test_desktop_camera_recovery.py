"""Same-source recovery after released Qt capture errors; no real hardware."""
from types import SimpleNamespace

import pytest

from proctoring.clock import FakeClock
from proctoring.vision.qt_camera import NamedCamera
from proctoring.vision.settings import VisionConfig
from test_desktop_workflow import make_ready, make_workflow


class ReleasedNamedCamera(NamedCamera):
    def __init__(self, config, clock, device_id):
        super().__init__(config, clock, device_id)
        self.capture_running, self.start_calls = False, 0

    @property
    def alive(self): return self.capture_running

    @property
    def latest(self): return self._latest

    @latest.setter
    def latest(self, value): self._latest = value

    def start(self):
        assert not self.alive and not self.stopped
        self.start_calls += 1
        self.capture_running = True

    def stop(self, timeout=.5):
        self.capture_running = False
        super().stop(timeout)


def fail_capture(bridge):
    camera = ReleasedNamedCamera(bridge.config.vision, bridge.clock, bridge.camera_key)
    camera._fail('Camera unavailable: injected physical disconnect')
    bridge.monitor._camera = bridge.camera = camera
    bridge.monitor.healthy = False
    bridge.monitor.failure_since = bridge.clock.monotonic()
    bridge.controller.step()  # Existing controller latches the outage first.
    return camera


def test_reopens_only_released_same_source_and_keeps_reference_fit_and_outage(tmp_path):
    bridge = make_workflow(tmp_path, identity_enabled=True)
    try:
        make_ready(bridge).dispatch('exam.start', {})
        baseline = bridge.controller._baseline_saved
        calibration = bridge.monitor.calibration
        camera = fail_capture(bridge)
        onset = bridge.controller.session._failure_since
        bridge.tick()
        assert camera.start_calls == 1 and bridge.monitor._camera is camera
        assert camera.error_at == onset and bridge.controller.session._failure_since == onset
        assert bridge.controller._baseline_saved is baseline
        assert bridge.monitor.identity_baseline is baseline
        assert bridge.monitor.calibration is calibration and calibration.ready
        bridge.tick()
        assert camera.start_calls == 1  # Never create a competing live owner.
        camera.capture_running = False  # Reopen failed while unplugged.
        bridge.clock.advance(.49)
        bridge.tick()
        assert camera.start_calls == 1
        bridge.clock.advance(.01)
        bridge.tick()
        assert camera.start_calls == 2
        assert camera.error_at == onset and bridge.controller.session._failure_since == onset
    finally:
        bridge.close()


def test_terminal_late_frame_cannot_prevent_same_source_reopen(tmp_path):
    from PySide6.QtGui import QImage
    bridge = make_workflow(tmp_path)
    try:
        make_ready(bridge).dispatch('exam.start', {})
        camera = fail_capture(bridge)
        onset = bridge.controller.session._failure_since
        image = QImage(4, 4, QImage.Format.Format_RGB888)
        image.fill('gray')
        bridge.clock.advance(.1)
        # A direct frame callback can finish after the error callback requested
        # loop exit. Exercise actual image admission; it clears camera.error.
        camera._accept_image(image)
        assert camera.error is None and not camera.alive and not camera.stopped
        # No additional frames arrive: the released capture is still unhealthy.
        bridge.clock.advance(bridge.config.vision.frame_stale_seconds)
        bridge.tick()
        assert camera.start_calls == 1 and bridge.monitor._camera is camera
        assert not bridge.controller.session.monitoring_healthy
        assert bridge.controller.session._failure_since == onset
        assert not bridge.controller.session.running
    finally:
        bridge.close()


@pytest.mark.parametrize('duration,needs_pin', [(14.9, False), (15., True)])
def test_capture_reopen_preserves_original_recovery_deadline(tmp_path, duration, needs_pin):
    bridge = make_workflow(tmp_path)
    try:
        make_ready(bridge).dispatch('exam.start', {})
        camera = fail_capture(bridge)
        frozen = bridge.controller.session.elapsed_seconds
        bridge.tick()
        bridge.clock.advance(duration)
        # Reopen alone does not recover: only new capture plus inference does.
        assert not bridge.controller.session.running
        camera._error = camera._error_at = None
        bridge.monitor.healthy = True
        bridge.monitor.publish()
        bridge.tick()
        assert bridge.controller.session.recovery_pin_required is needs_pin
        assert bridge.controller.session.running is not needs_pin
        assert bridge.controller.session.elapsed_seconds == frozen
    finally:
        bridge.close()


@pytest.mark.parametrize('blocker', ['setup', 'consent', 'stopped', 'alive', 'different_source',
                                    'selection_mismatch', 'switching', 'selection_error', 'healthy', 'ended'])
def test_reopen_cannot_bypass_source_or_lifecycle_guards(tmp_path, blocker):
    bridge = make_workflow(tmp_path)
    try:
        make_ready(bridge)
        if blocker != 'setup':
            bridge.dispatch('exam.start', {})
        camera = fail_capture(bridge)
        if blocker == 'consent': bridge.consent = False
        elif blocker == 'stopped': camera.stop(0)
        elif blocker == 'alive': camera.capture_running = True
        elif blocker == 'different_source': camera.device_id = 'other-camera'
        elif blocker == 'selection_mismatch': bridge.monitor.selected_camera_id = 'other-camera'
        elif blocker == 'switching': bridge.monitor._switching = True
        elif blocker == 'selection_error': bridge.monitor._selection_error = 'Injected error'
        elif blocker == 'healthy': bridge.controller.session.monitoring_recovered()
        elif blocker == 'ended': bridge.controller.end('test_finished')
        bridge._retry_selected_exam_camera()
        assert camera.start_calls == 0
    finally:
        bridge.close()


def test_reopened_qt_capture_receives_full_first_frame_grace(monkeypatch):
    """Exercise the actual Qt callback with fake native objects, no camera open."""
    import proctoring.vision.qt_camera as module
    import PySide6.QtMultimedia as multimedia
    clock = FakeClock(100.)
    camera = NamedCamera(VisionConfig(), clock, b'camera-a'.hex())
    camera._heartbeat = 80.  # Prior capture was disconnected for >10 seconds.
    camera._fail('Original disconnect')
    original_onset = camera.error_at
    callbacks = {}
    class Signal:
        def __init__(self, name): self.name = name
        def connect(self, callback, *_): callbacks[self.name] = callback
    class Timer:
        timeout = Signal('check')
        def start(self, *_): pass
        def stop(self): pass
    class Loop:
        ended = False
        def quit(self): self.ended = True
        def exec(self):
            clock.advance(.1)
            callbacks['check']()
            assert not self.ended  # Old heartbeat cannot kill new attempt.
            assert camera.error_at == original_onset
            clock.advance(10.)
            callbacks['check']()
            assert self.ended
    class Device:
        def id(self): return b'camera-a'
        def videoFormats(self): return []
    class NativeCamera:
        errorOccurred = Signal('error')
        def __init__(self, *_): pass
        def start(self): pass
        def stop(self): pass
    class CaptureSession:
        def setCamera(self, *_): pass
        def setVideoSink(self, *_): pass
    monkeypatch.setattr(module, 'QEventLoop', Loop)
    monkeypatch.setattr(module, 'QTimer', Timer)
    monkeypatch.setattr(multimedia, 'QMediaDevices', SimpleNamespace(videoInputs=lambda: [Device()]))
    monkeypatch.setattr(multimedia, 'QCamera', NativeCamera)
    monkeypatch.setattr(multimedia, 'QMediaCaptureSession', CaptureSession)
    monkeypatch.setattr(multimedia, 'QVideoSink', lambda: SimpleNamespace(videoFrameChanged=Signal('frame')))
    camera._run_qt()
    assert camera.error == 'Camera frames stopped; reconnect and retry camera'
    assert camera.error_at == original_onset
