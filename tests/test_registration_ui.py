"""Candidate registration precedes monitoring and preserves the existing UI flow."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import Observation
from proctoring.i18n import set_language, t
from proctoring.ui.registration import RegistrationWidget
from proctoring.ui.window import MainWindow
from proctoring.vision.calibration import Calibration
from proctoring.vision.types import HealthStatus


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def registration(qt_app):
    widget = RegistrationWidget()
    widget.show()
    qt_app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def fill(widget, first="  Айдана  ", last="  Иванова  ", group="  CS-42  "):
    widget.first_name.setText(first)
    widget.last_name.setText(last)
    widget.group_id.setText(group)


def test_required_fields_block_submission_and_emit_trimmed_unicode_metadata(registration):
    received = []
    registration.submitted.connect(received.append)
    assert not registration.continue_button.isEnabled()
    registration._submit()  # Enter may call submit even while the button is disabled.
    assert not received
    assert registration.error_label.text()
    registration.first_name.setText("Айдана")
    registration.last_name.setText("Иванова")
    registration.group_id.setText("   ")
    assert not registration.continue_button.isEnabled()
    fill(registration)
    assert registration.continue_button.isEnabled()
    QTest.mouseClick(registration.continue_button, Qt.MouseButton.LeftButton)
    assert received == [{"first_name": "Айдана", "last_name": "Иванова", "group_id": "CS-42"}]


def test_optional_group_accepts_empty_value(qt_app):
    widget = RegistrationWidget(require_group=False)
    fill(widget, group="   ")
    assert widget.continue_button.isEnabled()
    assert widget.candidate_info()["group_id"] == ""
    assert "optional" in widget.group_id_label.text()
    widget.deleteLater()


@pytest.mark.parametrize("field,value", [("first_name", "Ada\x00"), ("last_name", "Lovelace\nOther"),
                                         ("group_id", "42\t43")])
def test_control_characters_cannot_be_submitted(registration, field, value):
    fill(registration)
    getattr(registration, field).setText(value)
    assert not registration.continue_button.isEnabled()
    with pytest.raises(ValueError):
        registration.candidate_info()


@pytest.mark.parametrize("locale,first_label,button", [
    ("en", "First name *", "Proceed to Calibration"),
    ("ru", "Имя *", "Перейти к калибровке"),
    ("kk", "Аты *", "Калибрлеуге өту"),
])
def test_registration_retranslates_without_replacing_entered_data(registration, locale, first_label, button):
    fill(registration)
    before = registration.candidate_info()
    set_language(locale)
    assert registration.first_name_label.text() == first_label
    assert registration.first_name.placeholderText() == first_label
    assert registration.first_name.accessibleName() == first_label
    assert registration.continue_button.text() == button
    assert registration.continue_button.isEnabled()
    assert registration.candidate_info() == before
    registration.show_submission_error()
    assert registration.error_label.text() == t("registration.invalid")


class CameraMonitor:
    def __init__(self, config):
        self.calibration = Calibration(config)
        self.started = False
        self.start_count = 0
        self.latest_frame = None
        self.latest_result = None
        self.metrics = {}

    def start(self):
        self.started = True
        self.start_count += 1

    def stop(self):
        self.started = False

    def health(self, now):
        return HealthStatus(self.started, "Healthy" if self.started else "Camera not started")

    def sample(self, now):
        return Observation(now, source="camera") if self.started else None


@pytest.fixture
def make_window(qt_app, tmp_path):
    windows = []

    def create(*, enabled=True, camera=False, require_group=True):
        config = load_config()
        config = replace(config, sessions_dir=tmp_path,
                         registration=replace(config.registration, enabled=enabled, require_group=require_group),
                         remote=replace(config.remote, enabled=False))
        monitor = CameraMonitor(config.vision) if camera else None
        controller = AppController(config, FakeClock(), mode="camera" if camera else "synthetic", monitor=monitor)
        window = MainWindow(controller, enable_watchdog=False)
        windows.append(window)
        window.timer.stop()
        window.show()
        qt_app.processEvents()
        return window

    yield create
    for window in windows:
        if window.controller.session.started and not window.controller.session.ended:
            window.controller.emergency_end("test_cleanup")
        window.close()
        window.deleteLater()
    qt_app.processEvents()


def test_registration_is_first_screen_and_submission_updates_session_state(make_window, qt_app):
    window = make_window()
    assert window.stack.currentWidget() is window.registration_page
    assert not window.setup_page.isEnabled()
    assert not window.controller.registration_complete
    window._start()
    assert not window.controller.session.started
    assert window.stack.currentWidget() is window.registration_page
    assert window.registration_widget.error_label.text() == t("registration.required")
    fill(window.registration_widget)
    QTest.mouseClick(window.registration_widget.continue_button, Qt.MouseButton.LeftButton)
    assert window.controller.registration_complete
    assert window.controller.candidate_info == {"first_name": "Айдана", "last_name": "Иванова", "group_id": "CS-42"}
    assert window.stack.currentWidget() is window.setup_page
    assert window.setup_page.isEnabled()
    assert not window.controller.session.started
    QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    assert window.controller.session.running
    assert window.stack.currentWidget() is window.exam_page


def test_camera_and_calibration_wait_for_registration(make_window):
    window = make_window(camera=True)
    monitor = window.controller.monitor
    window._retry_camera()
    window._open_camera()
    window._start()
    assert monitor.start_count == 0
    assert not window.controller.session.started
    assert not window.start_button.isEnabled()
    assert window.stack.currentWidget() is window.registration_page
    fill(window.registration_widget)
    window.registration_widget._submit()
    assert not monitor.started
    assert window.stack.currentWidget() is window.setup_page
    window._retry_camera()
    assert monitor.start_count == 1
    assert not window.start_button.isEnabled()  # Registration does not replace calibration.


@pytest.mark.parametrize("camera", [False, True])
def test_registration_disabled_keeps_original_setup(make_window, camera):
    window = make_window(enabled=False, camera=camera)
    assert window.registration_widget is None
    assert window.registration_page is None
    assert window.stack.currentWidget() is window.setup_page
    assert window.setup_page.isEnabled()
    if camera:
        window._open_camera()
        assert window.controller.monitor.started
    else:
        window._start()
        assert window.controller.session.running


def test_window_language_selector_preserves_registered_identity(make_window):
    window = make_window()
    fill(window.registration_widget)
    for locale in ("ru", "kk", "en"):
        window.language_selector.setCurrentIndex(window.language_selector.findData(locale))
        assert window.registration_widget.continue_button.text() == t("registration.continue")
        assert window.registration_widget.first_name.text() == "  Айдана  "
    window.registration_widget._submit()
    assert window.controller.candidate_info["first_name"] == "Айдана"


def test_remote_enabled_privacy_message_does_not_claim_local_only(make_window):
    window = make_window()
    window.controller.config = replace(window.controller.config,
        remote=replace(window.controller.config.remote, enabled=True, webhook_url="https://example.test/events"))
    description = window._data_description()
    assert "also sent" in description
    assert "stays on this computer" not in description
    for locale in ("en", "ru", "kk"):
        set_language(locale)
        assert t("registration.remote_data") != "registration.remote_data"


def test_window_shutdown_closes_dispatcher_with_bounded_wait(make_window):
    window = make_window()
    window.controller.close_remote = Mock()
    window.shutdown_ui()
    window.controller.close_remote.assert_called_once_with(timeout=2.0)
