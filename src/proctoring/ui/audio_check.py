"""Small pre-exam microphone check; only reads the audio worker's latest state."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QSlider, QVBoxLayout)

from ..i18n import manager, t


class AudioLevelMeter(QProgressBar):
    """Normalized RMS with a threshold marker anchored to the full meter width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 1000)
        self.setTextVisible(False)
        self.setMinimumHeight(24)
        self.setMaximumHeight(28)
        self.threshold = .15

    def set_levels(self, rms: float, threshold: float) -> None:
        self.threshold = min(1., max(0., threshold))
        self.setValue(round(min(1., max(0., rms)) * 1000))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 3, -2, -3).toRectF()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8eef2"))
        painter.drawRoundedRect(rect, 5, 5)
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        gradient.setColorAt(0, QColor("#249b72"))
        gradient.setColorAt(max(.001, min(.90, self.threshold * .65)), QColor("#60b975"))
        gradient.setColorAt(max(.002, min(.95, self.threshold * .92)), QColor("#eebf43"))
        gradient.setColorAt(max(.003, min(.99, self.threshold * 1.08)), QColor("#da615c"))
        gradient.setColorAt(1, QColor("#cf4949"))
        painter.save()
        painter.setClipRect(rect.adjusted(0, 0, -rect.width() * (1 - self.value() / 1000), 0))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 5, 5)
        painter.restore()
        marker = rect.left() + rect.width() * self.threshold
        painter.setPen(QPen(QColor("#213d51"), 2))
        painter.drawLine(QPointF(marker, rect.top()), QPointF(marker, rect.bottom()))
        painter.setBrush(QColor("#213d51"))
        painter.drawPolygon(QPolygonF([QPointF(marker - 3, 0), QPointF(marker + 3, 0),
                                       QPointF(marker, rect.top() + 3)]))


