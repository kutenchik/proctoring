"""Explicit, session-local numerical export and independent labeled validation.

This widget is available only from calibration-debug. It never changes the
production calibration or emits vision observations/event-engine inputs.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..vision.diagnostic_validation import DiagnosticValidation


def frame_size(result):
    """Original source dimensions; inference/preview dimensions must not substitute."""
    if result is None:
        return None
    explicit = getattr(getattr(result, "face", None), "frame_size", None)
    if explicit is not None:
        return tuple(explicit)
    frame = getattr(result, "frame", None)
    return (int(frame.shape[1]), int(frame.shape[0])) if frame is not None else None


def numerical_metadata(result):
    face = getattr(result, "face", None)
    eyes = getattr(face, "diagnostics", None)
    pose = getattr(face, "head_pose", None)
    return {
        "frame_size": frame_size(result),
        "eyes": {"left": asdict(eyes.left_eye), "right": asdict(eyes.right_eye)} if eyes else None,
        "head_pose_degrees": asdict(pose) if pose else None,
    }


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class DiagnosticPanel(QWidget):
    active_changed = Signal(bool)
    target_changed = Signal(str)
    changed = Signal()
    TARGETS = ("CENTER", "LEFT", "RIGHT", "DOWN", "READING")
    MAX_RETAINED_ATTEMPTS = 8

    def __init__(self, config, *, clock, max_age, preparation_seconds, collection_seconds, cue,
                 parent=None):
        super().__init__(parent)
        self.config = config
        self.clock = clock
        self.max_age = max_age
        self.preparation_seconds = preparation_seconds
        self.collection_seconds = collection_seconds
        self.cue = cue
        self.attempts = []
        self._attempt_serial = 0
        self.validation = None
        self.active = False
        self.collecting = False
        self._healthy = False
        self._collector_busy = False
        self._index = 0
        self._start = self._end = None
        self._last_timestamp = -math.inf
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.attempt_selector = QComboBox()
        self.attempt_selector.setPlaceholderText("Finish a calibration target to retain numerical diagnostics")
        self.attempt_selector.currentIndexChanged.connect(self._select_attempt)
        layout.addWidget(self.attempt_selector)
        export_row = QHBoxLayout()
        self.export_enabled = QCheckBox("Enable local numerical export (no images or video)")
        self.export_enabled.setChecked(False)
        self.export_enabled.toggled.connect(self._render)
        export_row.addWidget(self.export_enabled)
        self.export_button = QPushButton("Export diagnostics…")
        self.export_button.clicked.connect(self._choose_export)
        export_row.addWidget(self.export_button)
        layout.addLayout(export_row)
        self.validation_status = QLabel(
            "DEBUG / UNVALIDATED: a separate labeled pass checks new measurements against a frozen attempt. "
            "It cannot enable exam start or create review events.")
        self.validation_status.setWordWrap(True)
        layout.addWidget(self.validation_status)
        validation_row = QHBoxLayout()
        self.validation_button = QPushButton("Start separate validation")
        self.validation_button.clicked.connect(self.begin_validation)
        validation_row.addWidget(self.validation_button)
        self.prepare_button = QPushButton("Prepare validation CENTER")
        self.prepare_button.clicked.connect(self.prepare_target)
        validation_row.addWidget(self.prepare_button)
        self.cancel_button = QPushButton("Stop validation")
        self.cancel_button.clicked.connect(self.cancel_validation)
        validation_row.addWidget(self.cancel_button)
        layout.addLayout(validation_row)
        self.export_status = QLabel("")
        self.export_status.setWordWrap(True)
        layout.addWidget(self.export_status)
        self._render()

    @property
    def selected_attempt(self):
        index = self.attempt_selector.currentIndex()
        return self.attempts[index] if 0 <= index < len(self.attempts) else None

    def remember(self, snapshot, outcome):
        """Freeze even an incomplete/rejected attempt before the collector clears it."""
        saved = {"outcome": outcome, "calibration": deepcopy(snapshot), "validation": None}
        if self.attempts and self.attempts[-1]["calibration"] == saved["calibration"]:
            return
        self._attempt_serial += 1
        self.attempts.append(saved)
        # Each attempt can contain bounded numerical rows for four targets.
        # Retain a useful recent history without accumulating indefinitely.
        if len(self.attempts) > self.MAX_RETAINED_ATTEMPTS:
            self.attempts.pop(0)
            self.attempt_selector.removeItem(0)
        self.attempt_selector.addItem(f"Attempt {self._attempt_serial} · {outcome}")
        self.attempt_selector.setCurrentIndex(len(self.attempts) - 1)
        self._render()

    def _select_attempt(self, *_):
        if not self.active:
            self.validation = None
        self._render()
        self.changed.emit()

    def set_availability(self, healthy, collector_busy):
        self._healthy = healthy
        self._collector_busy = collector_busy
        self._render()

    def _render(self, *_):
        saved = self.selected_attempt is not None
        self.export_button.setEnabled(saved and self.export_enabled.isChecked())
        self.attempt_selector.setEnabled(not self.active)
        self.validation_button.setEnabled(saved and self._healthy and not self.active and not self._collector_busy)
        self.prepare_button.setEnabled(self.active and self._healthy and self._start is None)
        self.prepare_button.setText(f"Prepare validation {self.TARGETS[min(self._index, 4)]}")
        self.cancel_button.setEnabled(self.active)

    def begin_validation(self):
        if not self.validation_button.isEnabled():
            return
        self.validation = DiagnosticValidation(self.selected_attempt["calibration"], self.config)
        self._index = 0
        self._start = self._end = None
        self._last_timestamp = -math.inf
        self.active = True
        self.active_changed.emit(True)
        self._show_target()
        self._render()

    def _show_target(self):
        target = self.TARGETS[self._index]
        directions = {
            "CENTER": "Look at the center of the screen.",
            "LEFT": "Move only your eyes just beyond the physical left edge of the screen.",
            "RIGHT": "Move only your eyes just beyond the physical right edge of the screen.",
            "DOWN": "Move only your eyes below the physical bottom edge of the screen.",
            "READING": "Read normally within the displayed quiz area, including question and answer choices.",
        }
        self.validation_status.setText(
            f"DEBUG / UNVALIDATED · new pass {self._index + 1}/5 · {target}. "
            f"{directions[target]} Keep your head comfortable and steady. Press Prepare; "
            "collection begins and ends with a beep. The operator supplies the target label.")
        # READING opens the actual quiz page and hides these controls. Keep
        # Prepare visible until its independent collection window is scheduled.
        if target != "READING":
            self.target_changed.emit(target)

    def prepare_target(self):
        if not self.prepare_button.isEnabled():
            return
        self._start = self.clock() + self.preparation_seconds
        self._end = self._start + self.collection_seconds
        try:
            self.validation.start_target(self.TARGETS[self._index], self._start, self._end)
        except ValueError as exc:
            self._start = self._end = None
            self.validation_status.setText(f"DEBUG / UNVALIDATED: {exc}")
            self._render()
            return
        self.collecting = False
        if self.TARGETS[self._index] == "READING":
            self.target_changed.emit("READING")
        self._render()

    def feed_result(self, result, now, healthy):
        self._healthy = healthy
        if not self.active:
            self._render()
            return
        if not healthy:
            self.cancel_validation("Monitoring interrupted; the validation window was discarded. Start a fresh pass.")
            return
        if self._start is None:
            self._render()
            return
        if now >= self._end:
            self.validation.finish_target(now)
            self.cue()
            self._save_report()
            self._start = self._end = None
            self.collecting = False
            self._index += 1
            if self._index == len(self.TARGETS):
                self.active = False
                self.active_changed.emit(False)
                self.target_changed.emit("")
                self.validation_status.setText(
                    "DEBUG / UNVALIDATED · separate pass complete. Inspect predicted labels, UNKNOWN rate "
                    "and target confusion in the numerical diagnostics/export. This is diagnostic evidence, "
                    "not proof of validated accuracy or permission to start a rejected calibration.")
            else:
                self._show_target()
            self._render()
            self.changed.emit()
            return
        if now < self._start:
            self.validation_status.setText(
                f"DEBUG / UNVALIDATED · Prepare {self.TARGETS[self._index]}: "
                f"{max(1, math.ceil(self._start - now))}… Keep looking at the target until the completion beep.")
            return
        if not self.collecting:
            self.collecting = True
            self.cue()
        self.validation_status.setText(
            f"DEBUG / UNVALIDATED · Collecting new {self.TARGETS[self._index]} measurements. "
            "Hold until the completion beep.")
        if result is None:
            return
        stamp = result.timestamp
        if not math.isfinite(stamp) or stamp <= self._last_timestamp or not 0 <= now - stamp < self.max_age:
            return
        if stamp < self._start or stamp >= self._end:
            return
        self._last_timestamp = stamp
        face = result.face
        reason = None
        if not result.face_present or face is None or not face.face_present or face.features is None:
            reason = getattr(getattr(face, "diagnostics", None), "reason", "") or "no_valid_eye_measurement"
        self.validation.add_sample(
            getattr(face, "features", None), stamp, getattr(face, "quality", 0.0),
            metadata=numerical_metadata(result), rejection_reason=reason)

    def _save_report(self):
        if self.validation is not None and self.selected_attempt is not None:
            self.selected_attempt["validation"] = deepcopy(self.validation.report)

    def cancel_validation(self, reason="Stopped by operator; start a fresh separate pass to collect all targets."):
        if not isinstance(reason, str):  # QPushButton.clicked carries a boolean.
            reason = "Stopped by operator; start a fresh separate pass to collect all targets."
        if self.validation is not None and self._start is not None:
            self.validation.cancel_target(reason)
        self._save_report()
        self._start = self._end = None
        self.collecting = False
        was_active, self.active = self.active, False
        if was_active:
            self.cue()
            self.active_changed.emit(False)
            self.target_changed.emit("")
        self.validation_status.setText(f"DEBUG / UNVALIDATED · {reason}")
        self._render()
        self.changed.emit()

    @property
    def diagnostics(self):
        if self.selected_attempt is None:
            return None
        report = self.validation.report if self.validation else self.selected_attempt["validation"]
        return {
            "retained_attempt": self.attempt_selector.currentText(),
            "retained_calibration": self.selected_attempt["calibration"].get("diagnostics", {}),
            "independent_validation": {key: value for key, value in report.items() if key != "samples"} if report else None,
            "raw_numerical_samples": "Available only in the explicitly requested export; not shown on each live UI refresh",
            "export_enabled": self.export_enabled.isChecked(),
        }

    def export_to_path(self, path):
        """Called only after explicit opt-in and an operator-chosen filename."""
        if not self.export_enabled.isChecked() or self.selected_attempt is None:
            raise ValueError("Enable numerical export and select a retained attempt first.")
        self._save_report()
        payload = {
            "format": "local-proctoring-gaze-diagnostics-v1",
            "classification_status": "DEBUG / UNVALIDATED",
            "contains_images_or_video": False,
            "purpose": "Operator-labeled numerical diagnosis; never used to authorize an exam or generate events.",
            "validation_ui_admission_policy": (
                "The UI excludes stale, future, duplicate and outside-window deliveries before sample collection. "
                "Validation rejection_reasons count fresh invalid measurements, not repeated UI polling. "
                "Invalid fresh measurements remain in the UNKNOWN-rate denominator."),
            **deepcopy(self.selected_attempt),
        }
        Path(path).write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        self.export_status.setText(f"Numerical diagnostics saved locally: {path}")

    def _choose_export(self):
        if not self.export_button.isEnabled():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save local numerical diagnostics", "gaze-diagnostics.json", "JSON (*.json)")
        if not path:
            return
        try:
            self.export_to_path(path)
        except (OSError, ValueError) as exc:
            self.export_status.setText(f"Could not export numerical diagnostics: {exc}")
