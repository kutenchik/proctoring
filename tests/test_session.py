"""All timing tests advance a fake monotonic clock; none sleep."""
import pytest

from proctoring.clock import FakeClock
from proctoring.domain import EventType, Observation
from proctoring.events import EventEngine
from proctoring.session import SessionController


@pytest.fixture
def session():
    clock = FakeClock()
    return clock, SessionController(clock, 100)


def test_timer_only_accrues_during_running_segments(session):
    clock, controller = session
    clock.advance(500)
    assert controller.remaining_seconds == 100
    assert controller.elapsed_seconds == 0
    controller.start()
    clock.advance(12.5)
    assert controller.elapsed_seconds == 12.5
    controller.pause_by_proctor()
    clock.advance(60)
    assert controller.remaining_seconds == 87.5
    assert controller.resume_by_proctor(pin_valid=True)
    clock.advance(10)
    controller.end()
    clock.advance(1000)
    assert controller.elapsed_seconds == 22.5
    assert not controller.running


@pytest.mark.parametrize("duration,requires_pin", [(14.9, False), (15.0, True), (15.1, True)])
def test_monitoring_recovery_boundary_without_intermediate_tick(session, duration, requires_pin):
    clock, controller = session
    controller.start()
    clock.advance(7)
    assert controller.monitoring_failed()
    assert not controller.running
    assert controller.pause_reasons == {"monitoring"}
    clock.advance(duration)
    assert controller.remaining_seconds == 93
    assert controller.monitoring_recovered()
    assert controller.recovery_pin_required is requires_pin
    assert controller.running is not requires_pin
    record = controller.records[-1]
    assert record["duration"] == pytest.approx(duration)
    assert record["recovery"] == ("pin_required" if requires_pin else "automatic")
    if requires_pin:
        assert not controller.resume_by_proctor(pin_valid=False)
        clock.advance(12)
        assert controller.remaining_seconds == 93
        assert controller.resume_by_proctor(pin_valid=True)
    clock.advance(1)
    assert controller.remaining_seconds == pytest.approx(92)


def test_long_outage_latches_at_deadline_and_cannot_resume_while_unhealthy(session):
    clock, controller = session
    controller.start()
    controller.monitoring_failed()
    clock.advance(15)
    controller.tick()
    assert controller.pause_reasons == {"monitoring", "recovery_pin"}
    assert not controller.resume_by_proctor(pin_valid=True)
    controller.tick()
    assert len([r for r in controller.records if r["event_type"] == "recovery_pin_required"]) == 1
    controller.monitoring_recovered()
    assert controller.pause_reasons == {"recovery_pin"}
    assert controller.resume_by_proctor(pin_valid=True)


@pytest.mark.parametrize("outage", [1.0, 14.9, 15.0, 20.0])
@pytest.mark.parametrize("proctor_first", [True, False])
def test_overlapping_pauses_never_auto_resume_proctor_pause(session, outage, proctor_first):
    clock, controller = session
    controller.start()
    clock.advance(3)
    if proctor_first:
        assert controller.pause_by_proctor()
    controller.monitoring_failed()
    if not proctor_first:
        assert controller.pause_by_proctor()
    clock.advance(outage)
    controller.monitoring_recovered()
    assert "proctor" in controller.pause_reasons
    assert not controller.running
    assert controller.elapsed_seconds == 3
    assert not controller.resume_by_proctor(pin_valid=False)
    assert controller.resume_by_proctor(pin_valid=True)
    assert controller.pause_reasons == set()
    clock.advance(2)
    assert controller.elapsed_seconds == 5


def test_new_short_outage_does_not_clear_existing_pin_requirement(session):
    clock, controller = session
    controller.start()
    controller.monitoring_failed()
    clock.advance(15)
    controller.monitoring_recovered()
    controller.monitoring_failed()
    clock.advance(1)
    controller.monitoring_recovered()
    assert controller.pause_reasons == {"recovery_pin"}
    assert not controller.running
    assert controller.resume_by_proctor(pin_valid=True)


