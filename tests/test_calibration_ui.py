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
    assert calibration.diagnostics["targets"]["CENTER"]["rejection_reasons"]["captured_before_collection"] == 1


@pytest.mark.parametrize("bad_stamp", [12.0, 11.9, 11.0, 13.5])
def test_reused_stale_future_and_out_of_order_measurements_rejected(setup, bad_stamp):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    feed_at(setup, 12.1, result(12.0))
    assert calibration.counts[GazeDirection.CENTER] == 1
    feed_at(setup, 12.4, result(bad_stamp))
    records = calibration.export_snapshot()["samples"]["CENTER"]
    assert not any(row["accepted"] and row["timestamp"] == bad_stamp for row in records
                   if bad_stamp != 12.0)
    assert calibration.counts[GazeDirection.CENTER] <= 1


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
    # Nominal expiry extends collection. Only the hard deadline excludes late arrivals.
    feed_at(setup, 15.0, result(15.0, quality=.1))
    assert widget.collecting and calibration.counts[GazeDirection.CENTER] == 2
    feed_at(setup, 18.0, result(17.8))
    assert widget.direction == GazeDirection.CENTER
    assert not calibration.ready
    assert calibration.counts[GazeDirection.CENTER] == 2
    assert "2/3" in widget.status.text()
    assert widget.collect_button.text() == "Retry this target"
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
    feed_at(setup, 19.0, result(17.9))
    assert not widget.collecting and not widget.preparing
    assert calibration.counts[GazeDirection.CENTER] == 0
    assert cues == [19.0]


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
    assert data["eye_only_estimate"] == {"direction": "UNKNOWN", "fit_similarity_not_probability": None,
                                         "reason": "stale_or_unavailable_measurement"}


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
    feed_at(setup, 15.0, result(15.0))
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
    feed_at(setup, 15.0, result(15.0))
    assert not widget.collecting and widget.preparing
    assert widget.direction == GazeDirection.LEFT
    feed_at(setup, 15.1, None, healthy=False)
    assert widget.direction == GazeDirection.CENTER
    assert sum(calibration.counts.values()) == 0


def test_nineteen_samples_extend_then_twentieth_completes(qt_app):
    clock = FakeClock(0.)
    config = replace(VisionConfig(), calibration_samples=20)
    calibration = Calibration(config)
    widget = CalibrationWidget(calibration, 20, 1., clock=clock.monotonic, cue=lambda: None,
                               preparation_seconds=.1, collection_seconds=3., max_collection_seconds=6.,
                               alignment_config=AlignmentConfig(stable_seconds=.001, max_sample_gap_seconds=10.))
    try:
        for stamp in (0., .01, .02):
            clock.advance(stamp - clock.monotonic())
            widget.feed_result(result(stamp), stamp, True)
        targets = []
        widget.guided_target_changed.connect(targets.append)
        widget.begin_collection()
        start = widget._collection_start
        for index in range(19):
            stamp = start + index * .15
            clock.advance(stamp - clock.monotonic())
            widget.feed_result(result(stamp), stamp, True)
        clock.advance(start + 3. - clock.monotonic())
        widget.feed_result(result(widget._latest_timestamp), clock.monotonic(), True)
        assert widget.collecting
        assert calibration.counts[GazeDirection.CENTER] == 19
        assert targets == ["CENTER"]
        stamp = start + 3.1
        clock.advance(stamp - clock.monotonic())
        widget.feed_result(result(stamp), stamp, True)
        assert calibration.counts[GazeDirection.CENTER] == 20
        assert widget.direction == GazeDirection.LEFT and widget.preparing
        assert targets == ["CENTER", "LEFT"]
    finally:
        widget.close()


