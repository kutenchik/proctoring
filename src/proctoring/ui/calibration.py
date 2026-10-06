"""Timed, session-only calibration using capture-time-qualified face results."""
from __future__ import annotations

from dataclasses import asdict
import json
import math
import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from ..vision.types import GazeDirection
from ..vision.alignment import FaceAlignment
from .diagnostic_panel import DiagnosticPanel, frame_size


class CalibrationWidget(QWidget):
    changed = Signal()
    validation_active_changed = Signal(bool)
    validation_target_changed = Signal(str)
    DIRECTIONS = (GazeDirection.CENTER, GazeDirection.LEFT, GazeDirection.RIGHT, GazeDirection.DOWN)

    def __init__(self, calibration, required_samples: int, max_age: float, parent=None,
                 *, clock=time.monotonic, preparation_seconds=2.0,
                 collection_seconds=3.0, diagnostics_enabled=False, cue=None, alignment_config=None):
        super().__init__(parent)
        self.calibration = calibration
        self.required_samples = required_samples
        self.max_age = max_age
        self.clock = clock
        self.preparation_seconds = preparation_seconds
        self.collection_seconds = collection_seconds
        self._cue = cue or QApplication.beep
        self.direction_index = 0
        self.preparing = False
        self.collecting = False
        self._healthy = False
        self._latest_timestamp = float("-inf")
        self._last_sample_timestamp = float("-inf")
        self._collection_start = None
        self._collection_end = None
        self._fit_failed = False
        self._last_rejected = {}
        self._latest_face = None
        self._latest_face_timestamp = None
        self._last_attempt = None
        self._current_result = None
        self.alignment = FaceAlignment(alignment_config or calibration.config.alignment, max_age=max_age)
        self.alignment_status = self.alignment.status
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.prompt = QLabel()
        self.prompt.setWordWrap(True)
        self.prompt.setStyleSheet("font-weight: 600; font-size: 16px")
        layout.addWidget(self.prompt)
        self.alignment_label = QLabel("Center your face inside the camera guide.")
        self.alignment_label.setWordWrap(True)
        layout.addWidget(self.alignment_label)
        self.alignment_progress = QProgressBar()
        self.alignment_progress.setRange(0, 100)
        self.alignment_progress.setFormat("Position stability %p%")
        self.alignment_progress.setValue(0)
        layout.addWidget(self.alignment_progress)
        self.status = QLabel("Align your face in the guide, then prepare the target.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setMaximum(1000 * len(self.DIRECTIONS))
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.collect_button = QPushButton()
        self.collect_button.clicked.connect(self.begin_collection)
        self.collect_button.setEnabled(False)
        buttons.addWidget(self.collect_button)
        self.retry_button = QPushButton("Retry all targets (new baseline)")
        self.retry_button.clicked.connect(self.reset)
        buttons.addWidget(self.retry_button)
        layout.addLayout(buttons)
        self.diagnostics_panel = QGroupBox("Developer calibration diagnostics · local; export only by request")
        self.diagnostics_panel.setCheckable(True)
        self.diagnostics_panel.setChecked(False)
        diagnostic_layout = QVBoxLayout(self.diagnostics_panel)
        self.diagnostics_text = QPlainTextEdit()
        self.diagnostics_text.setReadOnly(True)
        self.diagnostics_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.diagnostics_text.setMaximumHeight(160)
        self.diagnostics_text.setVisible(False)
        self.diagnostics_panel.toggled.connect(self.diagnostics_text.setVisible)
        diagnostic_layout.addWidget(self.diagnostics_text)
        self.diagnostic_workflow = DiagnosticPanel(
            calibration.config, clock=clock, max_age=max_age,
            preparation_seconds=preparation_seconds, collection_seconds=collection_seconds, cue=self._cue)
        self.diagnostic_workflow.setVisible(False)
        self.diagnostics_panel.toggled.connect(self.diagnostic_workflow.setVisible)
        self.diagnostic_workflow.active_changed.connect(self._validation_changed)
        self.diagnostic_workflow.target_changed.connect(self.validation_target_changed)
        self.diagnostic_workflow.changed.connect(self._render_diagnostics)
        diagnostic_layout.addWidget(self.diagnostic_workflow)
        self.diagnostics_panel.setVisible(diagnostics_enabled)
        self._diagnostics_enabled = diagnostics_enabled
        layout.addWidget(self.diagnostics_panel)
        self._render_prompt()

    @property
    def validation_active(self):
        return self.diagnostic_workflow.active

    def _validation_changed(self, active):
        self.retry_button.setEnabled(not active)
        self._render_prompt()
        self.validation_active_changed.emit(active)
        self.changed.emit()

    @property
    def direction(self):
        return self.DIRECTIONS[self.direction_index]

    def _count(self, direction):
        counts = self.calibration.counts
        return counts.get(direction, counts.get(direction.value, 0))

    def _render_prompt(self, now=None):
        if self.calibration.ready:
            self.prompt.setText("Calibration complete · ready to start")
        else:
            cue = {
                "CENTER": "at the center of the screen",
                "LEFT": "just beyond the physical LEFT edge of the screen",
                "RIGHT": "just beyond the physical RIGHT edge of the screen",
                "DOWN": "below the physical bottom edge of the screen, not at an application button",
            }[self.direction.value]
            self.prompt.setText(
                f"{self.direction_index + 1} / 4 · Look {cue}. "
                "Keep your head naturally facing the screen and your eyes visible. "
                "After pressing Prepare, move your eyes to the target; hold until the completion beep."
            )
        self.collect_button.setText(f"Prepare {self.direction.value}")
        self.collect_button.setEnabled(self._healthy and not self.collecting and not self.preparing and
                                       self.alignment_status.ready and not self.calibration.ready
                                       and not self._fit_failed and not self.validation_active)
        self.diagnostic_workflow.set_availability(self._healthy, self.collecting or self.preparing)
        value = self.direction_index * 1000
        if self.calibration.ready or self._fit_failed:
            value = 4000
        elif self.collecting and now is not None:
            value += int(1000 * min(1.0, max(0.0, (now - self._collection_start) / self.collection_seconds)))
        self.progress.setValue(value)
        self._render_diagnostics()

    def _render_diagnostics(self):
        if not self._diagnostics_enabled:
            return
        face = self._latest_face
        eye_data = getattr(face, "diagnostics", None)
        pose = getattr(face, "head_pose", None)
        direction, similarity = self.calibration.classify(getattr(face, "features", None))
        stamp = self._latest_face_timestamp
        age = self.clock() - stamp if stamp is not None and math.isfinite(stamp) else None
        fresh = self._healthy and age is not None and 0 <= age < self.max_age
        if not fresh:
            direction, similarity = GazeDirection.UNKNOWN, None
        data = {
            "coordinate_convention": "Unmirrored camera coordinates: +horizontal image right, +vertical image down",
            "eye_measurements": asdict(eye_data) if eye_data is not None else "Unavailable",
            "source_frame_dimensions": frame_size(self._current_result),
            "head_pose_degrees": asdict(pose) if pose is not None else "Unavailable",
            "measurement_status": {"age_seconds": age, "fresh_and_healthy": fresh},
            "alignment": asdict(self.alignment_status),
            "alignment_policy": asdict(self.alignment.config),
            "eye_only_estimate": {"direction": direction.value, "fit_similarity_not_probability": similarity},
            "phase": "preparing" if self.preparing else "collecting" if self.collecting else "idle",
            "target": self.direction.value,
            "last_attempt": self._last_attempt,
            "calibration": self.calibration.diagnostics,
            "diagnostic_workflow": self.diagnostic_workflow.diagnostics,
        }
        rendered = json.dumps(data, indent=2, ensure_ascii=False)
        if rendered != self.diagnostics_text.toPlainText():
            vertical = self.diagnostics_text.verticalScrollBar().value()
            horizontal = self.diagnostics_text.horizontalScrollBar().value()
            self.diagnostics_text.setPlainText(rendered)
            self.diagnostics_text.verticalScrollBar().setValue(vertical)
            self.diagnostics_text.horizontalScrollBar().setValue(horizontal)

    def begin_collection(self):
        if (not self._healthy or self.collecting or self.preparing or self.calibration.ready or self._fit_failed
                or self.validation_active):
            return
        # Recheck capture freshness at click time; a formerly green preview
        # cannot authorize collection after the camera stops updating.
        self._update_alignment(self._current_result, self.clock(), self._healthy)
        if not self.alignment_status.ready:
            self.status.setText(f"Collection blocked: {self.alignment_status.message}.")
            self._render_prompt()
            return
        # Every attempt begins with an empty target. A retry can never append an
        # earlier target's measurements or an interrupted attempt's measurements.
        self.calibration.discard_target(self.direction)
        now = self.clock()
        self._collection_start = now + self.preparation_seconds
        self._collection_end = self._collection_start + self.collection_seconds
        self._last_sample_timestamp = self._latest_timestamp
        self._last_rejected = {}
        self.preparing = True
        self.status.setStyleSheet("")
        self.status.setText(
            f"Prepare for {self.direction.value}: {self.preparation_seconds:g} seconds. "
            "Look at the target now. Collection starts with a beep; keep looking until the second beep."
        )
        self._render_prompt(now)

    def reset(self):
        if self.validation_active:
            return
        if any(self.calibration.counts.values()):
            self._archive_attempt("retained before retry")
        self.calibration.reset()
        self.alignment_status = self.alignment.reset()
        self._render_alignment()
        self.direction_index = 0
        self.collecting = self.preparing = False
        self._collection_start = self._collection_end = None
        self._fit_failed = False
        self._last_sample_timestamp = self._latest_timestamp
        self._last_rejected = {}
        self._last_attempt = None
        self.status.setText("Begin again at CENTER to establish a fresh baseline, then collect all four targets.")
        self.status.setStyleSheet("")
        self._render_prompt()
        self.changed.emit()

    def _render_alignment(self):
        state = self.alignment_status
        detail = (" · Ready to prepare" if state.ready else " · Collection blocked")
        if self.validation_active:
            detail = " · Diagnostic validation keeps invalid measurements for review"
        self.alignment_label.setText(state.message + detail)
        self.alignment_label.setStyleSheet("color: #13776a" if state.ready else "color: #916000")
        self.alignment_progress.setValue(round(100 * state.progress))

    def _update_alignment(self, result, now, healthy):
        self.alignment_status = self.alignment.update(result, now, healthy)
        self._render_alignment()

    def _reject(self, reason, timestamp):
        # An unchanged latest result is polled repeatedly. Count a given repeated
        # measurement/reason only once instead of making diagnostics depend on UI FPS.
        if self._last_rejected.get(reason) == timestamp:
            return
        self._last_rejected[reason] = timestamp
        self.calibration.record_rejection(
            self.direction, reason, timestamp=timestamp,
            measurement=getattr(self._current_result, "face", None), frame_size=frame_size(self._current_result))

    def _remember_attempt(self):
        self._last_attempt = {
            "target": self.direction.value,
            **self.calibration.diagnostics["targets"][self.direction.value],
        }

    def _archive_attempt(self, outcome):
        if self._diagnostics_enabled:
            self.diagnostic_workflow.remember(self.calibration.export_snapshot(), outcome)

    def _finish_collection(self):
        self.collecting = self.preparing = False
        self._cue()
        count = self._count(self.direction)
        self._remember_attempt()
        if count < self.required_samples:
            self._archive_attempt(f"{self.direction.value}: insufficient valid samples")
            self.calibration.discard_target(self.direction)
            reasons = self._last_attempt.get("rejection_reasons", {})
            reason_text = "; ".join(f"{key}: {value}" for key, value in reasons.items()) or "no valid measurements arrived"
            self.status.setText(
                f"Too few valid {self.direction.value} samples ({count}/{self.required_samples}). "
                f"Measured rejections: {reason_text}. "
                "This target was cleared; its numerical diagnostics remain available in debug mode."
            )
            self.status.setStyleSheet("color: #ab3434")
        elif self.direction_index < len(self.DIRECTIONS) - 1:
            self.direction_index += 1
            self.status.setText("Target complete. You may look back at the application and prepare the next target.")
        else:
            ok, message = self.calibration.fit()
            self._fit_failed = not ok
            self._archive_attempt("production fit accepted" if ok else "production fit rejected")
            self.status.setText(message if ok else
                                f"Calibration quality is insufficient: {message} "
                                "Inspect the measured contributions before retrying. Failed calibration cannot start an exam.")
            self.status.setStyleSheet("color: #13776a" if ok else "color: #ab3434")
        self._render_prompt()
        self.changed.emit()

    def feed_result(self, result, now: float, healthy: bool):
        self._healthy = healthy
        self._current_result = result
        self._update_alignment(result, now, healthy)
        if result is not None:
            if math.isfinite(result.timestamp):
                self._latest_timestamp = max(self._latest_timestamp, result.timestamp)
            self._latest_face = result.face
            self._latest_face_timestamp = result.timestamp
        self.diagnostic_workflow.feed_result(result, now, healthy)
        if self.validation_active:
            self._render_prompt(now)
            return
        if not healthy:
            if self.collecting or self.preparing or any(self.calibration.counts.values()):
                if self.collecting or self.preparing:
                    self._cue()  # Let a student looking away know collection stopped.
                self.collecting = self.preparing = False
                self._remember_attempt()
                self._archive_attempt("monitoring interrupted")
                # Camera recovery may change camera/seating geometry. Recollect
                # CENTER as well rather than trusting an unverified old baseline.
                self.calibration.reset()
                self.direction_index = 0
                self._collection_start = self._collection_end = None
                self._last_sample_timestamp = self._latest_timestamp
                self._last_rejected = {}
                self._fit_failed = False
                self.status.setText(
                    "Monitoring interrupted. All calibration samples were discarded. "
                    "Wait for recovery, then prepare CENTER to establish a new baseline."
                )
            self._render_prompt(now)
            return
        if not self.preparing and not self.collecting:
            self._render_prompt(now)
            return
        # End the interval before inspecting this arrival. Even a frame captured
        # in time is rejected if its inference only arrives after the deadline.
        if now >= self._collection_end:
            if (result is not None and math.isfinite(result.timestamp)
                    and result.timestamp > self._last_sample_timestamp):
                self._reject("arrived_after_collection", result.timestamp)
            self._finish_collection()
            return
        if self.preparing and now >= self._collection_start:
            if self.alignment_status.ready:
                self.preparing = False
                self.collecting = True
                self._cue()
            else:
                # Do not move the fixed capture window or silently make up
                # missing samples. Rejections explain insufficient collections.
                self.status.setText(f"Collection blocked: {self.alignment_status.message}.")
        if self.preparing:
            if now < self._collection_start:
                self.status.setText(
                    f"Prepare {self.direction.value}: {max(1, math.ceil(self._collection_start - now))}… "
                    "Keep looking at the target. Wait for the start beep."
                )
        elif not self.alignment_status.ready:
            self.status.setText(f"Collection blocked: {self.alignment_status.message}.")
        else:
            self.status.setText(
                f"Collecting {self.direction.value}. Hold your gaze until the completion beep; "
                "you do not need to watch this indicator."
            )
        if result is None:
            self._render_prompt(now)
            return
        stamp = result.timestamp
        if not math.isfinite(stamp):
            self._reject("invalid_timestamp", stamp)
        elif stamp < self._collection_start:
            self._reject("captured_before_collection", stamp)
        elif not 0 <= now - stamp < self.max_age:
            self._reject("stale_or_future_measurement", stamp)
        elif stamp >= self._collection_end:
            self._reject("captured_after_collection", stamp)
        elif stamp <= self._last_sample_timestamp:
            self._reject("reused_or_out_of_order_measurement", stamp)
        elif now >= self._collection_start:
            self._last_sample_timestamp = stamp
            face = result.face
            if not result.face_present or face is None or not face.face_present or face.features is None:
                reason = getattr(getattr(face, "diagnostics", None), "reason", "") or "no_valid_eye_measurement"
                self._reject(reason, stamp)
            elif not self.alignment_status.ready:
                self._reject(f"alignment_{self.alignment_status.reason}", stamp)
            else:
                diagnostics = getattr(face, "diagnostics", None)
                widths = [eye.width_pixels for eye in (diagnostics.left_eye, diagnostics.right_eye)
                          if eye.width_pixels is not None and eye.width_pixels > 0] if diagnostics else []
                floor = max((1 / width for width in widths), default=None)
                self.calibration.add_sample(self.direction, face.features, stamp, face.quality,
                                            noise_floor=floor, measurement=face, frame_size=frame_size(result))
        self._render_prompt(now)