def test_duplicate_failure_does_not_reset_outage_duration(session):
    clock, controller = session
    controller.start()
    controller.monitoring_failed("Webcam disconnected")
    clock.advance(14)
    assert not controller.monitoring_failed("Still disconnected")
    clock.advance(1)
    controller.monitoring_recovered()
    assert controller.recovery_pin_required
    assert len([r for r in controller.records if r["event_type"] == "monitoring_failed"]) == 1


def test_delayed_polling_counts_only_time_before_known_stale_deadline(session):
    clock, controller = session
    controller.start()
    clock.advance(17)
    assert controller.monitoring_failed("Observations overdue", detected_at=2)
    assert controller.elapsed_seconds == 2
    assert controller.recovery_pin_required
    controller.monitoring_recovered()
    assert controller.records[-1]["duration"] == 15
    assert not controller.running
    assert controller.resume_by_proctor(pin_valid=True)
    clock.advance(1)
    assert controller.elapsed_seconds == 3


@pytest.mark.parametrize("onset,expired", [(2.0, False), (10.0, True), (11.0, True)])
def test_failure_onset_orders_correctly_against_expiry(onset, expired):
    clock = FakeClock()
    controller = SessionController(clock, 10)
    controller.start()
    clock.advance(20)
    assert controller.monitoring_failed(detected_at=onset) is not expired
    assert controller.ended is expired
    if expired:
        assert controller.end_reason == "time_expired"
        assert controller.elapsed_seconds == 10
        assert controller.monitoring_healthy
    else:
        assert controller.elapsed_seconds == onset
        controller.tick()
        assert not controller.ended


def test_delayed_failure_preserves_existing_proctor_pause(session):
    clock, controller = session
    controller.start()
    clock.advance(3)
    controller.pause_by_proctor()
    clock.advance(20)
    controller.monitoring_failed(detected_at=8)
    assert controller.elapsed_seconds == 3
    assert controller.pause_reasons == {"proctor", "monitoring", "recovery_pin"}
    controller.monitoring_recovered()
    assert controller.records[-1]["duration"] == 15
    assert not controller.running
    assert controller.resume_by_proctor(pin_valid=True)
    clock.advance(2)
    assert controller.elapsed_seconds == 5


def test_old_onset_cannot_rewrite_a_completed_timer_segment(session):
    clock, controller = session
    controller.start()
    clock.advance(3)
    controller.pause_by_proctor()
    clock.advance(10)
    controller.resume_by_proctor(pin_valid=True)
    clock.advance(20)
    controller.monitoring_failed(detected_at=1)
    # Clamp to current segment start at 13, preserving the completed 3s segment.
    assert controller.elapsed_seconds == 3
    controller.monitoring_recovered()
    assert controller.records[-1]["duration"] == 20


@pytest.mark.parametrize("onset", [float("nan"), float("inf"), 1.0])
def test_invalid_failure_onset_leaves_session_unchanged(session, onset):
    _, controller = session
    controller.start()
    with pytest.raises(ValueError, match="onset"):
        controller.monitoring_failed(detected_at=onset)
    assert controller.monitoring_healthy
    assert controller.running
    assert controller.pause_reasons == set()


def test_delayed_failure_cannot_modify_ended_session(session):
    clock, controller = session
    controller.start()
    clock.advance(10)
    controller.end()
    original_records = list(controller.records)
    clock.advance(20)
    assert not controller.monitoring_failed(detected_at=2)
    assert controller.elapsed_seconds == 10
    assert controller.records == original_records


def test_repeated_pause_does_not_lose_running_elapsed_time(session):
    clock, controller = session
    controller.start()
    clock.advance(2)
    assert controller.pause_by_proctor()
    clock.advance(4)
    assert not controller.pause_by_proctor()
    assert not controller.resume_by_proctor(pin_valid=False)
    assert controller.elapsed_seconds == 2
    assert controller.resume_by_proctor(pin_valid=True)
    assert not controller.resume_by_proctor(pin_valid=True)
    clock.advance(1)
    assert controller.elapsed_seconds == 3


