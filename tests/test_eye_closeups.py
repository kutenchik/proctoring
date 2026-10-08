"""Eye inspection uses current source pixels without changing gaze admission."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from proctoring.ui.eye_closeups import ApertureContext, EyeCloseups
from proctoring.vision.types import EyeDiagnostic, EyeOverlay, FaceMeasurement, GazeDiagnostics, VisionResult


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qt_app):
    widget = EyeCloseups()
    widget.set_enabled(True)
    yield widget
    widget.close()


def overlay(offset=0):
    return SimpleNamespace(corners=((.3 + offset, .4), (.4 + offset, .4)),
                           lids=((.35 + offset, .39), (.35 + offset, .41)),
                           iris=((.35 + offset, .4), (.36 + offset, .4), (.35 + offset, .39),
                                 (.34 + offset, .4), (.35 + offset, .41)))


def result(timestamp=10, opening=.2, valid=True, reason="ok", dimensions=(640, 480)):
    eye = EyeDiagnostic(.5, .5, opening, valid, reason, 64)
    face = SimpleNamespace(face_present=True, frame_size=dimensions,
                           left_eye_overlay=overlay(), right_eye_overlay=overlay(.25),
                           diagnostics=GazeDiagnostics(eye, eye, valid, reason))
    return VisionResult(timestamp, face_present=True, face=face,
                        frame=np.full((480, 640, 3), (7, 9, 13), dtype=np.uint8))


def assert_cleared(panel):
    for view in (panel.left, panel.right):
        assert view.image.image.isNull()
        assert view.image.source_rect is None
        assert view.image.points == {}
        assert view.context.last_timestamp is None


def test_disabled_is_opt_in_and_discards_pixels_and_history(qt_app):
    panel = EyeCloseups()
    assert not panel._enabled
    panel.feed_result(result(), 10, True)
    assert_cleared(panel)
    panel.set_enabled(True)
    panel.feed_result(result(opening=.05), 10, True)
    assert not panel.left.image.image.isNull()
    panel.set_enabled(False)
    assert_cleared(panel)
    assert panel.isHidden()
    panel.set_enabled(True)
    assert_cleared(panel)
    panel.close()


def test_matching_frame_crops_preserve_source_pixels_and_fractional_markers(panel):
    current = result()
    source_before = current.frame.copy()
    panel.feed_result(current, 10.1, True)
    assert np.array_equal(current.frame, source_before)
    view = panel.left.image
    assert not view.image.isNull()
    x1, y1, x2, y2 = view.source_rect
    assert (view.image.width(), view.image.height()) == (x2 - x1, y2 - y1)
    assert view.image.pixelColor(0, 0).getRgb() == (13, 9, 7, 255)
    assert view.points["iris"][0] == pytest.approx((.35 * 640 - x1, .4 * 480 - y1))
    assert view.points["lids"][0] == pytest.approx((.35 * 640 - x1, .39 * 480 - y1))
    assert "0.200" in panel.left.details.text()
    assert "64.0 source px" in panel.left.details.text()
    assert "iris visibility not verified" in panel.left.details.text()
    assert "No automatic glare detection" in panel.status.text()
    # QImage owns a copy; the worker's memory cannot change a displayed crop.
    current.frame[:] = 255
    assert view.image.pixelColor(0, 0).getRgb() == (13, 9, 7, 255)


def test_degenerate_crop_clears_inspection_instead_of_raising_a_pipeline_failure(panel, monkeypatch):
    panel.feed_result(result(), 10., True)
    def bad_crop(*_):
        raise ValueError("Empty eye crop")
    monkeypatch.setattr(panel.left.image, "set_source", bad_crop)
    panel.feed_result(result(timestamp=10.1), 10.1, True)
    assert_cleared(panel)
    assert "degenerate source eye crop" in panel.status.text()


def test_real_face_overlay_contract_is_rendered(panel):
    current = result()
    left, right = overlay(), overlay(.25)
    face = FaceMeasurement(True, diagnostics=current.face.diagnostics, frame_size=(640, 480),
                           left_eye_overlay=EyeOverlay(left.corners, left.lids, left.iris),
                           right_eye_overlay=EyeOverlay(right.corners, right.lids, right.iris))
    panel.feed_result(replace(current, face=face), 10, True)
    assert not panel.left.image.image.isNull()
    assert not panel.right.image.image.isNull()


@pytest.mark.parametrize("size", [(350, 100), (180, 250), (700, 300)])
def test_markers_follow_crop_during_resizing_and_letterboxing(panel, size):
    panel.feed_result(result(), 10, True)
    view = panel.left.image
    view.setFixedSize(*size)
    target = view.image_target()
    center = view.mapped_point(view.points["iris"][0])
    x, y = view.points["iris"][0]
    assert center.x() == pytest.approx(target.x() + x / view.image.width() * target.width())
    assert center.y() == pytest.approx(target.y() + y / view.image.height() * target.height())
    rendered = view.grab().toImage()
    # Cross is painted from crop-local source coordinates, not preview coords.
    assert rendered.pixelColor(round(center.x()), round(center.y())).green() > 180


@pytest.mark.parametrize("age", [.5, .51, -0.01, float("nan"), float("inf")])
def test_stale_or_future_frame_clears_both_images_and_history(panel, age):
    panel.feed_result(result(), 10, True)
    panel.feed_result(result(), 10 + age, True)
    assert_cleared(panel)
    assert "timestamp" in panel.status.text()


@pytest.mark.parametrize("change", ["no_result", "unhealthy", "worker_unhealthy", "no_face", "absent_face",
                                   "no_frame", "wrong_dimensions", "unknown_dimensions", "wrong_format",
                                   "missing_pair", "nonfinite_overlay", "no_diagnostics"])
def test_unavailable_measurement_never_leaves_a_previous_eye_image(panel, change):
    panel.feed_result(result(), 10, True)
    current, healthy = result(10.1), True
    if change == "no_result":
        current = None
    elif change == "unhealthy":
        healthy = False
    elif change == "worker_unhealthy":
        current = replace(current, monitoring_healthy=False)
    elif change == "no_face":
        current = replace(current, face=None)
    elif change == "absent_face":
        current.face.face_present = False
    elif change == "no_frame":
        current = replace(current, frame=None)
    elif change == "wrong_dimensions":
        current.face.frame_size = (1280, 720)
    elif change == "unknown_dimensions":
        current.face.frame_size = None
    elif change == "wrong_format":
        current = replace(current, frame=np.zeros((480, 640), dtype=np.uint8))
    elif change == "missing_pair":
        current.face.right_eye_overlay = None
    elif change == "nonfinite_overlay":
        current.face.left_eye_overlay.lids = ((float("nan"), .4), (.5, .4))
    elif change == "no_diagnostics":
        current.face.diagnostics = None
    panel.feed_result(current, 10.2, healthy)
    assert_cleared(panel)
    assert "unavailable" in panel.status.text()


def test_invalid_geometry_remains_visible_for_inspection_without_claiming_valid_iris(panel):
    current = result(opening=.05, valid=False, reason="eye aperture below minimum")
    panel.feed_result(current, 10, True)
    assert not panel.left.image.image.isNull()
    assert "rejected: eye aperture below minimum" in panel.left.details.text()
    assert "blink / closure / narrowing unresolved" in panel.left.aperture.text()
    assert not current.face.diagnostics.valid


def test_panel_does_not_use_wall_clock_to_extend_a_duplicate_low_aperture(panel):
    current = result(opening=.05)
    panel.feed_result(current, 10, True)
    text = panel.left.aperture.text()
    panel.feed_result(current, 10.4, True)
    assert panel.left.aperture.text() == text
    panel.feed_result(result(10.2, opening=.05), 10.4, True)
    assert "0.20 s" in panel.left.aperture.text()
    panel.feed_result(result(10.1, opening=.05), 10.4, True)
    assert_cleared(panel)
    assert "out-of-order" in panel.status.text()


def test_aperture_context_is_descriptive_and_only_uses_unique_source_timestamps():
    context = ApertureContext()
    assert "0.00 s" in context.observe(1, .05)
    assert "0.20 s" in context.observe(1.2, .05)
    assert "0.20 s" in context.observe(1.2, .3)  # Same source frame cannot advance an episode.
    assert "ended after 0.40 s" in context.observe(1.4, .3)
    assert "not a confirmed blink" in context.last_text
    assert "ended after 0.40 s" in context.observe(1.6, .3)
    assert "ended after 0.40 s" in context.observe(2, .3)
    assert "No current" in context.observe(2.4, .3)


@pytest.mark.parametrize("opening,timestamp", [(None, 1.2), (float("nan"), 1.2),
                                               (float("inf"), 1.2), (.05, float("nan"))])
def test_nonfinite_aperture_context_does_not_preserve_episode(opening, timestamp):
    context = ApertureContext()
    context.observe(1, .05)
    assert "unavailable" in context.observe(timestamp, opening)
    assert context.last_timestamp is None
    assert context.low_since is None


@pytest.mark.parametrize("timestamp", [.5, 1.501])
def test_out_of_order_or_gapped_context_starts_new_episode(timestamp):
    context = ApertureContext()
    context.observe(1, .05)
    assert "0.00 s" in context.observe(timestamp, .05)


@pytest.mark.parametrize("max_age", [0, -1, float("nan"), float("inf")])
def test_invalid_freshness_configuration_is_rejected(qt_app, max_age):
    with pytest.raises(ValueError, match="max_age"):
        EyeCloseups(max_age=max_age)
