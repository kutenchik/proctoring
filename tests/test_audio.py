from dataclasses import replace
import threading
import time
from unittest.mock import Mock

import numpy as np
import pytest

from proctoring.audio.monitor import AudioMonitor, AudioObservation, EnergyDetector
from proctoring.clock import FakeClock, SystemClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType
from proctoring.settings import AudioConfig


def energy(value):
    return np.full((1600, 1), value, dtype=np.float32)


def test_ambient_calibration_then_energy_without_speech_claim():
    detector = EnergyDetector(AudioConfig(enabled=True))
    for step in range(30):
        sample = detector.observe(energy(.01), step / 10)
        assert sample.baseline is None and not sample.above_ambient
    assert detector.observe(energy(.01), 3.).baseline == pytest.approx(.01)
    assert not detector.observe(energy(.02), 3.1).above_ambient
    assert detector.observe(energy(.8), 3.2).above_ambient
    assert detector.observe(energy(.8), 3.2) is None
    assert detector.observe(energy(.8), 3.) is None


def test_missing_audio_resets_ambient_and_does_not_reuse_last_activity():
    detector = EnergyDetector(AudioConfig(enabled=True))
    for step in range(32):
        detector.observe(energy(.01), step / 10)
    assert detector.observe(energy(.8), 3.2).above_ambient
    sample = detector.observe(energy(.8), 5.)
    assert not sample.above_ambient and sample.baseline is None


@pytest.mark.parametrize("samples", [np.array([]), energy(float("nan")), energy(float("inf")), energy(2.)])
def test_bad_audio_cannot_create_evidence(samples):
    with pytest.raises(ValueError):
        EnergyDetector(AudioConfig()).observe(samples, 0.)


def test_disabled_audio_opens_no_stream_and_starts_no_thread():
    factory = Mock()
    monitor = AudioMonitor(AudioConfig(), SystemClock(), factory)
    monitor.start()
    monitor.stop()
    assert monitor._thread is None
    factory.assert_not_called()
    assert monitor.drain() == []


def test_missing_microphone_fails_soft_on_worker():
    thread_ids = []
    def missing(**kwargs):
        thread_ids.append(threading.get_ident())
        raise OSError("No audio input")
    monitor = AudioMonitor(AudioConfig(enabled=True), SystemClock(), missing)
    monitor.start()
    monitor._thread.join(1.)
    assert monitor.status == {"state": "unavailable", "reason": "OSError"}
    assert thread_ids != [threading.get_ident()]
    assert monitor.drain() == []
    monitor.stop()


def test_audio_buffer_is_bounded_and_overflow_is_an_explicit_invalid_observation():
    clock = FakeClock()
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            clock.advance(.1)
            if clock.monotonic() > 5.:
                raise OSError("Disconnected")
            return energy(.02), clock.monotonic() > 4.5
    monitor = AudioMonitor(AudioConfig(enabled=True), clock, lambda **kwargs: Stream())
    monitor.start()
    monitor._thread.join(2.)
    samples = monitor.drain()
    assert len(samples) <= 40
    assert any(not sample.healthy for sample in samples)
    assert monitor.drain() == []
    monitor.stop()


def test_audio_uses_existing_engine_duration_dedup_snapshots_and_never_pauses(tmp_path):
    clock = FakeClock()
    config = replace(load_config(), sessions_dir=tmp_path, audio=AudioConfig(enabled=True), snapshots_enabled=False)
    controller = AppController(config, clock)
    class Source:
        status = {"state": "available", "reason": "Energy only"}
        pending = []
        def start(self): pass
        def stop(self): pass
        def drain(self):
            values, self.pending = self.pending, []
            return values
    controller.audio = Source()
    try:
        assert controller.audio_status == "Audio: available\nEnergy only"
        controller.start()
        for index in range(21):
            timestamp = index / 10
            clock.advance(timestamp - clock.monotonic())
            controller.audio.pending = [AudioObservation(timestamp, True, .6, .01)]
            controller.step()
            if index < 20:
                assert not controller.audio_events.events
        assert controller.review_events[0]["event_type"] == "VOICE_DETECTED"
        assert controller.review_events[0]["duration_seconds"] == 2.
        assert controller.review_events[0]["event_id"].startswith("audio-")
        controller.monitor.set_condition(EventType.PHONE_VISIBLE, True)
        for index in range(21, 41):
            clock.advance(.1)
            controller.audio.pending = [AudioObservation(clock.monotonic(), True, .6, .01)]
            controller.step()
        assert {event["event_type"] for event in controller.review_events} == {"VOICE_DETECTED", "phone_visible"}
        assert len({event["event_id"] for event in controller.review_events}) == 2
        assert controller.session.running and controller.session.elapsed_seconds == pytest.approx(4.)
        controller.audio.status = {"state": "unavailable", "reason": "No input"}
        assert controller.audio_status == "Audio: unavailable"
        clock.advance(.1)
        controller.step()
        assert controller.session.running
        assert controller.audio_events.events[0]["state"] == "closed"
    finally:
        controller.end()
        controller.close_remote()
    assert controller.summary["event_count"] == 2


