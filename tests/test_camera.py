import threading
import time

import numpy as np

from proctoring.clock import SystemClock
from proctoring.vision.camera import LatestFrameCamera
from proctoring.vision.settings import VisionConfig


def eventually(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    assert predicate()


class Capture:
    def __init__(self, gate=None):
        self.count = 0
        self.released = False
        self.gate = gate
        self.settings = {}

    def isOpened(self): return True
    def set(self, key, value): self.settings[key] = value
    def read(self):
        if self.gate is not None:
            self.gate.wait(2)
        time.sleep(.003)
        self.count += 1
        return True, np.full((4, 6, 3), self.count % 255, dtype=np.uint8)
    def release(self): self.released = True


def test_camera_keeps_only_latest_frame_and_capture_owned_copy():
    capture = Capture()
    camera = LatestFrameCamera(VisionConfig(camera_backend="any"), SystemClock(),
                               capture_factory=lambda *args: capture)
    try:
        camera.start()
        eventually(lambda: camera.latest is not None and camera.latest.sequence >= 5)
        first = camera.latest
        eventually(lambda: camera.latest.sequence > first.sequence)
        assert camera.latest is not first
        # Windows monotonic resolution can be coarser than this fake camera's 3 ms reads.
        assert camera.latest.timestamp >= first.timestamp
        assert first.image[0, 0, 0] == first.sequence % 255
        assert camera.fps > 0
        assert camera.error is None
    finally:
        camera.stop()
    assert capture.released


def test_camera_read_failure_is_explicit_and_reconnects():
    class Disconnect(Capture):
        def read(self): return False, None
    broken = Disconnect()
    working = Capture()
    calls = []
    def factory(*args):
        calls.append(args)
        return broken if len(calls) == 1 else working
    camera = LatestFrameCamera(VisionConfig(camera_backend="any"), SystemClock(),
                               capture_factory=factory, retry_seconds=.05)
    try:
        camera.start()
        eventually(lambda: camera.error is not None and "disconnected" in camera.error)
        assert camera.error_at is not None
        eventually(lambda: camera.latest is not None and camera.error is None)
        assert len(calls) == 2
        assert broken.released
    finally:
        camera.stop()


def test_stop_is_bounded_when_native_read_stalls():
    gate = threading.Event()
    capture = Capture(gate)
    camera = LatestFrameCamera(VisionConfig(camera_backend="any"), SystemClock(),
                               capture_factory=lambda *args: capture)
    camera.start()
    eventually(lambda: bool(capture.settings))
    before = time.monotonic()
    camera.stop(timeout=.01)
    assert time.monotonic() - before < .2
    assert camera.stopped
    gate.set()
    eventually(lambda: capture.released)


def test_camera_open_runs_off_caller_thread():
    caller_thread = threading.get_ident()
    identities = []
    capture = Capture()
    def factory(*args):
        identities.append(threading.get_ident())
        return capture
    camera = LatestFrameCamera(VisionConfig(camera_backend="any"), SystemClock(), capture_factory=factory)
    try:
        camera.start()
        eventually(lambda: bool(identities))
        assert identities[0] != caller_thread
    finally:
        camera.stop()
