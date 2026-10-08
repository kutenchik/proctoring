"""Operator diagnostics work after a failed fit without authorizing an exam."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
import numpy as np
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.ui.calibration import CalibrationWidget
from proctoring.ui.diagnostic_panel import frame_size
from proctoring.vision.alignment import AlignmentConfig
from proctoring.vision.calibration import Calibration
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import (
    Box, EyeDiagnostic, EyeOverlay, FaceMeasurement, GazeDiagnostics, GazeDirection, HeadPose, VisionResult,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui(qt_app):
    clock = FakeClock(9.8)
    config = replace(VisionConfig(), calibration_samples=3)
    calibration = Calibration(config)
    widget = CalibrationWidget(calibration, 3, 1., clock=clock.monotonic,
                               preparation_seconds=2., collection_seconds=3.,
                               diagnostics_enabled=True, cue=lambda: None,
                               alignment_config=AlignmentConfig(stable_seconds=.001,
                                                                max_sample_gap_seconds=10.))
    widget.diagnostics_panel.setChecked(True)
    for stamp in (9.8, 9.9, 10.):
        clock.advance(stamp - clock.monotonic())
        widget.feed_result(measurement(stamp), stamp, True)
    yield clock, calibration, widget
    widget.close()


def measurement(stamp, features=(.5, .5, 0., 0.), *, valid=True):
    eye = EyeDiagnostic(features[0], features[1], .15, valid,
                        "" if valid else "blink_or_narrow_eye", 40. if valid else 30.)
    face = FaceMeasurement(True, box=Box(.35, .2, .65, .65),
                           features=features if valid else None, quality=1., frame_size=(640, 480),
                           head_pose=HeadPose(), diagnostics=GazeDiagnostics(eye, eye, valid,
                           "" if valid else "blink_or_narrow_eye"))
    return VisionResult(stamp, face_present=True, face=face)


def tick(ui, stamp, row=None, healthy=True):
    clock, _, widget = ui
    clock.advance(stamp - clock.monotonic())
    widget.feed_result(row, stamp, healthy)


def failed_snapshot(ui):
    """Repeatable but under the existing constant gate; this must stay rejected."""
    _, calibration, widget = ui
    features = {
        GazeDirection.CENTER: (.5, .5, 0., 0.),
        GazeDirection.LEFT: (.48, .5, 0., 0.),
        GazeDirection.RIGHT: (.52, .5, 0., 0.),
        GazeDirection.DOWN: (.5, .52, 0., 0.),
    }
    stamp = 1.
    for target, row in features.items():
        for _ in range(3):
            calibration.add_sample(target, row, stamp, 1., measurement=measurement(stamp, row).face)
            stamp += .1
    assert not calibration.fit()[0]
    widget._archive_attempt("production fit rejected")
    return features


def test_export_requires_separate_explicit_opt_in(ui, tmp_path):
    _, _, widget = ui
    panel = widget.diagnostic_workflow
    failed_snapshot(ui)
    assert not panel.export_enabled.isChecked()
    assert not panel.export_button.isEnabled()
    with pytest.raises(ValueError, match="Enable numerical export"):
        panel.export_to_path(tmp_path / "diagnostic.json")
    assert not list(tmp_path.iterdir())


def test_eye_inspection_opt_in_and_collapse_clear_pixels_without_changing_calibration(ui):
    clock, calibration, widget = ui
    assert not widget.eye_closeups_enabled.isChecked()
    source = np.full((480, 640, 3), 20, dtype=np.uint8)
    overlay = EyeOverlay(((.3, .4), (.4, .4)), ((.35, .39), (.35, .41)),
                         ((.35, .4), (.36, .4), (.35, .39), (.34, .4), (.35, .41)))
    current = measurement(clock.monotonic(), valid=False)
    current = replace(current, frame=source,
                      face=replace(current.face, left_eye_overlay=overlay, right_eye_overlay=overlay))
    widget.feed_result(current, clock.monotonic(), True)
    assert widget.eye_closeups.left.image.image.isNull()
    widget.eye_closeups_enabled.setChecked(True)
    assert not widget.eye_closeups.left.image.image.isNull()
    assert "rejected" in widget.eye_closeups.left.details.text()
    assert not widget.collect_button.isEnabled()  # Zoom cannot authorize invalid eyes.
    assert not calibration.ready
    assert sum(calibration.counts.values()) == 0
    widget.diagnostics_panel.setChecked(False)
    assert widget.eye_closeups.left.image.image.isNull()
    assert widget.eye_closeups.right.image.image.isNull()


def test_eye_frames_and_overlay_geometry_are_not_in_numerical_export(ui, tmp_path):
    _, calibration, widget = ui
    source = np.full((480, 640, 3), 137, dtype=np.uint8)
    overlay = EyeOverlay(((.3, .4), (.4, .4)), ((.35, .39), (.35, .41)),
                         ((.35, .4), (.36, .4), (.35, .39), (.34, .4), (.35, .41)))
    face = replace(measurement(10.).face, left_eye_overlay=overlay, right_eye_overlay=overlay)
    widget.feed_result(VisionResult(10., face_present=True, face=face, frame=source), 10., True)
    calibration.add_sample(GazeDirection.CENTER, face.features, 10., face.quality,
                           measurement=face, frame_size=face.frame_size)
    widget._archive_attempt("partial numerical-only attempt")
    panel = widget.diagnostic_workflow
    panel.export_enabled.setChecked(True)
    path = tmp_path / "numeric.json"
    panel.export_to_path(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["contains_images_or_video"] is False
    row = saved["calibration"]["samples"]["CENTER"][0]
    assert row["frame_size"] == [640, 480]
    assert row["eyes"]["left"]["opening"] == .15
    assert not any(key in path.read_text(encoding="utf-8") for key in ('"frame":', 'eye_overlay', '"iris":'))
    assert list(tmp_path.iterdir()) == [path]


def test_failed_attempt_can_export_no_images_and_does_not_enable_calibration(ui, tmp_path):
    _, calibration, widget = ui
    failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    panel.export_enabled.setChecked(True)
    path = tmp_path / "failed.json"
    panel.export_to_path(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["classification_status"] == "DEBUG / UNVALIDATED"
    assert saved["contains_images_or_video"] is False
    assert saved["calibration"]["diagnostics"]["ready"] is False
    assert len(saved["calibration"]["samples"]["DOWN"]) == 3
    assert saved["validation"] is None
    assert not calibration.ready


def test_failed_snapshot_survives_retry_and_preserves_original_rows(ui):
    _, calibration, widget = ui
    failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    old = panel.selected_attempt["calibration"]
    widget.reset()
    assert sum(calibration.counts.values()) == 0
    assert old["diagnostics"]["targets"]["CENTER"]["accepted"] == 3
    assert panel.selected_attempt["calibration"] == old
    assert panel.validation_button.isEnabled()


def test_insufficient_invalid_target_is_retained_until_local_retry(ui):
    _, calibration, widget = ui
    widget.begin_collection()
    tick(ui, 12.1, measurement(12.1))
    tick(ui, 12.2, measurement(12.2, valid=False))
    for stamp in (13., 14., 15., 16., 17., 18.):
        tick(ui, stamp, measurement(stamp, valid=False))
    assert calibration.counts[GazeDirection.CENTER] == 1
    snapshot = widget.diagnostic_workflow.selected_attempt["calibration"]
    assert snapshot["diagnostics"]["targets"]["CENTER"]["accepted"] == 1
    assert snapshot["diagnostics"]["targets"]["CENTER"]["rejection_reasons"]["blink_or_narrow_eye"] == 6
    assert snapshot["samples"]["CENTER"][1]["eyes"]["left"]["width_pixels"] == 30.
    assert "Eye measurements temporarily unavailable" in widget.status.text()
    assert "blink_or_narrow_eye" not in widget.status.text()


def test_fresh_validation_stays_separate_and_records_unknown_invalid_measurements(ui):
    _, calibration, widget = ui
    features = failed_snapshot(ui)
    baseline = calibration.export_snapshot()
    panel = widget.diagnostic_workflow
    active = []
    widget.validation_active_changed.connect(active.append)
    panel.begin_validation()
    assert widget.validation_active
    assert not widget.collect_button.isEnabled()
    assert not widget.retry_button.isEnabled()
    panel.prepare_target()  # [12,15)
    tick(ui, 12.1, measurement(11.9))  # Countdown capture not admitted.
    tick(ui, 12.2, measurement(12.2, features[GazeDirection.CENTER]))
    tick(ui, 12.3, measurement(12.2))  # Same arrival is not a second sample.
    tick(ui, 12.4, measurement(12.4, valid=False))
    tick(ui, 15., measurement(14.9))  # Inference arrived after deadline.
    report = panel.validation.report
    center = report["targets"]["CENTER"]
    assert center["collected"] == 2
    assert center["predicted_labels"]["CENTER"] == 1
    assert center["predicted_labels"]["UNKNOWN"] == 1
    assert center["unknown_rate"] == .5
    assert active == [True]
    assert calibration.export_snapshot() == baseline
    assert not calibration.ready


def test_validation_cannot_run_while_production_collection_is_active(ui):
    _, _, widget = ui
    failed_snapshot(ui)
    widget.reset()
    for stamp in (10.1, 10.2, 10.3):
        tick(ui, stamp, measurement(stamp))
    widget.begin_collection()
    assert widget.preparing
    panel = widget.diagnostic_workflow
    assert not panel.validation_button.isEnabled()
    panel.begin_validation()
    assert not panel.active


def test_retry_is_ignored_while_validation_is_active(ui):
    _, calibration, widget = ui
    failed_snapshot(ui)
    before = calibration.export_snapshot()
    widget.diagnostic_workflow.begin_validation()
    widget.reset()
    assert widget.validation_active
    assert calibration.export_snapshot() == before


def test_full_separate_sequence_reports_reading_and_clears_target_signal(ui, tmp_path):
    clock, calibration, widget = ui
    features = failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    targets, active = [], []
    widget.validation_target_changed.connect(targets.append)
    widget.validation_active_changed.connect(active.append)
    panel.begin_validation()
    for target in panel.TARGETS:
        start = clock.monotonic() + 2.
        panel.prepare_target()
        row = features[GazeDirection.CENTER if target == "READING" else GazeDirection(target)]
        for offset in (.1, .5, 1.):
            tick(ui, start + offset, measurement(start + offset, row))
        tick(ui, start + 3., measurement(start + 1., row))
    assert targets == ["CENTER", "LEFT", "RIGHT", "DOWN", "READING", ""]
    assert active == [True, False]
    assert not widget.validation_active
    report = panel.validation.report
    assert report["collection_complete"]
    assert report["confusion_matrix"]["READING"]["CENTER"] == 3
    assert report["overall_unknown_rate"] == 0.
    assert report["production_calibration_ready"] is False
    assert not calibration.ready
    panel.export_enabled.setChecked(True)
    path = tmp_path / "held-out.json"
    panel.export_to_path(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["validation"]["collection_complete"] is True
    assert len(saved["validation"]["samples"]["READING"]) == 3


def test_reading_target_signal_waits_until_collection_window_is_prepared(ui):
    clock, _, widget = ui
    features = failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    targets = []
    widget.validation_target_changed.connect(targets.append)
    panel.begin_validation()
    for target in panel.TARGETS[:4]:
        start = clock.monotonic() + 2.
        panel.prepare_target()
        row = features[GazeDirection(target)]
        tick(ui, start + .1, measurement(start + .1, row))
        tick(ui, start + 3., measurement(start + .1, row))
    assert targets == ["CENTER", "LEFT", "RIGHT", "DOWN"]
    assert panel.prepare_button.isEnabled()
    assert panel.prepare_button.text() == "Prepare validation READING"
    panel.prepare_target()
    assert targets[-1] == "READING"
    assert panel._start is not None
    panel.cancel_validation()
    assert targets[-1] == ""


def test_retained_attempts_are_bounded_and_numbering_remains_monotonic(ui):
    _, _, widget = ui
    panel = widget.diagnostic_workflow
    for index in range(12):
        panel.remember({"diagnostics": {"attempt_marker": index}}, f"sample {index}")
    assert len(panel.attempts) == panel.MAX_RETAINED_ATTEMPTS == 8
    assert panel.attempt_selector.count() == 8
    assert panel.attempts[0]["calibration"]["diagnostics"]["attempt_marker"] == 4
    assert panel.selected_attempt["calibration"]["diagnostics"]["attempt_marker"] == 11
    assert panel.attempt_selector.itemText(0).startswith("Attempt 5 ·")
    assert panel.attempt_selector.currentText().startswith("Attempt 12 ·")


def test_cancel_restores_controls_and_does_not_clear_frozen_attempt(ui):
    _, _, widget = ui
    failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    targets = []
    widget.validation_target_changed.connect(targets.append)
    panel.begin_validation()
    panel.prepare_target()
    tick(ui, 12.1, measurement(12.1))
    panel.cancel_validation()
    assert not panel.active
    assert targets[-1] == ""
    assert widget.retry_button.isEnabled()
    assert panel.selected_attempt["validation"]["targets"]["CENTER"]["collected"] == 0
    assert panel.selected_attempt["calibration"]["diagnostics"]["targets"]["CENTER"]["accepted"] == 3


def test_monitoring_interruption_ends_validation_and_retains_diagnostics(ui):
    _, _, widget = ui
    failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    panel.begin_validation()
    panel.prepare_target()
    tick(ui, 12.1, measurement(12.1))
    tick(ui, 12.2, None, healthy=False)
    assert not panel.active
    assert "Monitoring interrupted" in panel.validation_status.text()
    assert any(attempt["validation"] is not None for attempt in panel.attempts)


def test_live_diagnostics_do_not_repeat_all_raw_numerical_rows(ui):
    _, _, widget = ui
    failed_snapshot(ui)
    data = widget.diagnostic_workflow.diagnostics
    assert "samples" not in data["retained_calibration"]
    assert data["retained_calibration"]["pairs"]["CENTER_DOWN"]["threshold_contributions"]


def test_frame_size_comes_from_actual_source_not_requested_resolution():
    class Frame:
        shape = (480, 640, 3)
    result = VisionResult(1., frame=Frame())
    assert frame_size(result) == (640, 480)
    assert frame_size(VisionResult(1.)) is None


def test_retry_identifies_new_empty_baseline_and_retained_old_references(ui, tmp_path):
    _, calibration, widget = ui
    failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    identity = panel.selected_attempt["attempt_identity"].copy()
    widget.reset()
    assert panel.current_baseline["baseline_id"] != identity["baseline_id"]
    assert sum(panel.current_baseline["accepted_samples"].values()) == 0
    assert sum(calibration.counts.values()) == 0
    assert "Previous baseline selected" in panel.attempt_identity.text()
    assert "No validation collected" in panel.attempt_identity.text()
    panel.begin_validation()
    assert "Validation source: attempt 1" in panel.attempt_identity.text()
    panel.cancel_validation()
    panel.export_enabled.setChecked(True)
    path = tmp_path / "retained-after-retry.json"
    panel.export_to_path(path)
    exported = json.loads(path.read_text("utf-8"))
    assert exported["attempt_identity"] == identity
    assert exported["validation"]["source_attempt_identity"] == identity
    assert exported["current_collection_at_export"]["baseline_id"] != identity["baseline_id"]


def test_retry_fresh_samples_get_a_distinct_selected_attempt(ui, tmp_path):
    clock, calibration, widget = ui
    failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    old = panel.selected_attempt
    widget.reset()
    fresh_baseline = panel.current_baseline["baseline_id"]
    for stamp in (10.1, 10.2, 10.3):
        tick(ui, stamp, measurement(stamp))
    for features in ((.5, .5, 0, 0), (.2, .5, 0, 0), (.8, .5, 0, 0), (.5, .8, 0, 0)):
        widget.begin_collection()
        start = clock.monotonic() + 2
        for offset in (.1, .3, .5):
            tick(ui, start + offset, measurement(start + offset, features))
        assert panel.current_baseline["accepted_samples"][widget.direction.value] == 3
        tick(ui, start + 3, measurement(start + 2.9, features))
    fresh = panel.selected_attempt
    assert fresh is not old
    assert fresh["attempt_identity"]["baseline_id"] == fresh_baseline
    assert fresh["attempt_identity"]["attempt_id"] != old["attempt_identity"]["attempt_id"]
    assert fresh["attempt_identity"]["calibration_sha256"] != old["attempt_identity"]["calibration_sha256"]
    assert fresh["calibration"]["last_accepted_timestamp"] > old["calibration"]["last_recorded_timestamp"]
    assert all(row["timestamp"] > 10 for rows in fresh["calibration"]["samples"].values() for row in rows)
    assert fresh["validation"] is None
    assert "Previous baseline selected" not in panel.attempt_identity.text()
    assert calibration.ready


def test_reselecting_current_snapshot_does_not_leave_an_older_attempt_selected(ui):
    _, _, widget = ui
    panel = widget.diagnostic_workflow
    panel.remember({"last_accepted_timestamp": 1}, "old")
    panel.remember({"last_accepted_timestamp": 2}, "current")
    panel.attempt_selector.setCurrentIndex(0)
    panel.remember({"last_accepted_timestamp": 2}, "retained before retry")
    assert len(panel.attempts) == 2
    assert panel.selected_attempt["calibration"]["last_accepted_timestamp"] == 2


def test_validation_report_cannot_be_attached_to_a_different_selected_attempt(ui, tmp_path):
    _, _, widget = ui
    failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    source = panel.selected_attempt
    panel.remember({"last_accepted_timestamp": 3}, "other")
    other = panel.selected_attempt
    panel.attempt_selector.setCurrentIndex(0)
    panel.begin_validation()
    panel.prepare_target()
    tick(ui, 12.1, measurement(12.1))
    assert not panel.attempt_selector.isEnabled()
    # Guard also against a programmatic selection change despite disabled UI.
    panel.attempt_selector.setCurrentIndex(1)
    panel.export_enabled.setChecked(True)
    path = tmp_path / "other.json"
    panel.export_to_path(path)
    assert other["validation"] is None
    assert source["validation"]["source_attempt_identity"] == source["attempt_identity"]
    assert json.loads(path.read_text("utf-8"))["validation"] is None
    panel.cancel_validation()


def test_candidate_requires_explicit_enablement_and_stays_outside_production(ui):
    _, calibration, widget = ui
    failed_snapshot(ui)
    panel = widget.diagnostic_workflow
    assert not panel.candidate_enabled.isChecked()
    panel.candidate_enabled.setChecked(True)
    panel.begin_validation()
    assert not panel.candidate_enabled.isEnabled()
    assert panel.validation.targets[-4:] == ("BLINK", "BRIEF_CLOSURE", "SUSTAINED_CLOSURE", "SQUINT")
    assert not calibration.ready
