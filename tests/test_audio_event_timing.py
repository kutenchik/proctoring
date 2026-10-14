"""Only audio uses measured positive-buffer time and candidate gap tolerance."""
import pytest

from proctoring.clock import FakeClock
from proctoring.domain import EventType, Observation
from proctoring.events import EventEngine

VOICE = EventType.VOICE_DETECTED


def setup():
    clock = FakeClock()
    return clock, EventEngine({VOICE: 2.0}, .75, clock, max_observation_gap=.5,
                             accumulate_sample_durations=True)


def feed(clock, engine, positive, duration=.05):
    clock.advance(duration)
    return engine.observe(Observation(clock.monotonic(), {VOICE: None} if positive else {},
                                      'audio_energy', duration))


def test_repeated_interword_gaps_keep_candidate_but_do_not_count_silence():
    clock, engine = setup()
    positive = 0
    changes = []
    for index in range(100):
        active = index % 10 < 7
        positive += active
        changes += feed(clock, engine, active)
        if positive < 40:
            assert not engine.events
        elif positive == 40:
            break
    assert len(engine.events) == 1
    assert engine.events[0]['activity_seconds'] == pytest.approx(2.)
    assert engine.events[0]['duration_seconds'] > 2.
    assert [c['action'] for c in changes] == ['activated']


def test_exact_two_seconds_of_positive_buffers_activate_without_ui_tick_time():
    clock, engine = setup()
    for index in range(39):
        feed(clock, engine, True)
        assert not engine.events
    assert feed(clock, engine, True)[0]['action'] == 'activated'
    assert engine.candidate_duration(VOICE) == pytest.approx(2.)


def test_candidate_ends_after_configured_silence_and_new_episode_starts_from_zero():
    clock, engine = setup()
    for _ in range(20): feed(clock, engine, True)
    for _ in range(15): feed(clock, engine, False)
    assert engine.candidate_duration(VOICE) == 0.
    for _ in range(39): feed(clock, engine, True)
    assert not engine.events
    assert feed(clock, engine, True)[0]['action'] == 'activated'


def test_sustained_activity_deduplicates_and_later_episode_reactivates_after_clearing():
    clock, engine = setup()
    changes = []
    for _ in range(100): changes += feed(clock, engine, True)
    assert len(engine.events) == 1
    assert sum(c['action'] == 'activated' for c in changes) == 1
    for _ in range(16): changes += feed(clock, engine, False)
    assert engine.events[0]['state'] == 'closed'
    for _ in range(40): changes += feed(clock, engine, True)
    assert len(engine.events) == 2
    assert sum(c['action'] == 'activated' for c in changes) == 2


def test_stale_duplicate_reordered_and_overlapping_buffers_never_add_duration():
    clock, engine = setup()
    feed(clock, engine, True)
    evidence = Observation(clock.monotonic(), {VOICE: None}, 'audio_energy', .05)
    for _ in range(50): engine.observe(evidence)
    assert engine.candidate_duration(VOICE) == .05
    clock.advance(.01)
    engine.observe(Observation(clock.monotonic(), {VOICE: None}, 'audio_energy', .05))
    assert engine.candidate_duration(VOICE) == pytest.approx(.06)  # no double-counted interval
    clock.advance(1)
    engine.observe(Observation(.1, {VOICE: None}, 'audio_energy', .05))
    assert engine.candidate_duration(VOICE) == 0.
    assert engine.last_reset_reason == 'stale_observation'
    assert not engine.events


def test_audio_gap_interrupts_candidate_instead_of_counting_missing_samples():
    clock, engine = setup()
    for _ in range(30): feed(clock, engine, True)
    clock.advance(1)
    feed(clock, engine, True)
    assert engine.candidate_duration(VOICE) == pytest.approx(.05)
    assert engine.last_reset_reason == 'observation_gap'
    assert not engine.events


def test_buffer_crossing_interrupt_boundary_only_credits_new_audio():
    clock, engine = setup()
    for _ in range(10): feed(clock, engine, True)
    clock.advance(.5)
    engine.interrupt('audio_unavailable')
    clock.advance(.03)
    engine.observe(Observation(clock.monotonic(), {VOICE: None}, 'audio_energy', .05))
    assert engine.candidate_duration(VOICE) == pytest.approx(.03)
    assert not engine.events


@pytest.mark.parametrize('duration', [-1., float('nan'), float('inf'), .6])
def test_invalid_measured_durations_rejected(duration):
    clock, engine = setup()
    with pytest.raises(ValueError):
        engine.observe(Observation(0., {VOICE: None}, 'audio_energy', duration))
    assert not engine.events
