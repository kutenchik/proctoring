"""Explicit, session-local numerical export and independent labeled validation.

This widget is available only from calibration-debug. It never changes the
production calibration or emits vision observations/event-engine inputs.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget,
)

from ..i18n import get_manager, translate_text
from .i18n_widgets import QCheckBox, QLabel, QProgressBar, QPushButton
from ..vision.diagnostic_validation import DiagnosticValidation
from ..vision.collection import BoundedCollection, CollectionPositionGuard
from ..vision.screen_region_protocol import phase_at


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
                 parent=None, event_thresholds=None, clearing_seconds=.75, max_collection_seconds=None):
        super().__init__(parent)
        self.config = config
        self.clock = clock
        self.max_age = max_age
        self.preparation_seconds = preparation_seconds
        self.collection_seconds = collection_seconds
        self.max_collection_seconds = max(collection_seconds, max_collection_seconds if max_collection_seconds is not None
                                          else getattr(config, "calibration_max_collection_seconds", 6.))
        self.cue = cue
        self.event_thresholds = event_thresholds
        self.clearing_seconds = clearing_seconds
        self.target_metadata_provider = None
        self._target_metadata = None
        self._region_training = False
        self._alignment = None
        self._phase_instruction = None
        self._latest_result_timestamp = None
        self._latest_result = None
        self._scheduling_target = False
        self._transition_monitoring_failure = False
        self._bounded_collection = None
        self._position_guard = CollectionPositionGuard(config.alignment)
        self._collection_geometry_generation = None
        self._training_paused = False
        self._training_needs_retry = False
        self._suspended_training = None
        self._suspended_baseline = None
        self._suspended_index = 0
        self.attempts = []
        self._attempt_serial = 0
        self.validation = None
        self._validation_source = None
        self._baseline_id = uuid.uuid4().hex[:12]
        self._baseline_counts = {}
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
        self.attempt_selector.setPlaceholderText(translate_text("Finish a calibration target to retain numerical diagnostics"))
        self.attempt_selector.currentIndexChanged.connect(self._select_attempt)
        layout.addWidget(self.attempt_selector)
        self.attempt_identity = QLabel()
        self.attempt_identity.setWordWrap(True)
        self.attempt_identity.setTextInteractionFlags(
            self.attempt_identity.textInteractionFlags() | Qt.TextSelectableByMouse)
        layout.addWidget(self.attempt_identity)
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
        self.candidate_enabled = QCheckBox(
            "Evaluate calibrated eyelid-openness candidate · DEBUG / UNVALIDATED")
        self.candidate_enabled.setChecked(False)
        self.candidate_enabled.setToolTip(
            "Uses this retained attempt's eye measurements. Adds blink, brief closure, "
            "sustained closure and screen-facing squint windows after reading. "
            "Compare predictions with the operator's observation; no automatic blink or glare detection.")
        layout.addWidget(self.candidate_enabled)
        self.screen_region_enabled = QCheckBox("Screen-region experiment · DEBUG / UNVALIDATED")
        self.screen_region_enabled.setChecked(False)
        self.screen_region_enabled.toggled.connect(self._render)
        layout.addWidget(self.screen_region_enabled)
        self.region_calibration_button = QPushButton("Begin new screen-region calibration")
        self.region_calibration_button.clicked.connect(self.begin_region_calibration)
        layout.addWidget(self.region_calibration_button)
        self.region_restart_button = QPushButton("Start screen calibration with a new baseline")
        self.region_restart_button.clicked.connect(self.restart_region_calibration)
        layout.addWidget(self.region_restart_button)
        self.collection_progress = QProgressBar()
        self.collection_progress.setRange(0, config.calibration_samples)
        self.collection_progress.setFormat("Valid samples: %v/%m")
        layout.addWidget(self.collection_progress)
        self.collection_overall = QLabel("")
        layout.addWidget(self.collection_overall)
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
        training_row = QHBoxLayout()
        self.pause_button = QPushButton("Pause calibration")
        self.pause_button.clicked.connect(self.pause_collection)
        training_row.addWidget(self.pause_button)
        self.retry_target_button = QPushButton("Retry this target")
        self.retry_target_button.clicked.connect(self.retry_target)
        training_row.addWidget(self.retry_target_button)
        layout.addLayout(training_row)
        self.export_status = QLabel("")
        self.export_status.setWordWrap(True)
        layout.addWidget(self.export_status)
        get_manager().language_changed.connect(self.retranslate_ui)
        self._render()

    def retranslate_ui(self, *_):
        """Change presentation only; retained snapshots and running windows stay frozen."""
        self.attempt_selector.setPlaceholderText(translate_text(
            "Finish a calibration target to retain numerical diagnostics"))
        blocked = self.attempt_selector.blockSignals(True)
        try:
            for index in range(self.attempt_selector.count()):
                self.attempt_selector.setItemText(index, translate_text(self.attempt_selector.itemData(index)))
        finally:
            self.attempt_selector.blockSignals(blocked)
        self._render()

    @property
    def selected_attempt(self):
        index = self.attempt_selector.currentIndex()
        return self.attempts[index] if 0 <= index < len(self.attempts) else None

    @property
    def screen_region_active(self):
        return self.active and bool(getattr(self.validation, "target_specs", None))

    @property
    def current_target_spec(self):
        if not self.screen_region_active:
            return {}
        targets = self.validation.targets
        return self.validation.target_specs[targets[min(self._index, len(targets) - 1)]]

    def set_alignment(self, state):
        self._alignment = state

    @property
    def training_paused(self):
        return self._training_paused

    @property
    def training_needs_retry(self):
        return self._training_needs_retry

    def begin_region_calibration(self):
        if not self.region_calibration_button.isEnabled():
            return
        if self._suspended_training is not None and self._suspended_baseline == self._baseline_id:
            self.validation = self._suspended_training
            self._suspended_training = None
            self._index = self._suspended_index
            self._region_training = True
            self._validation_source = None
            self._training_paused = self._training_needs_retry = False
            self.active = True
            self.active_changed.emit(True)
            self._show_target()
            self._schedule_training_target()
            return
        self.new_baseline()
        self._region_training = True
        self._validation_source = None
        self.validation = DiagnosticValidation(
            {}, self.config, screen_region_phase="training", started_at=self.clock(),
            event_thresholds=self.event_thresholds, clearing_seconds=self.clearing_seconds)
        self._begin_workflow()

    def restart_region_calibration(self):
        if self.active or not self._healthy or self._collector_busy:
            return
        self._suspended_training = None
        self.begin_region_calibration()

    def _begin_workflow(self):
        self._index = 0
        self._start = self._end = None
        self._last_timestamp = -math.inf
        self._training_paused = self._training_needs_retry = False
        self.active = True
        self.active_changed.emit(True)
        self._show_target()
        if self._region_training:
            self._schedule_training_target()
        self._render()

    def remember(self, snapshot, outcome):
        """Freeze even an incomplete/rejected attempt before the collector clears it."""
        snapshot = deepcopy(snapshot)
        digest = hashlib.sha256(json.dumps(_json_safe(snapshot), sort_keys=True,
                                         separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        saved = {"outcome": outcome, "calibration": snapshot, "validation": None}
        if self.attempts and self.attempts[-1]["calibration"] == saved["calibration"]:
            # Retaining the current snapshot during retry should still select
            # it, even if the operator was inspecting an older retained item.
            self.attempt_selector.setCurrentIndex(len(self.attempts) - 1)
            self._render()
            return
        self._attempt_serial += 1
        saved["attempt_identity"] = {
            "attempt_id": uuid.uuid4().hex,
            "attempt_number": self._attempt_serial,
            "baseline_id": self._baseline_id,
            "calibration_sha256": digest,
            "last_accepted_timestamp": snapshot.get("last_accepted_timestamp"),
            "last_recorded_timestamp": snapshot.get("last_recorded_timestamp"),
        }
        self.attempts.append(saved)
        # Each attempt can contain bounded numerical rows for four targets.
        # Retain a useful recent history without accumulating indefinitely.
        if len(self.attempts) > self.MAX_RETAINED_ATTEMPTS:
            self.attempts.pop(0)
            self.attempt_selector.removeItem(0)
        label = f"Attempt {self._attempt_serial} · {outcome}"
        self.attempt_selector.addItem(translate_text(label), label)
        self.attempt_selector.setCurrentIndex(len(self.attempts) - 1)
        self._render()

    def _select_attempt(self, *_):
        if not self.active:
            self.validation = None
            self._validation_source = None
        self._render()
        self.changed.emit()

    def new_baseline(self):
        """A retry clears live samples; explicitly distinguish retained references."""
        self._baseline_id = uuid.uuid4().hex[:12]
        self._baseline_counts = {}
        self._region_training = False
        self._suspended_training = None
        self._suspended_baseline = None
        self._position_guard.reset()
        self._render()

    def set_current_baseline_counts(self, counts):
        if self._region_training and self.validation is not None:
            counts = self.validation.accepted_counts
        elif (self.screen_region_enabled.isChecked() and self.selected_attempt
              and self.selected_attempt["calibration"].get("protocol") == "screen_region_training_v1"):
            # A held-out region pass does not overwrite its diagnostic baseline
            # counts with the unrelated production four-target collection.
            self._render()
            return
        self._baseline_counts = {getattr(key, "value", str(key)): value for key, value in counts.items()}
        self._render()

    @property
    def current_baseline(self):
        return {"baseline_id": self._baseline_id, "accepted_samples": dict(self._baseline_counts)}

    def _validation_report(self, *, for_ui=False):
        if self._region_training and self.active:
            return self.validation.summary_report if for_ui else self.validation.report
        if self.validation is not None and self._validation_source is self.selected_attempt:
            return self._source_report(for_ui=for_ui)
        return self.selected_attempt["validation"] if self.selected_attempt else None

    def _source_report(self, *, for_ui=False):
        report = self.validation.summary_report if for_ui else self.validation.report
        report["source_attempt_identity"] = deepcopy(self._validation_source["attempt_identity"])
        return report

    def set_availability(self, healthy, collector_busy):
        self._healthy = healthy
        self._collector_busy = collector_busy
        self._render()

    def _render(self, *_):
        saved = self.selected_attempt is not None
        self.export_button.setEnabled(saved and self.export_enabled.isChecked())
        self.attempt_selector.setEnabled(not self.active)
        is_region = bool(self.selected_attempt and self.selected_attempt["calibration"].get("protocol")
                         == "screen_region_training_v1")
        self.candidate_enabled.setEnabled(not self.active and not is_region)
        self.screen_region_enabled.setEnabled(not self.active)
        self.region_calibration_button.setVisible(self.screen_region_enabled.isChecked())
        self.region_calibration_button.setEnabled(self.screen_region_enabled.isChecked() and self._healthy
                                                  and not self.active and not self._collector_busy)
        self.region_calibration_button.setText("Resume screen-region calibration" if self._suspended_training is not None
                                               else "Start screen-region calibration")
        self.region_restart_button.setVisible(self.screen_region_enabled.isChecked() and self._suspended_training is not None)
        self.region_restart_button.setEnabled(self.region_calibration_button.isEnabled())
        self.validation_button.setEnabled(saved and self._healthy and not self.active and not self._collector_busy)
        aligned = not self._region_training or bool(self._alignment and self._alignment.ready)
        self.prepare_button.setVisible(not self._region_training)
        self.prepare_button.setEnabled(self.active and self._healthy and self._start is None and aligned
                                       and not self._training_paused and not self._training_needs_retry)
        targets = self.validation.targets if self.validation else self.TARGETS
        phase = "screen calibration" if self._region_training else "validation"
        self.prepare_button.setText(f"Prepare {phase} {targets[min(self._index, len(targets) - 1)]}")
        self.cancel_button.setEnabled(self.active)
        self.cancel_button.setText("Cancel calibration" if self._region_training else "Stop validation")
        self.pause_button.setVisible(self._region_training)
        self.pause_button.setEnabled(self.active and self._region_training)
        self.pause_button.setText("Resume calibration" if self._training_paused else "Pause calibration")
        self.retry_target_button.setVisible(self._region_training)
        self.retry_target_button.setEnabled(self.active and self._region_training and self._training_needs_retry
                                            and not self._training_paused and self._healthy)
        self.collection_progress.setVisible(self._region_training)
        self.collection_overall.setVisible(self._region_training)
        if self._region_training and self.validation is not None:
            target = targets[min(self._index, len(targets) - 1)]
            count = self.validation.accepted_counts[target]
            self.collection_progress.setValue(min(count, self.config.calibration_samples))
            self.collection_overall.setText(
                f"Completed targets: {self._index}/{len(targets)} · Positioning: "
                f"{self._alignment.message if self._alignment else 'Waiting for a fresh face measurement'}")
        count_targets = self._baseline_counts if self._region_training else self.TARGETS[:4]
        counts = ", ".join(f"{translate_text(label)} {self._baseline_counts.get(label, 0)}" for label in count_targets)
        description = f"Current baseline {self._baseline_id} · accepted: {counts}."
        if self.selected_attempt:
            identity = self.selected_attempt["attempt_identity"]
            description += (
                f"\nSelected retained attempt {identity['attempt_number']} · ID {identity['attempt_id'][:12]}"
                f" · baseline {identity['baseline_id']} · last accepted {identity['last_accepted_timestamp']}."
            )
            if identity["baseline_id"] != self._baseline_id:
                description += "\nPrevious baseline selected. Validation/export use these retained references, not the current collection."
            if self.validation is not None and self._validation_source is self.selected_attempt:
                source = self._validation_source["attempt_identity"]
            else:
                source = (self.selected_attempt["validation"] or {}).get("source_attempt_identity")
            if source:
                description += f"\nValidation source: attempt {source.get('attempt_number')} · ID {str(source.get('attempt_id', 'unknown'))[:12]}."
            else:
                description += "\nNo validation collected for this retained attempt."
        else:
            description += "\nNo retained attempt selected for validation/export."
        # Translate complete lines separately so a template's free-text count
        # field cannot consume the following immutable-reference description.
        self.attempt_identity.setText("\n".join(translate_text(line) for line in description.split("\n")))

    def begin_validation(self):
        if not self.validation_button.isEnabled():
            return
        self._validation_source = self.selected_attempt
        self._region_training = False
        if self._validation_source["calibration"].get("protocol") == "screen_region_training_v1":
            self.screen_region_enabled.setChecked(True)
        self.validation = DiagnosticValidation(
            self._validation_source["calibration"], self.config,
            include_openness_candidate=(self.candidate_enabled.isChecked() and
                self._validation_source["calibration"].get("protocol") != "screen_region_training_v1"),
            event_thresholds=self.event_thresholds, clearing_seconds=self.clearing_seconds)
        self._begin_workflow()

    def _show_target(self):
        target = self.validation.targets[self._index]
        if self.screen_region_active:
            # Native layout settling may process timer deliveries. Those frames
            # update the preview, but must not recursively schedule this target.
            self._scheduling_target = True
            try:
                self.target_changed.emit(target if self._region_training else "")
            finally:
                self._scheduling_target = False
            if self._drain_transition_failure():
                return
            spec = self.current_target_spec
            phase = "training" if self._region_training else "held-out validation"
            alignment = (f" Collection blocked: {self._alignment.message}."
                         if self._region_training and self._alignment and not self._alignment.ready else "")
            self.validation_status.setText(
                f"DEBUG / UNVALIDATED · {phase} {self._index + 1}/{len(self.validation.targets)} · {target}. "
                f"{spec['instruction']} " +
                ("Collection begins automatically when positioned. " if self._region_training else
                 "Press Prepare, then look at the marker or specified physical target. ") +
                f"Hold until the completion beep.{alignment}")
            self.changed.emit()
            return
        directions = {
            "CENTER": "Look at the physical screen center, not upward or at a control in this panel.",
            "LEFT": "Move only your eyes just beyond the physical left edge of the screen.",
            "RIGHT": "Move only your eyes just beyond the physical right edge of the screen.",
            "DOWN": "Move only your eyes below the physical bottom edge of the screen.",
            "READING": "Read normally within the displayed quiz area, including question and answer choices.",
            "BLINK": "Look at the physical screen center and blink normally; do not look down.",
            "BRIEF_CLOSURE": "Look at the screen center, briefly close both eyes, then reopen them.",
            "SUSTAINED_CLOSURE": "Gently keep both eyes closed through this short collection window.",
            "SQUINT": "Keep looking at the physical screen center and gently squint; do not look down.",
        }
        self.validation_status.setText(
            f"DEBUG / UNVALIDATED · new pass {self._index + 1}/{len(self.validation.targets)} · {target}. "
            f"{directions[target]} Keep your head comfortable and steady. Press Prepare; "
            "collection begins and ends with a beep. The operator supplies the target label.")
        # READING opens the actual quiz page and hides these controls. Keep
        # Prepare visible until its independent collection window is scheduled.
        if target != "READING":
            self.target_changed.emit(target)

    def _schedule_training_target(self):
        if (not self.active or not self._region_training or self._start is not None
                or self._training_paused or self._training_needs_retry or self._scheduling_target):
            return
        self.prepare_target(automatic=True)

    def prepare_target(self, _checked=False, *, automatic=False):
        if self._scheduling_target or self._start is not None or (not automatic and not self.prepare_button.isEnabled()):
            return
        if self._region_training:
            stamp = self._latest_result_timestamp
            fresh = (stamp is not None and math.isfinite(stamp)
                     and 0 <= self.clock() - stamp < self.max_age)
            if not fresh or not self._healthy or not self._alignment or not self._alignment.ready:
                self.validation_status.setText(
                    "Positioning: " + (self._alignment.message if fresh and self._healthy and self._alignment else
                                       "Wait for a fresh aligned camera measurement.") +
                    " Collection will begin automatically.")
                self.changed.emit()
                return
            compatibility = self._position_guard.check(self._latest_result, self._alignment)
            if compatibility != "compatible":
                self._position_feedback(compatibility)
                return
        self._scheduling_target = True
        try:
            if self.screen_region_active:
                self.target_changed.emit(self.validation.targets[self._index])
                self._target_metadata = (self.target_metadata_provider()
                                         if self.target_metadata_provider else {})
                if self._target_metadata.get("target_visible_inside_client") is False:
                    raise ValueError("Target is outside the visible application area; resize and prepare again")
                self.validation.set_target_position(self.validation.targets[self._index], self._target_metadata)
            # Show the intended fixation before taking the new timing anchor.
            self._start = self.clock() + self.preparation_seconds
            if self._region_training:
                self._bounded_collection = BoundedCollection(self._start, self.collection_seconds,
                                                               self.max_collection_seconds, self.config.calibration_samples)
                self._end = self._bounded_collection.deadline
                self._position_guard.anchor(self._latest_result)
                self._collection_geometry_generation = self._alignment.geometry_generation
            else:
                self._end = self._start + (max(6., self.collection_seconds)
                                           if self.screen_region_active else self.collection_seconds)
            self.validation.start_target(self.validation.targets[self._index], self._start, self._end)
        except ValueError as exc:
            self._start = self._end = None
            if self.screen_region_active:
                self.target_changed.emit("")
            self.validation_status.setText(f"DEBUG / UNVALIDATED: {exc}")
            self._render()
            return
        finally:
            self._scheduling_target = False
            interrupted = self._drain_transition_failure()
        if interrupted:
            return
        self.collecting = False
        self._phase_instruction = None
        if self.validation.targets[self._index] == "READING":
            self.target_changed.emit("READING")
        self._render()
        self.changed.emit()

    def feed_result(self, result, now, healthy):
        self._healthy = healthy
        self._latest_result_timestamp = getattr(result, "timestamp", None)
        self._latest_result = result
        if self._scheduling_target:
            self._transition_monitoring_failure |= not healthy
            return
        if not self.active:
            self._render()
            return
        if not healthy:
            self.cancel_validation("Monitoring interrupted; the validation window was discarded. Start a fresh pass.")
            if self._region_training:
                self.new_baseline()
            return
        # Camera changes invalidate even a pending/preparation window. Never
        # finish the last target first and accidentally retain a mixed baseline.
        if (self._region_training and result is not None
                and math.isfinite(result.timestamp) and 0 <= now - result.timestamp < self.max_age
                and self._position_guard.check(result, self._alignment) == "camera_changed"):
            self._position_feedback("camera_changed")
            return
        if self._start is None:
            self._schedule_training_target()
            self._render()
            return
        count = self.validation.accepted_counts[self.validation.targets[self._index]]
        outcome = self._bounded_collection.outcome(now, count) if self._region_training else None
        if outcome == "timeout":
            self._fail_training_target("insufficient_samples")
            return
        if self.screen_region_active and self.target_metadata_provider and self._target_metadata is not None:
            current = self.target_metadata_provider()
            fixed_fields = ("screen_geometry", "client_geometry", "client_position", "desktop_position", "device_pixel_ratio")
            if any(current.get(key) != self._target_metadata.get(key) for key in fixed_fields):
                self.cancel_validation("Target/layout moved during collection; start a fresh pass with a fixed window layout.")
                if self._region_training:
                    self.new_baseline()
                return
        if self._region_training and now >= self._start:
            compatibility = self._position_guard.check(result, self._alignment)
            generation_changed = (self.collecting and self._collection_geometry_generation !=
                                  getattr(self._alignment, "geometry_generation", None))
            if compatibility != "compatible" or generation_changed:
                self._fail_training_target("position_interrupted")
                return
        if outcome == "complete" or (not self._region_training and now >= self._end):
            self._finish_target(now)
            return
        if now < self._start:
            self.validation_status.setText(
                f"DEBUG / UNVALIDATED · Prepare {self.validation.targets[self._index]}: "
                f"{max(1, math.ceil(self._start - now))}… Keep looking at the target until the completion beep.")
            self.changed.emit()
            return
        if not self.collecting:
            self.collecting = True
            if self._region_training:
                self._collection_geometry_generation = getattr(self._alignment, "geometry_generation", None)
            self.cue()
        instruction = "Hold until the completion beep."
        if self.screen_region_active:
            phase = phase_at(self.current_target_spec, (now - self._start) / (self._end - self._start))
            instruction = phase["instruction"]
            if self._phase_instruction is not None and instruction != self._phase_instruction:
                self.cue()
            self._phase_instruction = instruction
        self.validation_status.setText(
            f"DEBUG / UNVALIDATED · Collecting {self.validation.targets[self._index]}. {instruction} "
            "No exam is running.")
        if self._region_training:
            self._training_feedback()
        if result is None:
            self.changed.emit()
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
        elif self._region_training and not (self._alignment and self._alignment.ready):
            reason = "alignment_" + getattr(self._alignment, "reason", "not_ready")
        metadata = numerical_metadata(result)
        metadata.update(received_at=now, face_latency_ms=getattr(result, "face_latency_ms", None))
        self.validation.add_sample(
            getattr(face, "features", None), stamp, getattr(face, "quality", 0.0),
            metadata=metadata, rejection_reason=reason)
        if self._region_training:
            self._training_feedback()
            count = self.validation.accepted_counts[self.validation.targets[self._index]]
            if self._bounded_collection.outcome(now, count) == "complete":
                self._finish_target(now)
                return
        self._render()
        self.changed.emit()

    def _drain_transition_failure(self):
        if not self._transition_monitoring_failure:
            return False
        self._transition_monitoring_failure = False
        was_training = self._region_training
        self.cancel_validation("Monitoring interrupted during target positioning; start a fresh pass.")
        if was_training:
            self.new_baseline()
        return True

    def _training_feedback(self):
        target = self.validation.targets[self._index]
        count = self.validation.accepted_counts[target]
        message = ""
        if self._alignment and not self._alignment.ready:
            eye_reasons = ("eyes_not_visible", "eye_size_unavailable", "eye_measurements_disagree",
                           "eye_measurements_invalid", "eye_quality_low")
            message = ("Eye measurements temporarily unavailable. " if self._alignment.reason in eye_reasons
                       else f"Positioning: {self._alignment.message}. ")
        self.validation_status.setText(
            f"DEBUG / UNVALIDATED · {target}. {message}Keep looking at the target — "
            f"{count}/{self.config.calibration_samples} samples collected. "
            f"Completed targets: {self._index}/{len(self.validation.targets)}.")

    def _position_feedback(self, compatibility):
        if compatibility == "camera_changed":
            self.cancel_validation("Camera dimensions changed; this baseline is incompatible. Start a new calibration baseline.")
            self.new_baseline()
        else:
            self.validation_status.setText("Please return to the previous face position. Collection is waiting for stable positioning.")
        self._render()
        self.changed.emit()

    def _fail_training_target(self, reason):
        target = self.validation.targets[self._index]
        progress = self.validation.target_progress(target)
        count = progress["accepted"]
        # Keep the unsuccessful numerical window available before replacing it.
        self.remember(self.validation.training_snapshot(), f"{target} collection needs retry · DEBUG")
        self.validation.cancel_target(reason)
        self._start = self._end = None
        self.collecting = False
        self._training_needs_retry = True
        self.cue()
        if reason == "position_interrupted":
            message = "Please return to the previous face position. Fresh stable face geometry is required."
        else:
            reasons = progress["rejection_reasons"]
            dominant = max(reasons, key=reasons.get) if reasons else "insufficient_fresh_samples"
            if any(word in dominant for word in ("eye", "iris", "aperture", "quality", "blink")):
                message = "Eye measurements were temporarily unavailable. Check eye visibility and lighting."
            elif "alignment" in dominant:
                message = "Please return to the previous face position and hold still."
            else:
                message = "Not enough fresh usable measurements arrived before the time limit."
        self.validation_status.setText(
            f"This point needs another attempt: {target} collected {count}/{self.config.calibration_samples} usable samples. "
            f"{message} Retry this target; compatible completed targets are retained.")
        self._render()
        self.changed.emit()

    def retry_target(self):
        if (not self.active or not self._region_training or not self._training_needs_retry
                or self._training_paused or not self._healthy):
            return
        self._training_needs_retry = False
        self._show_target()
        self._schedule_training_target()
        self._render()

    def pause_collection(self):
        if not self.active or not self._region_training:
            return
        if self._training_paused:
            self._training_paused = False
            self._training_needs_retry = False
            self._show_target()
            self._schedule_training_target()
        else:
            if self._start is not None:
                self.validation.cancel_target("operator_paused")
            self._start = self._end = None
            self.collecting = False
            self._training_paused = True
            self.validation_status.setText(
                "Calibration paused. Compatible completed targets are retained; resume restarts this point with fresh samples.")
        self._render()
        self.changed.emit()

    def _finish_target(self, now):
        self.validation.finish_target(now, actual_end=min(now, self._end) if self._region_training else None)
        self.cue()
        if not self._region_training:
            self._save_report()
        self._start = self._end = None
        self.collecting = False
        self._index += 1
        if self._index == len(self.validation.targets):
            training_finished = self._region_training
            if training_finished:
                self.remember(self.validation.training_snapshot(), "screen-region training complete · DEBUG")
            self.active = False
            self.active_changed.emit(False)
            self.target_changed.emit("")
            self.validation_status.setText(
                ("DEBUG / UNVALIDATED · screen-region training retained. Inspect its OWN fit result. "
                 "Separate developer validation is optional and has not been performed. "
                 if training_finished else "DEBUG / UNVALIDATED · separate pass complete. ") +
                "Inspect predicted labels, UNKNOWN rate and target confusion in the numerical diagnostics/export. "
                "Collection completion is not proof of validated gaze accuracy or permission to start an exam.")
        else:
            self._show_target()
            self._schedule_training_target()
        self._render()
        self.changed.emit()

    def _save_report(self):
        # Bind to the immutable source selected when validation began. A later
        # selector change must never attach this pass to another baseline.
        if not self._region_training and self.validation is not None and self._validation_source is not None:
            self._validation_source["validation"] = self._source_report()

    def cancel_validation(self, reason="Stopped by operator; start a fresh separate pass to collect all targets."):
        if not isinstance(reason, str):  # QPushButton.clicked carries a boolean.
            reason = "Stopped by operator; start a fresh separate pass to collect all targets."
        if self._region_training and reason.startswith("Stopped by operator"):
            reason = "Calibration cancelled. Compatible completed targets are retained; Resume continues from this point."
        if self.validation is not None and self._start is not None:
            self.validation.cancel_target(reason)
        if self._region_training and self.validation is not None:
            self._suspended_training = self.validation
            self._suspended_baseline = self._baseline_id
            self._suspended_index = self._index
            self.remember(self.validation.training_snapshot(), "screen-region training interrupted · DEBUG")
        self._save_report()
        self._start = self._end = None
        self.collecting = False
        self._training_paused = False
        self._training_needs_retry = False
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
        if self.selected_attempt is None and not self.screen_region_active:
            return None
        if self.screen_region_active and self._region_training:
            return {"current_baseline": self.current_baseline,
                    "screen_region_training": self.validation.summary_report,
                    "export_enabled": self.export_enabled.isChecked()}
        report = self._validation_report(for_ui=True)
        return {
            "current_baseline": self.current_baseline,
            "selected_attempt_identity": deepcopy(self.selected_attempt["attempt_identity"]),
            # Presentation may be translated; numerical diagnostics keep the
            # canonical English descriptor alongside the immutable attempt ID.
            "retained_attempt": self.attempt_selector.currentData(),
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
            "current_collection_at_export": self.current_baseline,
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
        path, _ = QFileDialog.getSaveFileName(
            self, translate_text("Save local numerical diagnostics"),
            "gaze-diagnostics.json", "JSON (*.json)")
        if not path:
            return
        try:
            self.export_to_path(path)
        except (OSError, ValueError) as exc:
            self.export_status.setText(f"Could not export numerical diagnostics: {exc}")
