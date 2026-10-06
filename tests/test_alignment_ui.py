"""Positioning must gate collection without changing gaze-fit acceptance."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.ui.calibration import CalibrationWidget
from proctoring.vision.calibration import Calibration
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import (
    Box, EyeDiagnostic, FaceMeasurement, GazeDiagnostics, GazeDirection, HeadPose, VisionResult,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui(qt_app):
    clock = FakeClock(10.)
    calibration = Calibration(replace(VisionConfig(), calibration_samples=3))
    widget = CalibrationWidget(calibration, 3, 1., clock=clock.monotonic,
                               diagnostics_enabled=True, cue=lambda: None)
    yield clock, calibration, widget
    widget.close()


def measurement(stamp, *, box=Box(.35, .2, .65, .65), pose=HeadPose(),
                valid=True, eye_width=40., source=(640, 480), features=(.5, .5, 0., 0.)):
    eye = EyeDiagnostic(features[0], features[1], .18, valid,
                        "" if valid else "blink_or_narrow_eye", eye_width)
    face = FaceMeasurement(True, box=box, features=features if valid else None,
                           head_pose=pose, quality=1., frame_size=source,
                           diagnostics=GazeDiagnostics(eye, eye, valid,
                                                       "" if valid else "blink_or_narrow_eye"))
    return VisionResult(stamp, face_present=True, face=face)


def tick(ui, stamp, **kwargs):
    clock, _, widget = ui
    clock.advance(stamp - clock.monotonic())
    widget.feed_result(measurement(stamp, **kwargs), stamp, True)


def aligned(ui):
    for stamp in (10., 10.4, 10.8):
        tick(ui, stamp)
    assert ui[2].alignment_status.ready


def test_prepare_requires_visible_stable_face_even_when_monitoring_is_healthy(ui):
    clock, calibration, widget = ui
    widget.feed_result(None, clock.monotonic(), True)
    QTest.mouseClick(widget.collect_button, Qt.MouseButton.LeftButton)
    widget.begin_collection()
    assert not widget.collect_button.isEnabled()
    assert not widget.preparing and not widget.collecting
    assert sum(calibration.counts.values()) == 0
    tick(ui, 10.)
    tick(ui, 10.4)
    assert "Hold still" in widget.alignment_label.text()
    assert not widget.collect_button.isEnabled()
    tick(ui, 10.8)
    assert "Face aligned" in widget.alignment_label.text()
    assert widget.alignment_progress.value() == 100
    assert widget.collect_button.isEnabled()
    widget.begin_collection()
    assert widget.preparing
    assert calibration.counts[GazeDirection.CENTER] == 0


@pytest.mark.parametrize(("change", "reason", "feedback"), [
    ({"box": Box(.1, .2, .4, .65)}, "face_not_contained", "Center your face"),
    ({"box": Box(.4, .3, .6, .6)}, "face_too_small", "Move closer"),
    ({"eye_width": 31.}, "face_too_small", "Move closer"),
    ({"valid": False}, "eyes_not_visible", "Keep both eyes visible"),
    ({"pose": HeadPose(yaw=16.)}, "head_not_frontal", "Face the screen naturally"),
    ({"pose": HeadPose(pitch=16.)}, "head_not_frontal", "Face the screen naturally"),
    ({"pose": HeadPose(roll=13.)}, "head_not_frontal", "Face the screen naturally"),
    ({"source": None}, "source_dimensions_missing", "original camera dimensions"),
])
def test_failed_position_checks_disable_prepare_and_explain_reason(ui, change, reason, feedback):
    _, calibration, widget = ui
    aligned(ui)
    tick(ui, 10.9, **change)
    assert widget.alignment_status.reason == reason
    assert feedback in widget.alignment_label.text()
    assert not widget.collect_button.isEnabled()
    widget.begin_collection()
    assert not widget.preparing and not widget.collecting
    assert sum(calibration.counts.values()) == 0


def test_direct_prepare_rechecks_freshness_instead_of_trusting_enabled_button(ui):
    clock, _, widget = ui
    aligned(ui)
    assert widget.collect_button.isEnabled()
    clock.advance(2.)  # No UI refresh: the old enabled button is not authorization.
    widget.begin_collection()
    assert not widget.preparing and not widget.collecting
    assert not widget.alignment_status.ready
    assert "fresh camera frame" in widget.status.text()


def test_position_motion_requires_another_stable_window(ui):
    _, _, widget = ui
    aligned(ui)
    shifted = Box(.38, .2, .68, .65)
    tick(ui, 10.9, box=shifted)
    assert not widget.collect_button.isEnabled()
    assert "Hold still" in widget.alignment_label.text()
    tick(ui, 11.3, box=shifted)
    assert not widget.alignment_status.ready
    tick(ui, 11.7, box=shifted)
    assert widget.alignment_status.ready


def test_collection_skips_bad_alignment_and_preserves_eye_rejections_with_fixed_deadline(ui):
    _, calibration, widget = ui
    aligned(ui)
    widget.begin_collection()
    deadline = widget._collection_end
    for stamp in (11.2, 11.6, 12., 12.4, 12.8):
        tick(ui, stamp)
    assert calibration.counts[GazeDirection.CENTER] == 1
    tick(ui, 13., box=Box(.1, .2, .4, .65))
    assert calibration.counts[GazeDirection.CENTER] == 1
    for stamp in (13.1, 13.5):
        tick(ui, stamp)
    assert calibration.counts[GazeDirection.CENTER] == 1
    tick(ui, 13.9)
    assert calibration.counts[GazeDirection.CENTER] == 2
    tick(ui, 14., valid=False)
    assert calibration.counts[GazeDirection.CENTER] == 2
    assert widget._collection_end == deadline
    reasons = calibration.diagnostics["targets"]["CENTER"]["rejection_reasons"]
    assert reasons["alignment_face_not_contained"] == 1
    assert reasons["alignment_hold_still"] == 2
    assert reasons["blink_or_narrow_eye"] == 1
    tick(ui, deadline)
    assert not widget.collecting and not widget.preparing
    assert not calibration.ready
    assert "2/3" in widget.status.text()
    assert widget._last_attempt["accepted"] == 2
    assert widget._last_attempt["rejection_reasons"]["alignment_face_not_contained"] == 1


def test_alignment_diagnostics_stay_separate_from_gaze_fit_and_never_authorize_bad_fit(ui):
    _, calibration, widget = ui
    aligned(ui)
    assert widget.alignment_status.ready
    for index, direction in enumerate(widget.DIRECTIONS):
        for offset in range(3):
            calibration.add_sample(direction, (.5, .5, 0., 0.), 1. + index + offset / 10, 1.)
    assert not calibration.fit()[0]
    widget._render_diagnostics()
    details = json.loads(widget.diagnostics_text.toPlainText())
    assert details["alignment"]["ready"] is True
    assert details["alignment_policy"]["min_eye_width_pixels"] == 32.
    assert details["calibration"]["ready"] is False
    assert details["eye_only_estimate"]["direction"] == "UNKNOWN"
    assert not calibration.ready
