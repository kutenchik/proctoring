"""Source-frame alignment rendering, with no camera or Windows hooks."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from proctoring.ui.preview import CameraPreview


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


@pytest.mark.parametrize("source_size, target, guide", [
    ((640, 480), (80, 0, 480, 360), (166.4, 28.8, 307.2, 302.4)),
    ((1280, 720), (0, 0, 640, 360), (115.2, 28.8, 409.6, 302.4)),
])
def test_guide_uses_actual_source_aspect_ratio(preview, source_size, target, guide):
    width, height = source_size
    preview.set_frame(np.zeros((height, width, 3), dtype=np.uint8), healthy=True)
    preview.set_alignment(alignment())
    image_target = preview._image_target()
    assert image_target.getRect() == pytest.approx(target)
    actual = preview._normalized_rect(image_target, preview._alignment.guide)
    assert actual.getRect() == pytest.approx(guide)
    # The same mapping is used by painting, including the letterbox offset.
    rendered = preview.grab().toImage()
    assert rendered.pixelColor(round(actual.left()), round(actual.top())).name() == "#ffd166"
    assert rendered.pixelColor(round(actual.left()), round(actual.bottom())).name() == "#ffd166"
    bar = preview._alignment_feedback_rect(image_target, actual)
    assert bar.top() > actual.bottom()
    assert bar.bottom() < image_target.bottom()
    assert not bar.intersects(actual)


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
    rect = preview._normalized_rect(preview._image_target(), preview._alignment.guide)
    point = (round(rect.left()), round(rect.top()))
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
    guide = preview._normalized_rect(area, preview._alignment.guide)
    assert preview._alignment_feedback_rect(area, guide).isNull()
    rendered = preview.grab().toImage()
    assert rendered.pixelColor(round(guide.left()), round(guide.bottom())).name() == "#ffd166"
