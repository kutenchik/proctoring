"""Mic setup presentation and lifecycle use fake input; no hardware or HTTP."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea

from proctoring.audio.monitor import AudioMonitor
from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.i18n import set_language, t
from proctoring.settings import AudioConfig, RegistrationConfig
from proctoring.ui.audio_check import AudioCheckWidget
from proctoring.ui.window import MainWindow
from proctoring.vision.calibration import Calibration
from proctoring.vision.types import HealthStatus


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeAudio:
    def __init__(self):
        self.check_status = {"state": "idle", "rms": .025, "threshold": .15,
                             "ambient": None, "progress": 0, "sensitivity": 1.}
        self.begin_calibration = Mock()
        self.set_sensitivity = Mock()
        self.start = Mock()


@pytest.fixture
def widget(app):
    mic = FakeAudio()
    widget = AudioCheckWidget(mic, AudioConfig(enabled=True))
    widget.resize(460, 350)
    widget.show()
    app.processEvents()
    yield widget, mic
    widget.timer.stop()
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_level_meter_tracks_latest_state_and_renders_after_resize(widget, app):
    widget, mic = widget
    assert widget.timer.interval() == 50
    mic.check_status.update(rms=.27, threshold=.19)
    widget.refresh()
    assert widget.meter.value() == 270
    assert widget.meter.threshold == .19
    assert "0.270" in widget.level_label.text()
    for width in (380, 600):
        widget.resize(width, 350)
        app.processEvents()
        assert not widget.grab().isNull()


def test_interactive_ambient_then_speak_then_ready(widget):
    widget, mic = widget
    widget.calibrate_button.click()
    mic.begin_calibration.assert_called_once_with()
    mic.check_status.update(state="ambient", progress=.2)
    widget.refresh()
    assert "Remain quiet" in widget.status_label.text()
    assert "2.0" in widget.status_label.text()
    assert not widget.calibrate_button.isEnabled()
    assert not widget.sensitivity_slider.isEnabled()
    mic.check_status.update(state="speak", threshold=.105)
    widget.refresh()
    assert "Now speak" in widget.status_label.text()
    assert "ready" not in widget.status_label.text()
    mic.check_status.update(state="ready")
    widget.refresh()
    assert "Microphone ready" in widget.status_label.text()
    assert widget.calibrate_button.isEnabled()


@pytest.mark.parametrize("locale", ["en", "ru", "kk"])
def test_live_translation_preserves_levels_and_calibration(widget, locale):
    widget, mic = widget
    mic.check_status.update(state="ready", threshold=.1)
    widget.refresh()
    set_language(locale)
    assert widget.title() == t("audio_check.title")
    assert widget.status_label.text() == t("audio_check.ready", threshold=.1)
    assert widget.meter.threshold == .1
    mic.begin_calibration.assert_not_called()


def test_manual_sensitivity_is_threshold_scaling_and_locks_during_exam(widget):
    widget, mic = widget
    widget.sensitivity_slider.setValue(100)
    mic.set_sensitivity.assert_called_with(.5)
    widget.sensitivity_slider.setValue(0)
    mic.set_sensitivity.assert_called_with(1.5)
    widget.set_exam_active(True)
    assert not widget.calibrate_button.isEnabled()
    assert not widget.sensitivity_slider.isEnabled()
    assert not widget.timer.isActive()
    before = mic.set_sensitivity.call_count
    widget._sensitivity_changed(50)
    widget._calibrate()
    assert mic.set_sensitivity.call_count == before
    mic.begin_calibration.assert_not_called()


def test_missing_mic_has_clear_status_and_explicit_retry(widget):
    widget, mic = widget
    mic.check_status.update(state="unavailable", rms=0.)
    widget.refresh()
    assert widget.status_label.text() == "Microphone unavailable (Audio monitoring disabled)"
    assert widget.meter.value() == 0
    assert widget.calibrate_button.isEnabled()
    assert not widget.sensitivity_slider.isEnabled()
    widget.calibrate_button.click()
    mic.start.assert_called_once_with()
    mic.begin_calibration.assert_not_called()


def test_pending_threshold_is_distinct_from_a_committed_calibration(widget):
    widget, mic = widget
    mic.check_status.update(state="speak", ambient=.025, threshold_source="fallback")
    widget.refresh()
    assert "Ambient 0.025" in widget.level_label.text()
    assert "test candidate (not committed)" in widget.level_label.text()
    mic.check_status.update(state="ready", threshold_source="adaptive")
    widget.refresh()
    assert "Threshold source: calibrated" in widget.level_label.text()


@pytest.mark.parametrize("source", ["adaptive", "manual"])
@pytest.mark.parametrize("state", ["no_signal", "noisy", "unavailable"])
def test_failed_retry_displays_ambient_for_retained_committed_threshold(widget, source, state):
    widget, mic = widget
    mic.check_status.update(state=state, ambient=.2, committed_ambient=.02,
                            threshold_source=source, threshold=.1)
    widget.refresh()
    assert "Ambient 0.020" in widget.level_label.text()
    assert "Ambient 0.200" not in widget.level_label.text()
    mic.check_status.update(state="speak")
    widget.refresh()
    assert "Ambient 0.200" in widget.level_label.text()


@pytest.mark.parametrize("state", ["no_signal", "noisy"])
def test_failed_check_is_not_presented_as_ready(widget, state):
    widget, mic = widget
    mic.check_status["state"] = state
    widget.refresh()
    assert widget.status_label.text() == t(f"audio_check.{state}")
    assert widget.calibrate_button.isEnabled()


def test_fixed_mode_explains_disabled_auto_calibration(app):
    widget = AudioCheckWidget(FakeAudio(), AudioConfig(enabled=True, adaptive_calibration=False))
    try:
        assert not widget.calibrate_button.isEnabled()
        assert widget.sensitivity_slider.isEnabled()
        assert widget.status_label.text() == t("audio_check.fixed")
        widget.monitor.check_status["state"] = "unavailable"
        widget.refresh()
        assert widget.calibrate_button.isEnabled()
        assert widget.calibrate_button.text() == t("audio_check.retry")
        widget.calibrate_button.click()
        widget.monitor.start.assert_called_once_with()
    finally:
        widget.timer.stop()
        widget.deleteLater()


def test_setup_starts_shared_mic_only_after_registration(app, monkeypatch, tmp_path):
    config = replace(load_config(), sessions_dir=tmp_path,
                     audio=AudioConfig(enabled=True), registration=RegistrationConfig(enabled=True))
    controller = AppController(config, FakeClock())
    start = Mock(side_effect=lambda: controller.audio._set_status("available"))
    monkeypatch.setattr(controller.audio, "start", start)
    window = MainWindow(controller, enable_watchdog=False)
    window.timer.stop()
    try:
        assert window.audio_check_widget is not None
        assert isinstance(window.setup_page, QScrollArea)
        start.assert_not_called()
        window._submit_registration({"first_name": "Test", "last_name": "Candidate", "group_id": "DEMO"})
        start.assert_called_once_with()
        window._refresh_optional()
        start.assert_called_once_with()
        controller.audio._set_status("unavailable")
        controller.audio._detector.unavailable("Mock missing microphone")
        window._refresh()
        assert window.start_button.isEnabled()
        window._start()
        assert controller.session.running
        assert not window.audio_check_widget.calibrate_button.isEnabled()
        assert not window.audio_check_widget.sensitivity_slider.isEnabled()
        controller.emergency_end("test_cleanup")
    finally:
        window.shutdown_ui()
        window.deleteLater()


def test_disabled_audio_has_no_widget_or_device_start(app, monkeypatch, tmp_path):
    start = Mock()
    monkeypatch.setattr(AudioMonitor, "start", start)
    controller = AppController(replace(load_config(), sessions_dir=tmp_path), FakeClock())
    window = MainWindow(controller, enable_watchdog=False)
    try:
        assert window.audio_check_widget is None
        start.assert_not_called()
    finally:
        window.shutdown_ui()
        window.deleteLater()


def test_camera_setup_embeds_shared_audio_check_without_starting_webcam(app, monkeypatch, tmp_path):
    config = replace(load_config(), sessions_dir=tmp_path, audio=AudioConfig(enabled=True))
    camera = SimpleNamespace(calibration=Calibration(config.vision), latest_result=None,
                             latest_frame=None, metrics={}, start=Mock(), stop=Mock(),
                             health=lambda _now: HealthStatus(False, "Camera not started"))
    controller = AppController(config, FakeClock(), mode="camera", monitor=camera)
    start = Mock(side_effect=lambda: controller.audio._set_status("available"))
    monkeypatch.setattr(controller.audio, "start", start)
    window = MainWindow(controller, enable_watchdog=False)
    try:
        assert window.audio_check_widget.monitor is controller.audio
        assert window.stack.currentWidget() is window.setup_page
        start.assert_called_once_with()
        camera.start.assert_not_called()
        assert not window.start_button.isEnabled()  # Gaze calibration still required.
    finally:
        window.shutdown_ui()
        window.deleteLater()


@pytest.mark.parametrize("mode", ["synthetic", "camera"])
def test_pre_exam_emergency_stops_microphone_without_automatic_restart(app, monkeypatch, tmp_path, mode):
    config = replace(load_config(), sessions_dir=tmp_path, audio=AudioConfig(enabled=True))
    camera = None
    if mode == "camera":
        camera = SimpleNamespace(calibration=Calibration(config.vision), latest_result=None,
                                 latest_frame=None, metrics={}, start=Mock(), stop=Mock(),
                                 health=lambda _now: HealthStatus(False, "Camera not started"))
    controller = AppController(config, FakeClock(), mode=mode, monitor=camera)
    start = Mock(side_effect=lambda: controller.audio._set_status("available"))
    stop = Mock(wraps=controller.audio.stop)
    monkeypatch.setattr(controller.audio, "start", start)
    monkeypatch.setattr(controller.audio, "stop", stop)
    window = MainWindow(controller, enable_watchdog=False)
    try:
        start.assert_called_once_with()
        window._emergency()
        stop.assert_called_once_with()
        assert controller.audio.status["state"] == "stopped"
        window._refresh()
        start.assert_called_once_with()
        assert not controller.session.started
    finally:
        window.shutdown_ui()
        window.deleteLater()
