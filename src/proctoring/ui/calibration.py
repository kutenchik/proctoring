"""Timed, session-only calibration using capture-time-qualified face results."""
from __future__ import annotations

from dataclasses import asdict
import json
import math
import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ..vision.types import GazeDirection
from ..vision.alignment import FaceAlignment
from ..vision.collection import BoundedCollection, CollectionPositionGuard
from .diagnostic_panel import DiagnosticPanel, frame_size
from .eye_closeups import EyeCloseups
from .i18n_widgets import QCheckBox, QGroupBox, QLabel, QProgressBar, QPushButton


class CalibrationWidget(QWidget):
    changed = Signal()
    validation_active_changed = Signal(bool)
    validation_target_changed = Signal(str)
    guided_active_changed = Signal(bool)
    guided_target_changed = Signal(str)
    DIRECTIONS = (GazeDirection.CENTER, GazeDirection.LEFT, GazeDirection.RIGHT, GazeDirection.DOWN)

    def __init__(self, calibration, required_samples: int, max_age: float, parent=None,
                 *, clock=time.monotonic, preparation_seconds=2.0,
                 collection_seconds=3.0, max_collection_seconds=6.0, diagnostics_enabled=False, cue=None, alignment_config=None,
                 event_thresholds=None, clearing_seconds=.75):
        super().__init__(parent)
        self.calibration = calibration
        self.required_samples = required_samples
        self.max_age = max_age
        self.clock = clock
        self.preparation_seconds = preparation_seconds
        self.collection_seconds = collection_seconds
        self.max_collection_seconds = max(max_collection_seconds, collection_seconds)
        self.guided_active = False
        self.paused = False
        self._target_failed = False
        self._completed_targets = set()
        self._window = None
        self._geometry_generation = None
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
        self._position_guard = CollectionPositionGuard(self.alignment.config)
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
        self.status = QLabel("Align your face, then start the guided calibration.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setMaximum(1000 * len(self.DIRECTIONS))
        self.progress.setTextVisible(True)
        self.progress.setFormat("Overall calibration %p%")
        self.sample_progress = QProgressBar()
        self.sample_progress.setRange(0, required_samples)
        self.sample_progress.setFormat(f"Valid samples %v/{required_samples}")
        layout.addWidget(self.sample_progress)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.collect_button = QPushButton()
        self.collect_button.clicked.connect(self.begin_collection)
        self.collect_button.setEnabled(False)
        buttons.addWidget(self.collect_button)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_pause)
        buttons.addWidget(self.pause_button)
        self.cancel_button = QPushButton("Cancel calibration")
        self.cancel_button.clicked.connect(self.cancel_collection)
        buttons.addWidget(self.cancel_button)
        self.retry_button = QPushButton("Start new baseline")
        self.retry_button.clicked.connect(self.reset)
        buttons.addWidget(self.retry_button)
        layout.addLayout(buttons)
        self.diagnostics_panel = QGroupBox("Developer calibration diagnostics · local; export only by request")
        self.diagnostics_panel.setCheckable(True)
        self.diagnostics_panel.setChecked(False)
        diagnostic_layout = QVBoxLayout(self.diagnostics_panel)
        self.eye_closeups_enabled = QCheckBox("Show live eye close-ups (inspection only; never saved)")
        self.eye_closeups_enabled.setChecked(False)
        self.eye_closeups_enabled.setVisible(False)
        self.eye_closeups = EyeCloseups(max_age=min(.5, max_age))
        self.eye_closeups.setVisible(False)
        self.eye_closeups_enabled.toggled.connect(self._toggle_eye_closeups)
        self.diagnostics_panel.toggled.connect(self.eye_closeups_enabled.setVisible)
        self.diagnostics_panel.toggled.connect(self._toggle_eye_closeups)
        diagnostic_layout.addWidget(self.eye_closeups_enabled)
        diagnostic_layout.addWidget(self.eye_closeups)
        self.diagnostics_text = QPlainTextEdit()
        self.diagnostics_text.setReadOnly(True)
        self.diagnostics_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.diagnostics_text.setMaximumHeight(160)
        self.diagnostics_text.setVisible(False)
        self.diagnostics_panel.toggled.connect(self.diagnostics_text.setVisible)
        diagnostic_layout.addWidget(self.diagnostics_text)
        self.diagnostic_workflow = DiagnosticPanel(
            calibration.config, clock=clock, max_age=max_age,
            preparation_seconds=preparation_seconds, collection_seconds=collection_seconds,
            max_collection_seconds=self.max_collection_seconds, cue=self._cue,
            event_thresholds=event_thresholds, clearing_seconds=clearing_seconds)
        self.diagnostic_workflow.setVisible(False)
        self.diagnostics_panel.toggled.connect(self.diagnostic_workflow.setVisible)
        self.diagnostic_workflow.active_changed.connect(self._validation_changed)
        self.diagnostic_workflow.target_changed.connect(self.validation_target_changed)
        self.diagnostic_workflow.changed.connect(self._render_diagnostics)
        self.diagnostic_workflow.screen_region_enabled.toggled.connect(self._experiment_mode_changed)
        diagnostic_layout.addWidget(self.diagnostic_workflow)
        self.diagnostics_panel.setVisible(diagnostics_enabled)
        self._diagnostics_enabled = diagnostics_enabled
        layout.addWidget(self.diagnostics_panel)
        self._render_prompt()

    def _toggle_eye_closeups(self, *_):
        enabled = (self._diagnostics_enabled and self.diagnostics_panel.isChecked()
                   and self.eye_closeups_enabled.isChecked())
        self.eye_closeups.set_enabled(enabled)
        self.eye_closeups.setVisible(enabled)
        if enabled:
            self.eye_closeups.feed_result(self._current_result, self.clock(), self._healthy)

    @property
    def validation_active(self):
        return self.diagnostic_workflow.active

    def _experiment_mode_changed(self, *_):
        self._render_prompt()
        self.changed.emit()

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
                "CENTER": "at the marker at the physical screen center",
                "LEFT": "just beyond the physical LEFT edge of the screen",
                "RIGHT": "just beyond the physical RIGHT edge of the screen",
                "DOWN": "below the physical bottom edge of the screen, not at an application button",
            }[self.direction.value]
            self.prompt.setText(
                f"{self.direction_index + 1} / 4 · Look {cue}. "
                "Keep your head naturally facing the screen. "
                "Follow the cues; keep looking until the completion cue. "
                "Sequence: CENTER → LEFT → RIGHT → DOWN."
            )
        self.collect_button.setText("Retry this target" if self._target_failed else
                                    "Resume calibration" if self._completed_targets or self.paused else
                                    "Start calibration")
        available = (self._healthy and not self.collecting and not self.preparing and
                     self.alignment_status.ready and not self.calibration.ready
                     and not self._fit_failed and not self.validation_active
                     and not self.diagnostic_workflow.screen_region_enabled.isChecked())
        self.collect_button.setEnabled(available)
        self.pause_button.setText("Resume calibration" if self.paused else "Pause")
        self.pause_button.setEnabled(available if self.paused else self.collecting or self.preparing)
        self.cancel_button.setEnabled(self.guided_active or self.paused)
        self.retry_button.setEnabled(not self.validation_active and not self.collecting and not self.preparing)
        self.diagnostic_workflow.set_availability(self._healthy, self.guided_active or self.paused)
        self.diagnostic_workflow.set_current_baseline_counts(self.calibration.counts)
        count = self._count(self.direction)
        self.sample_progress.setValue(min(count, self.required_samples))
        # Completion depends on samples and elapsed time; an elapsed bar is not
        # evidence that an empty target has succeeded.
        value = len(self._completed_targets) * 1000
        if self.direction not in self._completed_targets:
            value += int(999 * min(count / self.required_samples, 1.))
        self.progress.setValue(value)
        self._render_diagnostics()

    def _render_diagnostics(self):
        if not self._diagnostics_enabled:
            return
        if self.diagnostic_workflow.screen_region_active and self.diagnostic_workflow.collecting:
            render_now = time.monotonic()
            if render_now - getattr(self, "_last_region_diagnostics_render", -math.inf) < .25:
                return
            self._last_region_diagnostics_render = render_now
        face = self._latest_face
        eye_data = getattr(face, "diagnostics", None)
        pose = getattr(face, "head_pose", None)
        direction, similarity, classification_reason = self.calibration.classify_details(
            getattr(face, "features", None), measurement=face)
        stamp = self._latest_face_timestamp
        age = self.clock() - stamp if stamp is not None and math.isfinite(stamp) else None
        fresh = self._healthy and age is not None and 0 <= age < self.max_age
        if not fresh:
            direction, similarity = GazeDirection.UNKNOWN, None
            classification_reason = "stale_or_unavailable_measurement"
        data = {
            "coordinate_convention": "Unmirrored camera coordinates: +horizontal image right, +vertical image down",
            "eye_measurements": asdict(eye_data) if eye_data is not None else "Unavailable",
            "source_frame_dimensions": frame_size(self._current_result),
            "head_pose_degrees": asdict(pose) if pose is not None else "Unavailable",
            "measurement_status": {"age_seconds": age, "fresh_and_healthy": fresh},
            "alignment": asdict(self.alignment_status),
            "alignment_policy": asdict(self.alignment.config),
            "eye_only_estimate": {"direction": direction.value, "fit_similarity_not_probability": similarity,
                                  "reason": classification_reason},
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
                or self.validation_active or self.diagnostic_workflow.screen_region_enabled.isChecked()):
            return
        now = self.clock()
        self._update_alignment(self._current_result, now, self._healthy)
        if not self.alignment_status.ready:
            self.status.setText(f"Collection blocked: {self.alignment_status.message}.")
            self._render_prompt()
            return
        compatibility = self._position_guard.check(self._current_result, self.alignment_status)
        if compatibility == "camera_changed":
            self._invalidate_baseline("Camera dimensions changed. Start calibration with a fresh baseline.")
            return
        if compatibility == "position_changed":
            self.status.setText("Please return to the previous face position, or start a new baseline.")
            self._render_prompt()
            return
        self._position_guard.anchor(self._current_result)
        self.paused = False
        self._target_failed = False
        self.guided_active = True
        self.guided_active_changed.emit(True)
        self._begin_target(now)

    def _begin_target(self, now):
        # A local retry replaces its own failed attempt. Completed compatible
        # targets and their baseline identity are deliberately retained.
        self.calibration.discard_target(self.direction)
        self._collection_start = now + self.preparation_seconds
        self._window = BoundedCollection(self._collection_start, self.collection_seconds,
                                         self.max_collection_seconds, self.required_samples)
        self._collection_end = self._window.nominal_end
        self._last_sample_timestamp = self._latest_timestamp
        self._last_rejected = {}
        self._geometry_generation = self.alignment_status.geometry_generation
        self.preparing, self.collecting = True, False
        self.status.setStyleSheet("")
        self.status.setText(f"Prepare {self.direction.value}: look at the target; collection begins after the cue.")
        self.guided_target_changed.emit(self.direction.value)
        self._render_prompt(now)

    def _stop_guided(self):
        self.guided_active = False
        self.collecting = self.preparing = False
        self.guided_target_changed.emit("")
        self.guided_active_changed.emit(False)

    def pause_collection(self):
        self.toggle_pause()

    def toggle_pause(self):
        if self.paused:
            self.begin_collection()
        elif self.guided_active:
            self._interrupt_current("paused", paused=True)

    def cancel_collection(self):
        if self.guided_active or self.paused:
            self._interrupt_current("cancelled", paused=False)

    def _interrupt_current(self, reason, *, paused=False):
        if self.collecting or self.preparing:
            self._remember_attempt()
            self._archive_attempt(f"{self.direction.value}: {reason}")
            self.calibration.discard_target(self.direction)
            self._cue()
        if paused:
            self.collecting = self.preparing = False
            self.guided_target_changed.emit("")
        else:
            self._stop_guided()
        self.paused = paused
        self._target_failed = False
        self._window = None
        self._collection_start = self._collection_end = None
        self.status.setText("Calibration paused. Completed compatible targets are retained." if paused else
                            "Calibration cancelled. Completed compatible targets are retained; resume when ready.")
        self._render_prompt()
        self.changed.emit()

    def reset(self):
        if self.validation_active:
            return
        if any(self.calibration.counts.values()):
            self._archive_attempt("retained before new baseline")
        self.calibration.reset()
        self.diagnostic_workflow.new_baseline()
        self.alignment_status = self.alignment.reset()
        self._position_guard.reset()
        self._render_alignment()
        self.direction_index = 0
        self._stop_guided()
        self.paused = self._target_failed = False
        self._completed_targets.clear()
        self._window = None
        self._collection_start = self._collection_end = None
        self._fit_failed = False
        self._last_sample_timestamp = self._latest_timestamp
        self._last_rejected = {}
        self._last_attempt = None
        self.status.setText("Align your face, then start a fresh baseline at CENTER.")
        self.status.setStyleSheet("")
        self._render_prompt()
        self.changed.emit()

    def _invalidate_baseline(self, message):
        self._remember_attempt()
        retained = self._last_attempt
        self._archive_attempt("baseline invalidated")
        self.reset()
        self._last_attempt = retained
        self.status.setText(message)
        self.status.setStyleSheet("color: #ab3434")

    def _render_alignment(self):
        state = self.alignment_status
        detail = (" · Ready to prepare" if state.ready else " · Collection blocked")
        if self.validation_active:
            detail = (" · Experimental training uses the same alignment admission"
                      if self.diagnostic_workflow._region_training else
                      " · Diagnostic validation keeps invalid measurements for review")
        self.alignment_label.setText(state.message + detail)
        self.alignment_label.setStyleSheet("color: #13776a" if state.ready else "color: #916000")
        self.alignment_progress.setValue(round(100 * state.progress))

    def _update_alignment(self, result, now, healthy):
        self.alignment_status = self.alignment.update(result, now, healthy)
        self.diagnostic_workflow.set_alignment(self.alignment_status)
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

    def _failure_feedback(self):
        reasons = self._last_attempt.get("rejection_reasons", {}) if self._last_attempt else {}
        meaningful = {reason: count for reason, count in reasons.items()
                      if reason not in ("captured_before_collection", "reused_or_out_of_order_measurement")}
        dominant = max(meaningful, key=meaningful.get, default="")
        if "aperture" in dominant or "eye" in dominant or "blink" in dominant:
            return "Eye measurements temporarily unavailable. Keep both eyes visible without forcing them open."
        if any(word in dominant for word in ("alignment", "position", "geometry")):
            return "Please return to the previous face position and hold still."
        if any(word in dominant for word in ("stale", "timestamp", "after_collection")):
            return "Fresh camera measurements were too infrequent. Wait for a steady preview."
        return "Too few valid measurements arrived within the available time."

    def _fail_target(self, message=None, *, discard=False):
        self._remember_attempt()
        self._archive_attempt(f"{self.direction.value}: collection incomplete")
        count = self._count(self.direction)
        if discard:
            self.calibration.discard_target(self.direction)
        self.collecting = self.preparing = False
        self.guided_target_changed.emit("")
        self._target_failed = True
        self.status.setText(
            f"This point needs another attempt — {count}/{self.required_samples} valid samples. "
            + (message or self._failure_feedback()))
        self.status.setStyleSheet("color: #ab3434")
        self._render_prompt()
        self.changed.emit()

    def _finish_collection(self, outcome="complete"):
        self.collecting = self.preparing = False
        self._cue()
        self._remember_attempt()
        if outcome != "complete":
            self._fail_target()
            return
        self._completed_targets.add(self.direction)
        if self.direction_index < len(self.DIRECTIONS) - 1:
            self.direction_index += 1
            self._begin_target(self.clock())
        else:
            self._stop_guided()
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
        self.eye_closeups.feed_result(result, now, healthy)
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
                    self._cue()
                self._invalidate_baseline(
                    "Monitoring interrupted. Camera recovery requires a new baseline; align and start calibration again.")
            self._render_prompt(now)
            return
        if not self.preparing and not self.collecting:
            self._render_prompt(now)
            return
        if now >= self._window.deadline and self._count(self.direction) < self.required_samples:
            if (result is not None and math.isfinite(result.timestamp)
                    and result.timestamp > self._last_sample_timestamp):
                self._reject("arrived_after_collection", result.timestamp)
            self._finish_collection("timeout")
            return
        compatibility = self._position_guard.check(result, self.alignment_status)
        if compatibility == "camera_changed":
            self._invalidate_baseline("Camera dimensions changed. Start calibration with a new baseline.")
            return
        if compatibility == "position_changed":
            self._reject("incompatible_face_position", getattr(result, "timestamp", None))
            self._cue()
            self._fail_target("Please return to the previous face position, then retry this target.", discard=True)
            return
        if self.alignment_status.geometry_generation != self._geometry_generation:
            self._reject("geometry_" + (self.alignment_status.geometry_reset_reason or "continuity_lost"),
                         getattr(result, "timestamp", None))
            self._cue()
            self._fail_target("Face-position continuity was lost. Return to the previous position, then retry this target.",
                              discard=True)
            return
        outcome = self._window.outcome(now, self._count(self.direction))
        if outcome != "collect":
            # No late inference may retroactively fill a window. At nominal end
            # insufficient targets continue, but the hard deadline never moves.
            if (now >= self._window.deadline and result is not None
                    and math.isfinite(result.timestamp) and result.timestamp > self._last_sample_timestamp):
                self._reject("arrived_after_collection", result.timestamp)
            self._finish_collection(outcome)
            return
        if self.preparing and now >= self._collection_start:
            self.preparing, self.collecting = False, True
            self._cue()
        if self.preparing:
            self.status.setText(
                f"Prepare {self.direction.value}: {max(1, math.ceil(self._collection_start - now))}… "
                "Keep looking at the target. Wait for the start cue.")
            # Preparation is intentional exclusion, not a user-facing failure.
            self._render_prompt(now)
            return
        if result is not None:
            stamp = result.timestamp
            if not math.isfinite(stamp):
                self._reject("invalid_timestamp", stamp)
            elif stamp < self._collection_start:
                self._reject("captured_before_collection", stamp)
            elif not 0 <= now - stamp < self.max_age:
                self._reject("stale_or_future_measurement", stamp)
            elif stamp >= self._window.deadline:
                self._reject("captured_after_collection", stamp)
            elif stamp <= self._last_sample_timestamp:
                self._reject("reused_or_out_of_order_measurement", stamp)
            else:
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
        count = self._count(self.direction)
        if not self.alignment_status.ready:
            self.status.setText("Eye measurements temporarily unavailable. Keep looking at the target."
                                if self.alignment_status.geometry_valid else
                                "Please return to the previous face position.")
        else:
            self.status.setText(f"Keep looking at the target — {count}/{self.required_samples} samples collected.")
        # An extension finishes as soon as enough fresh samples arrive, never
        # before the complete nominal observation interval has elapsed.
        outcome = self._window.outcome(now, count)
        if outcome == "complete":
            self._finish_collection(outcome)
        else:
            self._render_prompt(now)
