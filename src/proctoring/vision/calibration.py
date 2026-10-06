"""Session-local eye calibration, with head pose kept independently observable.

The first two features are iris position in units of eye-corner width. The last
two are yaw/60 and pitch/60. Only the eye features learn a direction: a head turn
cannot rescue overlapping eye references or create a gaze classification.
"""
from __future__ import annotations

import math
from copy import deepcopy
from collections import Counter
from statistics import median
from threading import RLock

from .settings import VisionConfig
from .types import FaceMeasurement, GazeDirection


DIRECTIONS = (
    GazeDirection.CENTER, GazeDirection.LEFT,
    GazeDirection.RIGHT, GazeDirection.DOWN,
)


def _distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _bounded_down_extension(features, centers, radii):
    """Match DOWN across its demonstrated horizontal offset from CENTER.

    The original point cores remain the fallback. This extension is a finite
    horizontal segment at the DOWN vertical reference, with endpoints supplied
    solely by training CENTER/DOWN. Its radius never exceeds the original DOWN
    tolerance and is capped by distance to the other references. It cannot turn
    an arbitrary horizontal position into DOWN or resolve overlapping cores.
    Returns a label, reference similarity (not probability), and reason, or None
    when the original point classifier should decide.
    """
    center, down = centers["CENTER"], centers["DOWN"]
    low, high = sorted((center[0], down[0]))
    original_radius = radii["DOWN"]
    if low == high or _distance(features[:2], down[:2]) <= original_radius:
        return None

    def segment_distance(point):
        nearest_horizontal = min(high, max(low, point[0]))
        return math.hypot(point[0] - nearest_horizontal, point[1] - down[1])

    others = {label: row for label, row in centers.items() if label != "DOWN"}
    radius = min(original_radius, .4 * min(segment_distance(row) for row in others.values()))
    distance = segment_distance(features)
    if radius <= 0 or distance > radius:
        return None
    other_distances = {label: _distance(features[:2], row[:2]) for label, row in others.items()}
    if any(distance_to_other <= radii[label] for label, distance_to_other in other_distances.items()):
        return "UNKNOWN", None, "overlapping_reference_cores"
    nearest_other = min(other_distances.values())
    margin = (nearest_other - distance) / max(nearest_other, 1e-9)
    if margin < .12:
        return "UNKNOWN", None, "ambiguous_reference_margin"
    similarity = min(1., max(0., margin * (1. - .5 * distance / radius)))
    return "DOWN", similarity, "within_bounded_down_core"


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(.9 * len(ordered)) - 1)]


def _finite(value) -> float | None:
    """JSON cannot represent nonfinite numbers; diagnostics never invent them."""
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def _summary(values: list[float]) -> dict | None:
    if not values:
        return None
    center = median(values)
    ordered = sorted(values)
    return {"count": len(values), "median": center,
            "spread_p90": _p90([abs(value - center) for value in values]),
            "p10": ordered[max(0, math.ceil(.1 * len(ordered)) - 1)],
            "p90": _p90(values), "min": ordered[0], "max": ordered[-1]}