def _calibrated_detector(ambient=.02, *, sensitivity=1.):
    detector = EnergyDetector(AudioConfig(enabled=True))
    if sensitivity != 1.:
        detector.set_sensitivity(sensitivity)
    assert detector.begin_calibration()
    for index in range(51):
        detector.observe(energy(ambient), index * .05)
    assert detector.check_status["state"] == "speak"
    return detector


def test_adaptive_quiet_window_is_2_5_seconds_and_speak_spike_commits_threshold():
    detector = EnergyDetector(AudioConfig(enabled=True))
    assert detector.begin_calibration()
    for index in range(50):
        detector.observe(energy(.02), index * .05)
    assert detector.check_status["state"] == "ambient"
    detector.observe(energy(.02), 2.5)
    assert detector.check_status["state"] == "speak"
    assert detector.check_status["ambient"] == pytest.approx(.02)
    assert detector.check_status["recommended_threshold"] == pytest.approx(.10)
    assert detector.custom_threshold is None  # Quiet samples alone do not verify input gain.
    for timestamp in (2.55, 2.60, 2.65):
        detector.observe(energy(.2), timestamp)
        assert detector.check_status["state"] == "speak"
    detector.observe(energy(.2), 2.70)
    assert detector.check_status["state"] == "ready"
    assert detector.custom_threshold == pytest.approx(.10)
    assert detector.custom_threshold > detector.baseline
    detector.begin_exam()
    assert detector.observe(energy(.12), 2.75).above_ambient
    assert detector.custom_threshold == pytest.approx(.10)
    assert not detector.begin_calibration()  # Exam observations cannot re-fit the quiet floor.


@pytest.mark.parametrize("ambient,recommended", [(.01, .09), (.02, .10), (.10, .25)])
def test_adaptive_formula_respects_both_ambient_terms(ambient, recommended):
    detector = _calibrated_detector(ambient)
    assert detector.check_status["recommended_threshold"] == pytest.approx(recommended)
    assert detector.check_status["threshold"] == pytest.approx(recommended)


def test_short_spike_is_not_verification_and_no_signal_times_out():
    detector = _calibrated_detector()
    detector.observe(energy(.8), 2.55)
    detector.observe(energy(.02), 2.60)
    for index in range(53, 211):
        detector.observe(energy(.02), index * .05)
    assert detector.check_status["state"] == "no_signal"
    assert detector.custom_threshold is None
    assert detector.begin_calibration()
    assert detector.check_status["state"] == "ambient"


def test_too_noisy_ambient_is_not_clamped_into_a_ready_check():
    detector = EnergyDetector(AudioConfig(enabled=True))
    detector.begin_calibration()
    for index in range(51):
        detector.observe(energy(.30), index * .05)
    assert detector.check_status["recommended_threshold"] == pytest.approx(.75)
    assert detector.check_status["state"] == "noisy"
    assert detector.custom_threshold is None
    assert detector.observe(energy(.95), 2.55).above_ambient is False


def test_sensitivity_scales_session_recommendation_without_remeasuring_ambient():
    detector = _calibrated_detector(.02)
    detector.set_sensitivity(.5)
    assert detector.check_status["threshold"] == pytest.approx(.05)
    for index in range(51, 55):
        detector.observe(energy(.1), index * .05)
    assert detector.check_status["state"] == "ready"
    detector.set_sensitivity(2.)
    assert detector.custom_threshold == pytest.approx(.2)
    assert detector.check_status["ambient"] == pytest.approx(.02)
    assert detector.check_status["state"] == "idle"
    assert detector.check_status["threshold_source"] == "manual"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -.1, .01, .41, True, "0.1"])
def test_custom_threshold_rejects_nonfinite_or_out_of_bounds(value):
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock())
    with pytest.raises(ValueError):
        monitor.set_custom_threshold(value)


