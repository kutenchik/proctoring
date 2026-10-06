"""Application orchestration; CV/UI remain replaceable adapters."""
from collections import Counter
import math
from uuid import uuid4

from .clock import Clock, SystemClock
from .config import AppConfig
from .domain import Observation
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
        self.events = EventEngine(config.thresholds, config.clearing_seconds, self.clock,
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
        self._record_cursor = 0
        self._last_sample: float | None = None
        self._recovery_sample_after = float("-inf")
        self._snapshots: dict[str, str] = {}
        self.snapshot_errors: list[str] = []
        self.security_events: list[dict] = []
        self._security_event_ids: set[str] = set()
        self._protection_started = False

    @property
    def review_events(self) -> list[dict]:
        """A shared presentation view; security events bypass CV thresholds."""
        return sorted([*self.events.events, *self.security_events],
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
            "start_timestamp": timestamp, "event_type": event_type,
            "description": description, "label": description,
            "details": details or {}, "state": "closed",
            "duration_seconds": 0.0, "confidence": None, "snapshot_path": None,
        }
        self.security_events.append(event)
        self._append(event)

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
        if self.mode == "camera" and not self.session.ended:
            self.monitor.start()

    def start(self) -> None:
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
        store = SessionStore(self.config.sessions_dir, self.clock)
        try:
            store.save_config({**self.config.public_dict(), "mode": self.mode,
                               "snapshots_available": self.mode == "camera"})
            self.store = store
            self.protection.arm()
            self._protection_started = self.protection.blocking_enabled
            self.session.start()
            self._write_session_records()
            self.step()
        except Exception:
            self.protection.release("startup_failure")
            if self.session.started:
                self.monitor.stop()
                self.session.end("startup_failure")
            store.close()
            self.store = None
            raise

    def _append(self, record: dict) -> None:
        if self.store is not None:
            try:
                self.store.append(record)
            except OSError as error:
                self.storage_error = str(error)

    def _write_session_records(self) -> None:
        for record in self.session.records[self._record_cursor:]:
            self._append({"record_kind": "lifecycle", **record})
        self._record_cursor = len(self.session.records)

    def _write_events(self, changes: list[dict]) -> None:
        for change in changes:
            if change.get("action") == "activated" and self.mode == "camera" and self.config.snapshots_enabled:
                self._save_snapshot(change)
            self._append({"record_kind": "review_event", "timestamp": self.clock.wall_time(),
                          "snapshot_path": self._snapshots.get(change["event_id"]), **change})

    def _save_snapshot(self, change: dict) -> None:
        # Snapshot IO is handled by a bounded background queue, never by Qt.
        if self.store is None:
            return
        result = self.monitor.delivered_result
        if result is None or result.frame is None:
            return
        try:
            self.store.enqueue_snapshot(change["event_id"], result.frame)
            self._snapshots[change["event_id"]] = f"snapshots/{change['event_id']}.jpg"
        except (OSError, RuntimeError) as error:
            self.snapshot_errors.append(str(error))

    def step(self) -> None:
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

    def answer(self, question: int, option: int) -> bool:
        self.session.tick()
        if not self.session.running:
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
        self._drain_protection_events()
        self.monitor.stop()
        self.session.end(reason)
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
        self._drain_protection_events()
        self.monitor.stop()
        self._write_events(self.events.close_all("session_ended"))
        self._write_session_records()
        if self.store is not None and self.mode == "camera":
            paths, errors = self.store.finish_snapshots()
            self._snapshots = paths
            self.snapshot_errors.extend(errors)
        events = [{**event, "snapshot_path": self._snapshots.get(event["event_id"])}
                  for event in self.review_events]
        self.summary = {
            "mode": self.mode, "ended_at": self.clock.wall_time(),
            "end_reason": self.session.end_reason, "score": self.quiz.score,
            "total_questions": self.quiz.total, "answered": self.quiz.answered_count,
            "answers": self.quiz.answers, "elapsed_seconds": self.session.elapsed_seconds,
            "remaining_seconds": self.session.remaining_seconds,
            "event_count": len(events), "event_counts": dict(Counter(e["event_type"] for e in events)),
            "events": events, "security_events": list(self.security_events), "lifecycle": self.session.records,
            "session_id": self.store.path.name if self.store else None,
            "snapshots_available": self.mode == "camera",
            "blocking_enabled": self.protection.blocking_enabled,
            "snapshot_errors": list(self.snapshot_errors),
            "storage_error": self.storage_error,
        }
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

