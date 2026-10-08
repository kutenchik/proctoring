"""Guided production calibration renders real screen targets without an exam."""
from PySide6.QtWidgets import QApplication

from proctoring.vision.types import GazeDirection
from test_ui_stage3 import camera_window, qt_app, align, publish, FEATURES


def start_guided(fixture):
    clock, monitor, window = fixture
    window._open_camera()
    align(clock, monitor, window)
    widget = window.calibration_widget
    widget.begin_collection()
    QApplication.processEvents()
    window._refresh_camera()
    return clock, monitor, window, widget


def assert_no_exam(window):
    assert not window.controller.session.started
    assert window.controller.session.elapsed_seconds == 0
    assert not window.controller.protection.blocking_enabled
    assert not window.controller.protection.armed
    assert not window.controller.quiz.answers


def test_guided_center_marker_uses_physical_screen_position_after_resize(camera_window):
    clock, monitor, window, widget = start_guided(camera_window)
    assert widget.preparing
    assert not window.screen_target.isHidden()
    assert window.stack.mapToGlobal(window.screen_target.point) == window.screen().geometry().center()
    assert window.screen_target.geometry() == window.stack.rect()
    window.showNormal()
    window.resize(1200, 820)
    QApplication.processEvents()
    window._refresh_camera()
    assert window.stack.mapToGlobal(window.screen_target.point) == window.screen().geometry().center()
    assert window.screen_target.geometry() == window.stack.rect()
    assert_no_exam(window)
    widget.cancel_collection()
    assert window.screen_target.isHidden()


def test_one_start_auto_advances_physical_directions_without_offscreen_marker(camera_window):
    clock, monitor, window = camera_window
    window._open_camera()
    align(clock, monitor, window)
    widget = window.calibration_widget
    targets = []
    widget.guided_target_changed.connect(targets.append)
    widget.begin_collection()
    QApplication.processEvents()
    seen = set()
    for _ in range(250):
        direction = widget.direction
        seen.add(direction)
        assert widget.guided_active
        assert_no_exam(window)
        window._refresh_camera()
        if direction == GazeDirection.CENTER:
            assert not window.screen_target.isHidden()
            assert window.stack.mapToGlobal(window.screen_target.point) == window.screen().geometry().center()
        else:
            assert window.screen_target.isHidden()
            assert window.screen_target.point is None
            assert "physical" in widget.prompt.text()
        publish(clock, monitor, window, FEATURES[widget.direction_index])
        if not widget.guided_active:
            break
    else:
        raise AssertionError("Guided flow did not finish within its four bounded windows")
    assert seen == set(widget.DIRECTIONS)
    assert targets == ["CENTER", "LEFT", "RIGHT", "DOWN", ""]
    assert monitor.calibration.ready
    assert window.screen_target.isHidden()
    assert window.start_button.isEnabled()
    assert_no_exam(window)


def test_pause_cancel_remove_marker_without_starting_or_pausing_exam(camera_window):
    clock, monitor, window, widget = start_guided(camera_window)
    widget.toggle_pause()
    assert widget.paused
    assert window.screen_target.isHidden()
    assert_no_exam(window)
    publish(clock, monitor, window)
    widget.toggle_pause()
    assert widget.preparing and not widget.paused
    assert not window.screen_target.isHidden()
    widget.cancel_collection()
    assert not widget.guided_active
    assert window.screen_target.isHidden()
    assert_no_exam(window)
