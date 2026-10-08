"""Separate, operator-labelled gaze collection; never participates in an exam.

References are frozen from a calibration attempt, including a failed attempt.
Predictions are exploratory labels, not calibrated confidence or authorization
to start an exam. Nothing here changes Calibration.ready or produces events.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math

from .calibration import Calibration, _bounded_down_extension, _distance, _summary
from .classifier import aperture_guard, derive_aperture_references
from .openness_candidate import OpennessCandidate
from .screen_region import ScreenRegionCandidate
from .screen_region_protocol import TRAINING_PROTOCOL, phase_at, training_specs, validation_specs
from .screen_region_timing import summarize_timing
from .settings import VisionConfig
from .types import EyeDiagnostic, FaceMeasurement, GazeDiagnostics, GazeDirection


VALIDATION_TARGETS = ("CENTER", "LEFT", "RIGHT", "DOWN", "READING")
CHALLENGE_TARGETS = ("BLINK", "BRIEF_CLOSURE", "SUSTAINED_CLOSURE", "SQUINT")
PREDICTION_LABELS = ("CENTER", "LEFT", "RIGHT", "DOWN", "UNKNOWN")
DEBUG_LABEL = "DEBUG / UNVALIDATED"


def _expected_label(target):
    # A blink/closure interval includes transitions: without frame-level human
    # annotation, UNKNOWN is an abstention, never an automatically correct label.
    if target in ("BLINK", "BRIEF_CLOSURE", "SUSTAINED_CLOSURE"):
        return None
    return "CENTER" if target in ("READING", "SQUINT") else target


def _prediction_counts(rows, label, key):
    predictions = Counter(row[key] for row in rows)
    expected = _expected_label(label)
    count = len(rows)
    return {
        "expected_label": expected,
        "predicted_labels": {name: predictions[name] for name in PREDICTION_LABELS},
        "correct_labels": predictions[expected] if expected is not None else None,
        "incorrect_labels": (count - predictions[expected] - predictions["UNKNOWN"]
                             if expected is not None else None),
        "unknown_measurements": predictions["UNKNOWN"],
        "unknown_rate": predictions["UNKNOWN"] / count if count else None,
        "expected_match_rate": (predictions[expected] / count
                                if count and expected is not None else None),
        "offscreen_prediction_rate": (sum(predictions[name] for name in ("LEFT", "RIGHT", "DOWN")) / count
                                      if count else None),
    }


def _finite_number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _features(value):
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    converted = tuple(_finite_number(x) for x in value)
    return converted if all(x is not None for x in converted) else None


def _metadata(value: dict | None) -> dict:
    """Only allow numerical diagnostic fields, never frames or arbitrary data."""
    value = value if isinstance(value, dict) else {}
    size = value.get("frame_size")
    result = {
        "frame_size": ([_finite_number(x) for x in size]
                       if isinstance(size, (tuple, list)) and len(size) == 2 else None),
        "eyes": {}, "head_pose_degrees": None,
    }
    eyes = value.get("eyes", {})
    for side in ("left", "right"):
        eye = eyes.get(side, {}) if isinstance(eyes, dict) else {}
        if not isinstance(eye, dict):
            eye = {}
        result["eyes"][side] = {
            key: _finite_number(eye.get(key))
            for key in ("horizontal", "vertical", "opening", "width_pixels")
        }
        result["eyes"][side].update(
            valid=eye.get("valid") is True,
            reason=str(eye.get("reason", "not supplied"))[:200],
        )
    pose = value.get("head_pose_degrees")
    if isinstance(pose, dict):
        result["head_pose_degrees"] = {
            axis: _finite_number(pose.get(axis)) for axis in ("yaw", "pitch", "roll")
        }
    return result


def _measurement(features, metadata, quality) -> FaceMeasurement:
    """Rebuild only the current numerical eye measurement, never a stale image.

    Missing per-eye fields stay missing/invalid. A stored feature vector alone
    cannot establish openness or iris observability for the guarded policy.
    """
    eyes = metadata["eyes"]
    left, right = (EyeDiagnostic(**eyes[side]) for side in ("left", "right"))
    valid = left.valid and right.valid
    return FaceMeasurement(True, features=features, quality=quality, diagnostics=GazeDiagnostics(
        left, right, valid, "" if valid else "missing_or_invalid_eye_measurements"))


class DiagnosticValidation:
    """Independent consecutive collection windows with immutable references.

    A sample must be newer than every recorded training measurement, inside its
    explicitly declared validation window, and newer than any previously seen
    validation sample. Invalid fresh measurements count as UNKNOWN; stale and
    out-of-window deliveries are excluded from prediction-rate denominators.
    """

    def __init__(self, attempt_export: dict, config: VisionConfig, *, include_openness_candidate=False,
                 screen_region_phase=None, started_at=None, event_thresholds=None, clearing_seconds=.75):
        self._snapshot = deepcopy(attempt_export)
        self.config = config
        if screen_region_phase is None and self._snapshot.get("protocol") == TRAINING_PROTOCOL:
            screen_region_phase = "validation"
        if screen_region_phase not in (None, "training", "validation"):
            raise ValueError("Unknown screen-region collection phase")
        if screen_region_phase and include_openness_candidate:
            raise ValueError("Screen-region comparison excludes the openness candidate")
        self.screen_region_phase = screen_region_phase
        self.event_thresholds = event_thresholds
        self.clearing_seconds = clearing_seconds
        self.target_specs = {}
        self.targets = VALIDATION_TARGETS + (CHALLENGE_TARGETS if include_openness_candidate else ())
        if screen_region_phase:
            specs = training_specs() if screen_region_phase == "training" else validation_specs()
            self.target_specs = {spec["id"]: deepcopy(spec) for spec in specs}
            self.targets = tuple(self.target_specs)
        self.candidate = OpennessCandidate(self._snapshot, config) if include_openness_candidate else None
        self.region_candidate = (ScreenRegionCandidate(self._snapshot, config)
                                 if screen_region_phase == "validation" else None)
        baseline = self._snapshot.get("baseline_reference", self._snapshot)
        self._classifier_policy = deepcopy(baseline.get("classifier_policy"))
        self._guarded_aperture = (isinstance(self._classifier_policy, dict)
                                  and self._classifier_policy.get("version") == "guarded_aperture_down_v1")
        policy = self._classifier_policy if self._guarded_aperture else {}
        required_samples = policy.get("required_samples", config.calibration_samples)
        self._aperture_references = (derive_aperture_references(
            baseline.get("samples", {}), required_samples=required_samples)
            if self._guarded_aperture else None)
        diagnostics = baseline.get("diagnostics", {})
        self.production_ready = diagnostics.get("ready") is True
        if screen_region_phase:
            self.production_ready = False
        timestamps = [self._snapshot.get("last_recorded_timestamp"),
                      self._snapshot.get("last_accepted_timestamp")]
        for rows in self._snapshot.get("samples", {}).values():
            timestamps.extend(row.get("timestamp") for row in rows if isinstance(row, dict))
        finite = [value for value in map(_finite_number, timestamps) if value is not None]
        self.training_cutoff = max(finite) if finite else None
        if screen_region_phase == "training":
            if _finite_number(started_at) is None:
                raise ValueError("Region training requires a finite monotonic start time")
            self.training_cutoff = float(started_at)
        self._last_timestamp = self.training_cutoff if self.training_cutoff is not None else -math.inf
        self._centers = {}
        for label in VALIDATION_TARGETS[:4]:
            target = diagnostics.get("targets", {}).get(label, {})
            eye, head = target.get("eye_median"), target.get("head_median_degrees")
            if (isinstance(eye, (tuple, list)) and len(eye) == 2
                    and isinstance(head, (tuple, list)) and len(head) == 2
                    and all(_finite_number(x) is not None for x in (*eye, *head))
                    and target.get("accepted", 0) >= required_samples):
                self._centers[label] = tuple(float(x) for x in eye) + tuple(float(x) / 60 for x in head)
        self._radii = {}
        # These are the existing production reference-core radii, frozen for an
        # exploratory held-out check. Production fit acceptance is NOT changed.
        if len(self._centers) == 4:
            center = self._centers["CENTER"][:2]
            distances = {label: _distance(center, reference[:2])
                         for label, reference in self._centers.items() if label != "CENTER"}
            center_fraction = policy.get("center_radius_fraction", config.calibration_center_radius_fraction)
            offscreen_fraction = policy.get("offscreen_radius_fraction", config.calibration_offscreen_radius_fraction)
            self._radii["CENTER"] = center_fraction * min(distances.values())
            for label, distance in distances.items():
                nearest = min(_distance(self._centers[label][:2], reference[:2])
                              for other, reference in self._centers.items() if label != other)
                self._radii[label] = min(offscreen_fraction * distance, .4 * nearest)
        self._rows = {label: [] for label in self.targets}
        self._rejections = {label: Counter() for label in self.targets}
        self._completed = set()
        self._windows = {}
        self._timing_cache = {}
        self._active = None
        self._last_window_end = self.training_cutoff if self.training_cutoff is not None else -math.inf

    @property
    def reference_snapshot(self) -> dict:
        return deepcopy(self._snapshot)

    @property
    def active_target(self) -> str | None:
        return self._active

    @property
    def accepted_counts(self):
        return {label: sum(row["accepted"] for row in rows) for label, rows in self._rows.items()}

    def target_progress(self, label):
        """Small collection-only summary; no fit or prediction replay on UI ticks."""
        return {"accepted": sum(row["accepted"] for row in self._rows[label]),
                "rejection_reasons": dict(self._rejections[label]),
                "completed": label in self._completed}

    @property
    def latest_region_prediction(self):
        if self.screen_region_phase != "validation" or self._active is None or not self._rows[self._active]:
            return None
        row = self._rows[self._active][-1]
        return {key: row[key] for key in ("timestamp", "predicted_label", "prediction_reason",
                                        "region_predicted_label", "region_prediction_reason")}

    def set_target_position(self, label, position):
        """Freeze actually displayed coordinates, never substitute requested ones."""
        if label not in self.target_specs or not isinstance(position, dict):
            raise ValueError("Unknown target or invalid rendered position")
        if self._rows[label] or label in self._completed:
            raise ValueError("Cannot move a target after collecting its measurements")
        self.target_specs[label]["position"] = deepcopy(position)

    def start_target(self, label: str, starts_at: float, ends_at: float) -> None:
        if label not in self.targets:
            raise ValueError("Unknown diagnostic validation target")
        expected = next((target for target in self.targets if target not in self._completed), None)
        if self._active is not None or label != expected:
            raise ValueError("Finish the current validation target; collect targets in sequence")
        if self.training_cutoff is None:
            raise ValueError("Training timestamps are missing; collect a new calibration attempt first")
        if (_finite_number(starts_at) is None or _finite_number(ends_at) is None
                or starts_at <= self._last_window_end or ends_at <= starts_at):
            raise ValueError("Validation windows must be finite, separate, and later than training")
        self._active = label
        # A retry replaces its cancelled window, including interruption reasons;
        # diagnostics for the failed window are retained by the owning UI.
        self._rows[label].clear()
        self._rejections[label].clear()
        self._windows[label] = {"starts_at": starts_at, "ends_at": ends_at}

    def predict(self, features, metadata=None, *, quality=1.) -> str:
        """Exploratory label, with no confidence or exam permission.

        Features-only calls retain the legacy point-core comparison API. The
        collection path always passes current metadata, including missing eye
        fields, to exercise the selected snapshot's full guarded policy.
        """
        return self._prediction(features, _metadata(metadata) if metadata is not None else None,
                                quality=quality)[0]

    def _prediction(self, features, metadata=None, *, quality=1.) -> tuple[str, str]:
        row = _features(features)
        if row is None:
            return "UNKNOWN", "missing_or_invalid_features"
        if len(self._centers) != 4:
            return "UNKNOWN", "incomplete_training_references"
        for axis in (2, 3):
            calibrated = [reference[axis] for reference in self._centers.values()]
            allowance = 10. / 60.
            if not min(calibrated) - allowance <= row[axis] <= max(calibrated) + allowance:
                return "UNKNOWN", "head_pose_outside_reference_coverage"
        if self._guarded_aperture and metadata is not None:
            guarded = aperture_guard(row, self._centers, self._radii,
                                     self._aperture_references, _measurement(row, metadata, quality))
            if guarded is not None:
                direction, _, reason = guarded
                return direction.value, reason
        extension = _bounded_down_extension(row, self._centers, self._radii)
        if extension is not None:
            label, _, reason = extension
            return label, reason
        ranked = sorted((_distance(row[:2], reference[:2]), label)
                        for label, reference in self._centers.items())
        distance, label = ranked[0]
        second_distance = ranked[1][0]
        radius = self._radii[label]
        if radius <= 0:
            return "UNKNOWN", "overlapping_training_references"
        if distance > radius:
            return "UNKNOWN", "outside_reference_core"
        if (second_distance - distance) / max(second_distance, 1e-9) < .12:
            return "UNKNOWN", "ambiguous_reference_margin"
        return label, "within_reference_core"

    def add_sample(self, features, timestamp: float, quality: float, *,
                   metadata: dict | None = None, rejection_reason: str | None = None) -> bool:
        label = self._active
        if label is None:
            return False
        rejections = self._rejections[label]
        window = self._windows[label]
        if _finite_number(timestamp) is None:
            rejections["nonfinite_timestamp"] += 1
            return False
        if timestamp <= self.training_cutoff:
            rejections["training_measurement_reused"] += 1
            return False
        if not window["starts_at"] <= timestamp <= window["ends_at"]:
            rejections["outside_validation_window"] += 1
            return False
        if timestamp <= self._last_timestamp:
            rejections["reused_or_out_of_order_measurement"] += 1
            return False
        self._last_timestamp = timestamp
        if len(self._rows[label]) >= self.config.calibration_max_samples:
            rejections["sample_capacity_reached"] += 1
            return False
        row = _features(features)
        reason = rejection_reason
        if reason is None and row is None:
            reason = "missing_or_invalid_features"
        if reason is None and (_finite_number(quality) is None or quality < .45):
            reason = "insufficient_measurement_quality"
        if reason is not None:
            reason = str(reason)[:200]
            rejections[reason] += 1
        clean_metadata = _metadata(metadata)
        predicted, prediction_reason = (self._prediction(row, clean_metadata, quality=quality)
                                        if reason is None else ("UNKNOWN", reason))
        expected = _expected_label(label)
        phase = None
        if self.screen_region_phase:
            phase = phase_at(self.target_specs[label],
                             (timestamp - window["starts_at"]) / (window["ends_at"] - window["starts_at"]))
            expected = phase.get("expected_label")
        recorded = {
            "timestamp": timestamp, "operator_target": label,
            "expected_label": expected,
            "features": list(row) if row is not None else None,
            "quality": _finite_number(quality), "accepted": reason is None,
            "rejection_reason": reason, "predicted_label": predicted,
            "prediction_reason": prediction_reason,
            "prediction_status": DEBUG_LABEL, **clean_metadata,
        }
        if self.candidate is not None:
            candidate_label, candidate_reason = self.candidate.predict(
                row, clean_metadata, quality=quality, rejection_reason=reason)
            recorded.update(candidate_predicted_label=candidate_label,
                            candidate_prediction_reason=candidate_reason)
        if self.screen_region_phase:
            metadata = metadata if isinstance(metadata, dict) else {}
            recorded.update(target_role=self.target_specs[label]["role"],
                            target_definition_id=label,
                            instructed_phase=deepcopy(phase),
                            received_at=_finite_number(metadata.get("received_at")),
                            face_latency_ms=_finite_number(metadata.get("face_latency_ms")))
            received = recorded["received_at"]
            recorded["capture_to_receive_ms"] = (1000 * (received - timestamp)
                                                 if received is not None and received >= timestamp else None)
            if self.region_candidate is not None:
                direction, detail = self.region_candidate.predict(
                    row, clean_metadata, quality=quality, rejection_reason=reason)
                recorded.update(region_predicted_label=direction, region_prediction_reason=detail)
        self._rows[label].append(recorded)
        return reason is None

    def finish_target(self, now: float, *, actual_end: float | None = None) -> None:
        if self._active is None:
            raise ValueError("No active validation target")
        window = self._windows[self._active]
        if _finite_number(now) is None:
            raise ValueError("Complete the separate validation interval before finishing")
        if actual_end is not None:
            # Adaptive TRAINING reserves a hard maximum window, then closes at
            # its actual completion time. Held-out phase timing remains fixed.
            if (self.screen_region_phase != "training" or _finite_number(actual_end) is None
                    or not window["starts_at"] < actual_end <= window["ends_at"]
                    or actual_end < self._last_timestamp or now < actual_end):
                raise ValueError("Invalid adaptive training window end")
            window["reserved_deadline"] = window["ends_at"]
            window["ends_at"] = actual_end
            window["end_inclusive"] = True  # The final admitted capture may itself complete the target.
        if _finite_number(now) is None or now < window["ends_at"]:
            raise ValueError("Complete the separate validation interval before finishing")
        self._completed.add(self._active)
        self._last_window_end = window["ends_at"]
        self._active = None

    def cancel_target(self, reason: str = "collection_interrupted") -> None:
        if self._active is not None:
            # Discard this incomplete interval, including its predictions.
            # Previously consumed timestamps remain unavailable for any retry.
            label = self._active
            self._rows[label].clear()
            self._rejections[label].clear()
            self._rejections[label][str(reason)[:200]] += 1
            self._last_window_end = max(self._last_window_end, self._last_timestamp)
            self._windows.pop(label)
            self._timing_cache = {key: value for key, value in self._timing_cache.items() if key[0] != label}
            self._active = None

    @property
    def report(self) -> dict:
        if self.screen_region_phase:
            return self._region_report()
        targets = {}
        confusion = {}
        all_predictions = Counter()
        for label, rows in self._rows.items():
            predictions = Counter(row["predicted_label"] for row in rows)
            confusion[label] = {prediction: predictions[prediction] for prediction in PREDICTION_LABELS}
            all_predictions.update(predictions)
            usable = sum(row["accepted"] for row in rows)
            status = ("completed" if label in self._completed and rows else
                      "completed_no_samples" if label in self._completed else
                      "in_progress" if self._active == label else "pending")
            expected = _expected_label(label)
            valid_rows = [row for row in rows if row["accepted"]]
            eye_axes = {axis: _summary([row["features"][index] for row in valid_rows])
                        for index, axis in enumerate(("horizontal", "vertical"))}
            eyes = {
                side: {field: _summary([row["eyes"][side][field] for row in valid_rows
                                      if row["eyes"][side][field] is not None])
                       for field in ("horizontal", "vertical", "opening", "width_pixels")}
                for side in ("left", "right")
            }
            targets[label] = {
                "status": status, "expected_label": expected, "collected": len(rows),
                "usable_measurements": usable, "invalid_measurements": len(rows) - usable,
                "enough_usable_measurements": usable >= self.config.calibration_samples,
                "rejection_reasons": dict(self._rejections[label]),
                "predicted_labels": dict(confusion[label]),
                "prediction_reasons": dict(Counter(row["prediction_reason"] for row in rows)),
                **_prediction_counts(rows, label, "predicted_label"),
                "window": deepcopy(self._windows.get(label)),
                "eye_axes": eye_axes, "eyes": eyes,
                "head_axes_degrees": {
                    axis: _summary([row["features"][index] * 60 for row in valid_rows])
                    for index, axis in ((2, "yaw"), (3, "pitch"))
                },
            }
        total = sum(all_predictions.values())
        reading = targets["READING"]
        reading_count = reading["collected"]
        complete = len(self._completed) == len(self.targets)
        # Closure challenges intentionally contain invalid eyes. They need
        # collected frames for inspection, not a minimum number of valid irises.
        review_ready = (complete
                        and all(targets[label]["enough_usable_measurements"] for label in VALIDATION_TARGETS)
                        and all(targets[label]["collected"] > 0 for label in self.targets if label in CHALLENGE_TARGETS))
        return {
            "schema_version": 1, "purpose": "Separate operator-labelled diagnostic validation",
            "prediction_status": DEBUG_LABEL, "production_calibration_ready": self.production_ready,
            "training_cutoff": self.training_cutoff,
            "collection_targets": list(self.targets),
            "challenge_scoring": "UNKNOWN is abstention, not correctness; blink/closure intervals need operator review",
            "collection_complete": complete,
            "ready_for_operator_review": review_ready,
            "human_validation_status": "operator_review_required" if review_ready else "pending",
            "sampling": "new contiguous intervals after training; no reused or randomly split training frames",
            "rate_denominator": "fresh unique in-window measurements, including invalid measurements as UNKNOWN",
            "reference_classifier": ("eye point cores, bounded DOWN extension and session-relative aperture guard; head pose can only veto"
                                     if self._guarded_aperture else
                                     "eye point cores plus bounded CENTER-to-DOWN horizontal extension; head pose can only veto"),
            "source_classifier_policy": deepcopy(self._classifier_policy),
            "guarded_aperture_enabled": self._guarded_aperture,
            "reference_available": len(self._centers) == 4,
            "missing_reference_targets": [label for label in VALIDATION_TARGETS[:4]
                                          if label not in self._centers],
            "reference_centers": {label: list(row) for label, row in self._centers.items()},
            "reference_radii": dict(self._radii),
            "targets": targets, "confusion_matrix": confusion,
            "overall_unknown_rate": all_predictions["UNKNOWN"] / total if total else None,
            "reading_offscreen_prediction_rate": (
                sum(confusion["READING"][label] for label in ("LEFT", "RIGHT", "DOWN")) / reading_count
                if reading_count else None),
            "samples": deepcopy(self._rows),
            "openness_candidate": self._candidate_report(),
            "production_effects": "none: does not enable exams, change calibration, or generate events",
        }

    @property
    def summary_report(self):
        """Live numerical UI does not need a copy of every raw sample."""
        if self.screen_region_phase:
            return self._region_report(include_samples=False)
        return {key: value for key, value in self.report.items() if key != "samples"}

    def _candidate_report(self):
        if self.candidate is None:
            return None
        targets = {}
        for label, rows in self._rows.items():
            targets[label] = {
                "collected": len(rows),
                "invalid_measurements": sum(not row["accepted"] for row in rows),
                **_prediction_counts(rows, label, "candidate_predicted_label"),
                "prediction_reasons": dict(Counter(row["candidate_prediction_reason"] for row in rows)),
            }
        count = sum(target["collected"] for target in targets.values())
        return {
            "prediction_status": DEBUG_LABEL,
            "calibration": deepcopy(self.candidate.fit_report),
            "targets": targets,
            "confusion_matrix": {label: target["predicted_labels"] for label, target in targets.items()},
            "overall_unknown_rate": (sum(target["unknown_measurements"] for target in targets.values()) / count
                                     if count else None),
            "reading_offscreen_prediction_rate": targets["READING"]["offscreen_prediction_rate"],
            "human_validation_status": "pending_new_operator_review",
            "production_effects": "none; this opt-in candidate never enables calibration or sends events",
        }

    def training_snapshot(self):
        if self.screen_region_phase != "training":
            raise ValueError("Only screen-region training produces new references")
        recorded = [row["timestamp"] for rows in self._rows.values() for row in rows]
        accepted = [row["timestamp"] for rows in self._rows.values() for row in rows if row["accepted"]]
        snapshot = {
            "protocol": TRAINING_PROTOCOL, "schema_version": 1,
            "purpose": "Experimental screen-region calibration; numerical measurements only",
            "target_definitions": deepcopy(list(self.target_specs.values())),
            "samples": deepcopy(self._rows),
            "last_recorded_timestamp": max(recorded) if recorded else self.training_cutoff,
            "last_accepted_timestamp": max(accepted) if accepted else None,
            "collection_complete": len(self._completed) == len(self.targets),
            "collection_windows": deepcopy(self._windows),
            "rejection_reasons": {label: dict(counts) for label, counts in self._rejections.items()},
            "contains_images_video_or_raw_landmarks": False,
            "fit_configuration": {key: getattr(self.config, key) for key in (
                "calibration_samples", "calibration_max_spread", "calibration_eye_noise_floor",
                "calibration_min_signal_noise", "calibration_pixel_uncertainty_multiplier", "calibration_center_radius_fraction",
                "calibration_offscreen_radius_fraction", "calibration_max_samples", "result_stale_seconds")},
        }
        # Baseline comparison learns only from the new four corresponding
        # training fixations. Held-out reading/boundary rows never enter a fit.
        baseline = Calibration(self.config)
        for source, label in (("CENTER_START", "CENTER"), ("OFF_LEFT", "LEFT"),
                              ("OFF_RIGHT", "RIGHT"), ("OFF_DOWN", "DOWN")):
            for row in self._rows[source]:
                if row["accepted"]:
                    widths = [row["eyes"][side]["width_pixels"] for side in ("left", "right")]
                    floor = 1 / min(widths) if all(value is not None and value > 0 for value in widths) else None
                    baseline.add_sample(GazeDirection(label), row["features"], row["timestamp"],
                                        row["quality"], noise_floor=floor)
        baseline.fit()
        snapshot["baseline_reference"] = baseline.export_snapshot()
        # The separate region experiment retains its original iris-only point
        # comparison. Its training rows do not implicitly opt that experiment
        # into the new four-target production aperture policy.
        snapshot["baseline_reference"].pop("classifier_policy", None)
        snapshot["baseline_comparison_policy"] = "legacy_iris_point_cores"
        fit = ScreenRegionCandidate(snapshot, self.config).fit_report
        snapshot["region_fit"] = fit
        snapshot["diagnostics"] = {"ready": False, "production_effects": "none", "screen_region_fit": fit}
        return snapshot

    @staticmethod
    def _region_counts(rows, key):
        def canonical(label):
            return "ON_SCREEN" if label == "CENTER" else label
        counts = Counter(canonical(row.get(key, "UNKNOWN")) for row in rows)
        scored = [row for row in rows if row.get("expected_label") is not None]
        correct = sum(canonical(row.get(key, "UNKNOWN")) == row["expected_label"] for row in scored)
        unknown = sum(row.get(key, "UNKNOWN") == "UNKNOWN" for row in scored)
        return {
            "collected": len(rows), "invalid_measurements": sum(not row["accepted"] for row in rows),
            "predicted_labels": {label: counts[label] for label in ("ON_SCREEN", "LEFT", "RIGHT", "DOWN", "UNKNOWN")},
            "correct_labels": correct, "incorrect_labels": len(scored) - correct - unknown,
            "unknown_measurements": counts["UNKNOWN"], "scored_unknown_measurements": unknown,
            "unknown_rate": counts["UNKNOWN"] / len(rows) if rows else None,
            "correct_rate": correct / len(scored) if scored else None,
            "scored_measurements": len(scored), "unscored_transition_measurements": len(rows) - len(scored),
        }

    def _region_report(self, *, include_samples=True):
        labels = {"baseline": "predicted_label"}
        if self.region_candidate is not None:
            labels["screen_region"] = "region_predicted_label"
        comparisons = {}
        for name, key in labels.items():
            targets = {}
            for label, rows in self._rows.items():
                targets[label] = {
                    **self._region_counts(rows, key),
                    "status": "completed" if label in self._completed else "in_progress" if self._active == label else "pending",
                    "window": deepcopy(self._windows.get(label)),
                    "rejection_reasons": dict(self._rejections[label]),
                    "timing": self._region_timing(label, key, rows),
                }
            comparisons[name] = {"targets": targets,
                                 "overall": self._region_counts([row for rows in self._rows.values() for row in rows], key)}
        return {
            "schema_version": 1, "prediction_status": DEBUG_LABEL,
            "protocol": TRAINING_PROTOCOL if self.screen_region_phase == "training" else "screen_region_validation_v1",
            "phase": self.screen_region_phase,
            "target_definitions": deepcopy(list(self.target_specs.values())),
            "collection_targets": list(self.targets),
            "collection_complete": len(self._completed) == len(self.targets),
            "training_cutoff": self.training_cutoff,
            "event_timing_config": {
                "thresholds_seconds": ({getattr(key, "value", key): value for key, value in self.event_thresholds.items()}
                                       if self.event_thresholds is not None else
                                       {"gaze_left": 3., "gaze_right": 3., "gaze_down": 3.}),
                "clearing_seconds": self.clearing_seconds,
                "max_observation_gap_seconds": self.config.result_stale_seconds,
            },
            "production_calibration_ready": False,
            "screen_region_candidate": self.region_candidate.fit_report if self.region_candidate else None,
            "comparison": comparisons,
            "targets": comparisons["baseline"]["targets"],
            **({"samples": deepcopy(self._rows)} if include_samples else {}),
            "phase_scoring": "Instructed open intervals expect ON_SCREEN; closure/transition intervals unscored, UNKNOWN never counted correct",
            "human_validation_status": "pending_operator_review",
            "production_effects": "none; isolated diagnostic comparison and event replay only",
        }

    def _region_timing(self, label, key, rows):
        # Finalize a window once. Replaying all events on every UI poll would
        # waste CPU and invent a different set of debug event IDs each time.
        if self.screen_region_phase != "validation" or label not in self._completed:
            return None
        cache_key = (label, key)
        if cache_key not in self._timing_cache:
            self._timing_cache[cache_key] = summarize_timing(
                rows, key, self.target_specs[label].get("expected_label"),
                thresholds=self.event_thresholds, clearing_seconds=self.clearing_seconds,
                max_observation_gap=self.config.result_stale_seconds)
        return deepcopy(self._timing_cache[cache_key])
