"""Separate, operator-labelled gaze collection; never participates in an exam.

References are frozen from a calibration attempt, including a failed attempt.
Predictions are exploratory labels, not calibrated confidence or authorization
to start an exam. Nothing here changes Calibration.ready or produces events.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math

from .calibration import _bounded_down_extension, _distance, _summary
from .settings import VisionConfig


VALIDATION_TARGETS = ("CENTER", "LEFT", "RIGHT", "DOWN", "READING")
PREDICTION_LABELS = ("CENTER", "LEFT", "RIGHT", "DOWN", "UNKNOWN")
DEBUG_LABEL = "DEBUG / UNVALIDATED"


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


class DiagnosticValidation:
    """Independent consecutive collection windows with immutable references.

    A sample must be newer than every recorded training measurement, inside its
    explicitly declared validation window, and newer than any previously seen
    validation sample. Invalid fresh measurements count as UNKNOWN; stale and
    out-of-window deliveries are excluded from prediction-rate denominators.
    """

    def __init__(self, attempt_export: dict, config: VisionConfig):
        self._snapshot = deepcopy(attempt_export)
        self.config = config
        diagnostics = self._snapshot.get("diagnostics", {})
        self.production_ready = diagnostics.get("ready") is True
        timestamps = [self._snapshot.get("last_recorded_timestamp"),
                      self._snapshot.get("last_accepted_timestamp")]
        for rows in self._snapshot.get("samples", {}).values():
            timestamps.extend(row.get("timestamp") for row in rows if isinstance(row, dict))
        finite = [value for value in map(_finite_number, timestamps) if value is not None]
        self.training_cutoff = max(finite) if finite else None
        self._last_timestamp = self.training_cutoff if self.training_cutoff is not None else -math.inf
        self._centers = {}
        for label in VALIDATION_TARGETS[:4]:
            target = diagnostics.get("targets", {}).get(label, {})
            eye, head = target.get("eye_median"), target.get("head_median_degrees")
            if (isinstance(eye, (tuple, list)) and len(eye) == 2
                    and isinstance(head, (tuple, list)) and len(head) == 2
                    and all(_finite_number(x) is not None for x in (*eye, *head))
                    and target.get("accepted", 0) >= config.calibration_samples):
                self._centers[label] = tuple(float(x) for x in eye) + tuple(float(x) / 60 for x in head)
        self._radii = {}
        # These are the existing production reference-core radii, frozen for an
        # exploratory held-out check. Production fit acceptance is NOT changed.
        if len(self._centers) == 4:
            center = self._centers["CENTER"][:2]
            distances = {label: _distance(center, reference[:2])
                         for label, reference in self._centers.items() if label != "CENTER"}
            self._radii["CENTER"] = config.calibration_center_radius_fraction * min(distances.values())
            for label, distance in distances.items():
                nearest = min(_distance(self._centers[label][:2], reference[:2])
                              for other, reference in self._centers.items() if label != other)
                self._radii[label] = min(config.calibration_offscreen_radius_fraction * distance, .4 * nearest)
        self._rows = {label: [] for label in VALIDATION_TARGETS}
        self._rejections = {label: Counter() for label in VALIDATION_TARGETS}
        self._completed = set()
        self._windows = {}
        self._active = None
        self._last_window_end = self.training_cutoff if self.training_cutoff is not None else -math.inf

    @property
    def reference_snapshot(self) -> dict:
        return deepcopy(self._snapshot)

    @property
    def active_target(self) -> str | None:
        return self._active

    def start_target(self, label: str, starts_at: float, ends_at: float) -> None:
        if label not in VALIDATION_TARGETS:
            raise ValueError("Unknown diagnostic validation target")
        expected = next((target for target in VALIDATION_TARGETS if target not in self._completed), None)
        if self._active is not None or label != expected:
            raise ValueError("Finish the current validation target; collect targets in sequence")
        if self.training_cutoff is None:
            raise ValueError("Training timestamps are missing; collect a new calibration attempt first")
        if (_finite_number(starts_at) is None or _finite_number(ends_at) is None
                or starts_at <= self._last_window_end or ends_at <= starts_at):
            raise ValueError("Validation windows must be finite, separate, and later than training")
        self._active = label
        self._windows[label] = {"starts_at": starts_at, "ends_at": ends_at}

    def predict(self, features) -> str:
        """Return an exploratory label only. Deliberately exposes no confidence."""
        return self._prediction(features)[0]

    def _prediction(self, features) -> tuple[str, str]:
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
        predicted, prediction_reason = self._prediction(row) if reason is None else ("UNKNOWN", reason)
        self._rows[label].append({
            "timestamp": timestamp, "operator_target": label,
            "expected_label": "CENTER" if label == "READING" else label,
            "features": list(row) if row is not None else None,
            "quality": _finite_number(quality), "accepted": reason is None,
            "rejection_reason": reason, "predicted_label": predicted,
            "prediction_reason": prediction_reason,
            "prediction_status": DEBUG_LABEL, **_metadata(metadata),
        })
        return reason is None

    def finish_target(self, now: float) -> None:
        if self._active is None:
            raise ValueError("No active validation target")
        window = self._windows[self._active]
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
            self._active = None

    @property
    def report(self) -> dict:
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
            expected = "CENTER" if label == "READING" else label
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
                "unknown_rate": predictions["UNKNOWN"] / len(rows) if rows else None,
                "expected_match_rate": predictions[expected] / len(rows) if rows else None,
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
        complete = len(self._completed) == len(VALIDATION_TARGETS)
        review_ready = complete and all(target["enough_usable_measurements"] for target in targets.values())
        return {
            "schema_version": 1, "purpose": "Separate operator-labelled diagnostic validation",
            "prediction_status": DEBUG_LABEL, "production_calibration_ready": self.production_ready,
            "training_cutoff": self.training_cutoff,
            "collection_complete": complete,
            "ready_for_operator_review": review_ready,
            "human_validation_status": "operator_review_required" if review_ready else "pending",
            "sampling": "new contiguous intervals after training; no reused or randomly split training frames",
            "rate_denominator": "fresh unique in-window measurements, including invalid measurements as UNKNOWN",
            "reference_classifier": "eye point cores plus bounded CENTER-to-DOWN horizontal extension; head pose can only veto",
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
            "production_effects": "none: does not enable exams, change calibration, or generate events",
        }
