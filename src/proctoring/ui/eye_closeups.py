"""Opt-in, transient source-frame eye inspection; never a gaze decision.

Enlargement cannot add camera detail. Landmark geometry is displayed even when
rejected so an operator can compare markers with the actual source pixels.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..i18n import manager, translate_text
from .i18n_widgets import QLabel


@dataclass
class ApertureContext:
    """Bounded descriptive history, not a blink or eye-validity classifier."""

    low_threshold: float = .10
    maximum_gap: float = .5
    last_timestamp: float | None = None
    low_since: float | None = None
    recovered_at: float | None = None
    last_text: str = "Aperture history unavailable"

    def reset(self) -> None:
        self.last_timestamp = self.low_since = self.recovered_at = None
        self.last_text = "Aperture history unavailable"

    def observe(self, timestamp: float, opening: float | None) -> str:
        if opening is None or not math.isfinite(opening) or not math.isfinite(timestamp):
            self.reset()
            return self.last_text
        if self.last_timestamp is not None:
            if timestamp == self.last_timestamp:
                return self.last_text
            if timestamp < self.last_timestamp or timestamp - self.last_timestamp > self.maximum_gap:
                self.reset()
        self.last_timestamp = timestamp
        if opening < self.low_threshold:
            self.recovered_at = None
            if self.low_since is None:
                self.low_since = timestamp
            self.last_text = (f"Low aperture for {timestamp - self.low_since:.2f} s; "
                              "blink / closure / narrowing unresolved")
        elif self.low_since is not None:
            self.last_text = (f"Low-aperture episode ended after {timestamp - self.low_since:.2f} s "
                              "(not a confirmed blink)")
            self.low_since = None
            self.recovered_at = timestamp
        elif self.recovered_at is not None and timestamp - self.recovered_at < 1:
            # Keep the descriptive result readable instead of flashing it for
            # one frame. This never holds or changes a gaze measurement.
            pass
        else:
            self.last_text = "No current low-aperture episode (descriptive only)"
        return self.last_text


class _EyeImage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image = QImage()
        self.source_rect: tuple[int, int, int, int] | None = None
        self.points: dict[str, tuple[tuple[float, float], ...]] = {}
        manager.language_changed.connect(self.update)

    def clear(self) -> None:
        self.image = QImage()
        self.source_rect = None
        self.points = {}
        self.update()

    def set_source(self, frame, overlay) -> None:
        height, width = frame.shape[:2]
        groups = {name: tuple((x * width, y * height) for x, y in getattr(overlay, name))
                  for name in ("corners", "lids", "iris")}
        points = sum(groups.values(), ())
        eye_width = math.dist(*groups["corners"])
        min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
        min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
        center_y = (min_y + max_y) / 2
        half_height = max((max_y - min_y) / 2 + eye_width * .15, eye_width * .35)
        x1, x2 = max(0, math.floor(min_x - eye_width * .25)), min(width, math.ceil(max_x + eye_width * .25))
        y1, y2 = max(0, math.floor(center_y - half_height)), min(height, math.ceil(center_y + half_height))
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Empty eye crop")
        crop = frame[y1:y2, x1:x2].copy(order="C")
        self.image = QImage(crop.data, x2 - x1, y2 - y1, crop.strides[0], QImage.Format.Format_BGR888).copy()
        self.source_rect = (x1, y1, x2, y2)
        self.points = {name: tuple((x - x1, y - y1) for x, y in values)
                       for name, values in groups.items()}
        self.update()

    def image_target(self) -> QRectF:
        if self.image.isNull():
            return QRectF()
        scale = min(self.width() / self.image.width(), self.height() / self.image.height())
        width, height = self.image.width() * scale, self.image.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def mapped_point(self, point) -> QPointF:
        target = self.image_target()
        return QPointF(target.x() + point[0] / self.image.width() * target.width(),
                       target.y() + point[1] / self.image.height() * target.height())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#162e3e"))
        if self.image.isNull():
            painter.setPen(QColor("#d2e6ec"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             translate_text("No fresh matching eye image"))
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        target = self.image_target()
        painter.drawImage(target, self.image)
        painter.setClipRect(target)
        corners = [self.mapped_point(p) for p in self.points["corners"]]
        upper, lower = [self.mapped_point(p) for p in self.points["lids"]]
        # Minimal eyelid geometry, not an invented full eyelid contour.
        painter.setPen(QPen(QColor("#ffd166"), 1.5))
        painter.drawPolyline(QPolygonF([corners[0], upper, corners[1], lower, corners[0]]))
        for point in corners + [upper, lower]:
            painter.drawEllipse(point, 2.5, 2.5)
        iris = [self.mapped_point(p) for p in self.points["iris"]]
        painter.setPen(QPen(QColor("#4de0b1"), 1.5))
        painter.drawPolygon(QPolygonF(iris[1:]))
        center = iris[0]
        painter.drawLine(center + QPointF(-5, 0), center + QPointF(5, 0))
        painter.drawLine(center + QPointF(0, -5), center + QPointF(0, 5))


class _EyeView(QWidget):
    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.image = _EyeImage(self)
        self.details = QLabel(f"{name}: unavailable")
        self.details.setWordWrap(True)
        self.aperture = QLabel("Aperture history unavailable")
        self.aperture.setWordWrap(True)
        self.name = name
        self.context = ApertureContext()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.image, self.details, self.aperture):
            layout.addWidget(widget)

    def clear(self, reason) -> None:
        self.image.clear()
        self.context.reset()
        self.details.setText(f"{self.name}: {reason}")
        self.aperture.setText(self.context.last_text)


class EyeCloseups(QWidget):
    """Developer-only inspection of both eyes from a fresh matching result."""

    def __init__(self, parent=None, max_age: float = .5):
        super().__init__(parent)
        if not math.isfinite(max_age) or max_age <= 0:
            raise ValueError("max_age must be positive and finite")
        self.max_age = max_age
        self._enabled = False
        self._last_timestamp = None
        self.status = QLabel("Eye inspection disabled")
        self.status.setWordWrap(True)
        self.left, self.right = _EyeView("Left eye"), _EyeView("Right eye")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(self.left)
        row.addWidget(self.right)
        layout.addLayout(row)
        self.set_enabled(False)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._clear("Waiting for fresh eye measurements" if enabled else "Eye inspection disabled")
        self.setVisible(self._enabled)

    def _clear(self, reason: str) -> None:
        self._last_timestamp = None
        self.status.setText(reason)
        self.left.clear(reason)
        self.right.clear(reason)

    @staticmethod
    def _overlay_valid(overlay) -> bool:
        if overlay is None:
            return False
        try:
            for name, count in (("corners", 2), ("lids", 2), ("iris", 5)):
                points = getattr(overlay, name)
                if len(points) != count or any(len(point) != 2 for point in points):
                    return False
                if any(not math.isfinite(v) or not 0 <= v <= 1 for point in points for v in point):
                    return False
            return math.dist(*overlay.corners) > 0
        except (AttributeError, TypeError, ValueError):
            return False

    def feed_result(self, result, now: float, healthy: bool) -> None:
        if not self._enabled:
            return
        if result is None or not healthy or not result.monitoring_healthy:
            self._clear("Eye inspection unavailable: monitoring unavailable")
            return
        timestamp = result.timestamp
        if not math.isfinite(now) or not math.isfinite(timestamp) or not 0 <= now - timestamp < self.max_age:
            self._clear("Eye inspection unavailable: stale or invalid source timestamp")
            return
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            self._clear("Eye inspection unavailable: out-of-order source result")
            return
        face, frame = result.face, result.frame
        if face is None or not face.face_present:
            self._clear("Eye inspection unavailable: no face measurement")
            return
        if (frame is None or len(frame.shape) != 3 or frame.shape[2] != 3
                or min(frame.shape[:2]) <= 0
                or frame.dtype.name != "uint8" or face.frame_size != (frame.shape[1], frame.shape[0])):
            self._clear("Eye inspection unavailable: missing matching source frame or dimensions")
            return
        overlays = (getattr(face, "left_eye_overlay", None), getattr(face, "right_eye_overlay", None))
        if face.diagnostics is None or not all(self._overlay_valid(overlay) for overlay in overlays):
            reason = face.diagnostics.reason if face.diagnostics is not None else "eye diagnostics unavailable"
            self._clear(f"Eye inspection unavailable: missing or invalid eye marker pair; {reason}")
            return
        # The source image and these overlays belong to the same worker result.
        # Never borrow pixels from a newer camera frame to fill a missing image.
        self._last_timestamp = timestamp
        self.status.setText("Live source-frame eye inspection — enlargement adds no detail. "
                            "Amber: corners / eyelids; green: iris landmarks. "
                            "No automatic glare detection; images are not saved.")
        for view, overlay, diagnostic in zip((self.left, self.right), overlays,
                                             (face.diagnostics.left_eye, face.diagnostics.right_eye)):
            try:
                view.image.set_source(frame, overlay)
            except (ValueError, OverflowError):
                self._clear("Eye inspection unavailable: degenerate source eye crop")
                return
            opening = (f"{diagnostic.opening:.3f}" if diagnostic.opening is not None and math.isfinite(diagnostic.opening)
                       else "unavailable")
            width = (f"{diagnostic.width_pixels:.1f}" if diagnostic.width_pixels is not None and math.isfinite(diagnostic.width_pixels)
                     else "unavailable")
            reason = ("geometry only; iris visibility not verified" if diagnostic.valid else
                      f"rejected: {diagnostic.reason}")
            view.details.setText(f"{view.name}: openness {opening} eye widths; width {width} source px; {reason}")
            view.aperture.setText(view.context.observe(timestamp, diagnostic.opening))
