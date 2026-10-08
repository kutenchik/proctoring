"""Frozen, iris-only DEBUG screen-region candidate; never a production backend.

An empirical convex hull in each eye's iris feature plane represents the sampled
on-screen area. It is not a projection into physical screen coordinates. Within
fixation variation supplies uncertainty; intentional variation between targets
does not. Axis-specific off-screen evidence must clear the corresponding screen
boundary and remain in a bounded calibrated domain. Unsupported data is UNKNOWN.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
from statistics import median

from .settings import VisionConfig


PROTOCOL = "screen_region_training_v1"
STATUS = "DEBUG / UNVALIDATED"
SIDES = ("left", "right")
AXES = ("horizontal", "vertical")


def _number(value):
    return (float(value) if isinstance(value, (int, float))
            and not isinstance(value, bool) and math.isfinite(value) else None)


def _p90(values):
    return sorted(values)[max(0, math.ceil(.9 * len(values)) - 1)]


def _measurement(features, metadata, quality, rejection_reason):
    """Retain measurement admission without adding aperture membership rules."""
    if rejection_reason:
        return None, str(rejection_reason)[:200]
    if not isinstance(features, (list, tuple)) or len(features) != 4:
        return None, "missing_or_invalid_features"
    feature = tuple(_number(value) for value in features)
    if any(value is None for value in feature):
        return None, "missing_or_invalid_features"
    quality = _number(quality)
    if quality is None or quality < .45:
        return None, "insufficient_measurement_quality"
    eyes = metadata.get("eyes", {}) if isinstance(metadata, dict) else {}
    measured = {}
    for side in SIDES:
        eye = eyes.get(side) if isinstance(eyes, dict) else None
        if not isinstance(eye, dict) or eye.get("valid") is not True:
            return None, f"{side}_eye_unobservable"
        values = {axis: _number(eye.get(axis)) for axis in
                  (*AXES, "opening", "width_pixels")}
        if any(value is None for value in values.values()):
            return None, f"{side}_eye_missing_or_nonfinite_measurements"
        if not .10 <= values["opening"] <= .75:
            return None, f"{side}_eye_aperture_unobservable"
        if values["width_pixels"] < 8:
            return None, f"{side}_eye_source_region_too_small"
        if not (.02 <= values["horizontal"] <= .98 and .15 <= values["vertical"] <= .85):
            return None, f"{side}_iris_geometry_outside_eye"
        measured[side] = values
    if (abs(measured["left"]["horizontal"] - measured["right"]["horizontal"]) > .30
            or abs(measured["left"]["vertical"] - measured["right"]["vertical"]) > .18):
        return None, "eyes_disagree_unreliable_measurement"
    for index, axis in enumerate(AXES):
        if abs(sum(measured[side][axis] for side in SIDES) / 2 - feature[index]) > 1e-6:
            return None, "feature_metadata_mismatch"
    measured["head"] = feature[2:]
    return measured, None


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _hull(points):
    points = sorted(set(points))
    if len(points) < 3:
        return points
    lower, upper = [], []
    for point in points:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _inside(point, hull):
    return len(hull) >= 3 and all(_cross(a, hull[(index + 1) % len(hull)], point) >= -1e-12
                                for index, a in enumerate(hull))


class ScreenRegionCandidate:
    """Own fit and stateless decisions from an explicitly collected DEBUG set.

    Input snapshot has ``protocol``, ``target_definitions`` (id, role,
    expected_label, position{x_normalized,y_normalized}, optional anchor=start/
    end) and ``samples`` keyed by id with normal diagnostic numeric records.
    CENTER_START/CENTER_END are recognized as anchors without the optional flag.
    Held-out definitions/records never participate in fitting. Source matching,
    freshness and operator timing remain the existing collection layer's job;
    pass its failure as ``rejection_reason`` to obtain UNKNOWN.

    fit_ready permits DEBUG predictions only. It cannot enable exam start, change
    production calibration, or generate events. No confidence score is invented.
    """

    def __init__(self, snapshot: dict, config: VisionConfig):
        source = deepcopy(snapshot)
        self._ready = False
        self._refs, self._hulls, self._domain, self._gates = {}, {}, {}, {}
        self._head_range = ()
        constant = config.calibration_eye_noise_floor * config.calibration_min_signal_noise
        self._report = {
            "candidate": "per_eye_axis_aware_screen_region_v1", "status": STATUS,
            "fit_ready": False, "human_validation_status": "pending",
            "production_effects": "none; cannot enable exam or create events",
            "source_attempt_id": source.get("attempt_id"),
            "source_baseline_id": source.get("baseline_id"),
            "target_definitions": deepcopy(source.get("target_definitions", [])),
            "accepted_training_counts": {}, "excluded_training_reasons": {},
            "references": {}, "boundary_gates": [], "anchor_repeatability": [],
            "on_screen_hulls": {}, "operating_domain": {}, "failures": [],
            "assumptions": {
                "units": "all iris coordinates, spreads and margins are eye widths; head features are degrees / 60",
                "support_radius": "max(constant_floor * signal_noise_multiplier, 2.5 * within-target p90 absolute deviation)",
                "constant_floor_eye_widths": config.calibration_eye_noise_floor,
                "constant_floor_multiplier": config.calibration_min_signal_noise,
                "spread_multiplier": 2.5,
                "pixel_floor": "1/source_eye_width * signal_noise_multiplier reported for comparison only; not a measured optical error bound and not a fit term",
                "within_vs_between": "spreads computed within each fixation; target medians define intentional screen extent",
                "on_screen": "convex hull of per-target median +/- per-axis support radius; empirical interpolation, not physical screen coordinates",
                "boundary_gate": "nearest off-screen support must clear extreme on-screen support on the relevant learned signed axis; positive gap required",
                "uncertainty": "gap between extreme screen support and nearest off-screen support is UNKNOWN; support bounds are assumptions pending independent validation",
                "domain": "horizontal extent from on-screen and lateral targets; vertical upper extent only on-screen, lower extent extends to DOWN; no unlimited half-spaces",
                "head_pose": "training coverage plus 10 degrees is a veto only, never a direction",
                "aperture": "existing measurement validity only; no aperture classification/membership or learned openness references",
                "repeatability": "CENTER end displacement cannot exceed the larger within-target support radius on either iris axis; no drift correction",
                "limitations": "small within-window spread does not prove iris visibility or accuracy; empirical convexity, margins and between-fixation drift need held-out human validation",
            },
        }
        failures = self._report["failures"]
        if source.get("protocol") != PROTOCOL:
            failures.append("missing explicit multi-point screen-region training; legacy point calibration is insufficient")
            return
        definitions = source.get("target_definitions")
        if not isinstance(definitions, list):
            failures.append("missing target definitions")
            return
        training = [d for d in definitions if isinstance(d, dict)
                    and d.get("role") in ("on_screen_calibration", "off_screen_calibration")]
        identifiers = [d.get("id") for d in training]
        if any(not isinstance(key, str) or not key for key in identifiers) or len(set(identifiers)) != len(identifiers):
            failures.append("missing or duplicated training target identifiers")
            return
        on = [d for d in training if d["role"] == "on_screen_calibration"]
        off = [d for d in training if d["role"] == "off_screen_calibration"]
        if (any(d.get("expected_label") != "ON_SCREEN" for d in on)
                or any(d.get("expected_label") not in ("LEFT", "RIGHT", "DOWN") for d in off)):
            failures.append("training roles and expected labels disagree")
        anchors = {name: [d for d in on if d.get("anchor") == name or d["id"] == f"CENTER_{name.upper()}"]
                   for name in ("start", "end")}
        if any(len(items) != 1 for items in anchors.values()):
            failures.append("one CENTER_START and one CENTER_END anchor are required")
        positions = []
        for definition in on:
            position = definition.get("position", {})
            xy = tuple(_number(position.get(axis)) for axis in ("x_normalized", "y_normalized")) if isinstance(position, dict) else (None, None)
            if any(value is None or not 0 <= value <= 1 for value in xy):
                failures.append(f"{definition['id']}: actual normalized on-screen target position missing")
            else:
                positions.append((definition["id"], xy))
        if not failures:
            start, end = (anchors[name][0]["id"] for name in ("start", "end"))
            position_map = dict(positions)
            center = position_map[start]
            if position_map[end] != center:
                failures.append("repeated CENTER anchor must use the same physical on-screen position")
            for index, axis in enumerate(("horizontal", "vertical")):
                if not min(p[index] for _, p in positions) < center[index] < max(p[index] for _, p in positions):
                    failures.append(f"on-screen positions do not span both {axis} sides of CENTER")
            if len(set(p for _, p in positions)) < 5:
                failures.append("at least five distinct on-screen target positions are required")
        for label in ("LEFT", "RIGHT", "DOWN"):
            if not any(d.get("expected_label") == label for d in off):
                failures.append(f"missing operator-labeled off-screen {label}")
        if failures:
            return
        records = source.get("samples", {})
        rows = {}
        seen = set()
        for definition in training:
            target = definition["id"]
            rows[target], excluded = [], Counter()
            for record in records.get(target, []) if isinstance(records, dict) else []:
                if not isinstance(record, dict) or record.get("accepted") is not True:
                    excluded["not_admitted_by_collection"] += 1
                    continue
                timestamp = _number(record.get("timestamp"))
                if timestamp is None or timestamp in seen:
                    excluded["missing_or_duplicate_source_timestamp"] += 1
                    continue
                value, reason = _measurement(record.get("features"), record, record.get("quality"), record.get("rejection_reason"))
                if reason:
                    excluded[reason] += 1
                else:
                    seen.add(timestamp)
                    rows[target].append(value)
            self._report["accepted_training_counts"][target] = len(rows[target])
            self._report["excluded_training_reasons"][target] = dict(excluded)
            if len(rows[target]) < config.calibration_samples:
                failures.append(f"{target}: insufficient unique valid paired eye samples")
        if failures:
            return
        for target, measurements in rows.items():
            self._refs[target] = {}
            for side in SIDES:
                self._refs[target][side] = {}
                for axis in AXES:
                    values = [row[side][axis] for row in measurements]
                    mid = median(values)
                    spread = _p90([abs(value - mid) for value in values])
                    measured = 2.5 * spread
                    radius = max(constant, measured)
                    self._refs[target][side][axis] = {
                        "median": mid, "spread_p90": spread, "constant_contribution": constant,
                        "spread_contribution": measured, "radius": radius,
                        "dominant_term": "spread" if measured > constant else "constant",
                        "pixel_assumption_comparator_not_used": config.calibration_min_signal_noise * _p90([1 / row[side]["width_pixels"] for row in measurements]),
                        "low": mid - radius, "high": mid + radius, "units": "eye_widths",
                    }
                    if spread > config.calibration_max_spread:
                        failures.append(f"{target}/{side}/{axis}: excessive within-fixation instability")
        self._report["references"] = deepcopy(self._refs)
        start, end = (anchors[name][0]["id"] for name in ("start", "end"))
        for side in SIDES:
            for axis in AXES:
                a, b = self._refs[start][side][axis], self._refs[end][side][axis]
                delta, required = abs(a["median"] - b["median"]), max(a["radius"], b["radius"])
                accepted = delta <= required
                self._report["anchor_repeatability"].append({"eye": side, "axis": axis, "start": start, "end": end,
                    "absolute_change": delta, "allowed_change": required, "accepted": accepted, "units": "eye_widths"})
                if not accepted:
                    failures.append(f"{side}/{axis}: repeated CENTER baseline changed beyond within-fixation support")
        for side in SIDES:
            medians = [(self._refs[d["id"]][side]["horizontal"]["median"], self._refs[d["id"]][side]["vertical"]["median"]) for d in on]
            if len(_hull(medians)) < 3:
                failures.append(f"{side}: on-screen iris medians do not support a two-dimensional region")
            corners = []
            for d in on:
                ref = self._refs[d["id"]][side]
                corners.extend((h, v) for h in (ref["horizontal"]["low"], ref["horizontal"]["high"])
                               for v in (ref["vertical"]["low"], ref["vertical"]["high"]))
            self._hulls[side] = _hull(corners)
            self._gates[side] = {}
            center = {axis: (self._refs[start][side][axis]["median"] + self._refs[end][side][axis]["median"]) / 2 for axis in AXES}
            for label in ("LEFT", "RIGHT", "DOWN"):
                axis = "vertical" if label == "DOWN" else "horizontal"
                definitions_for_label = [d for d in off if d["expected_label"] == label]
                deltas = [self._refs[d["id"]][side][axis]["median"] - center[axis] for d in definitions_for_label]
                sign = 1 if deltas[0] > 0 else -1
                if any(delta * sign <= 0 for delta in deltas):
                    failures.append(f"{side}/{label}: off-screen fixations disagree about direction convention")
                screen_outer = max(sign * self._refs[d["id"]][side][axis]["median"] + self._refs[d["id"]][side][axis]["radius"] for d in on)
                off_inner = min(sign * self._refs[d["id"]][side][axis]["median"] - self._refs[d["id"]][side][axis]["radius"] for d in definitions_for_label)
                off_outer = max(sign * self._refs[d["id"]][side][axis]["median"] + self._refs[d["id"]][side][axis]["radius"] for d in definitions_for_label)
                gap = off_inner - screen_outer
                boundary = [d["id"] for d in on if math.isclose(sign * self._refs[d["id"]][side][axis]["median"] + self._refs[d["id"]][side][axis]["radius"], screen_outer, abs_tol=1e-9)]
                gate = {"eye": side, "label": label, "axis": axis, "learned_sign": sign,
                        "screen_boundary_target_ids": boundary, "off_screen_target_ids": [d["id"] for d in definitions_for_label],
                        "screen_outer_signed": screen_outer, "off_inner_signed": off_inner,
                        "off_outer_signed": off_outer, "uncertainty_gap": gap,
                        "accepted": gap > 0, "units": "eye_widths"}
                self._gates[side][label] = gate
                self._report["boundary_gates"].append(deepcopy(gate))
                if gap <= 0:
                    failures.append(f"{side}/{label}: relevant on-screen boundary and off-screen support overlap")
            if self._gates[side]["LEFT"]["learned_sign"] == self._gates[side]["RIGHT"]["learned_sign"]:
                failures.append(f"{side}: LEFT and RIGHT must be on opposite horizontal sides of CENTER")
            horizontal_defs = on + [d for d in off if d["expected_label"] in ("LEFT", "RIGHT")]
            h_low = min(self._refs[d["id"]][side]["horizontal"]["low"] for d in horizontal_defs)
            h_high = max(self._refs[d["id"]][side]["horizontal"]["high"] for d in horizontal_defs)
            v_low = min(self._refs[d["id"]][side]["vertical"]["low"] for d in on)
            v_high = max(self._refs[d["id"]][side]["vertical"]["high"] for d in on)
            down = self._gates[side]["DOWN"]
            if down["learned_sign"] == 1:
                v_high = down["off_outer_signed"]
            else:
                v_low = -down["off_outer_signed"]
            self._domain[side] = {"horizontal": (h_low, h_high), "vertical": (v_low, v_high)}
        for label in ("LEFT", "RIGHT", "DOWN"):
            if self._gates["left"][label]["learned_sign"] != self._gates["right"][label]["learned_sign"]:
                failures.append(f"eyes disagree about learned {label} convention")
        self._report["on_screen_hulls"] = deepcopy(self._hulls)
        self._report["operating_domain"] = deepcopy(self._domain)
        # Fit acceptance must describe this classifier's actual support. A
        # nominal LEFT fixation with unsupported upper gaze must not approve a
        # model that then rejects its own LEFT reference. This is a consistency
        # check, never a held-out accuracy estimate.
        self._report["training_reference_support"] = []
        for definition in training:
            for side in SIDES:
                ref = self._refs[definition["id"]][side]
                label, reason = self._decide_eye(side, ref["horizontal"]["median"], ref["vertical"]["median"])
                accepted = label == definition["expected_label"]
                self._report["training_reference_support"].append({
                    "target_id": definition["id"], "eye": side,
                    "expected": definition["expected_label"], "predicted": label,
                    "reason": reason, "accepted": accepted,
                })
                if not accepted:
                    failures.append(f"{definition['id']}/{side}: reference lacks unambiguous support within operating domain")
        heads = [row["head"] for measurements in rows.values() for row in measurements]
        self._head_range = tuple((min(row[i] for row in heads) - 10 / 60,
                                  max(row[i] for row in heads) + 10 / 60) for i in (0, 1))
        self._report["head_coverage_degrees"] = {axis: {"low": low * 60, "high": high * 60}
                                                 for axis, (low, high) in zip(("yaw", "pitch"), self._head_range)}
        self._ready = not failures
        self._report["fit_ready"] = self._ready

    @property
    def fit_report(self):
        return deepcopy(self._report)

    def _decide_eye(self, side, h, v):
        if any(not low <= value <= high for value, (low, high) in
               zip((h, v), (self._domain[side][axis] for axis in AXES))):
            return "UNKNOWN", "outside_calibrated_operating_domain"
        matches = ["ON_SCREEN"] if _inside((h, v), self._hulls[side]) else []
        for label, gate in self._gates[side].items():
            value = (v if gate["axis"] == "vertical" else h) * gate["learned_sign"]
            if gate["off_inner_signed"] <= value <= gate["off_outer_signed"]:
                matches.append(label)
        if len(matches) > 1:
            return "UNKNOWN", "overlapping_directional_support"
        if not matches:
            return "UNKNOWN", "uncertainty_band_or_unsupported_region"
        return matches[0], ("within_calibrated_screen_region" if matches[0] == "ON_SCREEN"
                            else "beyond_learned_relevant_screen_boundary")

    def predict(self, features, metadata, quality=1., rejection_reason=None):
        row, reason = _measurement(features, metadata, quality, rejection_reason)
        if reason:
            return "UNKNOWN", reason
        if not self._ready:
            return "UNKNOWN", "screen_region_fit_rejected"
        if any(not low <= value <= high for value, (low, high) in zip(row["head"], self._head_range)):
            return "UNKNOWN", "head_pose_outside_reference_coverage"
        labels = []
        for side in SIDES:
            h, v = (row[side][axis] for axis in AXES)
            label, reason = self._decide_eye(side, h, v)
            if label == "UNKNOWN":
                return label, reason
            labels.append(label)
        if labels[0] != labels[1]:
            return "UNKNOWN", "eyes_disagree_about_supported_region"
        return labels[0], ("within_calibrated_screen_region" if labels[0] == "ON_SCREEN"
                           else "beyond_learned_relevant_screen_boundary")