def test_custom_threshold_updates_active_detector_and_survives_gap_without_stale_activity():
    detector = _calibrated_detector()
    for index in range(51, 55):
        detector.observe(energy(.2), index * .05)
    detector.begin_exam()
    detector.set_custom_threshold(.3)
    assert not detector.observe(energy(.2), 2.75).above_ambient
    detector.set_custom_threshold(.1)
    assert detector.observe(energy(.2), 2.80).above_ambient
    sample = detector.observe(energy(.2), 4.)
    assert not sample.above_ambient and sample.baseline is None
    assert detector.custom_threshold == .1
    assert detector.check_status["state"] == "no_signal"


def test_incomplete_check_at_exam_start_does_not_commit_provisional_threshold():
    detector = _calibrated_detector()
    assert detector.custom_threshold is None
    detector.begin_exam()
    for index in range(51, 61):
        detector.observe(energy(.3), index * .05)
    assert detector.custom_threshold is None
    assert detector.check_status["state"] == "idle"
    assert detector.threshold == pytest.approx(.17)


def test_monitor_processes_every_50ms_buffer_and_emits_20hz_normalized_levels():
    from PySide6.QtCore import Qt
    clock = FakeClock()
    reads, levels, samples, threads = [], [], [], []
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            threads.append(threading.get_ident())
            reads.append(size)
            clock.advance(.05)
            return np.full((size, 1), .02, np.float32), False
    monitor = AudioMonitor(AudioConfig(enabled=True), clock, lambda **kwargs: Stream())
    def received(value):
        levels.append((clock.monotonic(), value))
        samples.extend(monitor.drain())
        if len(levels) == 20:
            monitor._stop.set()
    monitor.audio_level_changed.connect(received, Qt.ConnectionType.DirectConnection)
    monitor.start()
    monitor._thread.join(1.)
    assert len(reads) == len(samples) == len(levels) == 20
    assert reads == [800] * 20
    assert all(value == pytest.approx(.02) for _, value in levels)
    assert all(0 <= value <= 1 for _, value in levels)
    assert all(b[0] - a[0] == pytest.approx(.05) for a, b in zip(levels, levels[1:]))
    assert threading.get_ident() not in threads
    monitor.stop()


def test_monitor_begin_exam_flushes_preview_and_uses_existing_thread():
    started, release = threading.Event(), threading.Event()
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            started.set()
            release.wait(1.)
            monitor._stop.set()
            return np.full((size, 1), .02, np.float32), False
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock(), lambda **kwargs: Stream())
    monitor.start()
    assert started.wait(1.)
    worker = monitor._thread
    monitor._observations.append(AudioObservation(0., True, .8, .01))
    monitor.begin_exam()
    assert monitor._thread is worker and monitor.drain() == []
    release.set()
    monitor.stop()


def test_failed_device_can_retry_without_restarting_an_alive_worker():
    attempts = []
    def missing(**kwargs):
        attempts.append(threading.get_ident())
        raise OSError("No microphone")
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock(), missing)
    assert monitor.begin_calibration()
    monitor._thread.join(1.)
    first = monitor._thread
    assert monitor.check_status["state"] == "unavailable"
    assert monitor.latest_level == 0.
    assert monitor.begin_calibration()
    monitor._thread.join(1.)
    assert monitor._thread is not first and len(attempts) == 2
    assert monitor.check_status["state"] == "unavailable"
    monitor.stop()


def test_stale_level_does_not_show_ready_or_reuse_the_last_meter_reading():
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock())
    monitor._detector = _calibrated_detector()
    for index in range(51, 55):
        monitor._detector.observe(energy(.2), index * .05)
    monitor.clock.advance(2.7)
    monitor._set_status("available")
    assert monitor.check_status["state"] == "ready"
    monitor.clock.advance(.6)
    assert monitor.check_status["state"] == "no_signal"
    assert monitor.latest_level == 0.


@pytest.mark.parametrize("adaptive", [True, False])
def test_manual_slider_works_before_calibration_and_without_adaptive_mode(adaptive):
    detector = EnergyDetector(AudioConfig(enabled=True, adaptive_calibration=adaptive))
    detector.set_sensitivity(.5)
    assert detector.threshold == pytest.approx(.075)
    assert detector.check_status["threshold_source"] == "manual"
    assert detector.check_status["state"] == "idle"
    assert detector.check_status["committed_ambient"] is None
    detector.set_sensitivity(2.)
    assert detector.threshold == pytest.approx(.30)  # Does not compound previous setting.
    if not adaptive:
        assert not detector.begin_calibration()
    for index in range(61):
        detector.observe(energy(.01), index * .05)
    detector.set_sensitivity(.5)
    assert detector.observe(energy(.30), 3.05).above_ambient
    assert detector.check_status["state"] == "idle"