class AudioCheckWidget(QGroupBox):
    """Never opens a second input device or performs microphone I/O in Qt slots.

    The parent starts the shared worker once registration is complete. A 20 Hz
    timer coalesces state changes, so queued worker levels cannot flood the UI.
    """

    def __init__(self, monitor, config, parent=None):
        super().__init__(parent)
        self.monitor, self.config = monitor, config
        self._exam_active = False
        self._status = {}
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        self.meter = AudioLevelMeter(self)
        layout.addWidget(self.meter)
        self.level_label = QLabel()
        self.level_label.setStyleSheet("color: #5c7081; font-size: 12px;")
        self.level_label.setWordWrap(True)
        layout.addWidget(self.level_label)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(42)
        layout.addWidget(self.status_label)
        self.calibrate_button = QPushButton()
        self.calibrate_button.clicked.connect(self._calibrate)
        layout.addWidget(self.calibrate_button)
        sensitivity = QHBoxLayout()
        self.sensitivity_label = QLabel()
        sensitivity.addWidget(self.sensitivity_label)
        self.sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity_slider.setObjectName("audioSensitivity")
        self.sensitivity_slider.setRange(0, 100)
        self.sensitivity_slider.setValue(50)
        self.sensitivity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sensitivity_slider.setTickInterval(50)
        self.sensitivity_slider.valueChanged.connect(self._sensitivity_changed)
        sensitivity.addWidget(self.sensitivity_slider, 1)
        self.sensitivity_value = QLabel()
        sensitivity.addWidget(self.sensitivity_value)
        layout.addLayout(sensitivity)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet("color: #5c7081; font-size: 12px;")
        layout.addWidget(self.notice)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        manager.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def set_exam_active(self, active: bool) -> None:
        self._exam_active = active
        if active:
            self.timer.stop()
        elif not self.timer.isActive():
            self.timer.start()
        self.refresh()

    def _calibrate(self) -> None:
        if not self._exam_active:
            if self.monitor.check_status.get("state") == "unavailable":
                # Retry hardware without forcing an ambient check or requiring
                # adaptive mode. The next calibration remains an explicit step.
                self.monitor.start()
            else:
                self.monitor.begin_calibration()
            self.refresh()

    def _sensitivity_changed(self, value: int) -> None:
        if not self._exam_active:
            # Higher sensitivity means a lower absolute trigger, not input gain.
            self.monitor.set_sensitivity(1.5 - value / 100)
            self.refresh()

    @staticmethod
    def _finite(value, default=0.) -> float:
        try:
            result = float(value)
            return result if math.isfinite(result) else default
        except (TypeError, ValueError):
            return default

    def refresh(self) -> None:
        self._status = dict(self.monitor.check_status)
        state = self._status.get("state", "idle")
        rms = self._finite(self._status.get("rms"))
        threshold = self._finite(self._status.get("threshold"), self.config.energy_threshold)
        self.meter.set_levels(rms, threshold)
        source = ("pending" if state == "speak" else self._status.get("threshold_source", "fallback"))
        if source not in {"pending", "fallback", "manual", "adaptive"}:
            source = "fallback"
        ambient = self._status.get("ambient")
        if (state not in {"ambient", "speak"} and source in {"adaptive", "manual"}
                and self._status.get("committed_ambient") is not None):
            # A failed retry retains the last committed trigger. Display its
            # matching reference, not the failed attempt's different room floor.
            ambient = self._status["committed_ambient"]
        elif ambient is None:
            ambient = self._status.get("committed_ambient")
        ambient_text = "—" if ambient is None else f"{self._finite(ambient):.3f}"
        self.level_label.setText(t("audio_check.level", rms=rms, threshold=threshold) + "\n" +
                                 t("audio_check.detail", ambient=ambient_text,
                                   source=t(f"audio_check.source.{source}")))
        self.meter.setAccessibleDescription(self.level_label.text())
        if self._exam_active:
            message = t("audio_check.exam")
        elif state == "ambient":
            progress = min(1., max(0., self._finite(self._status.get("progress"))))
            message = t("audio_check.ambient", seconds=max(0., 2.5 * (1 - progress)))
        elif state == "ready":
            message = t("audio_check.ready", threshold=threshold)
        elif state in ("unavailable", "disabled"):
            message = t("audio_check.unavailable" if state == "unavailable" else "audio_check.disabled")
        elif state in ("speak", "no_signal", "noisy", "initializing"):
            message = t(f"audio_check.{state}")
        else:
            message = t("audio_check.idle" if self.config.adaptive_calibration else "audio_check.fixed")
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: " + ("#13776a" if state == "ready" else
                                                     "#9b6511" if state in ("no_signal", "noisy", "unavailable")
                                                     else "#213d51") + ";")
        allowed = not self._exam_active and state not in ("disabled", "initializing")
        # A disconnected/denied device can be retried explicitly; never reopen
        # it automatically on every setup refresh.
        self.calibrate_button.setText(t("audio_check.retry" if state == "unavailable" else
                                        "audio_check.calibrate"))
        self.calibrate_button.setEnabled(allowed and state not in ("ambient", "speak")
                                         and (state == "unavailable" or self.config.adaptive_calibration))
        self.sensitivity_slider.setEnabled(allowed and state not in ("ambient", "unavailable"))
        value = self.sensitivity_slider.value()
        self.sensitivity_value.setText(t("audio_check.high" if value > 66 else
                                         "audio_check.low" if value < 34 else "audio_check.medium"))

    def retranslate_ui(self, *_):
        self.setTitle(t("audio_check.title"))
        self.calibrate_button.setText(t("audio_check.calibrate"))
        self.sensitivity_label.setText(t("audio_check.sensitivity"))
        self.sensitivity_slider.setAccessibleName(t("audio_check.sensitivity"))
        self.sensitivity_slider.setToolTip(t("audio_check.sensitivity_hint"))
        self.meter.setAccessibleName(t("audio_check.meter"))
        self.notice.setText(t("audio_check.notice"))
        self.refresh()