def test_eye_invalid_interval_keeps_samples_and_position_stability(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    feed_at(setup, 12., result(12.))
    generation = widget.alignment_status.geometry_generation
    eye = EyeDiagnostic(.5, .5, .05, False, "low eyelid aperture; iris visibility unverified", 40.)
    bad = result(12.1, diagnostics=GazeDiagnostics(eye, eye, False, eye.reason))
    bad = replace(bad, face=replace(bad.face, features=None))
    feed_at(setup, 12.1, bad)
    assert calibration.counts[GazeDirection.CENTER] == 1
    assert widget.collecting
    assert widget.alignment_status.geometry_generation == generation
    assert widget.alignment_status.positioning_stable
    assert "temporarily unavailable" in widget.status.text()
    feed_at(setup, 12.2, result(12.2))
    assert calibration.counts[GazeDirection.CENTER] == 2


def test_local_retry_replaces_failed_target_and_preserves_completed_baseline(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    for stamp in (12., 13., 14.):
        feed_at(setup, stamp, result(stamp))
    feed_at(setup, 15., result(15.))
    baseline_id = widget.diagnostic_workflow._baseline_id
    center = calibration.export_snapshot()["samples"]["CENTER"]
    feed_at(setup, 17., result(17., (.3, .5, 0., 0.)))
    feed_at(setup, 23., result(23., (.3, .5, 0., 0.)))
    assert widget._target_failed and widget.direction == GazeDirection.LEFT
    assert calibration.counts[GazeDirection.LEFT] == 1
    widget.begin_collection()
    assert widget.preparing
    assert calibration.counts[GazeDirection.LEFT] == 0
    assert calibration.export_snapshot()["samples"]["CENTER"] == center
    assert widget.diagnostic_workflow._baseline_id == baseline_id
    feed_at(setup, 25., result(24.9, (.3, .5, 0., 0.)))
    assert calibration.counts[GazeDirection.LEFT] == 0
    feed_at(setup, 25.1, result(25.1, (.3, .5, 0., 0.)))
    assert calibration.counts[GazeDirection.LEFT] == 1


def test_pause_and_cancel_keep_completed_targets_but_remove_partial_target(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    for stamp in (12., 13., 14.):
        feed_at(setup, stamp, result(stamp))
    feed_at(setup, 15., result(15.))
    feed_at(setup, 17., result(17., (.3, .5, 0., 0.)))
    widget.pause_collection()
    assert widget.paused and widget.guided_active
    assert calibration.counts[GazeDirection.CENTER] == 3
    assert calibration.counts[GazeDirection.LEFT] == 0
    widget.pause_collection()
    assert widget.preparing and not widget.paused
    widget.cancel_collection()
    assert not widget.guided_active
    assert calibration.counts[GazeDirection.CENTER] == 3
    assert widget.direction == GazeDirection.LEFT


def test_automatic_transition_uses_new_labels_and_capture_interval(setup):
    _, calibration, widget, _ = setup
    targets = []
    widget.guided_target_changed.connect(targets.append)
    widget.begin_collection()
    for stamp in (12., 13., 14.):
        feed_at(setup, stamp, result(stamp))
    feed_at(setup, 15., result(15.))
    assert targets == ["CENTER", "LEFT"]
    feed_at(setup, 16., result(16., (.3, .5, 0., 0.)))
    feed_at(setup, 17., result(16.9, (.3, .5, 0., 0.)))
    feed_at(setup, 17.1, result(17.1, (.3, .5, 0., 0.)))
    export = calibration.export_snapshot()
    assert [row["timestamp"] for row in export["samples"]["CENTER"] if row["accepted"]] == [12., 13., 14.]
    assert [row["timestamp"] for row in export["samples"]["LEFT"] if row["accepted"]] == [17.1]


def test_empty_collection_progress_never_looks_complete(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    for stamp in (12., 13., 14., 15., 16., 17.):
        feed_at(setup, stamp, result(stamp, quality=.1))
    assert widget.collecting
    assert widget.sample_progress.value() == 0
    assert widget.progress.value() == 0
    feed_at(setup, 18., result(18.))
    assert not widget.collecting
    assert widget._target_failed
    assert calibration.counts[GazeDirection.CENTER] == 0
    assert "This point needs another attempt" in widget.status.text()


@pytest.mark.parametrize("at_deadline", [False, True])
def test_final_target_camera_change_cannot_complete_old_baseline(setup, at_deadline):
    clock, calibration, widget, _ = setup
    widget.direction_index = 3
    widget.begin_collection()
    for stamp in (12., 13., 14.):
        feed_at(setup, stamp, result(stamp, (.5, .8, 0., 0.)))
    end = widget._window.deadline if at_deadline else widget._window.nominal_end
    changed = result(end, (.5, .8, 0., 0.))
    changed = replace(changed, face=replace(changed.face, frame_size=(1280, 720)))
    feed_at(setup, end, changed)
    assert not calibration.ready
    assert sum(calibration.counts.values()) == 0
    assert widget.direction == GazeDirection.CENTER
    assert "Camera dimensions changed" in widget.status.text()


def test_burst_does_not_shorten_nominal_window(setup):
    _, calibration, widget, _ = setup
    widget.begin_collection()
    for stamp in (12., 12.001, 12.002):
        feed_at(setup, stamp, result(stamp))
    assert calibration.counts[GazeDirection.CENTER] == 3
    assert widget.collecting and widget.direction == GazeDirection.CENTER
    feed_at(setup, 14., result(14.))
    assert widget.collecting
    feed_at(setup, 15., result(15.))
    assert widget.direction == GazeDirection.LEFT and widget.preparing
