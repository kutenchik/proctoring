from dataclasses import replace
import threading
import time
from types import SimpleNamespace

import numpy as np

from proctoring.clock import SystemClock
from proctoring.vision.camera import CapturedFrame
from proctoring.vision.identity import IdentityVerifier
from proctoring.vision.monitor import RealMonitor
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import Box, FaceMeasurement, HeadPose


class Camera:
    error = error_at = None
    fps = 30.
    alive = False

    def __init__(self, config, clock):
        self.clock, self.sequence, self.latest = clock, 0, None

    def refresh(self):
        self.sequence += 1
        self.latest = CapturedFrame(self.sequence, self.clock.monotonic(), np.zeros((480, 640, 3), np.uint8))

    def start(self): self.refresh()
    def stop(self, timeout=0): pass


class Face:
    seed = 8
    def __init__(self, config): pass

    def detect(self, image, timestamp):
        points = tuple(map(tuple, np.random.default_rng(self.seed).normal(size=(18, 3)) * 40 + [320, 240, 0]))
        return FaceMeasurement(True, box=Box(.3, .2, .7, .8), head_pose=HeadPose(),
                               frame_size=(640, 480), detected_face_count=1, identity_points=points)

    def close(self): pass


class Yolo:
    def __init__(self, config): pass
    def detect(self, image): return (), ()
    def close(self): pass


def eventually(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.005)
    assert predicate()


def make_monitor():
    monitor = RealMonitor(replace(VisionConfig(), face_fps=100., yolo_fps=100.), SystemClock(),
                          camera_factory=Camera, yolo_factory=Yolo, face_factory=Face)
    monitor.configure_identity(SimpleNamespace(selfie_verification_enabled=True,
                                               impersonation_threshold=.4,
                                               periodic_check_interval_seconds=30.))
    return monitor


def test_reference_capture_runs_on_worker_with_matching_fresh_frame(monkeypatch):
    calls = []
    original = IdentityVerifier.capture_baseline

    def capture(self, image, face, timestamp):
        calls.append((threading.get_ident(), image, timestamp))
        return original(self, image, face, timestamp)

    monkeypatch.setattr(IdentityVerifier, "capture_baseline", capture)
    monitor = make_monitor()
    try:
        assert not monitor.identity_ready
        assert not monitor.identity_can_capture
        monitor.start()
        eventually(lambda: monitor.identity_can_capture)
        assert monitor.identity_baseline is None
        assert monitor.request_identity_baseline()
        time.sleep(.02)
        assert monitor.identity_baseline is None  # Same captured frame is not reused.
        monitor._camera.refresh()
        paired = monitor._camera.latest
        eventually(lambda: monitor.identity_ready)
        assert calls[0][0] != threading.get_ident()
        assert calls[0][1] is paired.image
        assert calls[0][2] == paired.timestamp
        assert monitor.identity_baseline.timestamp == paired.timestamp
        assert monitor.available
        monitor.set_exam_active(True)
        assert not monitor.request_identity_baseline()  # Cannot replace session reference during an exam.
        assert not monitor.identity_can_capture
        time.sleep(.02)  # Windows monotonic clock may have a ~15 ms tick.
        monitor._camera.refresh()
        eventually(lambda: monitor.latest_result.timestamp == monitor._camera.latest.timestamp)
        assert not monitor.latest_result.identity_suspected
        assert monitor.latest_result.identity_distance < 1e-10
    finally:
        monitor.stop()


def test_optional_baseline_exception_does_not_fail_camera_monitoring(monkeypatch):
    def broken(*args): raise RuntimeError("optional encoding failure")
    monkeypatch.setattr(IdentityVerifier, "capture_baseline", broken)
    monitor = make_monitor()
    try:
        monitor.start()
        eventually(lambda: monitor.available)
        monitor.request_identity_baseline()
        monitor._camera.refresh()
        eventually(lambda: monitor.identity_status == "Identity comparison unavailable")
        assert monitor.available
        assert not monitor.identity_ready
        assert not monitor.latest_result.identity_suspected
    finally:
        monitor.stop()


def test_camera_error_disables_identity_capture_and_disabled_identity_uses_no_baseline():
    monitor = make_monitor()
    try:
        monitor.start()
        eventually(lambda: monitor.identity_can_capture)
        monitor._camera.error = "camera disconnected"
        assert not monitor.identity_can_capture
    finally:
        monitor.stop()
    disabled = RealMonitor(VisionConfig(), SystemClock(), camera_factory=Camera,
                           yolo_factory=Yolo, face_factory=Face)
    assert disabled.identity_ready
    assert not disabled.request_identity_baseline()
    assert disabled.identity_baseline is None


def test_identity_mismatch_streak_does_not_span_camera_outage_or_worker_restart(monkeypatch):
    monitor = make_monitor()
    monitor._identity_verifier.interval_seconds = .001

    def fresh():
        time.sleep(.025)
        monitor._camera.refresh()
        at = monitor._camera.latest.timestamp
        eventually(lambda: monitor.latest_result is not None and monitor.latest_result.timestamp == at)
        return monitor.latest_result

    try:
        monitor.start()
        eventually(lambda: monitor.identity_can_capture)
        monitor.request_identity_baseline()
        fresh()
        eventually(lambda: monitor.identity_ready)
        monitor.set_exam_active(True)
        monkeypatch.setattr(Face, "seed", 81)
        for _ in range(4): result = fresh()
        assert result.identity_suspected
        monitor._camera.error = "Camera disconnected"
        eventually(lambda: monitor._identity_reset_pending)
        assert not monitor.available
        monitor._camera.error = None
        assert not fresh().identity_suspected
        for _ in range(3): result = fresh()
        assert result.identity_suspected
        monitor.stop()
        monitor.start()
        monitor.set_exam_active(True)
        eventually(lambda: monitor.available)
        assert not fresh().identity_suspected
    finally:
        monitor.stop()


def test_inference_failure_marks_optional_continuity_for_reset():
    monitor = make_monitor()
    monitor._identity_reset_pending = False
    monitor._identity_can_capture = True
    monitor._accessories._count = 5
    monitor._fail(RuntimeError("inference failed"))
    assert monitor._identity_reset_pending
    assert not monitor._identity_can_capture
    assert monitor._accessories._count == 0
