"""Identity controls reuse the camera pipeline and remain an explicit gate."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from unittest.mock import Mock
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QCloseEvent

from proctoring.i18n import set_language, t
from proctoring.ui.registration import RegistrationWidget
from proctoring.ui.window import MainWindow
from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.settings import SystemChecksConfig, IdentityConfig
from proctoring.vision.calibration import Calibration
from proctoring.vision.types import HealthStatus


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def widget(app):
    widget = RegistrationWidget(identity_enabled=True)
    widget.first_name.setText("Test")
    widget.last_name.setText("Candidate")
    widget.group_id.setText("DEMO-1")
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_selfie_gate_blocks_both_button_and_enter_until_baseline_ready(widget):
    submitted, opened, captured = [], [], []
    widget.submitted.connect(submitted.append)
    widget.identity_open_requested.connect(opened.append)
    widget.identity_capture_requested.connect(lambda: captured.append(True))
    assert not widget.continue_button.isEnabled()
    assert not widget.identity_capture_button.isEnabled()
    widget._submit()
    assert not submitted
    assert widget.error_label.text() == t("identity.required")
    widget._open_identity()
    assert opened == [{"first_name": "Test", "last_name": "Candidate", "group_id": "DEMO-1"}]
    widget.identity_started()
    assert widget.first_name.isReadOnly()
    widget.set_identity_state(ready=False, status="Waiting for a fresh valid face", can_capture=False)
    assert not widget.identity_capture_button.isEnabled()
    widget.set_identity_state(ready=False, status="Ready to capture", can_capture=True)
    assert widget.identity_capture_button.isEnabled()
    widget.identity_capture_button.click()
    assert captured == [True]
    assert not widget.continue_button.isEnabled()  # Async persistence must finish.
    widget.set_identity_state(ready=True, status="Reference saved", can_capture=True)
    assert widget.continue_button.isEnabled()
    widget._submit()
    assert submitted == opened


@pytest.mark.parametrize("locale", ["en", "ru", "kk"])
def test_selfie_labels_localize_without_changing_baseline_readiness(widget, locale):
    set_language(locale)
    assert widget.identity_capture_button.text() == t("identity.capture")
    assert widget.identity_note.text() == t("identity.notice")
    assert not widget.continue_button.isEnabled()
    assert widget.first_name.text() == "Test"


def test_disabled_selfie_keeps_original_registration(app):
    widget = RegistrationWidget(identity_enabled=False)
    widget.first_name.setText("Test")
    widget.last_name.setText("Candidate")
    widget.group_id.setText("DEMO")
    assert widget.identity_box.isHidden()
    assert widget.continue_button.isEnabled()
    widget.deleteLater()


def test_multimonitor_blocks_start_and_unblocks_when_removed(app, tmp_path):
    config = replace(load_config(), sessions_dir=tmp_path, external_url="", allowed_domains=(),
                     system_checks=SystemChecksConfig(block_multimonitor=True))
    controller = AppController(config, FakeClock())
    screens = [object(), object()]
    controller.system_checker._screens_provider = lambda: screens
    window = MainWindow(controller, enable_watchdog=False)
    window.timer.stop()
    try:
        assert not window.start_button.isEnabled()
        window._start()  # Direct invocation still checks preflight.
        assert not controller.session.started
        assert "Multiple monitors" in window.preflight_label.text()
        screens.pop()
        window._refresh()
        assert window.start_button.isEnabled()
        window._start()
        assert controller.session.started
        controller.emergency_end("test_cleanup")
    finally:
        window.shutdown_ui()
        window.deleteLater()


class IdentityCamera:
    def __init__(self, config):
        self.calibration = Calibration(config)
        self.started = False
        self.latest_frame = self.latest_result = None
        self.metrics = {}
        self.identity_ready = False
        self.identity_can_capture = False
        self.identity_status = "Reference face not captured"
        self.identity_baseline = None
        self.start_count = self.capture_count = 0
    def configure_identity(self, config):
        self.identity_config = config
    def start(self):
        self.start_count += 1
        self.started = True
    def stop(self):
        self.started = False
    def health(self, now):
        return HealthStatus(self.started, "Healthy" if self.started else "Camera not started")
    def request_identity_baseline(self):
        self.capture_count += 1
    def sample(self, now):
        return None


def test_selfie_uses_same_monitor_and_saved_baseline_does_not_bypass_gaze(app, tmp_path):
    config = replace(load_config(), sessions_dir=tmp_path, external_url="", allowed_domains=(),
                     identity=IdentityConfig(selfie_verification_enabled=True))
    monitor = IdentityCamera(config.vision)
    controller = AppController(config, FakeClock(), mode="camera", monitor=monitor)
    window = MainWindow(controller, enable_watchdog=False)
    window.timer.stop()
    registration = window.registration_widget
    try:
        assert window.stack.currentWidget() is window.registration_page
        assert monitor.start_count == 0
        for field, text in ((registration.first_name, "Test"), (registration.last_name, "Candidate"),
                            (registration.group_id, "DEMO")):
            field.setText(text)
        registration._open_identity()
        assert monitor.start_count == 1
        assert not registration.continue_button.isEnabled()
        monitor.identity_can_capture = True
        window._refresh()
        registration.identity_capture_button.click()
        assert monitor.capture_count == 1
        assert not controller.identity_ready
        monitor.identity_baseline = SimpleNamespace(jpeg_bytes=b"\xff\xd8test", metadata={"purpose": "test fixture"})
        monitor.identity_ready = True
        window._tick()
        assert controller.identity_ready
        assert (controller.store.path / "reference_face.jpg").exists()
        assert registration.continue_button.isEnabled()
        registration._submit()
        assert window.stack.currentWidget() is window.setup_page
        assert not window.start_button.isEnabled()  # Gaze calibration remains required.
        assert not controller.session.started
        assert monitor.start_count == 1  # No second webcam or capture pipeline.
    finally:
        window.shutdown_ui()
        window.deleteLater()


def test_report_close_wait_keeps_gui_alive_without_rearming_protection(app, monkeypatch, tmp_path):
    controller = AppController(replace(load_config(), sessions_dir=tmp_path), FakeClock())
    window = MainWindow(controller, enable_watchdog=False)
    window.timer.stop()
    controller._report_job = SimpleNamespace(status="running", close=Mock())
    callbacks = []
    monkeypatch.setattr("proctoring.ui.window.QTimer.singleShot", lambda delay, callback: callbacks.append(callback))
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert len(callbacks) == 1
    assert not controller.protection.armed
    window.closeEvent(QCloseEvent())
    assert len(callbacks) == 1  # One retry timer only.
    controller._report_job.status = "complete"
    window.closeEvent(QCloseEvent())
    assert not window.timer.isActive()
    window.deleteLater()


@pytest.mark.parametrize("locale", ["en", "ru", "kk"])
def test_selfie_registration_layout_remains_scrollable_at_laptop_size(app, tmp_path, locale):
    config = replace(load_config(), sessions_dir=tmp_path, identity=IdentityConfig(True))
    controller = AppController(config, FakeClock(), mode="camera", monitor=IdentityCamera(config.vision))
    window = MainWindow(controller, enable_watchdog=False)
    window.timer.stop()
    try:
        set_language(locale)
        window.resize(1040, 760)
        window.show()
        app.processEvents()
        reg = window.registration_widget
        assert window.width() == 1040 and window.height() == 760
        assert reg.identity_preview.geometry().bottom() < reg.identity_status_label.geometry().top()
        assert reg.identity_status_label.geometry().bottom() < reg.identity_open_button.geometry().top()
        window.registration_page.ensureWidgetVisible(reg.continue_button)
        app.processEvents()
        viewport = window.registration_page.viewport()
        for button in (reg.identity_capture_button, reg.continue_button):
            top = button.mapTo(viewport, button.rect().topLeft()).y()
            bottom = button.mapTo(viewport, button.rect().bottomRight()).y()
            assert 0 <= top < bottom < viewport.height()
    finally:
        window.shutdown_ui()
        window.deleteLater()
