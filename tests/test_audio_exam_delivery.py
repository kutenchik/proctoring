"""Deterministic audio -> real controller/journal/Qt delivery; no human validation."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
import json
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from proctoring.audio.monitor import AudioMonitor, AudioObservation
from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.devices import InputDevice
from proctoring.domain import EVENT_LABELS, EventType
from proctoring.settings import AudioConfig, RegistrationConfig
from proctoring.ui.window import MainWindow


VOICE = EventType.VOICE_DETECTED


def samples(rms, rate=48000):
    phase = np.arange(int(rate * .05)) * 2 * np.pi * 220 / rate
    return (np.sin(phase) * rms * np.sqrt(2)).astype("float32")[:, None]


def calibrate_audio(audio, clock):
    """Exercise the actual quiet/speak computation with explicitly synthetic input."""
    assert audio.begin_calibration()
    levels = [.003, .0053, .008, .006, 0., 0.]
    for index in range(154):
        clock.advance(.05)
        rms = .00003 if index <= 30 else levels[index % len(levels)]
        sample = audio._detector.observe(samples(rms), clock.monotonic(), 48000)
        if sample is not None:
            audio._observations.append(sample)
    assert audio.check_status["state"] == "ready"
    # Let the committed gain settle during setup, before the first exam buffer.
    for _ in range(25):
        clock.advance(.05)
        audio._detector.observe(samples(0.), clock.monotonic(), 48000)
    return audio._detector.gain, audio._detector.threshold


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def delivery(qt_app, tmp_path, monkeypatch):
    config = replace(load_config(), sessions_dir=tmp_path, snapshots_enabled=False,
                     audio=AudioConfig(enabled=True), registration=RegistrationConfig(enabled=True))
    controller = AppController(config, FakeClock())
    assert controller.audio is not None
    # All processing/controller/UI are real; hardware opening alone is suppressed.
    monkeypatch.setattr(controller.audio, "start", Mock())
    controller.audio.selection = InputDevice("test-fifine", "Test Fifine", 18, "test-signature")
    controller.audio.device_key = "test-fifine"
    controller.audio.resolved_device = "Test Fifine · mock WASAPI input"
    controller.audio.stream_format = {"sample_rate": 48000., "channels": 1, "dtype": "float32"}
    controller.audio._set_status("available", "Synthetic PCM supplied by test")
    window = MainWindow(controller, enable_watchdog=False)
    window.timer.stop()
    if window.audio_check_widget is not None:
        window.audio_check_widget.timer.stop()
    yield controller, window
    if controller.session.started and not controller.session.ended:
        controller.end("test_cleanup")
    window.shutdown_ui()
    window.close()
    qt_app.processEvents()


def register_and_start(controller):
    controller.register_candidate({"first_name": "Synthetic", "last_name": "Candidate", "group_id": "TEST"})
    controller.start()
    assert controller.session.running
    assert not controller.protection.blocking_enabled


def feed(controller, rms, *, poll=True):
    controller.clock.advance(.05)
    sample = controller.audio._detector.observe(samples(rms), controller.clock.monotonic(), 48000)
    if sample is not None:
        controller.audio._observations.append(sample)
    if poll:
        controller.step()
    return sample


def journal(controller):
    return [json.loads(line) for line in (controller.store.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def test_calibration_registration_exam_warning_journal_ui_and_summary(delivery):
    controller, window = delivery
    audio = controller.audio
    detector = audio._detector
    gain, threshold = calibrate_audio(audio, controller.clock)
    assert gain == 8. and 0 < threshold < .05
    controller.poll_optional_workers()
    assert not controller.review_events and not controller.session.started
    assert controller.session.elapsed_seconds == 0
    register_and_start(controller)
    assert controller.audio is audio and audio._detector is detector
    assert (detector.gain, detector.threshold) == (gain, threshold)
    assert detector.check_status["threshold_source"] == "adaptive"
    assert audio.device_key == "test-fifine" and detector._exam_started
    assert audio.drain() == []  # Setup speech is flushed at the exam boundary.

    positive_count = 0
    for index in range(80):
        positive = index % 10 < 7
        sample = feed(controller, .0053 if positive else 0.)
        assert sample.above_ambient is positive
        positive_count += positive
        if positive_count < 40:
            assert not controller.review_events
        if positive_count == 40:
            break
    assert len(controller.review_events) == 1
    event = controller.review_events[0]
    assert event["event_type"] == VOICE.value and event["state"] == "active"
    assert event["activity_seconds"] == pytest.approx(2.)
    assert event["duration_seconds"] > 2.  # Inter-word silence is not credited.
    assert controller.session.running and not controller.session.pause_reasons
    assert controller.session.elapsed_seconds == pytest.approx((index + 1) * .05)
    window._refresh()
    assert window.event_table.rowCount() == 1
    assert window.event_table.item(0, 1).text() == EVENT_LABELS[VOICE]
    assert EVENT_LABELS[VOICE] in window.preview.text()
    activations = [row for row in journal(controller) if row.get("action") == "activated"]
    assert len(activations) == 1 and activations[0]["event_type"] == VOICE.value

    for _ in range(60):
        feed(controller, .0053)
    assert len(controller.review_events) == 1
    for _ in range(16):
        feed(controller, 0.)
    assert controller.review_events[0]["state"] == "closed"
    for _ in range(40):
        feed(controller, .0053)
    assert len(controller.review_events) == 2
    controller.end("completed")
    window._refresh()
    saved = json.loads((controller.store.path / "summary.json").read_text(encoding="utf-8"))
    assert saved["event_counts"] == {VOICE.value: 2}
    assert saved["audio_check"]["threshold"] == pytest.approx(threshold)
    assert saved["audio_check"]["gain"] == gain
    assert saved["candidate"]["group_id"] == "TEST"
    assert EVENT_LABELS[VOICE] in window.summary_events.text()
    assert len([row for row in journal(controller) if row.get("action") == "activated"]) == 2


def test_batched_audio_is_drained_independently_of_camera_or_ui_frequency(delivery):
    controller, _ = delivery
    calibrate_audio(controller.audio, controller.clock)
    register_and_start(controller)
    for _ in range(10):
        for _ in range(4):
            feed(controller, .0053, poll=False)
        controller.step()  # 5 Hz controller versus 20 Hz captured audio.
    assert len(controller.review_events) == 1
    assert controller.review_events[0]["activity_seconds"] == pytest.approx(2.)


@pytest.mark.parametrize("failure", ["silence", "stale", "unavailable"])
def test_short_activity_then_silence_stale_data_or_loss_never_activates_or_pauses(delivery, failure):
    controller, window = delivery
    calibrate_audio(controller.audio, controller.clock)
    register_and_start(controller)
    for _ in range(20):
        feed(controller, .0053)
    assert not controller.review_events
    if failure == "silence":
        for _ in range(18):
            feed(controller, 0.)
    elif failure == "stale":
        # Preserve normal healthy synthetic camera ticks while no audio arrives.
        for _ in range(6):
            controller.clock.advance(.1)
            controller.step()
        controller.audio._observations.append(AudioObservation(controller.clock.monotonic() - .6,
                                                               True, .1, .001))
        controller.step()
    else:
        controller.audio._set_status("unavailable", "Mock microphone removed")
        controller.clock.advance(.1)
        controller.step()
    assert controller.audio_events.candidate_duration(VOICE) == 0
    assert not controller.review_events and controller.session.running
    assert controller.session.elapsed_seconds > 1.
    window._refresh()
    assert window.event_table.rowCount() == 0
    assert not [row for row in journal(controller) if row.get("event_type") == VOICE.value]


def test_audio_disabled_constructs_no_worker_or_audio_event_engine(tmp_path, monkeypatch):
    construction = Mock(side_effect=AssertionError("Disabled audio constructed a worker"))
    monkeypatch.setattr("proctoring.audio.monitor.AudioMonitor", construction)
    controller = AppController(replace(load_config(), sessions_dir=tmp_path,
                                       audio=AudioConfig(enabled=False)), FakeClock())
    try:
        controller.start()
        for _ in range(30):
            controller.clock.advance(.1)
            controller.step()
        assert controller.audio is None and controller.audio_events is None
        assert controller.session.running and not controller.review_events
        construction.assert_not_called()
    finally:
        controller.end("test_cleanup")
        controller.close_optional_workers()


def test_same_device_worker_recreation_keeps_committed_gain_and_low_threshold(monkeypatch):
    clock = FakeClock()
    audio = AudioMonitor(AudioConfig(enabled=True), clock)
    actual_start = audio.start
    monkeypatch.setattr(audio, "start", Mock())
    gain, threshold = calibrate_audio(audio, clock)
    original = audio._detector
    audio.selection = InputDevice("same", "Test mic", 1, "same-signature")
    audio.device_key = "same"
    reads = []

    class Stream:
        samplerate, channels, dtype = 48000, 1, "float32"
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, size):
            assert size == 2400
            reads.append(size)
            clock.advance(.05)
            return samples(.0053), False

    audio._stream_factory = lambda **_: Stream()
    audio.audio_level_changed.connect(lambda _: audio._stop.set(), Qt.ConnectionType.DirectConnection)
    monkeypatch.setattr(audio, "start", actual_start)
    try:
        audio.start()
        audio._thread.join(1.)
        first = audio._thread
        audio.stop()
        audio.begin_exam()
        audio._thread.join(1.)
        assert audio._thread is not first and len(reads) == 2
        assert audio._detector is original
        assert (original.gain, original.threshold) == (gain, threshold)
        assert original.check_status["threshold_source"] == "adaptive"
        assert audio.device_key == "same"
        assert audio.drain()[-1].above_ambient
    finally:
        audio.stop()
