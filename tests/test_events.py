import math

import pytest

from proctoring.clock import FakeClock
from proctoring.domain import EventType, Observation
from proctoring.events import EventEngine


DEFAULTS = {
    EventType.PHONE_VISIBLE: 1.0,
    EventType.SECOND_PERSON: 1.0,
    EventType.PHONE_RAISED: 1.25,
    EventType.GAZE_DOWN: 3.0,
    EventType.GAZE_LEFT: 3.0,
    EventType.GAZE_RIGHT: 3.0,
    EventType.FACE_ABSENT: 3.0,
}


@pytest.fixture
def setup():
    clock = FakeClock()
    return clock, EventEngine(DEFAULTS, 0.75, clock)


def sample(clock, engine, time, conditions=None):
    clock.advance(time - clock.monotonic())
    return engine.observe(Observation(time, conditions or {}))


@pytest.mark.parametrize("kind,threshold", DEFAULTS.items())
def test_exact_thresholds_and_candidate_transition(setup, kind, threshold):
    clock, engine = setup
    assert sample(clock, engine, 0, {kind: 0.8}) == []
    assert engine.states[kind] == "candidate"
    sample(clock, engine, threshold / 2, {kind: 0.8})
    assert sample(clock, engine, threshold - 0.001, {kind: 0.8}) == []
    assert engine.events == []
    changes = sample(clock, engine, threshold, {kind: 0.8})
    assert len(changes) == 1
    assert changes[0]["action"] == "activated"
    assert changes[0]["duration_seconds"] == threshold
    assert engine.states[kind] == "active"


def test_raised_phone_label_is_exact(setup):
    clock, engine = setup
    sample(clock, engine, 0, {EventType.PHONE_RAISED: 0.9})
    sample(clock, engine, 1.25, {EventType.PHONE_RAISED: 0.9})
    assert engine.events[0]["label"] == "Phone raised — possible screen capture attempt."


def test_false_condition_resets_candidate(setup):
    clock, engine = setup
    kind = EventType.PHONE_VISIBLE
    sample(clock, engine, 0, {kind: 0.8})
    sample(clock, engine, 0.9)
    assert engine.states[kind] == "closed"
    sample(clock, engine, 1.0, {kind: 0.8})
    assert sample(clock, engine, 1.9, {kind: 0.8}) == []
    assert len(sample(clock, engine, 2.0, {kind: 0.8})) == 1


def test_hysteresis_boundary_excludes_clearing_from_duration(setup):
    clock, engine = setup
    kind = EventType.PHONE_VISIBLE
    sample(clock, engine, 0, {kind: 0.8})
    sample(clock, engine, 1, {kind: 0.8})
    changes = sample(clock, engine, 1.25)
    assert changes[0]["action"] == "clearing"
    assert engine.states[kind] == "clearing"
    assert sample(clock, engine, 1.999) == []
    closed = sample(clock, engine, 2.0)[0]
    assert closed["state"] == "closed"
    assert closed["duration_seconds"] == 1.0
    assert closed["close_reason"] == "condition_cleared"
    assert engine.states[kind] == "closed"


def test_brief_instability_keeps_same_event_and_peak_confidence(setup):
    clock, engine = setup
    kind = EventType.PHONE_VISIBLE
    sample(clock, engine, 0, {kind: 0.8})
    sample(clock, engine, 1, {kind: 0.8})
    sample(clock, engine, 1.1)
    recovered = sample(clock, engine, 1.8, {kind: 0.95})
    assert recovered[0]["action"] == "updated"
    assert len(engine.events) == 1
    assert engine.events[0]["state"] == "active"
    assert engine.events[0]["confidence"] == 0.95
    assert engine.events[0]["duration_seconds"] == 1.8


def test_positive_after_expired_hysteresis_starts_new_candidate(setup):
    clock, engine = setup
    kind = EventType.PHONE_VISIBLE
    sample(clock, engine, 0, {kind: 0.8})
    sample(clock, engine, 1, {kind: 0.8})
    sample(clock, engine, 1.25)
    changes = sample(clock, engine, 2.0, {kind: 0.8})
    assert [change["action"] for change in changes] == ["closed"]
    assert engine.states[kind] == "candidate"
    sample(clock, engine, 3.0, {kind: 0.8})
    assert len(engine.events) == 2
    assert engine.events[0]["event_id"] != engine.events[1]["event_id"]


def test_sustained_detection_activates_once_and_returns_copies(setup):
    clock, engine = setup
    changes = []
    for tick in range(101):
        changes.extend(sample(clock, engine, tick / 10, {EventType.PHONE_VISIBLE: 0.9}))
    assert len(engine.events) == 1
    assert sum(change["action"] == "activated" for change in changes) == 1
    assert engine.events[0]["duration_seconds"] == 10.0
    copied = engine.events
    copied[0]["state"] = "corrupted"
    changes[-1]["state"] = "corrupted"
    assert engine.events[0]["state"] == "active"


def test_duplicate_and_reordered_observations_do_not_advance_or_clear(setup):
    clock, engine = setup
    kind = EventType.PHONE_VISIBLE
    sample(clock, engine, 0, {kind: 0.8})
    sample(clock, engine, 1, {kind: 0.8})
    assert engine.observe(Observation(1)) == []
    assert engine.observe(Observation(0.5)) == []
    clock.advance(1)
    assert engine.observe(Observation(1)) == []
    assert engine.events[0]["state"] == "active"
    assert engine.events[0]["duration_seconds"] == 1