def test_explicit_manual_override_during_speak_is_not_a_verified_calibration():
    detector = _calibrated_detector()
    detector.set_custom_threshold(.12)
    assert detector.threshold == .12
    assert detector.check_status["threshold_source"] == "manual"
    assert detector.check_status["state"] == "idle"
    assert detector.check_status["committed_ambient"] is None
    for index in range(51, 70):
        detector.observe(energy(.50), index * .05)
    assert detector.check_status["state"] == "idle"


def test_failed_retry_keeps_original_threshold_and_its_committed_provenance():
    detector = _calibrated_detector(.02)
    for index in range(51, 55):
        detector.observe(energy(.20), index * .05)
    original = detector.check_status
    assert original["state"] == "ready"
    assert original["threshold_source"] == "adaptive"
    assert original["committed_ambient"] == pytest.approx(.02)
    assert original["committed_recommended_threshold"] == pytest.approx(.10)
    detector.begin_calibration()
    for index in range(55, 107):
        detector.observe(energy(.30), index * .05)
    status = detector.check_status
    assert status["state"] == "noisy"
    assert status["ambient"] == pytest.approx(.30)
    assert status["recommended_threshold"] == pytest.approx(.75)
    assert status["committed_ambient"] == original["committed_ambient"]
    assert status["committed_recommended_threshold"] == original["committed_recommended_threshold"]
    assert status["committed_threshold"] == original["committed_threshold"]
    detector.set_sensitivity(2.)
    assert detector.threshold == pytest.approx(.20)  # Original verified reference, not failed .75.
    assert detector.check_status["state"] == "noisy"
    detector.observe(energy(.01), 6.)
    assert detector.check_status["state"] != "ready"
    assert detector.check_status["committed_ambient"] == pytest.approx(.02)


@pytest.mark.parametrize("late_error", [False, True])
def test_read_finishing_after_stop_does_not_publish_activity_or_resurrect_status(late_error):
    from PySide6.QtCore import Qt
    started, release = threading.Event(), threading.Event()
    levels = []
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            started.set()
            release.wait(2.)
            if late_error:
                raise OSError("Late device failure after shutdown")
            return np.full((size, 1), .8, np.float32), False
    monitor = AudioMonitor(AudioConfig(enabled=True), FakeClock(), lambda **kwargs: Stream())
    monitor.audio_level_changed.connect(levels.append, Qt.ConnectionType.DirectConnection)
    monitor.start()
    assert started.wait(1.)
    monitor.stop(timeout=0.)
    assert monitor.status["state"] == "stopped"
    release.set()
    monitor._thread.join(1.)
    assert not monitor._thread.is_alive()
    assert monitor.status["state"] == "stopped"
    assert monitor.drain() == []
    assert levels == []
    assert monitor.latest_level == 0.


def test_plain_start_after_device_failure_restores_unverified_preview_without_adaptive_mode():
    from PySide6.QtCore import Qt
    clock = FakeClock()
    attempts, levels = [], []
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            clock.advance(.05)
            return np.full((size, 1), .02, np.float32), False
    def factory(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise OSError("Microphone initially unavailable")
        return Stream()
    monitor = AudioMonitor(AudioConfig(enabled=True, adaptive_calibration=False), clock, factory)
    monitor.set_custom_threshold(.12)
    monitor.start()
    monitor._thread.join(1.)
    assert monitor.check_status["state"] == "unavailable"
    def received(value):
        levels.append(value)
        if len(levels) == 3:
            monitor._stop.set()
    monitor.audio_level_changed.connect(received, Qt.ConnectionType.DirectConnection)
    monitor.start()
    monitor._thread.join(1.)
    assert len(attempts) == 2 and len(levels) == 3
    assert monitor.check_status["state"] == "idle"
    assert monitor.latest_level == pytest.approx(.02)
    assert monitor.check_status["committed_threshold"] == .12
    assert monitor.check_status["threshold_source"] == "manual"
    assert not monitor.begin_calibration()
    monitor.stop()
