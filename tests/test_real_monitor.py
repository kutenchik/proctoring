from dataclasses import replace
import threading
import time

import numpy as np

from proctoring.clock import SystemClock
from proctoring.domain import EventType
from proctoring.vision.camera import CapturedFrame
from proctoring.vision.monitor import RealMonitor
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import FaceMeasurement


def eventually(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.005)
    assert predicate()


class Camera:
    error = error_at = None
    fps = 30.
    alive = False
    def __init__(self, config, clock):
        self.clock = clock
        self.sequence = 0
        self.latest = None
    def refresh(self):
        self.sequence += 1
        self.latest = CapturedFrame(self.sequence, self.clock.monotonic(), np.zeros((8, 8, 3), dtype=np.uint8))
    def start(self): self.refresh()
    def stop(self, timeout=.5): pass


class Yolo:
    provider = "CPUExecutionProvider"
    input_width = input_height = 416
    def __init__(self, config): self.calls = 0
    def detect(self, image):
        self.calls += 1
        return (), ()
    def close(self): pass


class Face:
    def __init__(self, config): self.calls = 0
    def detect(self, image, timestamp):
        self.calls += 1
        return FaceMeasurement(False)
    def close(self): pass


def make_monitor(config=None, **kwargs):
    return RealMonitor(config or VisionConfig(), SystemClock(), camera_factory=kwargs.get("camera_factory", Camera),
                       yolo_factory=kwargs.get("yolo_factory", Yolo), face_factory=Face)


def test_new_combined_observation_only_once_and_no_face_is_healthy():
    monitor = make_monitor()
    try:
        monitor.start()
        eventually(lambda: monitor.available)
        sample = monitor.sample(monitor.clock.monotonic())
        assert sample is not None
        assert sample.timestamp == monitor._camera.latest.timestamp
        assert monitor.delivered_result.timestamp == sample.timestamp
        assert monitor.delivered_result.frame is monitor._camera.latest.image
        assert EventType.FACE_ABSENT in sample.conditions
        assert monitor.sample(monitor.clock.monotonic()) is None
        assert monitor.health(monitor.clock.monotonic()).healthy
        assert monitor.metrics["source_frame_size"] == (8, 8)
        assert monitor.metrics["requested_frame_size"] == (1280, 720)
    finally:
        monitor.stop()


def test_camera_stale_hides_cached_observation_and_is_monitoring_failure():
    monitor = make_monitor(replace(VisionConfig(), frame_stale_seconds=.05, result_stale_seconds=1.))
    try:
        monitor.start()
        eventually(lambda: monitor.available)
        time.sleep(.065)
        assert not monitor.available
        assert "Camera frames stale" in monitor.health(monitor.clock.monotonic()).reason
        assert monitor.sample(monitor.clock.monotonic()) is None
    finally:
        monitor.stop()


def test_face_updates_do_not_renew_old_yolo_evidence():
    monitor = make_monitor(replace(VisionConfig(), yolo_fps=1., face_fps=100.))
    try:
        monitor.start()
        eventually(lambda: monitor.available)
        original = monitor.sample(monitor.clock.monotonic())
        time.sleep(.02)
        monitor._camera.refresh()
        frame_timestamp = monitor._camera.latest.timestamp
        eventually(lambda: monitor.latest_face_timestamp == frame_timestamp)
        calibration_result = monitor.latest_calibration_result
        assert calibration_result.timestamp == frame_timestamp
        assert calibration_result.face is monitor.latest_face
        assert calibration_result.frame is None
        assert calibration_result.persons == () and calibration_result.phones == ()
        assert monitor.latest_result.timestamp == original.timestamp
        assert monitor.sample(monitor.clock.monotonic()) is None
    finally:
        monitor.stop()


def test_calibration_snapshot_uses_capture_time_without_refreshing_or_mixing_pairs():
    monitor = make_monitor()
    assert monitor.latest_calibration_result is None
    first_face = FaceMeasurement(True, features=(.5, .5, 0., 0.), quality=1.)
    with monitor._lock:
        monitor._latest_face, monitor._latest_face_timestamp = first_face, 10.
    first = monitor.latest_calibration_result
    assert first.timestamp == 10. and first.face is first_face
    assert monitor.latest_calibration_result.timestamp == 10.
    second_face = FaceMeasurement(True, features=(.5, .6, 0., 0.), quality=1.)
    with monitor._lock:
        monitor._latest_face, monitor._latest_face_timestamp = second_face, 11.
    assert first.timestamp == 10. and first.face is first_face
    assert monitor.latest_calibration_result.timestamp == 11.
    assert monitor.latest_calibration_result.face is second_face
    assert monitor.latest_result is None  # Face-only result is never exam evidence.


