"""A small, noninteractive fixation marker over the actual diagnostic layout.

Coordinates describe the visible screen/client geometry, never feature-space
gaze coordinates. The marker is unrelated to the camera face-positioning guide.
"""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class ScreenTarget(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.point = None
        self.hide()

    def set_point(self, point):
        self.setGeometry(self.parentWidget().rect())
        self.point = point
        self.setVisible(point is not None)
        self.raise_()
        self.update()

    def paintEvent(self, event):
        if self.point is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#ffffff"), 6))
        painter.drawEllipse(self.point, 12, 12)
        painter.setPen(QPen(QColor("#a64c00"), 3))
        painter.drawEllipse(self.point, 12, 12)
        painter.drawLine(self.point + QPoint(-5, 0), self.point + QPoint(5, 0))
        painter.drawLine(self.point + QPoint(0, -5), self.point + QPoint(0, 5))


def position_metadata(widget, point=None):
    """Qt logical pixels and actual desktop origin account for DPI/screens."""
    screen = widget.screen()
    screen_rect = screen.geometry()
    origin = widget.mapToGlobal(QPoint(0, 0))
    data = {
        "coordinate_units": "Qt logical pixels (device-independent); screen origin retained",
        "screen_geometry": [screen_rect.x(), screen_rect.y(), screen_rect.width(), screen_rect.height()],
        "device_pixel_ratio": screen.devicePixelRatio(),
        "client_geometry": [origin.x(), origin.y(), widget.width(), widget.height()],
    }
    if point is not None:
        desktop = widget.mapToGlobal(point)
        data.update(
            client_position=[point.x(), point.y()],
            desktop_position=[desktop.x(), desktop.y()],
            client_normalized=[point.x() / max(1, widget.width()), point.y() / max(1, widget.height())],
            screen_normalized=[(desktop.x() - screen_rect.x()) / max(1, screen_rect.width()),
                               (desktop.y() - screen_rect.y()) / max(1, screen_rect.height())],
            x_normalized=(desktop.x() - screen_rect.x()) / max(1, screen_rect.width()),
            y_normalized=(desktop.y() - screen_rect.y()) / max(1, screen_rect.height()),
            rendered=True,
        )
    return data
