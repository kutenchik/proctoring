"""Capture-time admission and timed calibration interaction without a webcam."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.ui.calibration import CalibrationWidget
from proctoring.vision.alignment import AlignmentConfig
from proctoring.vision.calibration import Calibration
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import (
    Box, EyeDiagnostic, FaceMeasurement, GazeDiagnostics, GazeDirection, HeadPose, VisionResult,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(qt_app):
    clock = FakeClock(9.8)
    calibration = Calibration(replace(VisionConfig(), calibration_samples=3))
    cues = []
    widget = CalibrationWidget(calibration, 3, 1.0, clock=clock.monotonic,
                               preparation_seconds=2.0, collection_seconds=3.0,
                               diagnostics_enabled=True, cue=lambda: cues.append(clock.monotonic()),
                               alignment_config=AlignmentConfig(stable_seconds=.001,
                                                                max_sample_gap_seconds=10.))
    for stamp in (9.8, 9.9, 10.):
        clock.advance(stamp - clock.monotonic())
        widget.feed_result(result(stamp), stamp, True)
    yield clock, calibration, widget, cues
    widget.close()


def result(timestamp, features=(.5, .5, 0.0, 0.0), quality=1.0, diagnostics=None):
    if diagnostics is None:
        eye = EyeDiagnostic(features[0], features[1], .18, True, "", 40.)
        diagnostics = GazeDiagnostics(eye, eye, True, "")
    face = FaceMeasurement(True, box=Box(.35, .2, .65, .65), features=features,
                           quality=quality, head_pose=HeadPose(0, 0, 0),
                           diagnostics=diagnostics, frame_size=(640, 480))
    return VisionResult(timestamp, face_present=True, face=face)


def feed_at(setup, now, measurement=None, healthy=True):
    clock, _, widget, _ = setup
    clock.advance(now - clock.monotonic())
    widget.feed_result(measurement, now, healthy)


def test_preparation_and_old_inflight_frames_are_excluded(setup):
    clock, calibration, widget, cues = setup
    widget.feed_result(result(10.), clock.monotonic(), True)
    widget.begin_collection()  # Captures must occur in [12, 15).
    assert widget.preparing and not widget.collecting
    feed_at(setup, 11.5, result(11.4))
    assert calibration.counts[GazeDirection.CENTER] == 0
    # Newer than the last displayed frame, but captured during the countdown.
    feed_at(setup, 12.1, result(11.9))
    assert widget.collecting and not widget.preparing
    assert cues == [12.1]
    assert calibration.counts[GazeDirection.CENTER] == 0
    feed_at(setup, 12.2, result(12.15))
    assert calibration.counts[GazeDirection.CENTER] == 1
    assert calibration.diagnostics["targets"]["CENTER"]["rejection_reasons"]["captured_before_collection"] == 2


def test_reused_stale_future_and_out_of_order_measurements_rejected(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    feed_at(setup, 12.1, result(12.0))
    feed_at(setup, 12.2, result(12.0))
    feed_at(setup, 12.3, result(12.0))  # Polling does not inflate reused rejection counts.
    feed_at(setup, 12.4, result(12.35))
    feed_at(setup, 12.5, result(12.2))
    feed_at(setup, 13.1, result(12.05))
    feed_at(setup, 13.2, result(13.3))
    assert calibration.counts[GazeDirection.CENTER] == 2
    reasons = calibration.diagnostics["targets"]["CENTER"]["rejection_reasons"]
    assert reasons["reused_or_out_of_order_measurement"] == 2
    assert reasons["stale_or_future_measurement"] == 2


def test_collects_entire_interval_not_first_minimum_samples(setup):
    _, calibration, widget, cues = setup
    widget.begin_collection()
    for stamp in (12.0, 12.3, 12.6, 13.0, 13.5, 14.0, 14.9):
        feed_at(setup, stamp, result(stamp))
    assert widget.collecting
    assert calibration.counts[GazeDirection.CENTER] == 7
    feed_at(setup, 15.0, result(15.0))
    assert not widget.collecting
    assert widget.direction == GazeDirection.LEFT
    assert cues == [12.0, 15.0]
    assert calibration.counts[GazeDirection.CENTER] == 7
    assert calibration.counts[GazeDirection.LEFT] == 0


def test_late_inference_arrival_is_not_used_to_complete_target(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    feed_at(setup, 12.1, result(12.1))
    feed_at(setup, 13.1, result(13.1))
    feed_at(setup, 15.0, result(14.8))  # Would meet minimum, but arrival is too late.
    assert widget.direction == GazeDirection.CENTER
    assert not calibration.ready
    assert calibration.counts[GazeDirection.CENTER] == 0
    assert "2/3" in widget.status.text()
    assert widget.collect_button.isEnabled()
    # Numerical failure diagnostics remain inspectable after target data clears.
    assert widget._last_attempt["accepted"] == 2
    assert widget._last_attempt["rejection_reasons"]["arrived_after_collection"] == 1


def test_new_target_cannot_reuse_previous_target_result(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    for stamp in (12.0, 12.5, 13.0):
        feed_at(setup, stamp, result(stamp))
    feed_at(setup, 15.0, result(14.9))
    widget.begin_collection()
    feed_at(setup, 17.0, result(16.9))
    assert calibration.counts[GazeDirection.LEFT] == 0
    feed_at(setup, 17.2, result(17.1, (.3, .5, 0, 0)))
    assert calibration.counts[GazeDirection.LEFT] == 1


def test_interruption_discards_calibration_and_retry_has_new_deadline(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    feed_at(setup, 12.1, result(12.1))
    feed_at(setup, 12.2, None, healthy=False)
    assert calibration.counts[GazeDirection.CENTER] == 0
    assert not widget.collecting and not widget.preparing
    feed_at(setup, 12.3, result(12.3))
    feed_at(setup, 12.31, result(12.31))
    feed_at(setup, 12.32, result(12.32))
    widget.begin_collection()
    feed_at(setup, 14.4, result(14.2))
    assert calibration.counts[GazeDirection.CENTER] == 0
    feed_at(setup, 14.5, result(14.4))
    assert calibration.counts[GazeDirection.CENTER] == 1


def test_long_ui_stall_does_not_retroactively_collect(setup):
    _, calibration, widget, cues = setup
    widget.begin_collection()
    feed_at(setup, 16.0, result(14.9))
    assert not widget.collecting and not widget.preparing
    assert calibration.counts[GazeDirection.CENTER] == 0
    assert cues == [16.0]


def test_diagnostics_show_each_eye_separately_from_head_and_fit(setup):
    _, _, widget, _ = setup
    diagnostics = GazeDiagnostics(
        EyeDiagnostic(.48, .52, .18, True, "", 60.0),
        EyeDiagnostic(.49, .53, .17, True, "", 55.0), True, "",
    )
    feed_at(setup, 10.1, result(10.1, diagnostics=diagnostics))
    data = json.loads(widget.diagnostics_text.toPlainText())
    assert data["eye_measurements"]["left_eye"]["vertical"] == .52
    assert data["eye_measurements"]["right_eye"]["opening"] == .17
    assert data["head_pose_degrees"]["pitch"] == 0
    assert data["eye_only_estimate"]["direction"] == "UNKNOWN"
    assert data["calibration"]["targets"]["CENTER"]["accepted"] == 0
    assert widget.diagnostics_panel.isCheckable()
    assert not widget.diagnostics_panel.isChecked()


def test_developer_diagnostics_hidden_by_default(qt_app):
    widget = CalibrationWidget(Calibration(VisionConfig()), 20, 2.0)
    assert widget.diagnostics_panel.isHidden()
    widget.close()


def test_diagnostics_mark_stale_measurements_and_do_not_claim_current_gaze(setup):
    _, _, widget, _ = setup
    feed_at(setup, 12.5, result(10.1))
    data = json.loads(widget.diagnostics_text.toPlainText())
    assert data["measurement_status"]["age_seconds"] == pytest.approx(2.4)
    assert data["measurement_status"]["fresh_and_healthy"] is False
    assert data["eye_only_estimate"] == {"direction": "UNKNOWN", "fit_similarity_not_probability": None}


def test_interruption_uses_audio_cue_for_student_looking_away(setup):
    _, _, widget, cues = setup
    widget.begin_collection()
    feed_at(setup, 12.1, result(12.1))
    feed_at(setup, 12.2, None, healthy=False)
    assert cues == [12.1, 12.2]


def test_down_instruction_uses_physical_screen_edge_not_ui_button(setup):
    _, _, widget, _ = setup
    widget.direction_index = 3
    widget._render_prompt()
    assert "below the physical bottom edge" in widget.prompt.text()
    assert "not at an application button" in widget.prompt.text()


def test_reset_during_countdown_discards_samples_and_removes_deadline(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    widget.reset()
    feed_at(setup, 12.1, result(12.1))
    assert not widget.preparing and not widget.collecting
    assert not calibration.ready
    assert sum(calibration.counts.values()) == 0
    assert widget._collection_start is None


def test_deadline_does_not_miscount_last_accepted_frame_as_late_arrival(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    for stamp in (12.0, 12.5, 13.0):
        feed_at(setup, stamp, result(stamp))
    feed_at(setup, 15.0, result(13.0))
    assert "arrived_after_collection" not in calibration.diagnostics["targets"]["CENTER"]["rejection_reasons"]


def test_diagnostics_keep_scroll_position_while_live_data_changes(setup, qt_app):
    _, _, widget, _ = setup
    widget.show()
    widget.diagnostics_panel.setChecked(True)
    qt_app.processEvents()
    scrollbar = widget.diagnostics_text.verticalScrollBar()
    assert scrollbar.maximum() > 20
    scrollbar.setValue(20)
    feed_at(setup, 10.1, result(10.1))
    assert scrollbar.value() == 20


def test_interruption_after_center_requires_new_center_baseline(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    for stamp in (12.0, 12.5, 13.0):
        feed_at(setup, stamp, result(stamp))
    feed_at(setup, 15.0, result(14.9))
    assert widget.direction == GazeDirection.LEFT
    widget.begin_collection()
    feed_at(setup, 17.1, result(17.1, (.3, .5, 0, 0)))
    feed_at(setup, 17.2, None, healthy=False)
    assert widget.direction == GazeDirection.CENTER
    assert sum(calibration.counts.values()) == 0
    assert widget._last_attempt["target"] == "LEFT"
    assert widget._last_attempt["accepted"] == 1
    assert "new baseline" in widget.status.text()


def test_interruption_between_targets_also_discards_baseline(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    for stamp in (12.0, 12.5, 13.0):
        feed_at(setup, stamp, result(stamp))
    feed_at(setup, 15.0, result(13.0))
    assert not widget.collecting and not widget.preparing
    assert widget.direction == GazeDirection.LEFT
    feed_at(setup, 15.1, None, healthy=False)
    assert widget.direction == GazeDirection.CENTER
    assert sum(calibration.counts.values()) == 0
