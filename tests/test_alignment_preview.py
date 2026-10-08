"""Source-frame alignment rendering, with no camera or Windows hooks."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from proctoring.ui.preview import CameraPreview
from proctoring.vision.types import Box


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def alignment(ready=False, message="Hold still", progress=.5):
    return SimpleNamespace(ready=ready, message=message, progress=progress,
                           guide=(.18, .08, .82, .92))


@pytest.fixture
def preview(qt_app):
    widget = CameraPreview()
    widget.setFixedSize(640, 360)
    yield widget
    widget.close()


@pytest.mark.parametrize("source_size, target", [
    ((640, 480), (80, 0, 480, 360)),
    ((1280, 720), (0, 0, 640, 360)),
])
def test_oval_uses_actual_source_aspect_ratio(preview, source_size, target):
    width, height = source_size
    preview.set_frame(np.zeros((height, width, 3), dtype=np.uint8), healthy=True)
    preview.set_alignment(alignment())
    image_target = preview._image_target()
    assert image_target.getRect() == pytest.approx(target)
    actual = preview._alignment_oval_rect(image_target, preview._alignment.guide)
    assert actual.getRect() == pytest.approx((206.6, 28.8, 226.8, 302.4))
    # The same mapping is used by painting, including the letterbox offset.
    rendered = preview.grab().toImage()
    assert_oval_stroke(rendered, actual, "#ffd166")
    # The old rectangle/corner brackets must not remain visible.
    for bounds in (actual, preview._normalized_rect(image_target, preview._alignment.guide)):
        for corner in (bounds.topLeft(), bounds.topRight(), bounds.bottomLeft(), bounds.bottomRight()):
            assert rendered.pixelColor(round(corner.x()), round(corner.y())).name() == "#000000"
    bar = preview._alignment_feedback_rect(image_target, actual)
    assert bar.top() > actual.bottom()
    assert bar.bottom() < image_target.bottom()
    assert not bar.intersects(actual)


def assert_oval_stroke(rendered, rect, color):
    for x, y in ((rect.center().x(), rect.top()), (rect.center().x(), rect.bottom()),
                 (rect.left(), rect.center().y()), (rect.right(), rect.center().y())):
        assert rendered.pixelColor(round(x), round(y)).name() == color


@pytest.mark.parametrize("source_size", [(640, 480), (1280, 720)])
def test_oval_stays_on_image_during_resize_and_letterboxing(preview, source_size):
    width, height = source_size
    preview.set_frame(np.zeros((height, width, 3), dtype=np.uint8), healthy=True)
    preview.set_alignment(alignment())
    for widget_width, widget_height in ((960, 360), (360, 640), (800, 600)):
        preview.setFixedSize(widget_width, widget_height)
        area = preview._image_target()
        oval = preview._alignment_oval_rect(area, preview._alignment.guide)
        assert oval.center() == area.center()
        assert oval.width() / oval.height() == pytest.approx(.75)
        assert area.contains(oval)
        # The same source coordinates survive both side and top/bottom bars.
        assert (oval.left() - area.left()) / area.width() == pytest.approx(.5 - .315 * height / width)
        assert (oval.top() - area.top()) / area.height() == pytest.approx(.08)
        rendered = preview.grab().toImage()
        assert_oval_stroke(rendered, oval, "#ffd166")
        if area.left() > 0:
            assert rendered.pixelColor(0, widget_height // 2).name() == "#162e3e"
        if area.top() > 0:
            assert rendered.pixelColor(widget_width // 2, 0).name() == "#162e3e"


def test_face_motion_does_not_move_or_resize_oval(preview):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    preview.set_alignment(alignment())
    for bounds in ((.3, .2, .6, .6), (.2, .15, .8, .9)):
        face = SimpleNamespace(face_present=True, box=Box(*bounds))
        preview.set_frame(frame, result=SimpleNamespace(persons=(), phones=(), face=face), healthy=True)
        oval = preview._alignment_oval_rect(preview._image_target(), preview._alignment.guide)
        assert oval.getRect() == pytest.approx((206.6, 28.8, 226.8, 302.4))
        assert_oval_stroke(preview.grab().toImage(), oval, "#ffd166")


def test_normalized_mapping_preserves_fractional_coordinates():
    area = QRectF(17.5, 2.125, 501.25, 320.5)
    bounds = (.18125, .08125, .82125, .92125)
    actual = CameraPreview._normalized_rect(area, bounds)
    assert actual.x() == pytest.approx(108.3515625)
    assert actual.y() == pytest.approx(28.165625)
    assert actual.width() == pytest.approx(320.8)
    assert actual.height() == pytest.approx(269.22)


def test_hiding_alignment_restores_preview_and_does_not_mutate_frame(preview):
    frame = np.full((480, 640, 3), 32, dtype=np.uint8)
    original = frame.copy()
    preview.set_frame(frame, healthy=True)
    plain = preview.grab().toImage()
    preview.set_alignment(alignment(True, "Face aligned", 1))
    guided = preview.grab().toImage()
    assert guided != plain
    assert np.array_equal(frame, original)
    assert preview._image.pixelColor(100, 100).name() == "#202020"
    preview.set_alignment(None)
    assert preview.grab().toImage() == plain


def test_ready_is_green_only_while_monitoring_is_healthy(preview):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    preview.set_frame(frame, healthy=True)
    preview.set_alignment(alignment(True, "Face aligned", 1))
    rect = preview._alignment_oval_rect(preview._image_target(), preview._alignment.guide)
    point = (round(rect.center().x()), round(rect.top()))
    assert preview.grab().toImage().pixelColor(*point).name() == "#4de0b1"
    preview.set_frame(frame, healthy=False, message="Camera disconnected")
    assert preview.grab().toImage().pixelColor(*point).name() == "#ffd166"


def test_empty_preview_has_no_invented_source_rectangle(preview):
    preview.set_alignment(alignment())
    assert preview._image_target().isNull()
    assert not preview.grab().toImage().isNull()


def test_small_preview_omits_feedback_instead_of_hiding_guide(preview):
    preview.setFixedSize(320, 180)
    preview.set_frame(np.zeros((480, 640, 3), dtype=np.uint8), healthy=True)
    preview.set_alignment(alignment())
    area = preview._image_target()
    guide = preview._alignment_oval_rect(area, preview._alignment.guide)
    assert preview._alignment_feedback_rect(area, guide).isNull()
    rendered = preview.grab().toImage()
    assert_oval_stroke(rendered, guide, "#ffd166")
