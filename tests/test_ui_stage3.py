"""Real-camera UI paths with deterministic observations and no webcam access."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import Observation
from proctoring.ui.window import MainWindow
from proctoring.vision.alignment import AlignmentConfig
from proctoring.vision.calibration import Calibration
from proctoring.vision.types import (Box, EyeDiagnostic, FaceMeasurement, GazeDiagnostics,
                                    GazeDirection, HeadPose, HealthStatus, VisionResult)


class FakeCameraMonitor:
    def __init__(self, config):
        self.calibration = Calibration(config)
        self.started = False
        self.start_count = 0
        self.stop_count = 0
        self.available = True
        self.latest_frame = None
        self.latest_result = None
        self.metrics = {"capture_fps": 30.0, "monitoring_fps": 10.0,
                        "yolo_latency_ms": 85.0, "face_latency_ms": 20.0,
                        "provider": "CPUExecutionProvider"}

    def start(self):
        self.started = True
        self.start_count += 1

    def stop(self):
        self.started = False
        self.stop_count += 1
        self.latest_frame = None
        self.latest_result = None

    def health(self, now):
        healthy = self.started and self.available
        return HealthStatus(healthy, "Camera not started" if not self.started else "Camera disconnected" if not healthy else "Healthy")

    def sample(self, now):
        return Observation(now, source="camera") if self.health(now).healthy else None


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def camera_window(qt_app, tmp_path, request):
    config = load_config()
    config = replace(config, sessions_dir=tmp_path, snapshots_enabled=False,
                     vision=replace(config.vision, calibration_samples=3,
                                    calibration_debug=getattr(request, "param", False),
                                    alignment=AlignmentConfig(stable_seconds=.001,
                                                              max_sample_gap_seconds=10.)))
    monitor = FakeCameraMonitor(config.vision)
    clock = FakeClock()
    controller = AppController(config, clock, mode="camera", monitor=monitor)
    win = MainWindow(controller, enable_watchdog=False)
    win.timer.stop()
    win.show()
    qt_app.processEvents()
    yield clock, monitor, win
    if controller.session.started and not controller.session.ended:
        controller.emergency_end("test_cleanup")
    win.close()
    qt_app.processEvents()


FEATURES = [(0.5, 0.5, 0.0, 0.0), (0.2, 0.5, -0.25, 0.0),
            (0.8, 0.5, 0.25, 0.0), (0.5, 0.8, 0.0, 0.3)]


def publish(clock, monitor, win, features=FEATURES[0], quality=1.0, face_present=True, age=0.0):
    clock.advance(.1)
    eye = EyeDiagnostic(features[0], features[1], .18, True, "", 40.)
    face = FaceMeasurement(face_present, box=Box(.35, .2, .65, .65), features=features,
                           quality=quality, head_pose=HeadPose(3, -2, 1),
                           diagnostics=GazeDiagnostics(eye, eye, True, ""), frame_size=(640, 480))
    monitor.latest_result = VisionResult(clock.monotonic() - age, face_present=face_present,
                                         face=face, person_count=1, head_pose=face.head_pose)
    win._refresh_camera()


def align(clock, monitor, win):
    for _ in range(3):
        publish(clock, monitor, win)
    assert win.calibration_widget.alignment_status.ready


def complete_calibration(clock, monitor, win, features=FEATURES):
    if not monitor.started:
        win._open_camera()
    widget = win.calibration_widget
    for direction_features in features:
        collect_target(clock, monitor, win, direction_features)


def collect_target(clock, monitor, win, features=FEATURES[0]):
    widget = win.calibration_widget
    if not widget.guided_active:
        align(clock, monitor, win)
        widget.begin_collection()
    clock.advance(max(0., widget._collection_start - clock.monotonic()))
    for _ in range(widget.required_samples):
        publish(clock, monitor, win, features)
    assert widget.collecting  # Reaching the minimum does not shorten the interval.
    clock.advance(widget._collection_end - clock.monotonic() - .1 + 1e-6)
    publish(clock, monitor, win, features)


def test_camera_not_opened_on_launch_and_start_requires_calibration(camera_window):
    clock, monitor, win = camera_window
    assert monitor.start_count == 0
    assert not win.start_button.isEnabled()
    assert win.synthetic_group.isHidden()
    assert win.failure_box.isHidden()
    assert win.stall_box.isHidden()
    QTest.mouseClick(win.open_camera_button, Qt.MouseButton.LeftButton)
    assert monitor.start_count == 1
    assert not win.start_button.isEnabled()
    assert not win.calibration_widget.collect_button.isEnabled()
    align(clock, monitor, win)
    assert win.calibration_widget.collect_button.isEnabled()
    assert "Capture 30.0 FPS" in win.setup_metrics.text()


def test_reduced_eye_availability_is_explicit_and_separate_from_monitoring_health(camera_window):
    clock, monitor, win = camera_window
    win._open_camera()
    eye = EyeDiagnostic(.5, .5, .05, False, "low eyelid aperture; iris visibility unverified", 40.)
    face = FaceMeasurement(True, features=None, head_pose=HeadPose(),
                           diagnostics=GazeDiagnostics(eye, eye, False, eye.reason))
    monitor.latest_result = VisionResult(clock.monotonic(), face_present=True, face=face,
                                        gaze_direction=GazeDirection.UNKNOWN, person_count=1)
    win._refresh_camera()
    assert "UNKNOWN" in win.gaze_label.text()
    assert "Gaze availability reduced" in win.gaze_label.text()
    assert eye.reason in win.gaze_label.text()
    assert "Face: present" in win.gaze_label.text()
    assert win.monitor_label.text() == "Monitoring healthy"
    assert not win.start_button.isEnabled()


def test_head_down_posture_is_visible_separately_from_unobservable_eyes(camera_window):
    from proctoring.i18n import set_language, t
    clock, monitor, win = camera_window
    win._open_camera()
    eye = EyeDiagnostic(.5, .5, .05, False, "low eyelid aperture; iris visibility unverified", 40.)
    face = FaceMeasurement(True, features=None, head_pose=HeadPose(pitch=20.),
                           diagnostics=GazeDiagnostics(eye, eye, False, eye.reason))
    monitor.latest_result = VisionResult(clock.monotonic(), face_present=True, face=face,
                                        gaze_direction=GazeDirection.UNKNOWN, person_count=1,
                                        head_pose=face.head_pose, head_down=True)
    win._refresh_camera()
    assert "Eye-gaze estimate: UNKNOWN" in win.gaze_label.text()
    assert "Head-down posture detected" in win.gaze_label.text()
    assert "pitch 20°" in win.gaze_label.text()
    assert win.monitor_label.text() == "Monitoring healthy"
    for language in ("ru", "kk", "en"):
        set_language(language)
        assert t("monitor.head_down_posture") in win.gaze_label.text()
    monitor.available = False
    win._refresh_camera()
    assert "Head-down posture detected" not in win.gaze_label.text()


def test_calibration_is_guided_then_exam_and_summary(camera_window):
    clock, monitor, win = camera_window
    win._open_camera()
    widget = win.calibration_widget
    assert win.setup_preview._alignment is widget.alignment_status
    collect_target(clock, monitor, win)
    assert widget.direction == GazeDirection.LEFT
    assert not widget.collecting
    assert win.setup_preview._alignment is widget.alignment_status
    publish(clock, monitor, win)
    assert monitor.calibration.counts[GazeDirection.LEFT] == 0
    for features in FEATURES[1:]:
        collect_target(clock, monitor, win, features)
    assert monitor.calibration.ready
    assert win.start_button.isEnabled()
    QTest.mouseClick(win.start_button, Qt.MouseButton.LeftButton)
    assert win.controller.session.running
    assert win.stack.currentWidget() is win.exam_page
    assert win.setup_preview._alignment is None
    assert win.preview._alignment is None
    assert "People: 1" in win.gaze_label.text()
    assert "yaw 3°" in win.gaze_label.text()
    assert "(mock)" not in win.gaze_label.text()
    win._emergency()
    assert win.stack.currentWidget() is win.summary_page
    assert "Camera session" in win.summary_path.text()
    assert "Synthetic session" not in win.summary_path.text()
    assert not monitor.started


def test_calibration_rejects_duplicate_stale_low_quality_and_absent_faces(camera_window):
    clock, monitor, win = camera_window
    win._open_camera()
    widget = win.calibration_widget
    align(clock, monitor, win)
    widget.begin_collection()
    win._refresh_camera()  # Existing result at collection start is not a new sample.
    assert monitor.calibration.counts[GazeDirection.CENTER] == 0
    clock.advance(widget.preparation_seconds)
    publish(clock, monitor, win)
    for _ in range(5):
        win._refresh_camera()
    assert monitor.calibration.counts[GazeDirection.CENTER] == 1
    publish(clock, monitor, win, age=3.0)
    publish(clock, monitor, win, quality=.1)
    publish(clock, monitor, win, face_present=False)
    assert monitor.calibration.counts[GazeDirection.CENTER] == 0
    assert widget._target_failed
    assert not win.start_button.isEnabled()


def test_poor_calibration_warns_and_allows_retry(camera_window):
    clock, monitor, win = camera_window
    complete_calibration(clock, monitor, win, [FEATURES[0]] * 4)
    assert not monitor.calibration.ready
    assert not win.start_button.isEnabled()
    assert "quality is insufficient" in win.calibration_widget.status.text()
    QTest.mouseClick(win.calibration_widget.retry_button, Qt.MouseButton.LeftButton)
    assert sum(monitor.calibration.counts.values()) == 0
    align(clock, monitor, win)
    assert win.calibration_widget.collect_button.isEnabled()
    complete_calibration(clock, monitor, win)
    assert monitor.calibration.ready


def test_setup_emergency_and_window_close_stop_monitor(camera_window):
    clock, monitor, win = camera_window
    win._open_camera()
    win._emergency()
    assert not monitor.started
    assert not win.controller.session.started
    assert not win.start_button.isEnabled()
    assert "Emergency recovery" in win.setup_error.text()
    win._open_camera()
    win.close()
    assert not monitor.started


def test_failure_pauses_exam_and_retry_keeps_session_calibration(camera_window):
    clock, monitor, win = camera_window
    complete_calibration(clock, monitor, win)
    win._start()
    monitor.available = False
    clock.advance(.2)
    win._tick()
    assert not win.controller.session.running
    assert "Monitoring unavailable" in win.monitor_label.text()
    assert win.retry_camera_button.isVisible()
    monitor.available = True
    win._retry_camera()
    assert monitor.started
    assert monitor.calibration.ready
    clock.advance(.1)
    win._tick()
    assert win.controller.session.running


def test_monitoring_outage_discards_interrupted_target(camera_window):
    clock, monitor, win = camera_window
    win._open_camera()
    widget = win.calibration_widget
    align(clock, monitor, win)
    widget.begin_collection()
    clock.advance(widget.preparation_seconds)
    publish(clock, monitor, win)
    assert monitor.calibration.counts[GazeDirection.CENTER] == 1
    monitor.available = False
    win._refresh_camera()
    assert not widget.collecting
    assert monitor.calibration.counts[GazeDirection.CENTER] == 0
    monitor.available = True
    align(clock, monitor, win)
    assert monitor.calibration.counts[GazeDirection.CENTER] == 0
    assert widget.collect_button.isEnabled()


def test_preview_renders_boxes_and_copies_camera_memory(camera_window, qt_app):
    import numpy as np
    clock, monitor, win = camera_window
    win._open_camera()
    monitor.latest_frame = np.zeros((120, 160, 3), dtype=np.uint8)
    monitor.latest_frame[:, :, 2] = 200
    monitor.latest_result = VisionResult(clock.monotonic(), persons=(Box(.1, .1, .8, .95, .9),),
                                         phones=(Box(.6, .2, .7, .4, .8),),
                                         face=FaceMeasurement(True, box=Box(.25, .2, .5, .5)))
    win._refresh_camera()
    image = win.setup_preview._image
    assert image.pixelColor(0, 0).red() == 200
    monitor.latest_frame[:] = 0
    assert image.pixelColor(0, 0).red() == 200
    assert not win.setup_preview.grab().isNull()
    monitor.available = False
    win._refresh_camera()
    assert not win.setup_preview.grab().isNull()


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_failed_fit_heldout_reading_uses_actual_quiz_without_exam_side_effects(camera_window):
    clock, monitor, win = camera_window
    weak = [(0.5, 0.5, 0., 0.), (0.48, 0.5, 0., 0.),
            (0.52, 0.5, 0., 0.), (0.5, 0.52, 0., 0.)]
    complete_calibration(clock, monitor, win, weak)
    assert not monitor.calibration.ready
    baseline = monitor.calibration.export_snapshot()
    win.calibration_widget.diagnostics_panel.setChecked(True)
    panel = win.calibration_widget.diagnostic_workflow
    panel.begin_validation()
    for features in weak:
        panel.prepare_target()
        clock.advance(panel.preparation_seconds)
        for _ in range(3):
            publish(clock, monitor, win, features)
        clock.advance(panel._end - clock.monotonic())
        win._refresh_camera()
    assert panel.TARGETS[panel._index] == "READING"
    assert win.stack.currentWidget() is win.setup_page  # Prepare remains accessible.
    panel.prepare_target()
    assert win.stack.currentWidget() is win.exam_page
    assert win.question_index == 1
    assert not win.quiz_card.isEnabled()
    assert not win.end_button.isEnabled()
    remaining = win.controller.session.remaining_seconds
    clock.advance(panel.preparation_seconds + .1)
    publish(clock, monitor, win, weak[0])
    win._tick()
    assert "DEBUG / UNVALIDATED" in win.session_banner.text()
    assert not win.controller.session.started
    assert win.controller.session.remaining_seconds == remaining
    assert win.controller.quiz.answered_count == 0
    assert win.controller.store is None
    assert win.controller.review_events == []
    assert not win.controller.protection.blocking_enabled
    clock.advance(panel._end - clock.monotonic())
    win._refresh_camera()
    assert not win.calibration_widget.validation_active
    assert win.stack.currentWidget() is win.setup_page
    assert win.question_index == 0
    assert panel.validation.report["targets"]["READING"]["collected"] == 1
    assert monitor.calibration.export_snapshot() == baseline
    assert not win.start_button.isEnabled()


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_validation_disables_start_even_with_accepted_production_fit(camera_window):
    clock, monitor, win = camera_window
    complete_calibration(clock, monitor, win)
    win.calibration_widget.diagnostics_panel.setChecked(True)
    panel = win.calibration_widget.diagnostic_workflow
    panel.begin_validation()
    assert monitor.calibration.ready
    assert not win.start_button.isEnabled()
    win._start()
    assert not win.controller.session.started
    assert "diagnostic validation" in win.setup_error.text()
    panel.cancel_validation()
    win._refresh_camera()
    assert win.start_button.isEnabled()


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_diagnostic_monitor_failure_cancels_and_restores_setup(camera_window):
    clock, monitor, win = camera_window
    complete_calibration(clock, monitor, win)
    win.calibration_widget.diagnostics_panel.setChecked(True)
    panel = win.calibration_widget.diagnostic_workflow
    panel.begin_validation()
    win._diagnostic_validation_target("READING")
    assert win.stack.currentWidget() is win.exam_page
    monitor.available = False
    win._refresh_camera()
    assert not win.calibration_widget.validation_active
    assert win.stack.currentWidget() is win.setup_page
    assert not monitor.calibration.ready
    assert not win.controller.session.started
    assert win.controller.store is None


def test_camera_ui_reports_actual_source_dimensions(camera_window):
    _, monitor, win = camera_window
    monitor.metrics["source_frame_size"] = (640, 480)
    win._refresh_camera()
    assert "Source: 640×480 px (requested 1280×720)" in win.setup_metrics.text()


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_debug_controls_remain_reachable_on_small_screen(camera_window, qt_app):
    from PySide6.QtWidgets import QScrollArea
    _, _, win = camera_window
    win.resize(1040, 760)
    win.calibration_widget.diagnostics_panel.setChecked(True)
    qt_app.processEvents()
    panel = win.calibration_widget.diagnostic_workflow
    assert isinstance(win.setup_page, QScrollArea)
    for control in (panel.export_button, panel.prepare_button, panel.cancel_button):
        assert control.height() >= control.minimumSizeHint().height()
        win.setup_page.ensureWidgetVisible(control)
        qt_app.processEvents()
        position = control.mapTo(win.setup_page.viewport(), control.rect().center())
        assert win.setup_page.viewport().rect().contains(position)


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_candidate_reading_returns_to_setup_for_eye_challenges_without_starting_exam(camera_window):
    clock, monitor, win = camera_window
    weak = [(0.5, 0.5, 0., 0.), (0.48, 0.5, 0., 0.),
            (0.52, 0.5, 0., 0.), (0.5, 0.52, 0., 0.)]
    complete_calibration(clock, monitor, win, weak)
    baseline = monitor.calibration.export_snapshot()
    assert not monitor.calibration.ready
    win.calibration_widget.diagnostics_panel.setChecked(True)
    panel = win.calibration_widget.diagnostic_workflow
    panel.candidate_enabled.setChecked(True)
    panel.begin_validation()
    targets = panel.validation.targets
    assert len(targets) == 9
    remaining = win.controller.session.remaining_seconds
    for target in targets:
        assert panel.validation.targets[panel._index] == target
        assert win.stack.currentWidget() is win.setup_page
        panel.prepare_target()
        assert win.stack.currentWidget() is (win.exam_page if target == "READING" else win.setup_page)
        clock.advance(panel.preparation_seconds)
        features = weak[targets.index(target)] if target in targets[:4] else weak[0]
        for _ in range(3):
            if target in ("BLINK", "BRIEF_CLOSURE", "SUSTAINED_CLOSURE"):
                clock.advance(.1)
                eye = EyeDiagnostic(.5, .5, .05, False, "iris visibility unverified", 40.)
                face = FaceMeasurement(True, features=None, head_pose=HeadPose(),
                                       diagnostics=GazeDiagnostics(eye, eye, False, eye.reason))
                monitor.latest_result = VisionResult(clock.monotonic(), face_present=True, face=face)
                win._refresh_camera()
            else:
                publish(clock, monitor, win, features)
        clock.advance(panel._end - clock.monotonic())
        win._refresh_camera()
        if target == "READING":
            assert panel.active
            assert panel.validation.targets[panel._index] == "BLINK"
            assert "blink normally" in panel.validation_status.text()
            assert win.question_index == 0
        assert win.stack.currentWidget() is win.setup_page
        assert not win.controller.session.started
        assert win.controller.session.remaining_seconds == remaining
        assert win.controller.store is None
        assert win.controller.review_events == []
        assert not win.controller.protection.blocking_enabled
    report = panel.selected_attempt["validation"]
    assert report["collection_complete"]
    assert report["source_attempt_identity"] == panel.selected_attempt["attempt_identity"]
    assert report["targets"]["SUSTAINED_CLOSURE"]["invalid_measurements"] == 3
    assert monitor.calibration.export_snapshot() == baseline
    assert not win.start_button.isEnabled()
