"""One webcam, a one-frame buffer, and bounded non-blocking lifecycle calls."""
from collections import deque
from dataclasses import dataclass
import platform
import threading
from typing import Any, Callable

from ..clock import Clock
from .settings import VisionConfig


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    timestamp: float
    image: Any


class LatestFrameCamera:
    """Capture owns the device; consumers can never build a frame backlog.

    The daemon thread owns open/read/release, because even opening a Windows
    camera can stall in its driver. ``stop`` waits at most the supplied timeout;
    it never calls a potentially blocking native release from the UI thread.
    """

    def __init__(self, config: VisionConfig, clock: Clock,
                 capture_factory: Callable | None = None, retry_seconds: float = .5):
        self.config = config
        self.clock = clock
        self._factory = capture_factory
        self._retry_seconds = retry_seconds
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: CapturedFrame | None = None
        self._sequence = 0
        self._times: deque[float] = deque(maxlen=60)
        self._error: str | None = "Camera has not started"
        self._error_at: float | None = None
        self._heartbeat: float | None = None
        self._backend = "unopened"

    @property
    def latest(self) -> CapturedFrame | None:
        with self._lock:
            return self._latest

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    @property
    def error_at(self) -> float | None:
        with self._lock:
            return self._error_at

    @property
    def heartbeat(self) -> float | None:
        with self._lock:
            return self._heartbeat

    @property
    def fps(self) -> float:
        with self._lock:
            times = tuple(self._times)
        return (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if self._stop.is_set():
            raise RuntimeError("A stopped camera cannot be restarted; create a new session")
        self._fail("Opening webcam")
        self._thread = threading.Thread(target=self._run, name="webcam-capture", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = .5) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def _fail(self, reason: str) -> None:
        with self._lock:
            if self._error is None or self._error_at is None:
                self._error_at = self.clock.monotonic()
            self._error = reason

    def _backends(self, cv2) -> list[tuple[str, int]]:
        name = self.config.camera_backend.lower()
        mapping = {"msmf": cv2.CAP_MSMF, "dshow": cv2.CAP_DSHOW, "any": cv2.CAP_ANY}
        if name != "auto":
            if name not in mapping:
                raise ValueError(f"Unsupported camera backend: {name}")
            return [(name, mapping[name])]
        if platform.system() == "Windows":
            return [("msmf", cv2.CAP_MSMF), ("dshow", cv2.CAP_DSHOW), ("any", cv2.CAP_ANY)]
        return [("any", cv2.CAP_ANY)]

    def _run(self) -> None:
        try:
            import cv2
            factory = self._factory or cv2.VideoCapture
            backends = self._backends(cv2)
        except Exception as error:
            self._fail(f"Camera initialization failed: {error}")
            return
        backend_index = 0
        while not self._stop.is_set():
            capture = None
            try:
                backend_name, backend_id = backends[backend_index % len(backends)]
                backend_index += 1
                with self._lock:
                    self._heartbeat = self.clock.monotonic()
                capture = factory(self.config.camera_index, backend_id)
                if not capture.isOpened():
                    raise RuntimeError(f"Cannot open webcam {self.config.camera_index} ({backend_name})")
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.capture_width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.capture_height)
                capture.set(cv2.CAP_PROP_FPS, self.config.capture_fps)
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Advisory; backend support varies.
                self._backend = backend_name
                while not self._stop.is_set():
                    with self._lock:
                        self._heartbeat = self.clock.monotonic()
                    ok, frame = capture.read()
                    if not ok or frame is None or getattr(frame, "size", 0) == 0:
                        raise RuntimeError("Webcam disconnected or returned an empty frame")
                    if len(frame.shape) != 3 or frame.shape[2] != 3:
                        raise RuntimeError("Webcam did not return a three-channel BGR frame")
                    timestamp = self.clock.monotonic()
                    # Copy once: OpenCV drivers may reuse their own capture memory.
                    owned_frame = frame.copy()
                    with self._lock:
                        self._sequence += 1
                        self._latest = CapturedFrame(self._sequence, timestamp, owned_frame)
                        self._times.append(timestamp)
                        self._heartbeat = timestamp
                        self._error = None
                        self._error_at = None
            except Exception as error:
                self._fail(str(error))
            finally:
                if capture is not None:
                    try:
                        capture.release()
                    except Exception:
                        pass
            self._stop.wait(self._retry_seconds)
