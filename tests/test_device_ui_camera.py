from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.devices import InputDevice
from proctoring.ui.devices import DevicesWidget
from proctoring.vision.qt_camera import NamedCamera
from proctoring.vision.monitor import RealMonitor
from proctoring.vision.settings import VisionConfig


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_qt_source_pixels_are_owned_bgr_and_late_frames_are_rejected(app):
    camera = NamedCamera(VisionConfig(), FakeClock(), 'stable-camera-id')
    image = QImage(4, 3, QImage.Format.Format_RGB888)
    image.fill('red')
    camera._accept_image(image)
    assert camera.latest.image.shape == (3, 4, 3)
    assert list(camera.latest.image[0, 0]) == [0, 0, 255]
    image.fill('blue')
    assert list(camera.latest.image[0, 0]) == [0, 0, 255]
    camera.stop(0)
    camera._accept_image(image)
    assert camera.latest is None


class OldCamera:
    alive = False
    def stop(self, timeout=0): self.closed = True


def test_camera_switch_invalidates_gaze_discards_old_result_and_uses_exact_id(monkeypatch):
    clock = FakeClock()
    old = OldCamera()
    calibration = Mock()
    monitor = RealMonitor(VisionConfig(), clock, calibration, camera_factory=lambda *_: old)
    monitor._latest_result = 'old-result'
    monitor._latest_face = 'old-face'
    opened = []
    def start():
        monitor._camera = monitor._camera_factory(monitor.config, clock)
        opened.append(monitor._camera.device_id)
    monkeypatch.setattr(monitor, 'start', start)
    assert monitor.select_camera('camera-moniker-hex')
    monitor._switch_thread.join(1)
    assert opened == ['camera-moniker-hex'] and old.closed
    calibration.reset.assert_called_once()
    assert monitor.latest_result is None and monitor.latest_face is None
    monitor.set_exam_active(True)
    assert not monitor.select_camera('other')
    monitor.stop(0)


def test_camera_driver_still_alive_prevents_competing_capture(monkeypatch):
    old = OldCamera(); old.alive = True
    monitor = RealMonitor(VisionConfig(), FakeClock(), camera_factory=lambda *_: old)
    start = Mock(); monkeypatch.setattr(monitor, 'start', start)
    monitor.select_camera('new'); monitor._switch_thread.join(1)
    start.assert_not_called()
    assert not monitor.health(0).healthy
    assert 'still releasing' in monitor.health(0).reason
    assert monitor.latest_frame is None


def test_saved_missing_camera_and_mic_do_not_open_an_unrelated_input(app, tmp_path):
    config = replace(load_config(), audio=replace(load_config().audio, enabled=False))
    monitor = SimpleNamespace(select_camera=Mock(), unavailable_selection=Mock())
    controller = SimpleNamespace(config=config, audio=None, clock=FakeClock(), monitor=monitor,
                                 session=SimpleNamespace(started=False))
    settings = QSettings(str(tmp_path/'prefs.ini'), QSettings.Format.IniFormat)
    settings.setValue('camera', 'missing-camera'); settings.setValue('microphone', 'missing-mic')
    widget = DevicesWidget(controller, settings=settings)
    widget._loaded((0, {'cameras': [InputDevice('other', 'Other camera')],
                        'microphones': [InputDevice('system-default', 'Default')]}))
    assert widget.camera.currentData() == 'missing'
    assert widget.microphone.currentData() == 'missing'
    monitor.unavailable_selection.assert_called_once()
    monitor.select_camera.assert_not_called()
    assert widget.audio._selection_error
    widget.shutdown(); widget.deleteLater(); app.processEvents()


def test_audio_only_switch_never_resets_gaze_or_enables_exam_audio(app, tmp_path):
    controller = AppController(load_config())
    monitor = SimpleNamespace(select_camera=Mock(), calibration=Mock())
    controller.monitor = monitor
    widget = DevicesWidget(controller, settings=QSettings(str(tmp_path/'prefs.ini'), QSettings.Format.IniFormat))
    widget.audio.select_device = Mock(return_value=True)
    selected = InputDevice('mic-stable', 'USB mic')
    widget.microphone.addItem(selected.label, selected)
    widget._microphone_selected(0)
    widget.audio.select_device.assert_called_once_with(selected)
    monitor.calibration.reset.assert_not_called()
    assert controller.audio is None and not controller.config.audio.enabled
    assert widget.settings.value('microphone') == 'mic-stable'
    controller.session.started = True
    widget._microphone_selected(0)
    assert widget.audio.select_device.call_count == 1
    widget.shutdown(); widget.deleteLater(); app.processEvents()


def test_setup_never_creates_audio_events_or_starts_timer(tmp_path):
    config = replace(load_config(), audio=replace(load_config().audio, enabled=True), sessions_dir=tmp_path)
    controller = AppController(config, FakeClock())
    from proctoring.audio.monitor import AudioObservation
    controller.audio._observations.append(AudioObservation(0, True, .9, .01))
    controller.poll_optional_workers()
    assert not controller.audio_events.events
    assert not controller.session.started and controller.store is None
    controller.close_remote()


def test_missing_buffers_time_out_calibration_without_waiting_forever():
    from proctoring.audio.monitor import AudioMonitor
    from proctoring.settings import AudioConfig
    clock = FakeClock()
    monitor = AudioMonitor(AudioConfig(enabled=True), clock)
    monitor.start = Mock()  # Device open/read never completes.
    monitor.begin_calibration()
    clock.advance(13)
    assert monitor.check_status['state'] == 'no_signal'
    assert 'timed out' in monitor.check_status['reason']
    assert monitor._detector.gain == 1