class Calibration:
    """Thread-safe eye-reference classifier with no implicit persistence.

    Separation must exceed both a measurement-noise floor and the actual sample
    spread. The UI supplies the one-pixel/eye-width floor when available; it is
    not a measured camera accuracy or a probability. Reference matching scores
    are likewise similarity scores, not calibrated probabilities of gaze.
    """

    def __init__(self, config: VisionConfig):
        self.config = config
        self._lock = RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._samples: dict[GazeDirection, list[tuple[float, ...]]] = {
                direction: [] for direction in DIRECTIONS
            }
            self._noise_floors: dict[GazeDirection, list[float]] = {
                direction: [] for direction in DIRECTIONS
            }
            self._supplied_noise_floors: dict[GazeDirection, list[float | None]] = {
                direction: [] for direction in DIRECTIONS
            }
            self._records: dict[GazeDirection, list[dict]] = {
                direction: [] for direction in DIRECTIONS
            }
            self._dropped_records = {direction: 0 for direction in DIRECTIONS}
            self._rejections: dict[GazeDirection, Counter] = {
                direction: Counter() for direction in DIRECTIONS
            }
            self._centers: dict[GazeDirection, tuple[float, ...]] = {}
            self._radii: dict[GazeDirection, float] = {}
            self._last_timestamp = -math.inf
            self._last_recorded_timestamp = -math.inf
            self._fit_message = "Calibration has not been fitted."
            self._failed_targets: tuple[GazeDirection, ...] = ()

    @property
    def ready(self) -> bool:
        with self._lock:
            return len(self._centers) == len(DIRECTIONS)

    @property
    def counts(self) -> dict[GazeDirection, int]:
        with self._lock:
            return {direction: len(values) for direction, values in self._samples.items()}

    def record_rejection(self, direction: GazeDirection, reason: str, *,
                         timestamp: float | None = None,
                         measurement: FaceMeasurement | None = None,
                         frame_size: tuple[int, int] | None = None) -> None:
        """Retain bounded numerical diagnostics, never a frame or landmarks."""
        if direction in DIRECTIONS:
            with self._lock:
                self._rejections[direction][reason] += 1
                self._record(direction, accepted=False, reason=reason, timestamp=timestamp,
                             measurement=measurement, frame_size=frame_size)

    def _record(self, direction, *, accepted, reason=None, timestamp=None,
                features=None, quality=None, noise_floor=None, measurement=None,
                frame_size=None):
        if (stamp := _finite(timestamp)) is not None:
            self._last_recorded_timestamp = max(self._last_recorded_timestamp, stamp)
        if len(self._records[direction]) >= self.config.calibration_max_samples:
            self._dropped_records[direction] += 1
            return
        if measurement is not None:
            features = measurement.features if features is None else features
            quality = measurement.quality if quality is None else quality
            frame_size = getattr(measurement, "frame_size", None) if frame_size is None else frame_size
        eyes = {"left": None, "right": None}
        if measurement is not None and measurement.diagnostics is not None:
            for side, eye in (("left", measurement.diagnostics.left_eye),
                              ("right", measurement.diagnostics.right_eye)):
                eyes[side] = {
                    "horizontal": _finite(eye.horizontal), "vertical": _finite(eye.vertical),
                    "opening": _finite(eye.opening), "width_pixels": _finite(eye.width_pixels),
                    "valid": bool(eye.valid), "reason": eye.reason,
                }
        pose = measurement.head_pose if measurement is not None else None
        self._records[direction].append({
            "timestamp": stamp, "accepted": accepted, "rejection_reason": reason,
            "features": [_finite(value) for value in features] if features is not None else None,
            "quality": _finite(quality), "supplied_noise_floor": _finite(noise_floor),
            "frame_size": (list(frame_size) if frame_size is not None and len(frame_size) == 2
                           and all(isinstance(value, int) and value > 0 for value in frame_size) else None),
            "eyes": eyes,
            "head_pose_degrees": ({"yaw": _finite(pose.yaw), "pitch": _finite(pose.pitch),
                                   "roll": _finite(pose.roll)} if pose is not None else None),
        })

    def discard_target(self, direction: GazeDirection) -> None:
        """Discard an interrupted collection, preserving the global freshness gate."""
        if direction not in DIRECTIONS:
            raise ValueError("Unknown calibration target")
        with self._lock:
            self._samples[direction].clear()
            self._noise_floors[direction].clear()
            self._supplied_noise_floors[direction].clear()
            self._records[direction].clear()
            self._dropped_records[direction] = 0
            self._rejections[direction].clear()
            self._centers.clear()
            self._radii.clear()
            self._failed_targets = ()
            self._fit_message = f"Collect fresh {direction.value} samples."

    def retry_targets(self, directions) -> tuple[GazeDirection, ...]:
        """Retry a failed target/pair and refresh CENTER to recheck the baseline."""
        requested = set(directions)
        if not requested.issubset(set(DIRECTIONS)):
            raise ValueError("Unknown calibration target")
        requested.add(GazeDirection.CENTER)
        ordered = tuple(direction for direction in DIRECTIONS if direction in requested)
        with self._lock:
            for direction in ordered:
                self.discard_target(direction)
        return ordered

    def add_sample(self, direction: GazeDirection, features: tuple[float, ...] | None,
                   timestamp: float, quality: float, *, noise_floor: float | None = None,
                   measurement: FaceMeasurement | None = None,
                   frame_size: tuple[int, int] | None = None) -> bool:
        """Accept a valid, fresh result; target timing is enforced by the collector.

        The configured sample count is a minimum, not an early stopping point:
        use the entire collection interval to reveal mixed or unsteady samples.
        """
        reason = None
        if direction not in DIRECTIONS:
            return False
        if features is None or len(features) != 4:
            reason = "missing_or_invalid_features"
        elif not all(math.isfinite(x) for x in features):
            reason = "nonfinite_features"
        elif not math.isfinite(timestamp):
            reason = "nonfinite_timestamp"
        elif not math.isfinite(quality) or quality < .45:
            reason = "insufficient_measurement_quality"
        elif noise_floor is not None and (not math.isfinite(noise_floor) or noise_floor <= 0):
            reason = "invalid_measurement_noise_floor"
        with self._lock:
            if reason is None:
                if timestamp <= self._last_timestamp:
                    reason = "reused_or_out_of_order_measurement"
                elif self.ready:
                    reason = "already_fitted"
                elif len(self._samples[direction]) >= self.config.calibration_max_samples:
                    reason = "sample_capacity_reached"
            if reason:
                self._rejections[direction][reason] += 1
                self._record(direction, accepted=False, reason=reason, timestamp=timestamp,
                             features=features, quality=quality, noise_floor=noise_floor,
                             measurement=measurement, frame_size=frame_size)
                return False
            self._samples[direction].append(tuple(float(x) for x in features))
            self._noise_floors[direction].append(max(
                self.config.calibration_eye_noise_floor, noise_floor or 0.0))
            self._supplied_noise_floors[direction].append(noise_floor)
            self._record(direction, accepted=True, timestamp=timestamp, features=features,
                         quality=quality, noise_floor=noise_floor,
                         measurement=measurement, frame_size=frame_size)
            self._last_timestamp = timestamp
            return True

    def _statistics(self) -> dict[GazeDirection, dict]:
        targets = {}
        for direction, rows in self._samples.items():
            records = self._records[direction]
            accepted_records = [record for record in records if record["accepted"]]
            frame_sizes = Counter(tuple(record["frame_size"]) for record in records
                                  if record["frame_size"] is not None)
            def eyes_summary(source):
                result = {}
                for side in ("left", "right"):
                    eyes = [record["eyes"][side] for record in source
                            if record["eyes"][side] is not None]
                    result[side] = {
                        field: _summary([eye[field] for eye in eyes if eye[field] is not None])
                        for field in ("horizontal", "vertical", "opening", "width_pixels")
                    }
                    result[side]["valid"] = sum(eye["valid"] for eye in eyes)
                    result[side]["invalid_reasons"] = dict(Counter(
                        eye["reason"] for eye in eyes if not eye["valid"]))
                return result
            target = {
                "accepted": len(rows),
                "rejected": sum(self._rejections[direction].values()),
                "rejection_reasons": dict(self._rejections[direction]),
                "eye_median": None,
                "head_median_degrees": None,
                "eye_spread_p90": None,
                "head_spread_p90_degrees": None,
                "measurement_noise_floor": None,
                "supplied_pixel_noise_floor_p90": None,
                "pixel_noise_floor_samples": sum(value is not None for value
                                                  in self._supplied_noise_floors[direction]),
                "pixel_noise_floor_missing_samples": sum(value is None for value
                                                          in self._supplied_noise_floors[direction]),
                "eye_axes": {"horizontal": None, "vertical": None},
                "eyes": eyes_summary(accepted_records),
                "all_recorded_eyes": eyes_summary(records),
                "source_frame_sizes": [{"width": width, "height": height, "samples": count}
                                       for (width, height), count in sorted(frame_sizes.items())],
                "source_frame_size_missing_samples": sum(record["frame_size"] is None for record in records),
                "retained_numerical_records": len(records),
                "dropped_numerical_records": self._dropped_records[direction],
                "radial_tail_axis_energy_fraction": None,
            }
            if rows:
                center = tuple(median(row[i] for row in rows) for i in range(4))
                target.update({
                    "eye_median": list(center[:2]),
                    "head_median_degrees": [value * 60 for value in center[2:]],
                    "eye_spread_p90": _p90([_distance(row[:2], center[:2]) for row in rows]),
                    "head_spread_p90_degrees": 60 * _p90([
                        _distance(row[2:], center[2:]) for row in rows]),
                    "measurement_noise_floor": _p90(self._noise_floors[direction]),
                    # Zeros only represent the existing gate's absent optional
                    # floor. The UI still sees missing counts rather than an
                    # invented source eye width or a claim of zero uncertainty.
                    "supplied_pixel_noise_floor_p90": (
                        _p90([value or 0.0 for value in self._supplied_noise_floors[direction]])
                        if any(value is not None for value in self._supplied_noise_floors[direction])
                        else None),
                    "eye_axes": {axis: _summary([row[index] for row in rows])
                                 for index, axis in enumerate(("horizontal", "vertical"))},
                })
                radial = [_distance(row[:2], center[:2]) for row in rows]
                tail = [row for row, radius in zip(rows, radial)
                        if radius >= target["eye_spread_p90"]]
                energy = [sum((row[index] - center[index]) ** 2 for row in tail)
                          for index in range(2)]
                total = sum(energy)
                target["radial_tail_axis_energy_fraction"] = {
                    axis: (energy[index] / total if total else 0.0)
                    for index, axis in enumerate(("horizontal", "vertical"))}
            targets[direction] = target
        return targets

    def _pair_statistics(self, targets: dict) -> dict[str, dict]:
        pairs = {}
        for index, direction in enumerate(DIRECTIONS):
            for other in DIRECTIONS[index + 1:]:
                first, second = targets[direction], targets[other]
                if first["eye_median"] is None or second["eye_median"] is None:
                    continue
                eye_separation = _distance(first["eye_median"], second["eye_median"])
                noise = max(first["measurement_noise_floor"], second["measurement_noise_floor"])
                required = max(
                    self.config.calibration_min_signal_noise * noise,
                    2.5 * max(first["eye_spread_p90"], second["eye_spread_p90"]),
                )
                constant = self.config.calibration_min_signal_noise * self.config.calibration_eye_noise_floor
                supplied = [value for value in (first["supplied_pixel_noise_floor_p90"],
                                                 second["supplied_pixel_noise_floor_p90"])
                            if value is not None]
                pixel = self.config.calibration_min_signal_noise * max(supplied) if supplied else None
                spread = 2.5 * max(first["eye_spread_p90"], second["eye_spread_p90"])
                contributions = {"constant_noise_floor": constant, "pixel_noise_floor": pixel,
                                 "spread": spread}
                dominant = [name for name, value in contributions.items()
                            if value is not None and math.isclose(value, required, rel_tol=1e-9, abs_tol=1e-12)]
                axes = {}
                for axis_index, axis in enumerate(("horizontal", "vertical")):
                    difference = second["eye_median"][axis_index] - first["eye_median"][axis_index]
                    axis_spread = 2.5 * max(first["eye_axes"][axis]["spread_p90"],
                                          second["eye_axes"][axis]["spread_p90"])
                    axis_contributions = dict(contributions, spread=axis_spread)
                    axis_required = max(value for value in axis_contributions.values() if value is not None)
                    eyes = {}
                    for side in ("left", "right"):
                        a, b = first["eyes"][side][axis], second["eyes"][side][axis]
                        eyes[side] = ({"signed_second_minus_first": b["median"] - a["median"],
                                       "separation": abs(b["median"] - a["median"]),
                                       "first_spread_p90": a["spread_p90"],
                                       "second_spread_p90": b["spread_p90"],
                                       "central_80_percent_intervals_overlap":
                                           max(a["p10"], b["p10"]) <= min(a["p90"], b["p90"])}
                                      if a is not None and b is not None else None)
                    a, b = first["eye_axes"][axis], second["eye_axes"][axis]
                    axes[axis] = {
                        "metric_dimensions": 1, "signed_second_minus_first": difference,
                        "separation": abs(difference), "threshold_contributions": axis_contributions,
                        "required_separation": axis_required,
                        "dominant_contributions": [name for name, value in axis_contributions.items()
                                                    if value is not None and math.isclose(
                                                        value, axis_required, rel_tol=1e-9, abs_tol=1e-12)],
                        "passed_diagnostic_comparison": abs(difference) >= axis_required,
                        "central_80_percent_intervals_overlap":
                            max(a["p10"], b["p10"]) <= min(a["p90"], b["p90"]),
                        "eyes": eyes,
                    }
                relevant_axis = ("vertical" if other == GazeDirection.DOWN else "horizontal") if direction == GazeDirection.CENTER else None
                pairs[f"{direction.value}_{other.value}"] = {
                    "eye_separation": eye_separation,
                    "required_eye_separation": required,
                    "eye_signal_noise": eye_separation / noise,
                    "required_signal_noise": required / noise,
                    "head_separation_degrees": _distance(
                        first["head_median_degrees"], second["head_median_degrees"]),
                    "passed": eye_separation >= required,
                    "metric_dimensions": 2,
                    "metric": "Euclidean distance of two-eye mean (horizontal, vertical)",
                    "units": "normalized eye-corner widths",
                    "threshold_contributions": contributions,
                    "dominant_contributions": dominant,
                    "axes": axes,
                    "relevant_axis": relevant_axis,
                    "axis_comparisons_are_diagnostic_only": True,
                    "unrelated_axis_spread_larger": (
                        max(first["eye_axes"]["horizontal" if relevant_axis == "vertical" else "vertical"]["spread_p90"],
                            second["eye_axes"]["horizontal" if relevant_axis == "vertical" else "vertical"]["spread_p90"])
                        > max(first["eye_axes"][relevant_axis]["spread_p90"],
                              second["eye_axes"][relevant_axis]["spread_p90"])
                        if relevant_axis else None),
                }
        return pairs

    @property
    def diagnostics(self) -> dict:
        """Independent aggregate snapshot: safe to display/export when requested."""
        with self._lock:
            targets = self._statistics()
            return {
                "ready": self.ready,
                "feature_units": "iris position / eye-corner width; head pose in degrees",
                "statistics_definitions": {
                    "spread_p90": "90th percentile absolute deviation from the coordinate median",
                    "eye_spread_p90": "90th percentile 2D Euclidean distance from coordinate medians",
                    "interval_overlap": "Empirical p10-to-p90 intervals, not confidence intervals or proof of generalizable separation",
                    "pixel_floor": "UI-supplied 1 / min(original-frame left eye width, right eye width); assumed scalar radial safeguard in the 2D two-eye-mean feature space, not measured landmark accuracy or a per-axis standard deviation",
                    "production_gate": "max(SNR * constant floor, SNR * supplied pixel floor p90, 2.5 * radial spread p90), all in normalized eye-width units",
                    "axis_comparisons": "One-dimensional diagnostic comparisons reuse the existing scalar radial safeguard, not a measured per-axis uncertainty; they do not change the two-dimensional production gate",
                    "eyes": "Per-eye medians/spreads use retained accepted samples; all_recorded_eyes additionally includes rejected measurements",
                    "radial_tail_axis_energy_fraction": "Fraction of squared horizontal/vertical deviations among samples at or above radial p90; reveals which axis contributes to the radial tail",
                },
                "classification": "eye point cores with bounded CENTER-to-DOWN horizontal extension; head pose only rejects unsupported poses",
                "targets": {direction.value: stats for direction, stats in targets.items()},
                "pairs": self._pair_statistics(targets),
                "failed_targets": [direction.value for direction in self._failed_targets],
                "fit_message": self._fit_message,
            }

    def export_snapshot(self) -> dict:
        """Explicit caller-controlled numerical export, also available after failure.

        This method does no filesystem writes. The UI must request an export;
        normal calibration/evidence behavior never persists these measurements.
        """
        with self._lock:
            return deepcopy({
                "schema_version": 1,
                "purpose": "DEBUG / UNVALIDATED — numerical calibration diagnostics",
                "diagnostics": self.diagnostics,
                "last_accepted_timestamp": _finite(self._last_timestamp),
                "last_recorded_timestamp": _finite(self._last_recorded_timestamp),
                "sample_limit_per_target": self.config.calibration_max_samples,
                "samples": {direction.value: rows for direction, rows in self._records.items()},
                "dropped_numerical_records": {direction.value: count for direction, count in self._dropped_records.items()},
                "contains_images_video_or_raw_landmarks": False,
            })

    def _failure(self, message: str, directions) -> tuple[bool, str]:
        self._fit_message = message
        self._failed_targets = tuple(directions)
        return False, message

    def fit(self) -> tuple[bool, str]:
        with self._lock:
            self._centers.clear()
            self._radii.clear()
            self._failed_targets = ()
            missing = [direction for direction in DIRECTIONS
                       if len(self._samples[direction]) < self.config.calibration_samples]
            if missing:
                details = []
                for direction in missing:
                    reasons = self._rejections[direction]
                    counts = ", ".join(f"{reason}: {count}" for reason, count in reasons.most_common(3))
                    details.append(f"{direction.value}: {len(self._samples[direction])}/"
                                   f"{self.config.calibration_samples} accepted, "
                                   f"{sum(reasons.values())} rejected" + (f" ({counts})" if counts else ""))
                return self._failure("More clear samples needed. " + "; ".join(details) + ".", missing)
            targets = self._statistics()
            for direction, stats in targets.items():
                if stats["eye_spread_p90"] > self.config.calibration_max_spread:
                    return self._failure(
                        f"Unsteady {direction.value} eye samples: measured radial p90 spread "
                        f"{stats['eye_spread_p90']:.4f} exceeds {self.config.calibration_max_spread:.4f} "
                        "eye widths. Inspect horizontal/vertical spread and invalid-sample reasons.",
                        (GazeDirection.CENTER, direction),
                    )
            for name, pair in self._pair_statistics(targets).items():
                if not pair["passed"]:
                    first, second = (GazeDirection(value) for value in name.split("_"))
                    dominant = pair["dominant_contributions"]
                    if "pixel_noise_floor" in dominant:
                        cause = "The assumed pixel-based uncertainty gate dominates"
                    elif "spread" in dominant:
                        cause = "The measured eye-spread gate dominates"
                    else:
                        cause = "The configured constant noise-floor gate dominates"
                    axis_name = pair["relevant_axis"]
                    axis_detail = (f" {axis_name.title()} separation "
                                   f"{pair['axes'][axis_name]['separation']:.4f}; diagnostic axis requirement "
                                   f"{pair['axes'][axis_name]['required_separation']:.4f}." if axis_name else "")
                    return self._failure(
                        f"{first.value} and {second.value} eye measurements were not distinct enough "
                        f"(separation {pair['eye_separation']:.4f}; required "
                        f"{pair['required_eye_separation']:.4f} eye widths). "
                        f"{cause}.{axis_detail} Inspect the numerical diagnostics/export; "
                        "this failure does not by itself establish overlapping gaze distributions.",
                        (first, second),
                    )
            self._centers = {
                direction: tuple(median(row[i] for row in rows) for i in range(4))
                for direction, rows in self._samples.items()
            }
            center = self._centers[GazeDirection.CENTER][:2]
            center_distances = {direction: _distance(center, reference[:2])
                                for direction, reference in self._centers.items()
                                if direction != GazeDirection.CENTER}
            self._radii[GazeDirection.CENTER] = (
                self.config.calibration_center_radius_fraction * min(center_distances.values()))
            for direction, distance in center_distances.items():
                nearest = min(_distance(self._centers[direction][:2], reference[:2])
                              for other, reference in self._centers.items() if other != direction)
                self._radii[direction] = min(
                    self.config.calibration_offscreen_radius_fraction * distance,
                    .4 * nearest,
                )
            self._fit_message = (
                "Calibration complete. Eye directions use this session's iris references; "
                "ambiguous measurements remain UNKNOWN. Head pose is shown separately.")
            return True, self._fit_message

    def classify(self, features: tuple[float, ...] | None) -> tuple[GazeDirection, float | None]:
        if features is None or len(features) != 4 or not all(math.isfinite(x) for x in features):
            return GazeDirection.UNKNOWN, None
        with self._lock:
            if not self.ready:
                return GazeDirection.UNKNOWN, None
            # Looking around with the head can invalidate the eye geometry. A
            # head cue only vetoes extrapolation, never supplies a direction.
            for axis in (2, 3):
                calibrated = [reference[axis] for reference in self._centers.values()]
                allowance = 10.0 / 60.0
                if not min(calibrated) - allowance <= features[axis] <= max(calibrated) + allowance:
                    return GazeDirection.UNKNOWN, None
            extension = _bounded_down_extension(features, self._centers, self._radii)
            if extension is not None:
                label, similarity, _ = extension
                return GazeDirection(label), similarity
            ranked = sorted(((_distance(features[:2], reference[:2]), direction)
                             for direction, reference in self._centers.items()), key=lambda pair: pair[0])
            distance, direction = ranked[0]
            second_distance = ranked[1][0]
            radius = self._radii[direction]
            # Moving away from exact CENTER is insufficient: offscreen labels
            # require reaching the small core around a demonstrated target.
            if distance > radius:
                return GazeDirection.UNKNOWN, None
            margin = (second_distance - distance) / max(second_distance, 1e-9)
            if margin < .12:
                return GazeDirection.UNKNOWN, None
            similarity = min(1.0, max(0.0, margin * (1.0 - .5 * distance / radius)))
            return direction, similarity
