from dataclasses import replace
import json

import pytest

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType


@pytest.fixture
def app_controller(tmp_path):
    clock = FakeClock()
    config = replace(load_config(), sessions_dir=tmp_path / "sessions")
    controller = AppController(config, clock)
    yield clock, controller
    if controller.session.started and not controller.session.ended:
        controller.end("test_cleanup")


def test_complete_synthetic_exam_persists_one_event_and_summary(app_controller):
    clock, app = app_controller
    app.start()
    assert app.protection.armed and not app.protection.blocking_enabled
    assert app.answer(0, 1)
    app.monitor.set_condition(EventType.PHONE_VISIBLE, True)
    app.step()
    for _ in range(5):
        clock.advance(.5)
        app.step()
    assert len(app.events.events) == 1
    assert app.session.running
    assert app.session.elapsed_seconds == 2.5
    assert not app.end_with_pin("0000")
    assert app.end_with_pin("2468")
    assert app.monitor.stopped and not app.protection.armed
    summary = json.loads((app.store.path / "summary.json").read_text(encoding="utf-8"))
    records = [json.loads(line) for line in (app.store.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["event_count"] == 1
    assert summary["score"] == 1
    assert summary["events"][0]["state"] == "closed"
    assert sum(r.get("action") == "activated" for r in records) == 1
    assert "2468" not in (app.store.path / "config.json").read_text(encoding="utf-8")
    assert not list(app.store.path.glob("*.jpg"))


@pytest.mark.parametrize("duration,requires_pin", [(14.9, False), (15., True)])
def test_monitoring_recovery_integrates_timer_and_pin(app_controller, duration, requires_pin):
    clock, app = app_controller
    app.start()
    clock.advance(1)
    app.step()
    app.monitor.available = False
    app.step()
    assert not app.session.running
    assert not app.answer(0, 0)
    remaining = app.session.remaining_seconds
    clock.advance(duration)
    app.monitor.available = True
    app.step()
    assert app.session.remaining_seconds == remaining
    assert app.session.recovery_pin_required is requires_pin
    assert app.session.running is not requires_pin
    if requires_pin:
        assert not app.resume("0000")
        assert app.resume("2468")
    assert app.session.running


def test_recovery_never_clears_proctor_pause(app_controller):
    clock, app = app_controller
    app.start()
    assert not app.pause("0000")
    assert app.pause("2468")
    app.monitor.available = False
    app.step()
    clock.advance(5)
    app.monitor.available = True
    app.step()
    assert app.session.pause_reasons == {"proctor"}
    assert app.resume("2468")


def test_silent_monitor_stall_pauses_at_freshness_deadline(app_controller):
    clock, app = app_controller
    app.start()
    app.monitor.stalled = True
    clock.advance(app.config.stale_seconds - .01)
    app.step()
    assert app.session.running
    clock.advance(.01)
    app.step()
    assert not app.session.running
    assert "monitoring" in app.session.pause_reasons
    clock.advance(3)
    app.monitor.stalled = False
    app.step()
    assert app.session.running


def test_monitor_failure_closes_events_without_counting_outage(app_controller):
    clock, app = app_controller
    app.start()
    app.monitor.set_condition(EventType.SECOND_PERSON, True)
    clock.advance(.1)
    app.step()
    clock.advance(1.)
    app.step()
    app.monitor.available = False
    app.step()
    assert app.events.events[0]["close_reason"] == "monitoring_unavailable"
    clock.advance(10)
    app.monitor.available = True
    app.step()
    assert len(app.events.events) == 1
    assert app.events.events[0]["duration_seconds"] == pytest.approx(1)


def test_expiry_finalizes_and_releases(app_controller):
    clock, app = app_controller
    app.start()
    for _ in range(int(app.config.duration_seconds)):
        clock.advance(1)
        app.step()
    assert app.session.end_reason == "time_expired"
    assert app.summary is not None
    assert not app.protection.armed
    assert app.monitor.stopped


def test_emergency_is_idempotent_and_stops_monitoring(app_controller):
    _, app = app_controller
    app.start()
    app.emergency_end()
    first_summary = app.summary
    app.emergency_end()
    assert app.summary is first_summary
    assert app.session.end_reason == "emergency_shortcut"
    assert app.protection.release_reason == "emergency_shortcut"
    assert app.monitor.stopped


def test_summary_failure_still_releases_and_stops_monitor(app_controller, monkeypatch):
    _, app = app_controller
    app.start()
    def failing_summary(_):
        raise OSError("simulated full disk")
    monkeypatch.setattr(app.store, "finalize", failing_summary)
    app.emergency_end()
    assert not app.protection.armed
    assert app.monitor.stopped
    assert "full disk" in app.storage_error
    assert (app.store.path / "events.jsonl").exists()


def test_cannot_start_without_synthetic_health(app_controller):
    _, app = app_controller
    app.monitor.available = False
    with pytest.raises(RuntimeError, match="Restore"):
        app.start()
    assert not app.session.started


def test_late_callback_preserves_gap_and_does_not_erase_pin_requirement(app_controller):
    clock, app = app_controller
    app.start()
    clock.advance(17)
    app.step()
    assert app.session.elapsed_seconds == 2
    assert app.session.recovery_pin_required
    assert app.session.monitoring_healthy
    assert not app.session.running


def test_replayed_sample_cannot_recover_failed_monitoring(app_controller, monkeypatch):
    from proctoring.domain import Observation
    clock, app = app_controller
    app.start()
    app.monitor.available = False
    app.step()
    clock.advance(1)
    app.monitor.available = True
    monkeypatch.setattr(app.monitor, "sample", lambda _: Observation(0))
    app.step()
    assert not app.session.monitoring_healthy
    assert not app.session.running


@pytest.mark.parametrize("fault", ["exception", "future", "nonfinite", "invalid_confidence"])
def test_bad_monitoring_data_pauses_instead_of_crashing(app_controller, monkeypatch, fault):
    from proctoring.domain import Observation
    clock, app = app_controller
    app.start()
    clock.advance(.1)
    def bad_sample(now):
        if fault == "exception":
            raise RuntimeError("detector failed")
        if fault == "future":
            return Observation(now + 100)
        if fault == "nonfinite":
            return Observation(float("nan"))
        return Observation(now, {EventType.PHONE_VISIBLE: 3.0})
    monkeypatch.setattr(app.monitor, "sample", bad_sample)
    app.step()
    assert not app.session.running
    assert not app.session.monitoring_healthy


def test_startup_storage_error_can_be_retried(app_controller, monkeypatch):
    from proctoring.storage import SessionStore
    _, app = app_controller
    original = SessionStore.save_config
    def fail_once(self, config):
        raise OSError("simulated write failure")
    monkeypatch.setattr(SessionStore, "save_config", fail_once)
    with pytest.raises(OSError):
        app.start()
    assert not app.session.started
    assert not app.monitor.stopped
    assert app.store is None
    monkeypatch.setattr(SessionStore, "save_config", original)
    app.start()
    assert app.session.running


def test_unseen_pre_failure_sample_cannot_resume_exam(app_controller, monkeypatch):
    from proctoring.domain import Observation
    clock, app = app_controller
    app.start()
    clock.advance(1)
    app.monitor.available = False
    app.step()
    clock.advance(.2)
    app.monitor.available = True
    monkeypatch.setattr(app.monitor, "sample", lambda _: Observation(.9))
    app.step()
    assert not app.session.running
    assert not app.session.monitoring_healthy
    monkeypatch.setattr(app.monitor, "sample", lambda now: Observation(now))
    app.step()
    assert app.session.running


def test_close_failure_preserves_summary_and_recovery(app_controller, monkeypatch):
    _, app = app_controller
    app.start()
    original = app.store.close
    def fail_close():
        original()
        raise OSError("simulated close error")
    monkeypatch.setattr(app.store, "close", fail_close)
    app.emergency_end()
    assert app.session.ended and not app.protection.armed
    assert app.summary is not None
    assert "close error" in app.summary["storage_error"]

