"""Actual-rate buffer evidence survives jitter; stale native backlog is invalid."""
import numpy as np
import pytest

from proctoring.audio.monitor import AudioMonitor
from proctoring.clock import FakeClock
from proctoring.domain import EventType, Observation
from proctoring.events import EventEngine
from proctoring.settings import AudioConfig


def test_sequential_buffers_use_sample_rate_not_read_completion_jitter():
    clock = FakeClock()
    engine = EventEngine({EventType.VOICE_DETECTED: 2.}, .75, clock,
                         max_observation_gap=.5, accumulate_sample_durations=True)
    class Stream:
        samplerate, channels, dtype, read_available = 48000, 1, 'float32', 0
        count = 0
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, size):
            assert size == 2400
            if self.count == 40:
                monitor._stop.set()
                return np.zeros((size, 1), np.float32), False
            clock.advance(.05 if self.count == 0 else .07 if self.count % 2 else .03)
            self.count += 1
            return np.full((size, 1), .1, np.float32), False
    monitor = AudioMonitor(AudioConfig(enabled=True), clock, lambda **_: Stream())
    monitor._detector.set_custom_threshold(.05)
    monitor._detector.baseline = .001
    # Drain from the worker synchronously for this test: no UI callback count.
    from PySide6.QtCore import Qt
    observations = []
    def consume(_):
        for sample in monitor.drain():
            observations.append(sample)
            engine.observe(Observation(sample.timestamp, {EventType.VOICE_DETECTED: None}
                           if sample.above_ambient else {}, 'audio_energy', sample.duration_seconds))
    monitor.audio_level_changed.connect(consume, Qt.ConnectionType.DirectConnection)
    monitor.start()
    monitor._thread.join(2.)
    consume(0)
    assert len(observations) == 40
    assert all(sample.duration_seconds == .05 for sample in observations)
    assert observations[-1].timestamp == pytest.approx(2.)
    assert engine.events[0]['activity_seconds'] == pytest.approx(2.)
    assert len(engine.events) == 1
    monitor.stop()


def test_native_capture_backlog_is_not_relabelled_as_fresh_activity():
    clock = FakeClock()
    class Stream:
        samplerate, channels, dtype, read_available = 48000, 1, 'float32', 48000
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, size):
            clock.advance(.05)
            return np.full((size, 1), .1, np.float32), False
    monitor = AudioMonitor(AudioConfig(enabled=True), clock, lambda **_: Stream())
    from PySide6.QtCore import Qt
    monitor.audio_level_changed.connect(lambda _: monitor._stop.set(), Qt.ConnectionType.DirectConnection)
    monitor.start()
    monitor._thread.join(1.)
    sample = monitor.drain()[0]
    assert not sample.healthy and not sample.above_ambient
    assert clock.monotonic()-sample.timestamp == pytest.approx(1.)
    assert sample.duration_seconds == .05
    monitor.stop()


def test_same_device_worker_restart_preserves_committed_gain_threshold_and_baseline():
    clock = FakeClock()
    class Stream:
        samplerate, channels, dtype = 48000, 1, 'float32'
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, size):
            clock.advance(.05)
            return np.full((size, 1), .00534811, np.float32), False
    monitor = AudioMonitor(AudioConfig(enabled=True), clock, lambda **_: Stream())
    detector = monitor._detector
    detector.processed_speech = .04278487
    detector._commit_threshold(.01725431, 'adaptive', .00023392, .01725431)
    detector.gain = detector.applied_gain = 8.
    detector.baseline = .00023392
    detector._check_state = 'ready'
    monitor.device_key = 'same-resolved-microphone'
    from PySide6.QtCore import Qt
    monitor.audio_level_changed.connect(lambda _: monitor._stop.set(), Qt.ConnectionType.DirectConnection)
    for _ in range(2):
        monitor.start()
        monitor._thread.join(1.)
        sample = monitor.drain()[0]
        assert sample.above_ambient
        assert sample.rms == pytest.approx(.04278488, rel=1e-5)
        monitor.stop()
        assert monitor._detector is detector
        assert detector.threshold == .01725431 and detector.gain == 8.
        assert detector.baseline == .00023392
        assert monitor.device_key == 'same-resolved-microphone'
    detector.begin_exam()
    silence = detector.observe(np.zeros((2400, 1)), clock.monotonic()+.05, 48000)
    assert not silence.above_ambient  # no positive silent tail from moving RMS
