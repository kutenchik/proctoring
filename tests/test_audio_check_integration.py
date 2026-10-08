from dataclasses import replace
import json
from pathlib import Path

import pytest

from proctoring.audio.monitor import AudioMonitor, AudioObservation
from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.settings import AudioConfig, RegistrationConfig


@pytest.mark.parametrize("values", [
    {"adaptive_calibration": "yes"}, {"min_energy_threshold": 0},
    {"min_energy_threshold": float("nan")}, {"max_energy_threshold": float("inf")},
    {"max_energy_threshold": 1.1}, {"min_energy_threshold": .4, "max_energy_threshold": .4},
    {"min_energy_threshold": .5, "max_energy_threshold": .4},
])
def test_invalid_adaptive_settings_are_rejected(values):
    with pytest.raises(ValueError):
        AudioConfig(**values)


def test_toml_exposes_adaptive_audio_fields(isolated_default_config, tmp_path):
    source = Path(isolated_default_config).read_text(encoding="utf-8")
    source = source.replace("min_energy_threshold = 0.05", "min_energy_threshold = 0.06")
    source = source.replace("max_energy_threshold = 0.40", "max_energy_threshold = 0.35")
    path = tmp_path / "adaptive.toml"
    path.write_text(source, encoding="utf-8")
    config = load_config(path)
    assert config.audio.adaptive_calibration is True
    assert config.audio.min_energy_threshold == .06
    assert config.audio.max_energy_threshold == .35
    assert config.public_dict()["audio"]["max_energy_threshold"] == .35


class PreviewAudio:
    def __init__(self):
        self.status = {"state": "not_started", "reason": ""}
        self.check_status = {"state": "ready", "ambient": .02, "recommended_threshold": .1,
                             "threshold": .1, "sensitivity": 1.0}
        self.pending = []
        self.opens = 0
        self.exam_starts = 0

    def start(self):
        if self.status["state"] == "not_started":
            self.opens += 1
            self.status = {"state": "available", "reason": "Energy only; speech is not verified"}

    def begin_exam(self):
        self.exam_starts += 1
        self.pending.clear()

    def drain(self):
        result, self.pending = self.pending, []
        return result

    def stop(self):
        self.status = {"state": "stopped", "reason": ""}


@pytest.fixture
def controller(tmp_path):
    config = replace(load_config(), sessions_dir=tmp_path, audio=AudioConfig(enabled=True),
                     snapshots_enabled=False)
    app = AppController(config, FakeClock())
    app.audio = PreviewAudio()
    yield app
    if app.session.started and not app.session.ended:
        app.end()
    app.close_remote()


def test_preview_waits_for_registration_and_reuses_audio_worker(controller):
    app = controller
    app.config = replace(app.config, registration=RegistrationConfig(enabled=True))
    app.prepare_audio_check()
    assert app.audio.opens == 0
    app.register_candidate({"first_name": "Demo", "last_name": "Candidate", "group_id": "A"})
    app.prepare_audio_check()
    app.prepare_audio_check()
    assert app.audio.opens == 1
    app.start()
    app.prepare_audio_check()
    assert app.audio.opens == 1 and app.audio.exam_starts == 1


def test_preview_sound_cannot_seed_exam_duration_and_threshold_is_saved(controller):
    app = controller
    app.prepare_audio_check()
    app.audio.pending = [AudioObservation(index / 10, True, .4, .02) for index in range(30)]
    app.clock.advance(3.)
    app.poll_optional_workers()
    assert not app.review_events and not app.session.started and app.store is None
    app.start()
    assert app.audio.pending == []
    assert not app.review_events
    # A buffer racing with the boundary is also excluded, even if queued later.
    app.audio.pending = [AudioObservation(2.9, True, .4, .02)]
    app.step()
    for index in range(21):
        timestamp = 3. + index / 10
        app.clock.advance(timestamp - app.clock.monotonic())
        app.audio.pending = [AudioObservation(timestamp, True, .4, .02)]
        app.step()
        if index < 20:
            assert not app.review_events
    assert len(app.review_events) == 1
    assert app.review_events[0]["event_type"] == "VOICE_DETECTED"
    assert app.review_events[0]["duration_seconds"] == pytest.approx(2.)
    assert app.session.running and app.session.elapsed_seconds == pytest.approx(2.)
    metadata = json.loads((app.store.path / "session.json").read_text(encoding="utf-8"))
    assert metadata["audio_check"]["threshold"] == .1
    assert metadata["audio_check"]["ambient"] == .02
    app.end()
    assert app.summary["audio_check"]["threshold"] == .1


def test_queued_stale_audio_does_not_create_a_new_exam_event(controller):
    app = controller
    app.start()
    app.clock.advance(4.)
    app.audio.pending = [AudioObservation(index / 10, True, .4, .02) for index in range(21)]
    app.step()
    assert not app.review_events
    assert app.session.running


def test_missing_microphone_does_not_gate_or_pause_exam(controller):
    app = controller
    def missing(**kwargs):
        raise PermissionError("Permission denied")
    app.audio = AudioMonitor(app.config.audio, app.clock, stream_factory=missing)
    app.prepare_audio_check()
    app.audio._thread.join(1.)
    assert app.audio.status["state"] == "unavailable"
    for _ in range(3):
        app.prepare_audio_check()  # no repeated reopen attempts from UI ticks
    app.start()
    app.audio._thread.join(1.)
    app.clock.advance(.1)
    app.step()
    assert app.session.running and not app.review_events
    assert app.audio.check_status["state"] == "unavailable"