def test_large_observation_gap_cannot_accumulate_candidate_time(setup):
    clock, engine = setup
    kind = EventType.GAZE_DOWN
    sample(clock, engine, 0, {kind: None})
    sample(clock, engine, 1, {kind: None})
    sample(clock, engine, 4, {kind: None})
    sample(clock, engine, 5, {kind: None})
    sample(clock, engine, 6, {kind: None})
    assert engine.events == []
    sample(clock, engine, 7, {kind: None})
    assert len(engine.events) == 1
    assert engine.events[0]["duration_seconds"] == 3
    assert engine.events[0]["confidence"] is None


def test_large_gap_closes_active_event_before_new_candidate(setup):
    clock, engine = setup
    kind = EventType.PHONE_VISIBLE
    sample(clock, engine, 0, {kind: 0.8})
    sample(clock, engine, 1, {kind: 0.8})
    closed = sample(clock, engine, 4, {kind: 0.8})[0]
    assert closed["close_reason"] == "observation_gap"
    assert closed["duration_seconds"] == 1
    assert engine.states[kind] == "candidate"


def test_stale_sample_cannot_activate_evidence(setup):
    clock, engine = setup
    kind = EventType.PHONE_VISIBLE
    sample(clock, engine, 0, {kind: 0.8})
    clock.advance(4)
    assert engine.observe(Observation(1, {kind: 0.8})) == []
    assert engine.states[kind] == "closed"
    assert engine.events == []


def test_stale_sample_closes_active_event(setup):
    clock, engine = setup
    kind = EventType.PHONE_VISIBLE
    sample(clock, engine, 0, {kind: 0.8})
    sample(clock, engine, 1, {kind: 0.8})
    clock.advance(4)
    closed = engine.observe(Observation(2, {kind: 0.8}))[0]
    assert closed["close_reason"] == "stale_observation"
    assert closed["duration_seconds"] == 1


@pytest.mark.parametrize("step", [0.05, 0.2, 0.5, 1.0])
def test_thresholds_are_time_based_at_varied_sampling_rates(step):
    clock = FakeClock()
    kind = EventType.GAZE_DOWN
    engine = EventEngine({kind: 3.0}, 0.75, clock)
    for tick in range(int(round(3.0 / step)) + 1):
        sample(clock, engine, round(tick * step, 8), {kind: None})
    assert len(engine.events) == 1
    assert engine.events[0]["duration_seconds"] == 3.0


def test_interrupt_closes_active_resets_candidate_and_drops_queued_samples(setup):
    clock, engine = setup
    conditions = {EventType.PHONE_VISIBLE: 0.8, EventType.GAZE_LEFT: None}
    sample(clock, engine, 0, conditions)
    sample(clock, engine, 1, conditions)
    clock.advance(0.5)
    changes = engine.interrupt()
    assert len(changes) == 1
    assert changes[0]["close_reason"] == "monitoring_unavailable"
    assert changes[0]["duration_seconds"] == 1
    assert all(state == "closed" for state in engine.states.values())
    assert engine.observe(Observation(1.2, conditions)) == []
    sample(clock, engine, 1.5, conditions)
    assert len(engine.events) == 1
    assert engine.states[EventType.PHONE_VISIBLE] == "candidate"


def test_close_all_is_idempotent_and_does_not_count_shutdown_time(setup):
    clock, engine = setup
    sample(clock, engine, 0, {EventType.PHONE_VISIBLE: 0.8})
    sample(clock, engine, 1, {EventType.PHONE_VISIBLE: 0.8})
    clock.advance(10)
    closed = engine.close_all()[0]
    assert closed["duration_seconds"] == 1
    assert closed["close_reason"] == "session_ended"
    assert engine.close_all() == []


def test_wall_clock_jumps_do_not_change_durations(setup):
    clock, engine = setup
    kind = EventType.PHONE_VISIBLE
    clock.timestamp = "2026-10-04T20:00:00+00:00"
    sample(clock, engine, 0, {kind: 0.8})
    clock.timestamp = "2025-01-01T00:00:00+00:00"
    sample(clock, engine, 1, {kind: 0.8})
    assert engine.events[0]["duration_seconds"] == 1
    assert engine.events[0]["activated_timestamp"] == clock.timestamp
    clock.timestamp = "2030-01-01T00:00:00+00:00"
    sample(clock, engine, 1.25)
    closed = sample(clock, engine, 2)[0]
    assert closed["duration_seconds"] == 1
    assert closed["closed_timestamp"] == clock.timestamp


@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan])
def test_invalid_thresholds_are_rejected(value):
    with pytest.raises(ValueError):
        EventEngine({EventType.PHONE_VISIBLE: value}, 0.75, FakeClock())


@pytest.mark.parametrize("field", ["clearing_seconds", "max_observation_gap"])
def test_invalid_timing_configuration_is_rejected(field):
    args = dict(thresholds=DEFAULTS, clearing_seconds=0.75, clock=FakeClock(), max_observation_gap=2)
    args[field] = 0
    with pytest.raises(ValueError):
        EventEngine(**args)


def test_empty_thresholds_are_rejected():
    with pytest.raises(ValueError):
        EventEngine({}, 0.75, FakeClock())


def test_future_timestamp_is_rejected(setup):
    clock, engine = setup
    with pytest.raises(ValueError, match="future"):
        engine.observe(Observation(1, {EventType.PHONE_VISIBLE: 0.8}))


@pytest.mark.parametrize("confidence", [-0.1, 1.1, math.inf, math.nan])
def test_invalid_confidence_is_rejected(setup, confidence):
    clock, engine = setup
    with pytest.raises(ValueError, match="confidence"):
        engine.observe(Observation(0, {EventType.PHONE_VISIBLE: confidence}))