def test_camera_read_error_immediately_blocks_samples():
    monitor = make_monitor()
    try:
        monitor.start()
        eventually(lambda: monitor.available)
        monitor._camera.error = "Camera disconnected"
        monitor._camera.error_at = monitor.clock.monotonic()
        assert not monitor.available
        assert monitor.sample(monitor.clock.monotonic()) is None
    finally:
        monitor.stop()


def test_inference_exception_is_unhealthy_and_background_only():
    identities = []
    class BrokenYolo(Yolo):
        def detect(self, image):
            identities.append(threading.get_ident())
            raise RuntimeError("detector broke")
    monitor = make_monitor(yolo_factory=BrokenYolo)
    try:
        monitor.start()
        eventually(lambda: "detector broke" in monitor.health(monitor.clock.monotonic()).reason)
        assert not monitor.available
        assert monitor.latest_result is None
        assert identities[0] != threading.get_ident()
    finally:
        monitor.stop()


def test_result_staleness_independent_of_fresh_camera_frames():
    monitor = make_monitor(replace(VisionConfig(), yolo_fps=1., result_stale_seconds=.05, face_fps=100.))
    try:
        monitor.start()
        eventually(lambda: monitor.available)
        time.sleep(.065)
        monitor._camera.refresh()
        assert "Vision results stale" in monitor.health(monitor.clock.monotonic()).reason
        assert monitor.sample(monitor.clock.monotonic()) is None
    finally:
        monitor.stop()


def test_cleanly_stopped_monitor_can_start_with_new_camera():
    monitor = make_monitor()
    try:
        monitor.start()
        eventually(lambda: monitor.available)
        old_camera = monitor._camera
        monitor.stop()
        assert monitor.stopped
        monitor.start()
        eventually(lambda: monitor.available)
        assert monitor._camera is not old_camera
        assert monitor.sample(monitor.clock.monotonic()) is not None
        assert monitor.metrics["input_size"] == "416x416"
    finally:
        monitor.stop()


def test_inference_stall_expires_heartbeat_and_stop_remains_bounded():
    gate = threading.Event()
    entered = threading.Event()
    class SlowYolo(Yolo):
        def detect(self, image):
            entered.set()
            gate.wait(2)
            return (), ()
    monitor = make_monitor(replace(VisionConfig(), heartbeat_stale_seconds=.03), yolo_factory=SlowYolo)
    try:
        monitor.start()
        assert entered.wait(1)
        time.sleep(.04)
        assert not monitor.health(monitor.clock.monotonic()).healthy
        before = time.monotonic()
        monitor.stop(timeout=.01)
        assert time.monotonic() - before < .2
        assert monitor.stopped
    finally:
        gate.set()
        monitor.stop()


def test_start_refuses_to_duplicate_a_worker_still_stopping():
    import pytest
    gate = threading.Event()
    entered = threading.Event()
    class SlowYolo(Yolo):
        def detect(self, image):
            entered.set()
            gate.wait(2)
            return (), ()
    monitor = make_monitor(yolo_factory=SlowYolo)
    try:
        monitor.start()
        assert entered.wait(1)
        monitor.stop(timeout=.01)
        with pytest.raises(RuntimeError, match="still shutting down"):
            monitor.start()
    finally:
        gate.set()
        monitor.stop()


def test_ready_models_do_not_mask_missing_camera_with_initializing_message():
    class MissingCamera(Camera):
        error = "Webcam unavailable"
        def start(self): self.error_at = self.clock.monotonic()
    monitor = make_monitor(camera_factory=MissingCamera)
    try:
        monitor.start()
        eventually(lambda: monitor.health(monitor.clock.monotonic()).reason == "Webcam unavailable")
        assert not monitor.available
        assert monitor.latest_result is None
        assert monitor.sample(monitor.clock.monotonic()) is None
    finally:
        monitor.stop()


def test_reinitializing_models_does_not_clear_real_inference_failure():
    constructed = []
    class BrokenYolo(Yolo):
        def __init__(self, config):
            super().__init__(config)
            constructed.append(self)
        def detect(self, image): raise RuntimeError("detector broke")
    monitor = make_monitor(yolo_factory=BrokenYolo)
    try:
        monitor.start()
        eventually(lambda: "detector broke" in monitor.health(monitor.clock.monotonic()).reason)
        monitor._camera.latest = None
        eventually(lambda: len(constructed) >= 2)
        assert "detector broke" in monitor.health(monitor.clock.monotonic()).reason
        assert not monitor.available
    finally:
        monitor.stop()
