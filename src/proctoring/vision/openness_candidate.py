"""A small frozen DEBUG candidate; never used by the production gaze backend.

Each eye supplies horizontal/vertical iris position and eyelid aperture. Only
aperture is divided by that eye's session CENTER median. DOWN needs *both* a
vertical iris shift and supporting aperture change, inside finite learned
support. A lower aperture alone is not a direction or evidence of a blink.

The empirical envelopes below are development assumptions, not camera accuracy
bounds. In particular, within-pass repeatability cannot establish across-pass
accuracy or optical iris visibility. Independent labelled collection is needed.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
from statistics import median

from .settings import VisionConfig


TARGETS = ("CENTER", "LEFT", "RIGHT", "DOWN")
SIDES = ("left", "right")
AXES = ("horizontal", "vertical", "opening_normalized")
STATUS = "DEBUG / UNVALIDATED"


def _number(value):
    return (float(value) if isinstance(value, (int, float))
            and not isinstance(value, bool) and math.isfinite(value) else None)


def _p90(values):
    return sorted(values)[max(0, math.ceil(.9 * len(values)) - 1)]


def _measurement(features, metadata, quality, rejection_reason):
    if rejection_reason is not None:
        return None, str(rejection_reason)[:200]
    if not isinstance(features, (list, tuple)) or len(features) != 4:
        return None, "missing_or_invalid_features"
    row = tuple(_number(value) for value in features)
    if any(value is None for value in row):
        return None, "missing_or_invalid_features"
    quality = _number(quality)
    if quality is None or quality < .45:
        return None, "insufficient_measurement_quality"
    eyes = metadata.get("eyes", {}) if isinstance(metadata, dict) else {}
    result = {}
    for side in SIDES:
        eye = eyes.get(side) if isinstance(eyes, dict) else None
        if not isinstance(eye, dict) or eye.get("valid") is not True:
            return None, f"{side}_eye_unobservable"
        values = {axis: _number(eye.get(axis)) for axis in
                  ("horizontal", "vertical", "opening", "width_pixels")}
        if any(value is None for value in values.values()):
            return None, f"{side}_eye_missing_or_nonfinite_measurements"
        # Preserve the existing backend's basic aperture/size admission. This
        # candidate does not use nominal iris coordinates to rescue closure.
        if values["opening"] < .10 or values["opening"] > .75:
            return None, f"{side}_eye_aperture_unobservable"
        if values["width_pixels"] < 8.:
            return None, f"{side}_eye_source_region_too_small"
        if not (.02 <= values["horizontal"] <= .98 and .15 <= values["vertical"] <= .85):
            return None, f"{side}_iris_geometry_outside_eye"
        result[side] = values
    for axis, index in (("horizontal", 0), ("vertical", 1)):
        if abs(sum(result[side][axis] for side in SIDES) / 2 - row[index]) > 1e-6:
            return None, "feature_metadata_mismatch"
    result["head"] = row[2:]
    return result, None


class OpennessCandidate:
    """Session references and independent acceptance, with no production effects.

    ``fit_report['fit_ready']`` is permission only to compute DEBUG predictions.
    The supplied attempt is copied; its production ``ready`` flag is ignored.
    ``predict`` is stateless and exposes a label/reason, never confidence. Caller
    owns source-frame matching, freshness and independent validation windows.
    """

    def __init__(self, attempt_export: dict, config: VisionConfig):
        self._refs = {}
        self._baseline = {}
        self._head_range = ()
        self._ready = False
        source = deepcopy(attempt_export)
        floor = config.calibration_eye_noise_floor
        floor_multiplier = config.calibration_min_signal_noise
        self._report = {
            "candidate": "per_eye_iris_and_center_normalized_openness_v1",
            "status": STATUS, "fit_ready": False,
            "human_validation_status": "pending",
            "production_effects": "none; cannot enable exam or create events",
            "accepted_training_counts": {}, "excluded_training_reasons": {},
            "center_opening_baselines": {}, "references": {}, "gates": [],
            "failures": [],
            "assumptions": {
                "spread_multiplier": 2.5, "constant_floor_multiplier": floor_multiplier,
                "constant_floor_eye_widths": floor,
                "support": "finite per-axis median +/- max(constant_floor_multiplier*constant_floor, 2.5*p90_absolute_deviation)",
                "normalization": "opening / same-eye CENTER opening median; iris coordinates remain eye-width units",
                "pixel_floor": "reported per-axis for comparison, not an established subpixel error bound and not used by this empirical DEBUG candidate",
                "iris_visibility": "requires valid source eye measurements; numerical validity does not prove optical visibility",
                "head_pose": "coverage veto only; never supplies a direction",
                "limitations": "within-pass repeatability is not independent accuracy; amplitude or baseline drift may remain UNKNOWN",
            },
        }
        rows = {}
        for label in TARGETS:
            records = source.get("samples", {}).get(label, [])
            rows[label], exclusions = [], Counter()
            for record in records:
                if not isinstance(record, dict) or record.get("accepted") is not True:
                    continue
                value, reason = _measurement(record.get("features"), record,
                                             record.get("quality"), record.get("rejection_reason"))
                if reason:
                    exclusions[reason] += 1
                else:
                    rows[label].append(value)
            self._report["accepted_training_counts"][label] = len(rows[label])
            self._report["excluded_training_reasons"][label] = dict(exclusions)
            if len(rows[label]) < config.calibration_samples:
                self._report["failures"].append(f"{label}: insufficient valid paired eye samples")
        if self._report["failures"]:
            return
        self._baseline = {
            side: median(row[side]["opening"] for row in rows["CENTER"])
            for side in SIDES
        }
        self._report["center_opening_baselines"] = dict(self._baseline)
        for label in TARGETS:
            self._refs[label] = {}
            for side in SIDES:
                self._refs[label][side] = {}
                for axis in AXES:
                    scale = self._baseline[side] if axis == "opening_normalized" else 1.
                    raw_axis = "opening" if axis == "opening_normalized" else axis
                    values = [row[side][raw_axis] / scale for row in rows[label]]
                    midpoint = median(values)
                    spread = _p90([abs(value - midpoint) for value in values])
                    constant = floor_multiplier * floor / scale
                    measured = 2.5 * spread
                    radius = max(constant, measured)
                    # A two-landmark difference underlies aperture, so its
                    # diagnostic pixel comparator has two source-pixel terms.
                    pixel_factor = 2. if axis == "opening_normalized" else 1.
                    pixel = floor_multiplier * _p90([pixel_factor / row[side]["width_pixels"] / scale
                                                     for row in rows[label]])
                    self._refs[label][side][axis] = {
                        "median": midpoint, "spread_p90": spread,
                        "constant_contribution": constant, "spread_contribution": measured,
                        "pixel_assumption_comparator_not_used": pixel,
                        "radius": radius, "low": midpoint - radius, "high": midpoint + radius,
                        "units": ("fraction_of_same_eye_CENTER_opening" if axis == "opening_normalized"
                                  else "eye_widths"),
                    }
        self._report["references"] = deepcopy(self._refs)
        for side in SIDES:
            for first, second in (("CENTER", "LEFT"), ("CENTER", "RIGHT"), ("LEFT", "RIGHT")):
                self._gate(first, second, side, "horizontal")
            self._gate("CENTER", "DOWN", side, "vertical", expected_sign=1.)
            self._gate("CENTER", "DOWN", side, "opening_normalized", expected_sign=-1.)
            center = self._refs["CENTER"][side]["horizontal"]["median"]
            left = self._refs["LEFT"][side]["horizontal"]["median"] - center
            right = self._refs["RIGHT"][side]["horizontal"]["median"] - center
            if left * right >= 0:
                self._report["failures"].append(f"{side}: LEFT and RIGHT must lie on opposite sides of CENTER")
        # Cross-eye polarity must agree, but no anatomical sign is hard-coded.
        if ((self._refs["LEFT"]["left"]["horizontal"]["median"]
             - self._refs["CENTER"]["left"]["horizontal"]["median"])
                * (self._refs["LEFT"]["right"]["horizontal"]["median"]
                   - self._refs["CENTER"]["right"]["horizontal"]["median"]) <= 0):
            self._report["failures"].append("eyes disagree about calibrated horizontal direction")
        heads = [row["head"] for label in TARGETS for row in rows[label]]
        self._head_range = tuple((min(row[i] for row in heads), max(row[i] for row in heads))
                                 for i in (0, 1))
        self._report["head_coverage_degrees"] = {
            axis: {"low": low * 60. - 10., "high": high * 60. + 10.}
            for axis, (low, high) in zip(("yaw", "pitch"), self._head_range)
        }
        self._ready = not self._report["failures"]
        self._report["fit_ready"] = self._ready

    def _gate(self, first, second, side, axis, expected_sign=None):
        a, b = self._refs[first][side][axis], self._refs[second][side][axis]
        delta = b["median"] - a["median"]
        constant = max(a["constant_contribution"], b["constant_contribution"])
        spread = max(a["spread_contribution"], b["spread_contribution"])
        required = max(constant, spread)
        sign_ok = expected_sign is None or delta * expected_sign > 0
        accepted = abs(delta) > required and sign_ok
        self._report["gates"].append({
            "pair": [first, second], "eye": side, "axis": axis,
            "signed_separation": delta, "separation": abs(delta),
            "constant_contribution": constant, "spread_contribution": spread,
            "pixel_assumption_comparator_not_used": max(a["pixel_assumption_comparator_not_used"],
                                                       b["pixel_assumption_comparator_not_used"]),
            "required": required, "dominant_term": "spread" if spread > constant else "constant",
            "expected_sign": expected_sign, "accepted": accepted, "units": a["units"],
        })
        if not accepted:
            self._report["failures"].append(f"{side} {first}/{second}: {axis} not repeatably separated in expected direction")

    @property
    def fit_report(self):
        return deepcopy(self._report)

    def predict(self, features, metadata, quality=1., rejection_reason=None):
        row, reason = _measurement(features, metadata, quality, rejection_reason)
        if reason:
            return "UNKNOWN", reason
        if not self._ready:
            return "UNKNOWN", "candidate_fit_rejected"
        for value, (low, high) in zip(row["head"], self._head_range):
            if not low - 10. / 60. <= value <= high + 10. / 60.:
                return "UNKNOWN", "head_pose_outside_reference_coverage"
        candidates = []
        for label in TARGETS:
            matches = True
            for side in SIDES:
                for axis in AXES:
                    value = (row[side]["opening"] / self._baseline[side]
                             if axis == "opening_normalized" else row[side][axis])
                    ref = self._refs[label][side][axis]
                    low, high = ref["low"], ref["high"]
                    if label == "DOWN" and axis == "horizontal":
                        # DOWN iris position need not reproduce incidental
                        # lateral movement: allow the finite CENTER/DOWN span.
                        center = self._refs["CENTER"][side][axis]
                        low, high = min(low, center["low"]), max(high, center["high"])
                    if not low <= value <= high:
                        matches = False
                    if label == "DOWN" and axis in ("vertical", "opening_normalized"):
                        center = self._refs["CENTER"][side][axis]["median"]
                        displacement = (value - center) / (ref["median"] - center)
                        # Iris AND aperture must each support the learned
                        # direction; closeness on another axis cannot rescue it.
                        if displacement < .5:
                            matches = False
            if matches:
                candidates.append(label)
        if len(candidates) > 1:
            return "UNKNOWN", "ambiguous_candidate_support"
        if not candidates:
            return "UNKNOWN", "outside_calibrated_joint_eye_support"
        return candidates[0], "within_calibrated_joint_eye_support"
