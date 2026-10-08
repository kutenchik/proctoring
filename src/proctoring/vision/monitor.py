"""Responsive real monitoring adapter; all device and inference work is off the UI."""
from collections import deque
from dataclasses import replace
import threading
import time
from typing import Callable

from ..clock import Clock
from ..domain import Observation
from .calibration import Calibration
from .accessories import AccessoryObservation, EarphoneHeuristicDetector
from .camera import LatestFrameCamera
from .health import assess_health
from .identity import IdentityObservation, IdentityVerifier, face_quality_reason
from .rules import build_result, to_observation
from .settings import VisionConfig
from .types import HealthStatus, VisionResult


class RealMonitor:
    """Latest-frame capture plus independently scheduled Face/YOLO inference.

    Face landmarks can run faster than YOLO, but an event observation is emitted
    only after a *new* YOLO execution and matching face measurement on that frame.
    Cached phone/person evidence therefore never receives a refreshed timestamp.
    A single inference worker bounds memory and avoids CPU oversubscription.
    """

    def __init__(self, config: VisionConfig, clock: Clock,
                 calibration: Calibration | None = None, *,
                 camera_factory: Callable | None = None,
                 yolo_factory: Callable | None = None,
                 face_factory: Callable | None = None):
        self.config = config
        self.clock = clock
        self.calibration = calibration if calibration is not None else Calibration(config)
        self._camera_factory = camera_factory or LatestFrameCamera
        self._yolo_factory = yolo_factory
        self._face_factory = face_factory
        self._camera = self._camera_factory(config, clock)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._heartbeat: float | None = None
        self._worker_error: str | None = None
        self._worker_error_at: float | None = None
        self._latest_result: VisionResult | None = None
        self._delivered_result: VisionResult | None = None
        self._latest_face = None
        self._latest_face_timestamp: float | None = None
        self._latest_face_frame = None
        self._published_sequence = 0
        self._delivered_sequence = 0
        self._yolo_latency_ms = 0.0
        self._face_latency_ms = 0.0
        self._provider = "initializing"
        self._input_size = "initializing"
        self._fixed_input = False
        self._times: deque[float] = deque(maxlen=30)
        self._identity_verifier: IdentityVerifier | None = None
        self._identity_requested = False
        self._identity_requested_after = float("-inf")
        self._identity_generation = 0
        self._identity_baseline = None
        self._identity_status = "Identity comparison disabled"
        self._identity_can_capture = False
        self._identity_reset_pending = False
        self._exam_active = False
        self._accessories = EarphoneHeuristicDetector(config.accessories)

    def configure_identity(self, config) -> None:
        """Configure before starting the camera; no extra thread or model."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Configure identity before starting the vision worker")
        verifier = (IdentityVerifier(threshold=config.impersonation_threshold,
                                     interval_seconds=config.periodic_check_interval_seconds)
                    if config.selfie_verification_enabled else None)
        with self._lock:
            self._identity_verifier = verifier
            self._identity_baseline = None
            self._identity_requested = False
            self._identity_can_capture = False
            self._identity_generation += 1
            self._identity_status = "Reference face not captured" if verifier else "Identity comparison disabled"

    @property
    def identity_baseline(self):
        with self._lock:
            return self._identity_baseline

    @property
    def identity_ready(self) -> bool:
        with self._lock:
            return self._identity_verifier is None or self._identity_baseline is not None

    @property
    def identity_status(self) -> str:
        with self._lock:
            return self._identity_status

    @property
    def identity_can_capture(self) -> bool:
        # All geometric checks have already run on the worker. The UI only
        # checks freshness and published readiness; it never performs fitting.
        now = self.clock.monotonic()
        with self._lock:
            return bool(self._identity_can_capture and not self._exam_active and not self.stopped
                        and self._camera.error is None
                        and self._worker_error is None and self._latest_face_timestamp is not None
                        and 0 <= now - self._latest_face_timestamp < self.config.frame_stale_seconds)

    def request_identity_baseline(self) -> bool:
        with self._lock:
            if self._identity_verifier is None or self._exam_active:
                return False
            self._identity_requested = True
            self._identity_requested_after = self.clock.monotonic()
            self._identity_baseline = None
            self._identity_generation += 1
            self._identity_status = "Waiting for a fresh reference face"
        return True

    def set_exam_active(self, active: bool) -> None:
        with self._lock:
            self._exam_active = bool(active)
            self._identity_reset_pending = True

    def _optional_observations(self, frame, measurement, timestamp):
        """Optional failures reduce that detector's availability, never health."""
        with self._lock:
            verifier = self._identity_verifier
            requested = self._identity_requested and timestamp >= self._identity_requested_after
            generation = self._identity_generation
            active = self._exam_active
            reset = self._identity_reset_pending
            self._identity_reset_pending = False
            if requested:
                self._identity_requested = False
        identity = IdentityObservation()
        can_capture = False
        if reset:
            self._accessories.reset()
        try:
            if verifier is not None:
                if reset:
                    verifier.reset_checks()
                reason = face_quality_reason(measurement)
                can_capture = reason is None
                if requested and not active:
                    baseline = verifier.capture_baseline(frame, measurement, timestamp)
                    with self._lock:
                        if generation == self._identity_generation and not self._exam_active:
                            self._identity_baseline = baseline
                    identity = IdentityObservation(status="Reference captured; shape consistency is not identity authentication")
                elif active:
                    identity = verifier.observe(measurement, timestamp)
                elif self.identity_baseline is not None:
                    identity = IdentityObservation(status="Reference captured; identity comparisons start with the exam")
                else:
                    identity = IdentityObservation(status=reason or "Ready to capture reference face")
        except Exception as error:
            if verifier is not None:
                verifier.reset_checks()
            # Never propagate optional processing faults into camera health.
            identity = IdentityObservation(status=(str(error) if isinstance(error, ValueError)
                                                   else "Identity comparison unavailable"))
        with self._lock:
            self._identity_status = identity.status
            self._identity_can_capture = can_capture
        accessory = AccessoryObservation()
        try:
            if active:
                accessory = self._accessories.observe(frame, measurement, timestamp)
            else:
                self._accessories.reset()
        except Exception:
            self._accessories.reset()
            accessory = AccessoryObservation(status="Ear-adjacent appearance check unavailable")
        return identity, accessory

    @property
    def available(self) -> bool:
        return self.health(self.clock.monotonic()).healthy

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def latest_result(self) -> VisionResult | None:
        with self._lock:
            return self._latest_result

    @property
    def delivered_result(self) -> VisionResult | None:
        """Exact frame/result consumed by the controller, for event evidence."""
        with self._lock:
            return self._delivered_result

    @property
    def latest_frame(self):
        captured = self._camera.latest
        return captured.image if captured is not None else None

    @property
    def latest_face(self):
        with self._lock:
            return self._latest_face

    @property
    def latest_face_timestamp(self):
        with self._lock:
            return self._latest_face_timestamp

    @property
    def latest_calibration_result(self) -> VisionResult | None:
        """Atomic face/timestamp pair at face cadence, without cached YOLO data.

        Use the capture time, not inference completion or UI delivery time, so
        the calibration interval can exclude older in-flight measurements.
        In debug mode, also retain its exact source frame for live eye inspection.
        This never publishes an exam observation or refreshes phone evidence.
        """
        with self._lock:
            if self._latest_face is None or self._latest_face_timestamp is None:
                return None
            face = self._latest_face
            return VisionResult(self._latest_face_timestamp, face_present=face.face_present,
                                face=face, head_pose=face.head_pose, frame=self._latest_face_frame,
                                face_latency_ms=self._face_latency_ms)

    @property
    def metrics(self) -> dict:
        health = self.health(self.clock.monotonic())
        captured = self._camera.latest
        frame_size = ((int(captured.image.shape[1]), int(captured.image.shape[0]))
                      if captured is not None else None)
        with self._lock:
            times = tuple(self._times)
            result = {"yolo_latency_ms": self._yolo_latency_ms,
                      "face_latency_ms": self._face_latency_ms,
                      "provider": self._provider, "input_size": self._input_size,
                      "model_fixed_input": self._fixed_input,
                      "configured_input_size": self.config.yolo_input_size}
        result.update({"capture_fps": self._camera.fps,
                       "monitoring_fps": ((len(times) - 1) / (times[-1] - times[0])
                                          if len(times) > 1 and times[-1] > times[0] else 0.0),
                       "error": None if health.healthy else health.reason,
                       "camera_backend": getattr(self._camera, "backend", "injected"),
                       "source_frame_size": frame_size,
                       "requested_frame_size": (self.config.capture_width, self.config.capture_height)})
        return result

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            if self.stopped:
                raise RuntimeError("Vision worker is still shutting down; wait before retrying")
            return
        if self.stopped:
            if getattr(self._camera, "alive", False):
                raise RuntimeError("Webcam driver is still shutting down; retry after it releases the camera")
            self._camera = self._camera_factory(self.config, self.clock)
            self._stop = threading.Event()
        with self._lock:
            self._started_at = self.clock.monotonic()
            self._heartbeat = self._started_at
            self._worker_error = "Initializing local vision models"
            self._worker_error_at = self._started_at
            self._latest_result = None
            self._delivered_result = None
            self._latest_face = None
            self._latest_face_timestamp = None
            self._latest_face_frame = None
            self._identity_can_capture = False
            self._identity_reset_pending = True
            self._times.clear()
            self._delivered_sequence = self._published_sequence
        self._camera.start()
        self._thread = threading.Thread(target=self._run, name="vision-inference", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = .5) -> None:
        self.set_exam_active(False)
        self._stop.set()
        self._camera.stop(timeout=0)
        thread = self._thread
        deadline = time.monotonic() + max(0.0, timeout)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        self._camera.stop(timeout=max(0.0, deadline - time.monotonic()))

    def health(self, now: float) -> HealthStatus:
        frame = self._camera.latest
        camera_error = self._camera.error
        with self._lock:
            error = self._worker_error or camera_error
            error_at = self._worker_error_at if self._worker_error else self._camera.error_at
            return assess_health(config=self.config, now=now, started_at=self._started_at,
                                 frame_at=frame.timestamp if frame is not None else None,
                                 result_at=self._latest_result.timestamp if self._latest_result else None,
                                 heartbeat_at=self._heartbeat, error=error, error_at=error_at,
                                 stopped=self.stopped)

    def sample(self, now: float) -> Observation | None:
        if not self.health(now).healthy:
            return None
        with self._lock:
            if self._delivered_sequence == self._published_sequence or self._latest_result is None:
                return None
            result = self._latest_result
            if self._worker_error or now - result.timestamp >= self.config.result_stale_seconds:
                return None
            self._delivered_sequence = self._published_sequence
            self._delivered_result = result
        return to_observation(result)

    def _fail(self, error: Exception) -> None:
        with self._lock:
            if self._worker_error is None:
                self._worker_error_at = self.clock.monotonic()
            self._worker_error = f"Vision inference failed: {error}"
            self._identity_can_capture = False
            self._identity_reset_pending = True
        self._accessories.reset()

    @staticmethod
    def _close(detector) -> None:
        if detector is not None and hasattr(detector, "close"):
            try:
                detector.close()
            except Exception:
                pass

    def _run(self) -> None:
        yolo = face = None
        try:
            from .yolo import YoloDetector
            from .face import FaceAnalyzer
            yolo_factory = self._yolo_factory or YoloDetector
            face_factory = self._face_factory or FaceAnalyzer
            last_face_sequence = last_yolo_sequence = -1
            next_yolo_at = next_face_at = float("-inf")
            cached_face = None
            optional_identity = IdentityObservation()
            optional_accessory = AccessoryObservation()
            while not self._stop.is_set():
                now = self.clock.monotonic()
                with self._lock:
                    self._heartbeat = now
                try:
                    if yolo is None:
                        yolo = yolo_factory(self.config)
                        with self._lock:
                            self._provider = getattr(yolo, "provider", "injected")
                            self._input_size = f"{getattr(yolo, 'input_width', '?')}x{getattr(yolo, 'input_height', '?')}"
                            self._fixed_input = getattr(yolo, "fixed_input", False)
                    if face is None:
                        face = face_factory(self.config)
                    with self._lock:
                        self._heartbeat = self.clock.monotonic()
                        # Models being ready is distinct from a usable camera. Do
                        # not let the startup message hide device errors forever.
                        # Genuine inference failures clear only after a new result.
                        if self._worker_error == "Initializing local vision models":
                            self._worker_error = None
                            self._worker_error_at = None
                    captured = self._camera.latest
                    if (captured is None or self._camera.error is not None
                            or now - captured.timestamp >= self.config.frame_stale_seconds):
                        with self._lock:
                            self._identity_can_capture = False
                            self._identity_reset_pending = True
                        self._accessories.reset()
                        self._stop.wait(.02)
                        continue
                    run_yolo = now >= next_yolo_at and captured.sequence != last_yolo_sequence
                    run_face = ((now >= next_face_at or run_yolo)
                                and captured.sequence != last_face_sequence)
                    if run_face:
                        began = time.perf_counter()
                        cached_face = face.detect(captured.image, captured.timestamp)
                        face_ms = (time.perf_counter() - began) * 1000
                        optional_identity, optional_accessory = self._optional_observations(
                            captured.image, cached_face, captured.timestamp)
                        last_face_sequence = captured.sequence
                        next_face_at = self.clock.monotonic() + 1 / self.config.face_fps
                        with self._lock:
                            self._latest_face = cached_face
                            self._latest_face_timestamp = captured.timestamp
                            self._latest_face_frame = captured.image if self.config.calibration_debug else None
                            self._face_latency_ms = face_ms
                            self._heartbeat = self.clock.monotonic()
                    if run_yolo and cached_face is not None:
                        began = time.perf_counter()
                        persons, phones = yolo.detect(captured.image)
                        yolo_ms = (time.perf_counter() - began) * 1000
                        last_yolo_sequence = captured.sequence
                        completed_at = self.clock.monotonic()
                        next_yolo_at = completed_at + 1 / self.config.yolo_fps
                        # Result timestamp is the captured frame's time, never completion time.
                        result = build_result(captured.timestamp, persons, phones, cached_face,
                                              self.calibration, self.config, frame=captured.image,
                                              yolo_latency_ms=yolo_ms, face_latency_ms=self._face_latency_ms)
                        result = replace(result, identity_suspected=optional_identity.suspected,
                                         identity_distance=optional_identity.distance,
                                         identity_status=optional_identity.status,
                                         earphone_suspected=optional_accessory.suspected,
                                         earphone_status=optional_accessory.status)
                        with self._lock:
                            self._latest_result = result
                            self._published_sequence += 1
                            self._yolo_latency_ms = yolo_ms
                            self._provider = getattr(yolo, "provider", self._provider)
                            self._times.append(completed_at)
                            self._heartbeat = completed_at
                            self._worker_error = None
                            self._worker_error_at = None
                    self._stop.wait(.005)
                except Exception as error:
                    self._fail(error)
                    self._close(face)
                    self._close(yolo)
                    face = yolo = None
                    cached_face = None
                    last_face_sequence = last_yolo_sequence = -1
                    # Retry local resources after a recoverable exception without busy looping.
                    self._stop.wait(.5)
        except Exception as error:
            self._fail(error)
        finally:
            self._close(face)
            self._close(yolo)
