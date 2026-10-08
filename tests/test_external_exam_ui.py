"""External exam/session integration without initializing Chromium or a webcam."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType
from proctoring.ui.window import MainWindow
from proctoring.vision.alignment import AlignmentConfig
from test_ui_stage3 import FakeCameraMonitor, complete_calibration


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def make_window(qt_app, tmp_path, monkeypatch):
    instances = []

    class FakeBrowser(QWidget):
        def __init__(self, url, allowed_domains=(), parent=None):
            super().__init__(parent)
            self.url = url
            self.allowed_domains = allowed_domains
            self.available = True
            self.unavailable_reason = "QtWebEngine is not installed"
            self.start_count = self.stop_count = self.shutdown_count = 0
            instances.append(self)

        def start_exam(self):
            self.start_count += 1

        def stop(self):
            self.stop_count += 1

        def shutdown(self):
            self.shutdown_count += 1

    monkeypatch.setattr("proctoring.ui.browser.SecureBrowserWidget", FakeBrowser)
    windows = []

    def create(*, external=True, camera=False, duration=600.):
        config = load_config()
        config = replace(config, sessions_dir=tmp_path, snapshots_enabled=False,
                         external_url="https://lms.example.edu/quiz" if external else "",
                         allowed_domains=("lms.example.edu",) if external else (),
                         duration_seconds=duration, blocking_enabled=False,
                         protection=replace(config.protection, enabled=False),
                         vision=replace(config.vision, calibration_samples=3, calibration_debug=True,
                                        alignment=AlignmentConfig(stable_seconds=.001,
                                                                  max_sample_gap_seconds=10.)))
        clock = FakeClock()
        monitor = FakeCameraMonitor(config.vision) if camera else None
        controller = AppController(config, clock, mode="camera" if camera else "synthetic", monitor=monitor)
        win = MainWindow(controller, enable_watchdog=False)
        win.timer.stop()
        win.show()
        qt_app.processEvents()
        windows.append(win)
        return clock, win

    create.browser_instances = instances
    yield create
    for win in windows:
        if win.controller.session.started and not win.controller.session.ended:
            win.controller.emergency_end("test_cleanup")
        win.close()
    qt_app.processEvents()


def authorize_next_pin(win):
    def authorize():
        assert win.active_pin_dialog is not None
        win.active_pin_dialog.pin_edit.setText(win.controller.config.proctor_pin)
        win.active_pin_dialog._check()
    QTimer.singleShot(0, authorize)


def test_native_quiz_never_constructs_browser(make_window):
    _, win = make_window(external=False)
    assert make_window.browser_instances == []
    assert win.browser is None
    win._start()
    assert win.exam_content.currentWidget() is win.quiz_card
    assert win.controller.answer(0, 1)
    assert win.controller.quiz.answers == {0: 1}


def test_external_url_loads_only_after_successful_session_start(make_window):
    _, win = make_window()
    assert win.browser.url == "https://lms.example.edu/quiz"
    assert win.browser.allowed_domains == ("lms.example.edu",)
    assert win.browser.start_count == 0
    assert not win.browser.isEnabled()
    assert not win.controller.session.started
    win._start()
    assert win.browser.start_count == 1
    assert win.browser.isEnabled()
    assert win.exam_content.currentWidget() is win.browser
    assert win.stack.currentWidget() is win.exam_page
    assert win.monitor_label.isVisible()
    assert win.timer_label.isVisible()
    assert win.event_table.isVisible()
    assert not win.controller.answer(0, 1)
    assert win.controller.quiz.answers == {}
    win._start()  # A duplicate start must not reload/reset the LMS page.
    assert win.browser.start_count == 1


def test_unavailable_browser_cannot_start_exam_or_fall_back_silently(make_window):
    _, win = make_window()
    win.browser.available = False
    win._start()
    assert not win.controller.session.started
    assert win.controller.store is None
    assert win.browser.start_count == 0
    assert win.setup_error.text() == win.browser.unavailable_reason
    assert win.stack.currentWidget() is win.setup_page


def test_unexpected_browser_start_error_releases_the_started_session(make_window, monkeypatch):
    _, win = make_window()

    def fail_start():
        raise RuntimeError("Renderer initialization failed")

    monkeypatch.setattr(win.browser, "start_exam", fail_start)
    win._start()
    assert win.controller.session.end_reason == "browser_start_failed"
    assert win.controller.session.ended
    assert not win.controller.protection.armed
    assert win.browser.shutdown_count >= 1
    assert win.stack.currentWidget() is win.summary_page
    assert "Renderer initialization failed" in win.summary_text.text()


@pytest.mark.parametrize("interruption,requires_pin", [(14.9, False), (15.0, True)])
def test_external_exam_obeys_monitoring_recovery_boundary(make_window, interruption, requires_pin):
    clock, win = make_window()
    win._start()
    clock.advance(1)
    win._tick()
    win.failure_box.setChecked(True)
    remaining = win.controller.session.remaining_seconds
    assert not win.browser.isEnabled()
    assert not win.controller.session.running
    clock.advance(interruption)
    win.failure_box.setChecked(False)
    assert win.controller.session.remaining_seconds == remaining
    assert win.controller.session.recovery_pin_required is requires_pin
    assert win.browser.isEnabled() is not requires_pin
    if requires_pin:
        assert not win.controller.resume("incorrect")
        authorize_next_pin(win)
        win._pause_or_resume()
    assert win.controller.session.running
    assert win.browser.isEnabled()
    clock.advance(1)
    win._tick()
    assert win.controller.session.remaining_seconds == pytest.approx(remaining - 1)
    assert win.browser.start_count == 1  # Recovery resumes the existing page.


def test_external_exam_overlapping_proctor_and_monitoring_pauses(make_window):
    clock, win = make_window()
    win._start()
    win.failure_box.setChecked(True)
    authorize_next_pin(win)
    win._pause_or_resume()
    assert win.controller.session.pause_reasons == {"monitoring", "proctor"}
    remaining = win.controller.session.remaining_seconds
    clock.advance(2)
    win.failure_box.setChecked(False)
    assert win.controller.session.pause_reasons == {"proctor"}
    assert not win.browser.isEnabled()
    assert win.controller.session.remaining_seconds == remaining
    authorize_next_pin(win)
    win._pause_or_resume()
    assert win.browser.isEnabled()
    assert win.controller.session.running


def test_phone_warning_keeps_browser_and_timer_running(make_window):
    clock, win = make_window()
    win._start()
    before = win.controller.session.remaining_seconds
    win.condition_boxes[EventType.PHONE_VISIBLE].setChecked(True)
    threshold = win.controller.config.thresholds[EventType.PHONE_VISIBLE]
    for _ in range(int(threshold / .1) + 3):
        clock.advance(.1)
        win._tick()
    assert win.event_table.rowCount() == 1
    assert win.controller.review_events[0]["event_type"] == EventType.PHONE_VISIBLE.value
    assert win.controller.session.running
    assert win.browser.isEnabled()
    assert win.controller.session.remaining_seconds < before


@pytest.mark.parametrize("ending", ["emergency", "pin", "timeout"])
def test_external_end_stops_browser_and_saves_summary_without_native_score(make_window, ending):
    clock, win = make_window(duration=3.)
    win._start()
    if ending == "emergency":
        win._emergency()
    elif ending == "pin":
        authorize_next_pin(win)
        win._end_with_pin()
    else:
        for _ in range(6):
            clock.advance(.5)
            win._tick()
    assert win.controller.session.ended
    assert not win.browser.isEnabled()
    assert win.browser.stop_count >= 1
    assert win.stack.currentWidget() is win.summary_page
    assert "Submission and score are managed by the exam website" in win.summary_text.text()
    assert "Score: 0 /" not in win.summary_text.text()
    summary = json.loads((win.controller.store.path / "summary.json").read_text(encoding="utf-8"))
    assert summary["exam_mode"] == "external"
    assert summary["score"] is None
    assert summary["total_questions"] is None
    assert summary["answered"] is None
    assert summary["answers"] == {}
    assert not win.controller.protection.armed
    win.close()
    assert win.browser.shutdown_count >= 1


def test_external_camera_mode_requires_healthy_monitoring_and_real_calibration(make_window):
    clock, win = make_window(camera=True)
    monitor = win.controller.monitor
    win._start()
    assert not win.controller.session.started
    assert win.browser.start_count == 0
    win._open_camera()
    win._start()
    assert not win.controller.session.started
    assert "calibration" in win.setup_error.text().lower()
    assert win.browser.start_count == 0
    complete_calibration(clock, monitor, win)
    assert monitor.calibration.ready
    monitor.available = False
    win._start()
    assert not win.controller.session.started
    assert win.browser.start_count == 0
    monitor.available = True
    win._start()
    assert win.controller.session.running
    assert win.browser.start_count == 1


def test_external_mode_diagnostic_reading_uses_native_quiz_without_loading_url(make_window):
    _, win = make_window(camera=True)
    win._diagnostic_validation_target("READING")
    assert win.stack.currentWidget() is win.exam_page
    assert win.exam_content.currentWidget() is win.quiz_card
    assert not win.quiz_card.isEnabled()
    assert "DEBUG / UNVALIDATED" in win.session_banner.text()
    assert win.browser.start_count == 0
    assert not win.controller.session.started
    assert win.controller.store is None
    win._diagnostic_validation_target("")
    assert win.stack.currentWidget() is win.setup_page
    assert win.browser.start_count == 0
