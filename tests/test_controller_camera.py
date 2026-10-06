"""Camera integration through the existing controller, event engine and timer."""
from collections import deque
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType
from proctoring.vision.rules import to_observation
from proctoring.vision.types import GazeDirection, HealthStatus, VisionResult


class QueuedMonitor:
    """Deliberately does not suppress samples when health is false.

    This exercises the controller's defense against queued pre-failure results.
    Result delivery and the most recently captured result are kept separate.
    """
    def __init__(self):
        self.calibration = SimpleNamespace(ready=True)
        self.healthy = True
        self.failure_since = None
        self.started = False
        self.stopped = False
        self.queued = deque()
        self.latest_result = None
        self.delivered_result = None
        self.sample_calls = 0

    def start(self):
        self.started = True
        self.stopped = False

    def stop(self):
        self.stopped = True

    def health(self, now):
        return HealthStatus(self.healthy and not self.stopped, "Camera disconnected", self.failure_since)

    def publish(self, now, **values):
        data = {"face_present": True, "gaze_direction": GazeDirection.CENTER, "person_count": 1, **values}
        result = VisionResult(timestamp=now, **data)
        self.queued.append(result)
        self.latest_result = result
        return result

    def sample(self, now):
        self.sample_calls += 1
        if not self.queued:
            return None
        self.delivered_result = self.queued.popleft()
        return to_observation(self.delivered_result)


@pytest.fixture
def camera_controller(tmp_path):
    clock = FakeClock()
    config = replace(load_config(), sessions_dir=tmp_path / "sessions", snapshots_enabled=False)
    monitor = QueuedMonitor()
    app = AppController(config, clock, mode="camera", monitor=monitor)
    yield clock, monitor, app
    if app.session.started and not app.session.ended:
        app.end("test_cleanup")


def start(clock, monitor, app):
    app.prepare_monitoring()
    monitor.publish(clock.monotonic())
    app.start()


def advance(clock, monitor, app, duration=.5, **values):
    clock.advance(duration)
    result = monitor.publish(clock.monotonic(), **values)
    app.step()
    return result


def test_start_requires_health_and_session_calibration(camera_controller):
    clock, monitor, app = camera_controller
    monitor.healthy = False
    with pytest.raises(RuntimeError, match="Camera disconnected"):
        app.start()
    assert not app.session.started
    assert app.store is None
    monitor.healthy = True
    monitor.calibration.ready = False
    with pytest.raises(RuntimeError, match="Complete gaze calibration"):
        app.start()
    assert not app.session.started
    monitor.calibration.ready = True
    start(clock, monitor, app)
    assert app.session.running
    assert app.protection.armed and not app.protection.blocking_enabled


def test_unhealthy_camera_cannot_resume_from_queued_fresh_result(camera_controller):
    clock, monitor, app = camera_controller
    start(clock, monitor, app)
    clock.advance(.5)
    monitor.healthy = False
    monitor.failure_since = clock.monotonic()
    monitor.publish(clock.monotonic())
    previous_calls = monitor.sample_calls
    app.step()
    assert not app.session.running
    assert not app.session.monitoring_healthy
    assert monitor.sample_calls == previous_calls
    assert len(monitor.queued) == 1
    clock.advance(1)
    app.step()
    assert not app.session.running
    assert app.session.elapsed_seconds == .5


@pytest.mark.parametrize("duration,requires_pin", [(14.9, False), (15.0, True)])
@pytest.mark.parametrize("proctor_paused", [False, True])
def test_recovery_boundary_and_proctor_pause_remain_independent(camera_controller, duration,
                                                               requires_pin, proctor_paused):
    clock, monitor, app = camera_controller
    start(clock, monitor, app)
    advance(clock, monitor, app, 1)
    if proctor_paused:
        assert app.pause("2468")
    monitor.healthy = False
    monitor.failure_since = clock.monotonic()
    app.step()
    frozen = app.session.remaining_seconds
    assert not app.resume("2468")  # A valid PIN cannot authorize missing monitoring.
    clock.advance(duration)
    monitor.healthy = True
    monitor.failure_since = None
    monitor.publish(clock.monotonic())
    app.step()
    assert app.session.remaining_seconds == frozen
    assert app.session.monitoring_healthy
    assert app.session.recovery_pin_required is requires_pin
    assert ("proctor" in app.session.pause_reasons) is proctor_paused
    assert app.session.running is (not requires_pin and not proctor_paused)
    recovery = [r for r in app.session.records if r["event_type"] == "monitoring_recovered"][-1]
    assert recovery["duration"] == pytest.approx(duration)
    if requires_pin or proctor_paused:
        assert not app.resume("0000")
        assert not app.session.running
        assert app.resume("2468")
    advance(clock, monitor, app, .5)
    assert app.session.elapsed_seconds == pytest.approx(1.5)


