"""Application orchestration; CV/UI remain replaceable adapters."""
from collections import Counter
import logging
import math
import platform
from uuid import uuid4

from .clock import Clock, SystemClock
from .config import AppConfig
from .domain import EventType, Observation
from .events import EventEngine
from .exam import Quiz
from .security import EmergencyRelease, PinVerifier
from .session import SessionController
from .storage import SessionStore
from .vision.synthetic import SyntheticMonitor


class AppController:
    def __init__(self, config: AppConfig, clock: Clock | None = None,
                 mode: str = "synthetic", monitor=None, protection=None):
        if mode not in ("synthetic", "camera"):
            raise ValueError("mode must be synthetic or camera")
        self.mode = mode
        self.config = config
        self.clock = clock or SystemClock()
        self.observation_stale_seconds = config.vision.result_stale_seconds if mode == "camera" else config.stale_seconds
        self.quiz = Quiz.from_file(config.quiz_path)
        self.session = SessionController(self.clock, config.duration_seconds, config.recovery_seconds)
        thresholds = dict(config.thresholds)
        # Optional vision workers already require four identity comparisons / five
        # accessory frames. One subsequent fresh observation confirms activation.
        if config.identity.selfie_verification_enabled:
            thresholds[EventType.IMPERSONATION_SUSPECTED] = .001
        if config.vision.accessories.earphone_detection_enabled:
            thresholds[EventType.EARPHONE_SUSPECTED] = .001
        self.events = EventEngine(thresholds, config.clearing_seconds, self.clock,
                                  max_observation_gap=self.observation_stale_seconds)
        if monitor is not None:
            self.monitor = monitor
        elif mode == "camera":
            from .vision.monitor import RealMonitor
            self.monitor = RealMonitor(config.vision, self.clock)
        else:
            self.monitor = SyntheticMonitor()
        if protection is None:
            from .security import create_protection
            protection = create_protection(config.protection)
        self.protection = protection
        self.emergency = EmergencyRelease(self.protection)
        self.pin = PinVerifier(config.proctor_pin)
        self.store: SessionStore | None = None
        self.summary: dict | None = None
        self.storage_error: str | None = None
        self.connected_attempt: dict | None = None
        self._record_cursor = 0
        self._last_sample: float | None = None
        self._recovery_sample_after = float("-inf")
        self._snapshots: dict[str, str] = {}
        self.snapshot_errors: list[str] = []
        self.security_events: list[dict] = []
        self._security_event_ids: set[str] = set()
        self._protection_started = False
        self._pending_remote_alerts: dict[str, dict] = {}
        self._event_metadata: dict[str, dict] = {}
        self._baseline_saved = None
        self._identity_save_error = ""
        self._system_metadata = None
        self._optional_status = {}
        self._device_info = {}
        self._optional_closed = False
        self.device_selection_ready = True
        self._camera_preview_allowed = False
        self._report_job = None
        self.audio = None
        self.audio_events = None
        self._last_audio_sample = None
        self._audio_exam_started_at = None
        self._audio_check_metadata = {}
        self.system_checker = None
        if any(vars(config.system_checks).values()):
            from .security.system_checks import SystemIntegrityChecker
            self.system_checker = SystemIntegrityChecker(config.system_checks)
            self.system_checker.start_vm_check()
        if config.identity.selfie_verification_enabled and self.mode == "camera":
            self.monitor.configure_identity(config.identity)
        if config.audio.enabled:
            from .audio.monitor import AudioMonitor
            self.audio = AudioMonitor(config.audio, self.clock)
            self.audio_events = EventEngine({EventType.VOICE_DETECTED: config.audio.voice_duration_threshold},
                                           config.clearing_seconds, self.clock, max_observation_gap=.5,
                                           accumulate_sample_durations=True)
        self.remote = None
        if config.remote.enabled:
            from .storage.remote_dispatcher import RemoteDispatcher
            self.remote = RemoteDispatcher(config.remote)

    @property
    def candidate_info(self) -> dict | None:
        return self.session.candidate.as_dict() if self.session.candidate is not None else None

    @property
    def registration_complete(self) -> bool:
        return ((not self.config.registration.enabled or self.session.candidate is not None)
                and self.identity_ready)

    def register_candidate(self, info: dict) -> None:
        if not self.session.started and self.store is not None and info != self.candidate_info:
            raise RuntimeError("Candidate identity is fixed after saving the reference photo")
        self.session.set_candidate(info, require_group=self.config.registration.require_group)

    @property
    def identity_ready(self) -> bool:
        return (not self.config.identity.selfie_verification_enabled
                or (self._baseline_saved is not None and self.store is not None
                    and not self._identity_save_error
                    and getattr(self.monitor, "identity_baseline", None) is self._baseline_saved
                    and bool(getattr(self.monitor, "identity_ready", False))))

    @property
    def identity_status(self) -> str:
        if not self.config.identity.selfie_verification_enabled:
            return "Identity comparison disabled"
        if self.mode != "camera":
            return "Selfie verification requires camera mode"
        return self._identity_save_error or self.monitor.identity_status

    @property
    def identity_can_capture(self) -> bool:
        return bool(self.mode == "camera" and self.config.identity.selfie_verification_enabled
                    and not self.session.started and getattr(self.monitor, "identity_can_capture", False))

    def prepare_identity(self, info: dict) -> None:
        if self.mode != "camera" or not self.config.identity.selfie_verification_enabled:
            raise RuntimeError("Selfie verification requires camera mode")
        if self.session.started:
            raise RuntimeError("Exam already started")
        self.register_candidate(info)
        self.prepare_camera_preview()

    def prepare_camera_preview(self) -> None:
        """Explicit camera activation before registration, without saving a photo."""
        if self.mode != "camera" or self.session.started:
            raise RuntimeError("Camera testing is available before the exam")
        if not self.device_selection_ready:
            raise RuntimeError("Wait for device selection to finish")
        self._camera_preview_allowed = True
        self.monitor.start()

    def select_camera(self, device_id) -> bool:
        if self.session.started:
            return False
        previous = getattr(self.monitor, "selected_camera_id", None)
        changed = self.monitor.select_camera(device_id, activate=self._camera_preview_allowed)
        if changed and previous != device_id:
            self._invalidate_camera_reference()
        return changed

    def camera_unavailable(self) -> None:
        if not self.session.started:
            self.monitor.unavailable_selection()
            self._invalidate_camera_reference()

    def _invalidate_camera_reference(self) -> None:
        self._baseline_saved = None
        self._identity_save_error = ""
        # Keep the local file as historical data; it cannot authorize an exam.
        if self.store is not None:
            try:
                self.store.update_metadata({"reference_face": None, "identity_reference": None,
                                            "identity_reference_invalidated": "camera_changed"})
            except OSError as error:
                self.storage_error = str(error)
                self._identity_save_error = "Reference invalidated; local metadata could not be updated"

    def capture_identity_baseline(self) -> None:
        if not self.identity_can_capture or (self.config.registration.enabled and self.session.candidate is None):
            raise RuntimeError("A fresh, single, frontal face is required for the baseline photo")
        self._identity_save_error = ""
        self.monitor.request_identity_baseline()

    def preflight_status(self) -> dict:
        if self.system_checker is None:
            return {"ready": True, "screen_count": None, "reason": "", "vm": {"status": "disabled"}}
        return self.system_checker.status()

    @property
    def audio_status(self) -> str:
        status = self.audio.status if self.audio is not None else {"state": "disabled"}
        message = "Audio: " + status["state"]
        # Only the worker's controlled operational guidance belongs in the UI;
        # device exception details remain in the local availability record.
        if status["state"] in {"calibrating", "available"} and status.get("reason"):
            message += "\n" + status["reason"]
        return message

    def prepare_audio_check(self) -> None:
        """Open the one audio worker on setup, once registration is complete."""
        if (self.audio is not None and self.registration_complete
                and self.device_selection_ready and not self.session.started and not self._optional_closed):
            # Unavailable input is retried only through the explicit Calibrate
            # button, not on every Qt refresh.
            if self.audio.status["state"] == "not_started":
                self.audio.start()

    def _audio_check_snapshot(self) -> dict:
        if self.audio is None:
            return {}
        check = getattr(self.audio, "check_status", {})
        return {"adaptive_calibration": self.config.audio.adaptive_calibration,
                "units": check.get('units', 'normalized_rms'), **{key: check[key] for key in (
                    "state", "ambient", "recommended_threshold", "threshold", "sensitivity",
                    "threshold_source", "committed_threshold", "committed_ambient",
                    "committed_recommended_threshold", 'gain', 'device_key', 'stream_format',
                    'speech_rms_raw', 'ambient_rms_raw', 'calibration_peak_raw') if key in check}}

    def audio_debug_status(self) -> dict:
        """Small numerical view of the existing worker/engine; no media or secrets."""
        audio = self.audio
        check = getattr(audio, 'check_status', {}) if audio is not None else {}
        timestamp = check.get('timestamp')
        thread = getattr(audio, '_thread', None)
        engine = self.audio_events
        return {
            'config_path': str(self.config.source_path) if self.config.source_path else None,
            'audio_enabled': self.config.audio.enabled,
            'session_state': ('ended' if self.session.ended else 'setup' if not self.session.started
                              else 'running' if self.session.running else 'paused'),
            'selected_microphone': getattr(getattr(audio, 'selection', None), 'label', 'system-default'),
            'resolved_microphone': check.get('resolved_device'),
            'stream_format': check.get('stream_format', {}),
            'worker_running': bool(thread is not None and thread.is_alive()),
            'buffer_age_seconds': None if timestamp is None else max(0., self.clock.monotonic()-timestamp),
            'gain': check.get('gain'), 'applied_gain': check.get('applied_gain'),
            'processed_rms': check.get('rms'), 'threshold': check.get('committed_threshold'),
            'threshold_source': check.get('threshold_source'),
            'candidate_duration_seconds': engine.candidate_duration(EventType.VOICE_DETECTED) if engine else 0.,
            'required_duration_seconds': self.config.audio.voice_duration_threshold,
            'event_state': engine.states[EventType.VOICE_DETECTED] if engine else 'disabled',
            'reset_or_clear_reason': engine.last_reset_reason if engine else None,
            'activated_event_count': len(engine.events) if engine else 0,
        }

    @property
    def report_status(self) -> str:
        return self._report_job.status if self._report_job is not None else getattr(self, '_restored_report_status', 'disabled')

    def retry_report(self) -> bool:
        """Retry only failed local generation; successful reports are not resent."""
        if (self.summary is None or self.store is None or not self.config.reporting.generate_pdf_report
                or self.report_status != 'failed'):
            return False
        self._start_report_job()
        return True

    def _start_report_job(self) -> None:
        from .storage.report_generator import ReportJob
        def report_complete(result):
            if (result.path is not None and self.config.reporting.send_pdf_to_telegram
                    and self.config.remote.enabled and self.config.remote.telegram_enabled):
                self._enqueue_remote('session_report', self._remote_payload(
                    trust_score=result.trust_score, total_events=self.summary['event_count']), document_path=result.path)
        self._report_job = ReportJob(self.store.path, self.summary, self.config.reporting, report_complete)

    def _ensure_store(self):
        if self.store is None:
            store = SessionStore(self.config.sessions_dir, self.clock, candidate=self.candidate_info or {},
                                 session_id=getattr(self, 'connected_session_id', None))
            try:
                store.save_config({**self.config.public_dict(), "mode": self.mode,
                                   "snapshots_available": self.mode == "camera"})
                if self.connected_attempt:
                    store.update_metadata({"connected_attempt": self.connected_attempt})
            except Exception:
                store.close()
                raise
            self.store = store
        return self.store

    def poll_optional_workers(self) -> None:
        """Only status/small records are consumed here; no CV/audio/PDF inference."""
        if (self.config.identity.selfie_verification_enabled and self.mode == "camera"
                and not self.session.started):
            baseline = getattr(self.monitor, "identity_baseline", None)
            if baseline is not None and baseline is not self._baseline_saved:
                try:
                    self._ensure_store().save_reference(baseline.jpeg_bytes, baseline.metadata)
                    self.store.update_metadata({"identity_reference_invalidated": None})
                    self._baseline_saved = baseline
                    self._identity_save_error = ""
                except (OSError, ValueError) as error:
                    self._identity_save_error = f"Reference photo could not be saved: {type(error).__name__}"
        if self.system_checker is not None and self.store is not None and self.summary is None:
            metadata = self.system_checker.metadata()
            if metadata != self._system_metadata:
                try:
                    self.store.update_metadata({"system_checks": metadata})
                    self._system_metadata = metadata
                except OSError as error:
                    self.storage_error = str(error)
            if self.session.started:
                for event in self.system_checker.drain_events():
                    self.record_security_event(event["event_type"], event["description"], event.get("details"))
        if self.audio is not None and self.session.started and not self.session.ended:
            state = self.audio.status
            if state != self._optional_status.get("audio"):
                self._append({"record_kind": "optional_monitor_status", "timestamp": self.clock.wall_time(),
                              "component": "audio", **state})
                self._optional_status["audio"] = state
            for sample in self.audio.drain():
                # Calibration speech and queued preview buffers must never seed
                # the exam's two-second review-event accumulator.
                duration = getattr(sample, 'duration_seconds', None)
                interval_start = sample.timestamp - (duration or 0.0)
                if (self._audio_exam_started_at is not None
                        and interval_start < self._audio_exam_started_at - 1e-9):
                    continue
                camera_healthy = (self.mode != "camera" or self.monitor.health(self.clock.monotonic()).healthy)
                if (not sample.healthy or not camera_healthy or not self.session.monitoring_healthy
                        or self.clock.monotonic() - sample.timestamp > .5):
                    reason = ("audio_unhealthy" if not sample.healthy else "audio_stale"
                              if self.clock.monotonic() - sample.timestamp > .5 else "monitoring_unavailable")
                    changes = self.audio_events.interrupt(reason)
                else:
                    conditions = {EventType.VOICE_DETECTED: None} if sample.above_ambient else {}
                    changes = self.audio_events.observe(Observation(sample.timestamp, conditions, "audio_energy", duration))
                    if self._last_audio_sample is None or sample.timestamp > self._last_audio_sample:
                        self._last_audio_sample = sample.timestamp
                self._write_audio_events(changes)
            if (state["state"] == "unavailable" or (self._last_audio_sample is not None
                    and self.clock.monotonic() - self._last_audio_sample > .5)):
                self._write_audio_events(self.audio_events.interrupt("audio_unavailable"))

    def _write_audio_events(self, changes):
        self._write_events([{**record, "event_id": "audio-" + record["event_id"]} for record in changes])

    def close_optional_workers(self) -> None:
        if self._optional_closed:
            return
        self._optional_closed = True
        if self.system_checker is not None:
            self.system_checker.close()
        if self.audio is not None:
            self.audio.stop()
        if self._report_job is not None:
            self._report_job.close(timeout=2.)
        if self.store is not None and not self.session.started:
            self.store.close()

    def _require_registration(self) -> None:
        if not self.registration_complete:
            raise RuntimeError("Complete candidate registration before calibration or exam start")

    def _remote_payload(self, **values) -> dict:
        return {"session_id": self.store.path.name if self.store else None,
                "candidate": self.candidate_info or {}, "timestamp": self.clock.wall_time(), **values}

    def _remote_warning(self, warning: dict) -> None:
        # Never write exception text: transport exceptions can contain bot URLs
        # and credentials. Transport warnings are not misconduct events.
        if self.store is not None:
            try:
                self.store.append_remote_warning({"timestamp": self.clock.wall_time(), **warning})
                return
            except OSError:
                pass
        logging.getLogger(__name__).warning("Remote dispatch warning: %s", warning.get("code", "unknown"))

    def _drain_remote_warnings(self) -> None:
        if self.remote is not None:
            try:
                for warning in self.remote.drain_warnings():
                    self._remote_warning(warning)
            except Exception:
                self._remote_warning({"type": "remote_dispatch_warning", "code": "warning_drain_failed"})

    def _enqueue_remote(self, kind: str, payload: dict, snapshot_path=None, document_path=None) -> None:
        if self.remote is not None:
            try:
                if document_path is None:
                    self.remote.enqueue(kind, payload, snapshot_path=snapshot_path)
                else:
                    self.remote.enqueue(kind, payload, document_path=document_path)
            except Exception:
                self._remote_warning({"type": "remote_dispatch_warning", "code": "enqueue_failed",
                                      "dispatch_type": kind})
            self._drain_remote_warnings()

    def _drain_snapshot_results(self, final: bool = False) -> None:
        if self.store is None:
            return
        for result in self.store.snapshot_results():
            metadata = self._event_metadata.get(result["event_id"], {})
            status = "ready" if result["snapshot_path"] else "unavailable"
            metadata["snapshot_status"] = status
            self._append({"record_kind":"snapshot_result", "timestamp":self.clock.wall_time(),
                          "event_id":result["event_id"], "event_type":metadata.get("event_type"), "start_timestamp":metadata.get("start_timestamp"),
                          "snapshot_path":result["snapshot_path"], "snapshot_status":status,
                          "duration_seconds":metadata.get("duration_seconds", 0),
                          "snapshot_reason":None if result["snapshot_path"] else "production_failed"})
            payload = self._pending_remote_alerts.pop(result["event_id"], None)
            if payload is not None:
                path = self.store.path / result["snapshot_path"] if result["snapshot_path"] else None
                self._enqueue_remote("violation_alert", payload, path)
        if final:
            # A writer exceeding its existing shutdown deadline must not hold
            # remote alerts indefinitely or duplicate them when it finishes.
            pending, self._pending_remote_alerts = self._pending_remote_alerts, {}
            for payload in pending.values():
                self._enqueue_remote("violation_alert", payload)

    def close_remote(self, timeout: float = 2.0) -> None:
        self.close_optional_workers()
        if self.remote is not None:
            try:
                self.remote.close(timeout=min(timeout, 2.0))
            except Exception:
                self._remote_warning({"type": "remote_dispatch_warning", "code": "shutdown_failed"})
            self._drain_remote_warnings()

    @property
    def review_events(self) -> list[dict]:
        """A shared presentation view; security events bypass CV thresholds."""
        audio_events = ([{**event, "event_id": "audio-" + event["event_id"]} for event in self.audio_events.events]
                        if self.audio_events is not None else [])
        records = [{**event, **self._event_metadata.get(event["event_id"], {})}
                   for event in [*self.events.events, *audio_events, *self.security_events]]
        return sorted(records,
                      key=lambda event: event["start_timestamp"])

    def record_security_event(self, event_type: str, description: str,
                              details: dict | None = None, *, timestamp: str | None = None,
                              event_id: str | None = None) -> None:
        if self.store is None or self.summary is not None:
            return
        event_id = event_id or f"security-{uuid4().hex}"
        if event_id in self._security_event_ids:
            return
        self._security_event_ids.add(event_id)
        timestamp = timestamp or self.clock.wall_time()
        event = {
            "record_kind": "security_event", "event_id": event_id,
            "session_id": self.store.path.name, "timestamp": timestamp,
            "candidate": self.candidate_info or {},
            "start_timestamp": timestamp, "event_type": event_type,
            "description": description, "label": description,
            "details": details or {}, "state": "closed",
            "duration_seconds": 0.0, "confidence": None, "snapshot_path": None,
        }
        self.security_events.append(event)
        self._append(event)
        self._enqueue_remote("violation_alert", self._remote_payload(
            event_id=event_id, event_type=event_type, description=description,
            duration_seconds=0.0, timestamp=timestamp, confidence=None))

    def _drain_protection_events(self) -> None:
        for event in self.protection.drain_events():
            self.record_security_event(
                event["event_type"], event.get("description", event["event_type"]),
                event.get("details"), timestamp=event.get("timestamp"),
                event_id=event.get("event_id"))

    def _poll_protection(self) -> bool:
        """A helper release is terminal; a later heartbeat must never re-arm it."""
        self._drain_protection_events()
        if (self._protection_started and not self.session.ended
                and (self.protection.status == "RECOVERY" or not self.protection.armed)):
            self.emergency_end(self.protection.release_reason or "protection_unavailable")
            return False
        return True

    def prepare_monitoring(self) -> None:
        self._require_registration()
        if not self.device_selection_ready:
            raise RuntimeError('Wait for the device list before opening the camera')
        if self.mode == "camera" and not self.session.ended:
            self._camera_preview_allowed = True
            self.monitor.start()

    def start(self) -> None:
        if not self.device_selection_ready or (self.audio is not None and getattr(self.audio, '_switching', False)):
            raise RuntimeError('Wait for device selection to finish before starting')
        self.poll_optional_workers()
        self._require_registration()
        status = self.preflight_status()
        if not status["ready"]:
            raise RuntimeError(status["reason"])
        if self.session.started:
            raise RuntimeError("This session has already started")
        if self.protection.blocking_enabled and self.mode != "camera":
            raise RuntimeError("Windows protection requires healthy camera monitoring and session calibration")
        if self.mode == "camera":
            health = self.monitor.health(self.clock.monotonic())
            if not health.healthy:
                raise RuntimeError(health.reason)
            if not self.monitor.calibration.ready:
                raise RuntimeError("Complete gaze calibration before starting")
        elif self.monitor.sample(self.clock.monotonic()) is None:
            raise RuntimeError("Restore synthetic monitoring before starting")
        store = self._ensure_store()
        try:
            store.save_config({**self.config.public_dict(), "mode": self.mode,
                               "snapshots_available": self.mode == "camera"})
            self.store = store
            self.protection.arm()
            self._protection_started = self.protection.blocking_enabled
            self.session.start()
            self._recovery_sample_after = self.clock.monotonic()
            store.update_metadata({"system": {"platform": platform.system(), "release": platform.release(),
                                               "machine": platform.machine(), "python": platform.python_version()},
                                   "screen_count": status.get("screen_count")})
            self._write_session_records()
            self._enqueue_remote("session_start", self._remote_payload())
            if self.mode == "camera" and hasattr(self.monitor, "set_exam_active"):
                self.monitor.set_exam_active(True)
            if self.system_checker is not None:
                self.system_checker.start_exam(lambda event: self.record_security_event(
                    event["event_type"], event["description"], event.get("details")))
            if self.audio is not None:
                self._audio_exam_started_at = self.clock.monotonic()
                self._last_audio_sample = None
                begin_exam = getattr(self.audio, "begin_exam", None)
                if begin_exam is not None:
                    begin_exam()
                else:
                    self.audio.start()
                self._audio_check_metadata = self._audio_check_snapshot()
                store.update_metadata({"audio_check": self._audio_check_metadata})
            self.step()
        except Exception:
            self.protection.release("startup_failure")
            if self.system_checker is not None:
                self.system_checker.stop()
            if self.session.started:
                self.session.end("startup_failure")
                # Persist the interruption before potentially slow driver cleanup.
                # Keep the journal/summary inspectable after a partial Start.
                self._write_session_records()
                try:
                    self.end("startup_failure")
                except Exception as cleanup_error:
                    self.storage_error = f"Startup cleanup failed: {type(cleanup_error).__name__}"
                    try:
                        store.close()
                    except OSError:
                        pass
            else:
                try:
                    if self.audio is not None:
                        self.audio.stop()
                finally:
                    store.close()
                    self.store = None
            raise

    def _append(self, record: dict) -> None:
        if self.store is not None:
            try:
                self.store.append({"session_id": self.store.path.name,
                                   "candidate": self.candidate_info or {}, **record})
            except OSError as error:
                self.storage_error = str(error)

    def _write_session_records(self) -> None:
        for record in self.session.records[self._record_cursor:]:
            self._append({"record_kind": "lifecycle", **record})
        self._record_cursor = len(self.session.records)

    def _write_events(self, changes: list[dict]) -> None:
        for change in changes:
            if change.get("action") == "activated":
                severity = ("high" if change["event_type"] == EventType.IMPERSONATION_SUSPECTED.value else "review")
                self._event_metadata[change["event_id"]] = {"severity": severity, "event_type": change["event_type"], "start_timestamp": change.get("start_timestamp")}
            if "duration_seconds" in change:
                self._event_metadata.setdefault(change["event_id"], {})["duration_seconds"] = change["duration_seconds"]
            change = {**change, **self._event_metadata.get(change["event_id"], {})}
            queued_snapshot = False
            if change.get("action") == "activated" and self.mode == "camera" and self.config.snapshots_enabled:
                queued_snapshot = self._save_snapshot(change)
                status = "pending" if queued_snapshot else "unavailable"
                self._event_metadata[change["event_id"]]["snapshot_status"] = status
                change["snapshot_status"] = status
                if not queued_snapshot: change["snapshot_reason"] = "capture_unavailable"
            elif change.get("action") == "activated":
                change["snapshot_status"] = "disabled" if not self.config.snapshots_enabled else "unavailable"
                if self.config.snapshots_enabled: change["snapshot_reason"] = "capture_unavailable"
            self._append({"record_kind": "review_event", "timestamp": self.clock.wall_time(),
                          "snapshot_path": self._snapshots.get(change["event_id"]), **change})
            if change.get("action") == "activated" and self.remote is not None:
                payload = self._remote_payload(
                    event_id=change["event_id"], event_type=change["event_type"],
                    description=change.get("label", change["event_type"]),
                    duration_seconds=change["duration_seconds"], confidence=change.get("confidence"),
                    timestamp=change.get("activated_timestamp") or self.clock.wall_time(),
                    start_timestamp=change.get("start_timestamp"))
                if queued_snapshot:
                    self._pending_remote_alerts[change["event_id"]] = payload
                else:
                    self._enqueue_remote("violation_alert", payload)

    def _save_snapshot(self, change: dict) -> bool:
        # Snapshot IO is handled by a bounded background queue, never by Qt.
        if self.store is None:
            return False
        result = self.monitor.delivered_result
        if result is None or result.frame is None:
            return False
        try:
            self.store.enqueue_snapshot(change["event_id"], result.frame)
            self._snapshots[change["event_id"]] = f"snapshots/{change['event_id']}.jpg"
            boxes = [{"x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2, "label": label}
                     for label, collection in (("person", getattr(result, "persons", ())),
                                                ("phone", getattr(result, "phones", ()))) for box in collection]
            self._event_metadata.setdefault(change["event_id"], {})["snapshot_boxes"] = boxes
            change["snapshot_boxes"] = boxes
            return True
        except (OSError, RuntimeError) as error:
            self.snapshot_errors.append(str(error))
            return False

    def step(self) -> None:
        self.poll_optional_workers()
        self._drain_snapshot_results()
        self._drain_remote_warnings()
        if not self.session.started:
            return
        if self.session.ended:
            self._finalize()
            return
        if not self._poll_protection():
            return
        now = self.clock.monotonic()
        camera_healthy = True
        if self.mode == "camera":
            status = self.monitor.health(now)
            camera_healthy = status.healthy
            if not status.healthy:
                self._monitoring_failure(status.reason, detected_at=status.since)
        # Preserve the known freshness deadline even if the UI callback is late.
        # A fresh sample arriving now cannot erase the unobserved interval.
        if self._last_sample is not None and now - self._last_sample >= self.observation_stale_seconds:
            self._monitoring_failure("Monitoring observations overdue",
                                     detected_at=self._last_sample + self.observation_stale_seconds)
        try:
            observation = self.monitor.sample(now) if camera_healthy else None
            if observation is not None:
                if not isinstance(observation, Observation) or not math.isfinite(observation.timestamp):
                    raise ValueError("Invalid observation timestamp")
                if observation.timestamp > now + 1e-6:
                    raise ValueError("Observation timestamp is in the future")
                fresh = (now - observation.timestamp < self.observation_stale_seconds
                         and observation.timestamp >= self._recovery_sample_after
                         and (self._last_sample is None or observation.timestamp > self._last_sample))
                if fresh and not self.session.ended:
                    if self.mode == "camera":
                        delivered = getattr(self.monitor, "delivered_result", None)
                        face = getattr(delivered, "face", None)
                        self._device_info = {
                            "camera_index": self.config.vision.camera_index,
                            "requested_frame_size": [self.config.vision.capture_width, self.config.vision.capture_height],
                            "source_frame_size": getattr(face, "frame_size", None),
                            "audio_enabled": self.config.audio.enabled,
                            "audio_sample_rate": self.config.audio.sample_rate if self.config.audio.enabled else None,
                        }
                    changes = self.events.observe(observation)
                    self._last_sample = observation.timestamp
                    self.session.monitoring_recovered()
                    self._write_events(changes)
            elif self.mode == "synthetic" and (not self.monitor.available or self.monitor.stopped):
                self._monitoring_failure("Synthetic monitor unavailable")
        except Exception as error:
            # A failing CV adapter is monitoring unavailability, not misconduct.
            self._monitoring_failure(f"Monitoring adapter failed: {error}")
        self.session.tick()
        self._write_session_records()
        if self.session.ended:
            self._finalize()

    def _monitoring_failure(self, reason: str, detected_at: float | None = None) -> None:
        if self.session.monitoring_failed(reason, detected_at=detected_at):
            self._recovery_sample_after = self.clock.monotonic()
            self._write_events(self.events.interrupt("monitoring_unavailable"))
            if self.audio_events is not None:
                self._write_audio_events(self.audio_events.interrupt("monitoring_unavailable"))

    def answer(self, question: int, option: int) -> bool:
        self.session.tick()
        if not self.session.running or self.config.external_url:
            return False
        self.quiz.answer(question, option)
        return True

    def pause(self, pin: str) -> bool:
        if not self.pin.verify(pin):
            return False
        result = self.session.pause_by_proctor()
        self._write_session_records()
        return result

    def resume(self, pin: str) -> bool:
        result = self.session.resume_by_proctor(self.pin.verify(pin))
        self._write_session_records()
        return result

    def end_with_pin(self, pin: str) -> bool:
        if not self.pin.verify(pin):
            return False
        self.end("proctor_ended")
        return True

    def end(self, reason: str = "completed") -> None:
        # Recover input first, even if persistence or downstream cleanup fails.
        self.protection.release(reason)
        if self.system_checker is not None:
            self.system_checker.stop()
        # Once restrictions are released, the exam is terminal even if a media
        # driver blocks during cleanup. Cleanup time must not count as exam time.
        self.session.end(reason)
        terminal_hook = getattr(self, 'connected_terminal_hook', None)
        if terminal_hook is not None:
            terminal_hook()
        if self.mode == "camera" and hasattr(self.monitor, "set_exam_active"):
            self.monitor.set_exam_active(False)
        self._drain_protection_events()
        self.monitor.stop()
        self._finalize()

    def emergency_end(self, reason: str = "emergency_shortcut") -> None:
        if self.emergency.trigger(reason) and self.protection.blocking_enabled:
            self._drain_protection_events()
            # The independent helper normally records recovery itself. Preserve
            # evidence when the local shortcut wins or the helper has died.
            if not any(e["event_type"] in ("PROTECTION_RECOVERY", "EMERGENCY_RELEASE")
                       for e in self.security_events):
                self.record_security_event("PROTECTION_RECOVERY", "Protection released for recovery",
                                           {"reason": reason})
        self.end(reason)

    def _finalize(self) -> None:
        if self.summary is not None or not self.session.started:
            return
        self.protection.release(self.session.end_reason or "session_ended")
        terminal_hook = getattr(self, 'connected_terminal_hook', None)
        if terminal_hook is not None:
            terminal_hook()
        if self.system_checker is not None:
            self.system_checker.stop()
        if self.audio is not None:
            self._audio_check_metadata = self._audio_check_snapshot()
            self.audio.stop()
        self._drain_protection_events()
        self.monitor.stop()
        self._write_events(self.events.close_all("session_ended"))
        if self.audio_events is not None:
            self._write_audio_events(self.audio_events.close_all("session_ended"))
        self._write_session_records()
        if self.store is not None and self.mode == "camera":
            paths, errors = self.store.finish_snapshots()
            self._snapshots = {**self._snapshots, **paths}
            self.snapshot_errors.extend(errors)
        self._drain_snapshot_results(final=True)
        events = [{**event, "snapshot_path": self._snapshots.get(event["event_id"])}
                  for event in self.review_events]
        ended_at = self.clock.wall_time()
        if self.connected_attempt:
            # Finalizing an interrupted terminal write on a later launch must
            # retain actual completion time (including retention provenance).
            ended_at = next((record['timestamp'] for record in reversed(self.session.records)
                             if record.get('event_type') == 'session_ended'), ended_at)
        self.summary = {
            "mode": self.mode, "ended_at": ended_at,
            "end_reason": self.session.end_reason, "score": self.quiz.score,
            "total_questions": self.quiz.total, "answered": self.quiz.answered_count,
            "answers": self.quiz.answers, "elapsed_seconds": self.session.elapsed_seconds,
            "remaining_seconds": self.session.remaining_seconds,
            "duration_seconds": self.session.duration_seconds,
            "time_adjustment_ids": list(self.session.time_adjustment_ids),
            "event_count": len(events), "event_counts": dict(Counter(e["event_type"] for e in events)),
            "events": events, "security_events": list(self.security_events), "lifecycle": self.session.records,
            "session_id": self.store.path.name if self.store else None,
            "candidate": self.candidate_info or {},
            **({"connected_attempt": self.connected_attempt} if self.connected_attempt else {}),
            "snapshots_available": self.mode == "camera",
            "blocking_enabled": self.protection.blocking_enabled,
            "snapshot_errors": list(self.snapshot_errors),
            "storage_error": self.storage_error,
            "system_checks": self._system_metadata or {},
            "optional_monitor_status": dict(self._optional_status),
            "audio_check": dict(self._audio_check_metadata),
            "reference_face": self.store._metadata.get('reference_face') if self._baseline_saved is not None and self.store else None,
            "system": {"platform": platform.system(), "release": platform.release(), "machine": platform.machine()},
            "device_info": dict(self._device_info),
        }
        if self.config.external_url:
            # The embedded site owns answers/submission/grading. Do not report
            # the hidden diagnostic quiz as the student's external exam score.
            self.summary.update(exam_mode="external", score=None,
                                total_questions=None, answered=None, answers={})
        if self.store is not None:
            try:
                self.store.finalize(self.summary)
            except OSError as error:
                self.storage_error = str(error)
            finally:
                try:
                    self.store.close()
                except OSError as error:
                    self.storage_error = str(error)
            self.summary["storage_error"] = self.storage_error
        self._enqueue_remote("session_end", self._remote_payload(
            total_events=len(events), end_reason=self.session.end_reason,
            elapsed_seconds=self.session.elapsed_seconds,
            event_counts=self.summary["event_counts"]))
        if self.config.reporting.generate_pdf_report and self.store is not None and self.storage_error is None:
            self._start_report_job()

