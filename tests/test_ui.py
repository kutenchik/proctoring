"""Exercise actual Qt widgets without a webcam or operating-system hooks."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType
from proctoring.ui.window import MainWindow, PinDialog


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt_app, tmp_path):
    clock = FakeClock()
    controller = AppController(replace(load_config(), sessions_dir=tmp_path), clock)
    win = MainWindow(controller, enable_watchdog=False)
    win.timer.stop()
    win.show()
    qt_app.processEvents()
    yield clock, win
    if controller.session.started and not controller.session.ended:
        controller.emergency_end("test_cleanup")
    win.close()
    qt_app.processEvents()


def test_launch_answer_navigate_warning_and_summary(window, qt_app):
    clock, win = window
    QTest.mouseClick(win.start_button, Qt.MouseButton.LeftButton)
    assert win.stack.currentWidget() is win.exam_page
    QTest.mouseClick(win.options_group.button(1), Qt.MouseButton.LeftButton)
    assert win.controller.quiz.answers == {0: 1}
    QTest.mouseClick(win.next_button, Qt.MouseButton.LeftButton)
    assert win.question_index == 1
    QTest.mouseClick(win.previous_button, Qt.MouseButton.LeftButton)
    assert win.options_group.checkedId() == 1
    win.condition_boxes[EventType.PHONE_VISIBLE].setChecked(True)
    clock.advance(.1)
    win._tick()
    clock.advance(1)
    win._tick()
    assert win.event_table.rowCount() == 1
    assert win.controller.session.running
    assert win.quiz_card.isEnabled()
    win._emergency()
    assert win.stack.currentWidget() is win.summary_page
    assert "Score: 1 / 6" in win.summary_text.text()
    assert "Monitoring stopped" in win.summary_text.text()


def test_ui_failure_recovery_and_pin_dialog(window, qt_app):
    clock, win = window
    win._start()
    win.failure_box.setChecked(True)
    assert not win.quiz_card.isEnabled()
    frozen = win.timer_label.text()
    clock.advance(15)
    win.failure_box.setChecked(False)
    assert not win.quiz_card.isEnabled()
    assert win.timer_label.text() == frozen
    assert "PIN required" in win.session_banner.text()
    def authorize():
        dialog = win.active_pin_dialog
        assert dialog is not None
        dialog.pin_edit.setText("2468")
        dialog._check()
    QTimer.singleShot(0, authorize)
    QTest.mouseClick(win.pause_button, Qt.MouseButton.LeftButton)
    assert win.controller.session.running
    assert win.quiz_card.isEnabled()


def test_pin_dialog_rejects_invalid_and_accepts_valid(window, qt_app):
    _, win = window
    dialog = PinDialog(win.controller.pin, "Pause exam", win)
    dialog.show()
    qt_app.processEvents()
    dialog.pin_edit.setText("0000")
    QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "Incorrect PIN" in dialog.error_label.text()
    dialog.pin_edit.setText("2468")
    QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()


def test_emergency_shortcut_ends_without_pin(window, qt_app):
    _, win = window
    win._start()
    win.activateWindow()
    win.setFocus()
    qt_app.processEvents()
    QTest.keyClick(win, Qt.Key.Key_Q,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier)
    qt_app.processEvents()
    assert win.controller.session.ended
    assert win.controller.session.end_reason == "emergency_shortcut"
    assert not win.controller.protection.armed


def test_pin_authorized_end_from_button(window, qt_app):
    _, win = window
    win._start()
    def authorize():
        dialog = win.active_pin_dialog
        dialog.pin_edit.setText("2468")
        dialog._check()
    QTimer.singleShot(0, authorize)
    QTest.mouseClick(win.end_button, Qt.MouseButton.LeftButton)
    assert win.controller.session.end_reason == "proctor_ended"
    assert win.stack.currentWidget() is win.summary_page


def test_proctor_can_add_pause_during_monitoring_outage(window, qt_app):
    clock, win = window
    win._start()
    win.failure_box.setChecked(True)
    assert win.pause_button.isEnabled()
    def authorize():
        win.active_pin_dialog.pin_edit.setText("2468")
        win.active_pin_dialog._check()
    QTimer.singleShot(0, authorize)
    QTest.mouseClick(win.pause_button, Qt.MouseButton.LeftButton)
    assert win.controller.session.pause_reasons == {"proctor", "monitoring"}
    clock.advance(2)
    win.failure_box.setChecked(False)
    assert not win.controller.session.running
    assert win.controller.session.pause_reasons == {"proctor"}


def test_background_watchdog_releases_before_ui_processes_recovery(qt_app, tmp_path):
    import threading
    clock = FakeClock()
    controller = AppController(replace(load_config(), sessions_dir=tmp_path), clock)
    win = MainWindow(controller, enable_watchdog=True)
    win.timer.stop()
    win._start()
    released = threading.Event()
    original_release = controller.protection.release
    def observe_release(reason):
        original_release(reason)
        if reason == "heartbeat_timeout":
            released.set()
    controller.protection.release = observe_release
    try:
        clock.advance(5)
        assert released.wait(timeout=2), "Background watchdog did not run"
        assert not controller.protection.armed
        assert not controller.session.ended  # Qt event loop is deliberately idle.
        qt_app.processEvents()
        assert controller.session.end_reason == "heartbeat_timeout"
    finally:
        if not controller.session.ended:
            controller.emergency_end("test_cleanup")
        win.close()


def test_cancelled_window_close_keeps_exam_running(window, qt_app):
    _, win = window
    win._start()
    QTimer.singleShot(0, lambda: win.active_pin_dialog.reject())
    win.close()
    assert win.isVisible()
    assert win.controller.session.running


def test_emergency_shortcut_works_inside_pin_dialog(window, qt_app):
    _, win = window
    win._start()
    win.activateWindow()
    qt_app.processEvents()
    def emergency():
        dialog = win.active_pin_dialog
        # Prevent a failed shortcut from leaving the automated test in a modal loop.
        QTimer.singleShot(300, dialog.reject)
        dialog.activateWindow()
        qt_app.processEvents()
        QTest.keyClick(dialog, Qt.Key.Key_Q,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier)
    QTimer.singleShot(0, emergency)
    QTest.mouseClick(win.end_button, Qt.MouseButton.LeftButton)
    assert win.controller.session.end_reason == "emergency_shortcut"
    assert win.stack.currentWidget() is win.summary_page