def test_healthy_status_needs_fresh_complete_result_to_resume(camera_controller):
    clock, monitor, app = camera_controller
    start(clock, monitor, app)
    advance(clock, monitor, app, .5)
    monitor.healthy = False
    monitor.failure_since = clock.monotonic()
    app.step()
    clock.advance(.5)
    monitor.healthy = True
    app.step()
    assert not app.session.running
    monitor.publish(.4)  # Fresh by age, but captured before this interruption.
    app.step()
    assert not app.session.running
    monitor.publish(clock.monotonic())
    app.step()
    assert app.session.running


def test_stale_results_pause_at_capture_freshness_deadline(camera_controller):
    clock, monitor, app = camera_controller
    start(clock, monitor, app)
    clock.advance(app.config.vision.result_stale_seconds + .5)
    app.step()
    assert not app.session.running
    assert app.session.elapsed_seconds == app.config.vision.result_stale_seconds
    monitor.publish(.1)  # Replaying an old frame does not recover the timer.
    app.step()
    assert not app.session.running
    monitor.publish(clock.monotonic())
    app.step()
    assert app.session.running


def test_fresh_frames_without_face_trigger_review_without_pausing(camera_controller):
    clock, monitor, app = camera_controller
    start(clock, monitor, app)
    advance(clock, monitor, app, .1, face_present=False)
    for _ in range(7):
        advance(clock, monitor, app, .5, face_present=False)
    assert app.session.running
    assert app.session.elapsed_seconds == pytest.approx(3.6)
    assert len(app.events.events) == 1
    assert app.events.events[0]["event_type"] == EventType.FACE_ABSENT.value
    assert app.events.events[0]["state"] == "active"


@pytest.mark.parametrize("enabled", [False, True])
def test_one_snapshot_per_active_event_uses_delivered_frame(camera_controller, monkeypatch, enabled):
    clock, monitor, app = camera_controller
    app.config = replace(app.config, snapshots_enabled=enabled)
    start(clock, monitor, app)
    writes = []
    monkeypatch.setattr(app.store, "enqueue_snapshot", lambda event_id, frame: writes.append((event_id, frame)))
    monkeypatch.setattr(app.store, "finish_snapshots", lambda: (
        {event_id: f"snapshots/{event_id}.jpg" for event_id, frame in writes}, []))
    delivered_frame = object()
    other_frame = object()
    advance(clock, monitor, app, .1, phone_visible=True, phone_confidence=.91, frame=delivered_frame)
    for _ in range(8):
        clock.advance(.5)
        monitor.publish(clock.monotonic(), phone_visible=True, phone_confidence=.91, frame=delivered_frame)
        # Capture/inference advances after delivery was queued. Snapshots must
        # stay associated with the result actually handed to the event engine.
        monitor.latest_result = replace(monitor.latest_result, frame=other_frame)
        app.step()
    assert len(app.events.events) == 1
    assert len(writes) == int(enabled)
    if enabled:
        assert writes[0][1] is delivered_frame
    assert app.session.running
    app.end_with_pin("2468")
    summary = json.loads((app.store.path / "summary.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "camera"
    assert summary["blocking_enabled"] is False
    assert bool(summary["events"][0]["snapshot_path"]) is enabled
    assert monitor.stopped


def test_snapshot_enqueue_failure_does_not_stop_exam(camera_controller, monkeypatch):
    clock, monitor, app = camera_controller
    app.config = replace(app.config, snapshots_enabled=True)
    start(clock, monitor, app)
    def full_queue(event_id, frame):
        raise RuntimeError("Snapshot queue full")
    monkeypatch.setattr(app.store, "enqueue_snapshot", full_queue)
    advance(clock, monitor, app, .1, phone_visible=True, phone_confidence=.9, frame=object())
    advance(clock, monitor, app, 1, phone_visible=True, phone_confidence=.9, frame=object())
    assert app.session.running
    assert len(app.events.events) == 1
    assert app.snapshot_errors == ["Snapshot queue full"]
    app.end()
    assert app.summary["events"][0]["snapshot_path"] is None
    assert "Snapshot queue full" in app.summary["snapshot_errors"]
