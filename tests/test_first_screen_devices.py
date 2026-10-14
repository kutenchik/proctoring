"""Shared preflight controls operate before registration without extra capture."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.devices import InputDevice
from proctoring.ui.window import MainWindow
from proctoring.vision.calibration import Calibration
from proctoring.vision.types import HealthStatus


class Camera:
    def __init__(self, config):
        self.calibration = Calibration(config)
        self.started = False
        self.selected_camera_id = None
        self.opened = []
        self.latest_frame = self.latest_result = None
        self.metrics = {}
        self.identity_ready = self.identity_can_capture = False
        self.identity_baseline = None
        self.identity_status = 'Reference face not captured'
        self._switching = False

    def configure_identity(self, config): pass
    def start(self):
        if not self.started:
            self.opened.append(self.selected_camera_id)
        self.started = True
    def stop(self): self.started = False
    def health(self, now): return HealthStatus(self.started, 'Ready' if self.started else 'Not started')
    def sample(self, now): return None
    def select_camera(self, key, *, activate=True):
        if key == self.selected_camera_id:
            return False
        self.stop()
        self.selected_camera_id = key
        self.identity_baseline = None
        self.identity_ready = self.identity_can_capture = False
        self.calibration.reset()
        if activate: self.start()
        return True
    def request_identity_baseline(self):
        self.identity_baseline = SimpleNamespace(jpeg_bytes=b'\xff\xd8test',
                                                metadata={'camera': self.selected_camera_id})
        self.identity_ready = True


@pytest.fixture
def make_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    windows = []
    def make(registration=True, identity=True):
        base = load_config()
        config = replace(base, sessions_dir=tmp_path,
                         registration=replace(base.registration, enabled=registration),
                         identity=replace(base.identity, selfie_verification_enabled=identity))
        monitor = Camera(config.vision)
        controller = AppController(config, FakeClock(), mode='camera', monitor=monitor)
        window = MainWindow(controller, enable_watchdog=False)
        window.timer.stop()
        window.show()
        windows.append(window)
        for _ in range(100):
            app.processEvents()
            if controller.device_selection_ready: break
            QTest.qWait(5)
        assert controller.device_selection_ready
        return window
    yield make
    for window in windows:
        window.shutdown_ui()
        window.deleteLater()
    app.processEvents()


def choose_camera(window, key):
    combo = window.devices_widget.camera
    combo.addItem(key, InputDevice(key, key))
    combo.setCurrentIndex(combo.count()-1)
    window.devices_widget._camera_selected(combo.currentIndex())


def fill(window):
    form = window.registration_widget
    form.first_name.setText('Ada')
    form.last_name.setText('Lovelace')
    form.group_id.setText('A-1')


def test_device_controls_and_explicit_tests_precede_fields_and_selfie(make_window):
    window = make_window()
    assert window.stack.currentWidget() is window.registration_page
    assert window.registration_widget.devices_layout.itemAt(0).widget() is window.device_controls
    assert not window.registration_widget.continue_button.isEnabled()
    assert window.devices_widget.isEnabled()
    assert window.test_camera_button.isEnabled()
    choose_camera(window, 'usb-camera')
    assert window.controller.monitor.opened == []  # Selection is not capture consent.
    window.test_camera_button.click()
    assert window.controller.monitor.opened == ['usb-camera']
    assert window.controller.candidate_info is None
    assert window.controller.store is None
    audio = window.devices_widget.audio
    audio.begin_calibration = Mock()
    window.audio_check_widget._calibrate()
    audio.begin_calibration.assert_called_once()
    assert window.controller.audio is None  # Preview test doesn't enable exam audio.
    assert not window.controller.session.started


def test_registration_disabled_first_screen_still_has_shared_controls(make_window):
    window = make_window(registration=False, identity=False)
    assert window.registration_widget is None
    assert window.stack.currentWidget() is window.setup_page
    assert window.setup_devices_layout.itemAt(0).widget() is window.device_controls
    assert window.devices_widget.isEnabled()


def test_same_selected_camera_supplies_selfie_and_calibration_and_switch_invalidates_only_dependents(make_window):
    window = make_window()
    choose_camera(window, 'camera-a')
    window._test_camera()
    fill(window)
    monitor = window.controller.monitor
    monitor.identity_can_capture = True
    window._capture_identity()
    window.controller.poll_optional_workers()
    window._refresh_optional()
    assert window.controller._baseline_saved.metadata['camera'] == 'camera-a'
    assert window.controller.identity_ready
    window.registration_widget._submit()
    panel = window.device_controls
    assert window.setup_devices_layout.itemAt(0).widget() is panel
    window.controller.prepare_monitoring()
    assert monitor.opened == ['camera-a']  # Existing capture is reused.
    audio_detector = window.devices_widget.audio._detector
    audio_detector.gain = 4.
    before = window.controller.candidate_info
    choose_camera(window, 'camera-b')
    assert not window.controller.identity_ready
    assert window.controller._baseline_saved is None
    assert not monitor.calibration.ready
    assert window.stack.currentWidget() is window.registration_page
    assert window.registration_widget.devices_layout.itemAt(0).widget() is panel
    assert window.controller.candidate_info == before
    assert window.registration_widget.first_name.text() == 'Ada'
    assert window.devices_widget.audio._detector is audio_detector
    assert audio_detector.gain == 4.
    assert monitor.opened == ['camera-a', 'camera-b']
    assert window.controller.store._metadata['reference_face'] is None
    assert not window.start_button.isEnabled()


def test_mic_change_preserves_fields_gaze_and_reference(make_window):
    window = make_window()
    fill(window)
    calibration = window.controller.monitor.calibration
    calibration.reset = Mock()
    baseline = object()
    window.controller._baseline_saved = baseline
    window.devices_widget.audio.select_device = Mock(return_value=True)
    combo = window.devices_widget.microphone
    combo.addItem('Mic', InputDevice('mic', 'Mic'))
    window.devices_widget._microphone_selected(combo.count()-1)
    calibration.reset.assert_not_called()
    assert window.registration_widget.first_name.text() == 'Ada'
    assert window.controller._baseline_saved is baseline


def test_device_changes_locked_after_exam_start(make_window):
    window = make_window(registration=False, identity=False)
    window.controller.session.started = True
    window._refresh_optional()
    assert not window.devices_widget.isEnabled()
    assert not window.test_camera_button.isEnabled()
    assert not window.controller.select_camera('other')
    window.controller.session.started = False


def test_missing_camera_invalidates_controller_reference_metadata(make_window):
    window = make_window()
    controller = window.controller
    controller.monitor.unavailable_selection = Mock()
    controller._baseline_saved = object()
    controller.store = Mock()
    controller.camera_unavailable()
    assert controller._baseline_saved is None
    controller.store.update_metadata.assert_called_once_with({
        'reference_face': None, 'identity_reference': None,
        'identity_reference_invalidated': 'camera_changed'})
    controller.store = None


def test_metadata_failure_does_not_skip_camera_ui_invalidation(make_window):
    window = make_window()
    window.controller.store = Mock()
    window.controller.store.update_metadata.side_effect = OSError('disk unavailable')
    choose_camera(window, 'changed')
    assert window.stack.currentWidget() is window.registration_page
    assert not window.controller.identity_ready
    assert window.controller.storage_error == 'disk unavailable'
    assert not window.start_button.isEnabled()
    window.controller.store = None
