"""Capture consent, source fidelity, and old-camera publication boundaries."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import threading
import time

import numpy as np
import pytest

from proctoring.clock import SystemClock
from proctoring.vision.camera import CapturedFrame
from proctoring.vision.monitor import RealMonitor
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import FaceMeasurement


class Camera:
    error = error_at = None
    fps = 30.
    alive = False

    def __init__(self, config, clock, device_id=None):
        self.clock, self.device_id = clock, device_id
        self.started = False
        self.latest = None

    def start(self):
        self.started = self.alive = True
        self.refresh()

    def refresh(self):
        sequence = self.latest.sequence + 1 if self.latest else 1
        pixels = np.full((4, 4, 3), 99 if self.device_id == 'selected-camera' else 1, np.uint8)
        self.latest = CapturedFrame(sequence, self.clock.monotonic(), pixels)

    def stop(self, timeout=0):
        self.alive = False
        self.latest = None


class Face:
    def __init__(self, config): pass
    def detect(self, image, timestamp): return FaceMeasurement(False)


class Yolo:
    def __init__(self, config): pass
    def detect(self, image): return (), ()


def eventually(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.005)
    assert predicate()


def monitor(**kwargs):
    return RealMonitor(replace(VisionConfig(), face_fps=100., yolo_fps=100.), SystemClock(),
                       camera_factory=Camera, yolo_factory=kwargs.get('yolo_factory', Yolo),
                       face_factory=kwargs.get('face_factory', Face))


def test_selection_before_consent_configures_without_opening_and_later_uses_exact_source(monkeypatch):
    monkeypatch.setattr('proctoring.vision.qt_camera.NamedCamera', Camera)
    source = monitor()
    try:
        assert source.select_camera('selected-camera', activate=False)
        source._switch_thread.join(2)
        assert source.selected_camera_id == 'selected-camera'
        assert not source._camera.started
        assert source.latest_frame is None
        assert source.stopped

        # This is the explicit consent/preview activation path. It uses the
        # same exact source for preview, future identity, calibration and exam.
        source.start()
        eventually(lambda: source.latest_result is not None)
        assert source._camera.device_id == 'selected-camera'
        assert np.all(source.latest_frame == 99)
        assert np.all(source.latest_result.frame == 99)
        assert source.latest_face_timestamp == source.latest_result.timestamp
        current = source._camera
        source.calibration.reset = Mock()
        assert not source.select_camera('selected-camera', activate=True)
        assert source._camera is current and current.alive
        source.calibration.reset.assert_not_called()
    finally:
        source.stop()


def test_identity_capture_from_previous_camera_cannot_finish_after_selection(monkeypatch):
    entered, complete = threading.Event(), threading.Event()
    source = monitor()
    monkeypatch.setattr('proctoring.vision.monitor.face_quality_reason', lambda _: None)

    class Verifier:
        baseline = None
        def capture_baseline(self, *args):
            entered.set()
            assert complete.wait(2)
            self.baseline = 'old-camera-photo'
            return self.baseline
        def reset_checks(self): pass

    source._identity_verifier = verifier = Verifier()
    source._identity_baseline = 'previous-photo'
    source._latest_result = source._latest_face = 'old'
    assert source.request_identity_baseline()
    generation = source._identity_generation
    source._thread = threading.Thread(target=lambda: source._optional_observations(
        object(), object(), source.clock.monotonic()))
    source._thread.start()
    assert entered.wait(2)
    try:
        assert source.select_camera('selected-camera', activate=False)
        assert source._identity_generation > generation
        assert source.identity_baseline is None and not source.identity_ready
        assert source.latest_result is None and source.latest_face is None
        assert not source.request_identity_baseline()
        complete.set()
        source._switch_thread.join(2)
        assert not source._switch_thread.is_alive()
        assert source.identity_baseline is None
        assert verifier.baseline is None
        assert source.identity_status == 'Reference face not captured'
        assert not source.identity_can_capture
    finally:
        complete.set()
        source.stop()


@pytest.mark.parametrize('detector', ['face', 'yolo'])
def test_inflight_old_camera_inference_cannot_republish_during_handoff(detector):
    entered, complete = threading.Event(), threading.Event()

    class SlowFace(Face):
        def detect(self, *args):
            entered.set()
            assert complete.wait(2)
            return super().detect(*args)

    class SlowYolo(Yolo):
        def detect(self, *args):
            entered.set()
            assert complete.wait(2)
            return super().detect(*args)

    source = monitor(face_factory=SlowFace if detector == 'face' else Face,
                     yolo_factory=SlowYolo if detector == 'yolo' else Yolo)
    try:
        source.start()
        assert entered.wait(2)
        assert source.select_camera('selected-camera', activate=False)
        complete.set()
        source._switch_thread.join(2)
        assert not source._switch_thread.is_alive()
        assert source.latest_result is None
        assert source.latest_face is None
        assert source.latest_calibration_result is None
    finally:
        complete.set()
        source.stop()


def test_missing_selected_camera_immediately_clears_reference_and_gaze_state():
    source = monitor()
    source.calibration.reset = Mock()
    source._identity_verifier = SimpleNamespace(baseline='old-reference')
    source._identity_baseline = 'old-reference'
    source._identity_requested = True
    source._latest_result = source._latest_face = 'old-result'
    generation = source._identity_generation
    source.unavailable_selection()
    assert source.identity_baseline is None and not source.identity_ready
    assert not source._identity_requested
    assert source._identity_generation > generation
    assert source.latest_result is None and source.latest_face is None
    source.calibration.reset.assert_called_once()
    assert not source.request_identity_baseline()


def test_reselecting_configured_inactive_camera_keeps_calibration_and_does_not_open(monkeypatch):
    source = monitor()
    source.select_camera('selected-camera', activate=False)
    source._switch_thread.join(2)
    source.calibration.reset = Mock()
    start = Mock()
    monkeypatch.setattr(source, 'start', start)
    assert not source.select_camera('selected-camera', activate=False)
    source.calibration.reset.assert_not_called()
    start.assert_not_called()
