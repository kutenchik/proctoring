"""Small Qt camera preview. The UI never runs a CV model or mutates a frame."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..i18n import manager, translate_text


class CameraPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image = QImage()
        self._frame_identity = None
        self._result = None
        self._healthy = False
        self._message = "Open the camera to begin"
        self._alignment = None
        manager.language_changed.connect(self.update)

    def set_alignment(self, status=None) -> None:
        """Show calibration alignment without changing camera data or detections.

        Fixed normalized *source-frame* bounds position the visual oval; the
        readiness policy keeps its existing rectangular containment check.
        Passing None removes the guide (for example, during the exam).
        """
        self._alignment = status
        self.update()

    def _image_target(self) -> QRectF:
        if self._image.isNull():
            return QRectF()
        scale = min(self.width() / self._image.width(), self.height() / self._image.height())
        width, height = self._image.width() * scale, self._image.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    @staticmethod
    def _normalized_rect(area: QRectF, bounds) -> QRectF:
        """Map source coordinates into the actual letterboxed camera image."""
        x1, y1, x2, y2 = bounds
        return QRectF(area.x() + x1 * area.width(), area.y() + y1 * area.height(),
                      (x2 - x1) * area.width(), (y2 - y1) * area.height())

    @classmethod
    def _alignment_oval_rect(cls, area: QRectF, bounds) -> QRectF:
        """A fixed portrait oval, independent of the detected face's bounds.

        Fit inside the configured guide region so widescreen camera frames do
        not turn the face guide sideways. Coordinates use the same image target
        as camera painting, including its letterbox offset and resize scale.
        This affects drawing only, never sample admission or readiness.
        """
        region = cls._normalized_rect(area, bounds)
        height = min(region.height(), region.width() / .75)
        oval = QRectF(0, 0, height * .75, height)
        oval.moveCenter(region.center())
        return oval

    @staticmethod
    def _alignment_feedback_rect(area: QRectF, guide: QRectF) -> QRectF:
        """Keep optional preview feedback wholly below the guide boundary."""
        height = min(27.0, area.bottom() - guide.bottom() - 7.0)
        if height < 20.0:
            # Small previews cannot fit readable text in this gap. The complete
            # feedback remains visible in the separate calibration widget.
            return QRectF()
        return QRectF(area.left() + 8, guide.bottom() + 4, area.width() - 16, height)

    def set_frame(self, frame, result=None, healthy: bool = False, message: str = "") -> None:
        self._result, self._healthy, self._message = result, healthy, message
        if frame is None:
            self._image = QImage()
            self._frame_identity = None
        elif frame is not self._frame_identity:
            # Workers publish immutable, contiguous BGR uint8 arrays. Copy the
            # QImage so painting cannot access a released camera buffer.
            if len(frame.shape) != 3 or frame.shape[2] != 3 or frame.dtype.name != "uint8":
                self._image = QImage()
                self._message = "Invalid camera preview format"
            else:
                h, w = frame.shape[:2]
                self._image = QImage(frame.data, w, h, frame.strides[0], QImage.Format.Format_BGR888).copy()
            self._frame_identity = frame
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#162e3e"))
        if self._image.isNull():
            painter.setPen(QColor("#d2e6ec"))
            painter.drawText(self.rect().adjusted(20, 20, -20, -20),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             translate_text(self._message or "Waiting for camera frames"))
            return
        target = self._image_target()
        painter.drawImage(target, self._image)
        if self._result is not None and self._healthy:
            for box in self._result.persons:
                self._box(painter, target, box, "Person", "#60dbbc")
            for box in self._result.phones:
                self._box(painter, target, box, "Phone", "#ffd166")
            face = self._result.face
            if face is not None and face.face_present and face.box is not None:
                self._box(painter, target, face.box, "", "#adccff", dashed=True)
        if not self._healthy:
            painter.fillRect(target, QColor(10, 20, 30, 160))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(target.adjusted(16, 16, -16, -16),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             translate_text(self._message or "Monitoring unavailable"))
        if self._alignment is not None:
            self._draw_alignment(painter, target)

    def _draw_alignment(self, painter: QPainter, area: QRectF) -> None:
        # A stale ready status must never remain green over an unhealthy feed.
        ready = self._healthy and self._alignment.ready
        color = QColor("#4de0b1" if ready else "#ffd166")
        rect = self._alignment_oval_rect(area, self._alignment.guide)
        painter.save()
        painter.setClipRect(area)
        painter.setPen(QPen(color, 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)

        message = (self._alignment.message if self._healthy else
                   self._message or "Waiting for fresh camera frames")
        # Keep the cue on the image, away from the eyes; the complete message is
        # also presented outside the preview by the calibration widget.
        bar = self._alignment_feedback_rect(area, rect)
        if not bar.isNull():
            painter.fillRect(bar, QColor(10, 20, 30, 210))
            painter.setPen(color)
            text = painter.fontMetrics().elidedText(translate_text(message), Qt.TextElideMode.ElideRight,
                                                   max(1, int(bar.width() - 12)))
            painter.drawText(bar.adjusted(6, 0, -6, -3), Qt.AlignmentFlag.AlignVCenter, text)
            progress = max(0.0, min(1.0, self._alignment.progress)) if self._healthy else 0.0
            painter.fillRect(QRectF(bar.left(), bar.bottom() - 2, bar.width() * progress, 2), color)
        painter.restore()

    @staticmethod
    def _box(painter, area, box, text, color, dashed=False):
        rect = QRectF(area.x() + box.x1 * area.width(), area.y() + box.y1 * area.height(),
                      box.width * area.width(), box.height * area.height())
        painter.setPen(QPen(QColor(color), 2, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
        painter.drawRect(rect)
        if text:
            painter.drawText(QPointF(rect.x() + 4, max(area.y() + 15, rect.y() - 5)),
                             f"{translate_text(text)} {box.confidence:.0%}")