def test_wall_clock_changes_do_not_affect_timer_or_recovery(session):
    clock, controller = session
    controller.start()
    clock.advance(10)
    clock.timestamp = "1900-01-01T00:00:00+00:00"
    controller.monitoring_failed()
    clock.advance(14.9)
    clock.timestamp = "2200-01-01T00:00:00+00:00"
    controller.monitoring_recovered()
    assert controller.running
    assert controller.elapsed_seconds == 10
    assert controller.records[-1]["timestamp"].startswith("2200")


@pytest.mark.parametrize("before", [99.9, 99.999])
def test_timer_expires_only_at_deadline(session, before):
    clock, controller = session
    controller.start()
    clock.advance(before)
    controller.tick()
    assert not controller.ended
    clock.advance(100 - before)
    controller.tick()
    assert controller.ended
    assert controller.end_reason == "time_expired"
    assert controller.remaining_seconds == 0
    assert controller.elapsed_seconds == 100
    clock.advance(20)
    controller.tick()
    assert len([r for r in controller.records if r["event_type"] == "session_ended"]) == 1


def test_late_ui_callback_clamps_timer_and_end_is_idempotent(session):
    clock, controller = session
    controller.start()
    clock.advance(1000)
    controller.tick()
    assert controller.elapsed_seconds == 100
    assert not controller.end("completed")
    assert controller.end_reason == "time_expired"
    assert not controller.pause_by_proctor()
    assert not controller.monitoring_failed()
    assert not controller.resume_by_proctor(pin_valid=True)


def test_pause_at_expiry_does_not_prevent_completion(session):
    clock, controller = session
    controller.start()
    clock.advance(100)
    assert not controller.pause_by_proctor()
    assert controller.end_reason == "time_expired"


def test_timer_is_independent_of_observation_and_warning_records(session):
    clock, controller = session
    controller.start()
    engine = EventEngine({EventType.GAZE_DOWN: 3.0}, 0.75, clock)
    engine.observe(Observation(clock.monotonic(), {EventType.GAZE_DOWN: None}))
    for _ in range(12):
        clock.advance(1)
        engine.observe(Observation(clock.monotonic(), {EventType.GAZE_DOWN: None}))
        controller.tick()
    assert len(engine.events) == 1
    assert engine.events[0]["state"] == "active"
    assert engine.events[0]["duration_seconds"] == 12
    assert controller.running
    assert controller.elapsed_seconds == 12


def test_invalid_lifecycle_operations_and_health_before_start(session):
    clock, controller = session
    assert not controller.pause_by_proctor()
    assert not controller.resume_by_proctor(pin_valid=True)
    assert not controller.end()
    controller.monitoring_failed()
    with pytest.raises(RuntimeError, match="healthy"):
        controller.start()
    clock.advance(30)
    controller.monitoring_recovered()
    assert not controller.recovery_pin_required
    assert not controller.running
    controller.start()
    with pytest.raises(RuntimeError, match="once"):
        controller.start()
    controller.end("proctor_ended")
    with pytest.raises(RuntimeError, match="once"):
        controller.start()
    assert controller.end_reason == "proctor_ended"


def test_ending_during_failure_finalizes_interruption(session):
    clock, controller = session
    controller.start()
    clock.advance(5)
    controller.monitoring_failed()
    clock.advance(10)
    assert controller.end("emergency")
    interruption = controller.records[-2]
    assert interruption["event_type"] == "monitoring_interruption_ended"
    assert interruption["duration"] == 10
    assert controller.elapsed_seconds == 5
    assert controller.pause_reasons == set()
    assert not controller.monitoring_recovered()


def test_pause_reasons_cannot_be_mutated_by_caller(session):
    _, controller = session
    controller.start()
    controller.pause_by_proctor()
    controller.pause_reasons.clear()
    assert not controller.running


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_timer_configuration(value):
    with pytest.raises(ValueError):
        SessionController(FakeClock(), value)
    with pytest.raises(ValueError):
        SessionController(FakeClock(), 100, value)
