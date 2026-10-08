"""A guarded aperture supplement to already-fitted session iris references.

This is not an eye-closure detector or evidence that iris landmarks are optically
correct. Aperture can support calibrated vertical displacement; it cannot supply
a direction without valid iris measurements. The caller still owns freshness,
calibration acceptance, and the existing head-pose veto.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Mapping

from .types import FaceMeasurement, GazeDirection


@dataclass(frozen=True)
class ApertureEyeReference:
    center_horizontal: float
    center_vertical: float
    center_opening: float
    down_horizontal: float | None = None
    down_vertical: float | None = None


@dataclass(frozen=True)
class ApertureReferences:
    left: ApertureEyeReference
    right: ApertureEyeReference


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_eye(eye: Mapping) -> bool:
    # Keep FaceAnalyzer's admission intact. In particular, the new absolute
    # closure guard at .08 does not relax the existing .10 aperture requirement.
    return (eye.get("valid") is True
            and all(_finite(eye.get(key)) for key in
                    ("horizontal", "vertical", "opening", "width_pixels"))
            and .10 <= eye["opening"] <= .75
            and eye["width_pixels"] >= 8.
            and .02 <= eye["horizontal"] <= .98
            and .15 <= eye["vertical"] <= .85)


def _paired_record(record: Mapping) -> bool:
    features = record.get("features")
    quality = record.get("quality")
    eyes = record.get("eyes")
    if (record.get("accepted") is not True or record.get("rejection_reason")
            or not isinstance(features, (list, tuple)) or len(features) != 4
            or not all(_finite(value) for value in features)
            or not _finite(quality) or quality < .45
            or not isinstance(eyes, Mapping)):
        return False
    for side in ("left", "right"):
        if not isinstance(eyes.get(side), Mapping) or not _valid_eye(eyes[side]):
            return False
    return all(abs((eyes["left"][axis] + eyes["right"][axis]) / 2 - features[index]) <= 1e-6
               for index, axis in enumerate(("horizontal", "vertical")))


def derive_aperture_references(records: Mapping, required_samples: int = 1) -> ApertureReferences | None:
    """Use only accepted paired measurements from this fitted attempt.

    CENTER alone is enough to retain the relative closure guard. Missing DOWN
    metadata disables aperture assistance rather than inventing a reference.
    Nothing is carried between baselines or inferred from head measurements.
    """
    if required_samples < 1:
        raise ValueError("required_samples must be positive")
    rows = {label: [record for record in records.get(label, [])
                    if isinstance(record, Mapping) and _paired_record(record)]
            for label in ("CENTER", "DOWN")}
    if len(rows["CENTER"]) < required_samples:
        return None
    result = []
    for side in ("left", "right"):
        center = [row["eyes"][side] for row in rows["CENTER"]]
        down = ([row["eyes"][side] for row in rows["DOWN"]]
                if len(rows["DOWN"]) >= required_samples else [])
        result.append(ApertureEyeReference(
            center_horizontal=median(row["horizontal"] for row in center),
            center_vertical=median(row["vertical"] for row in center),
            center_opening=median(row["opening"] for row in center),
            down_horizontal=median(row["horizontal"] for row in down) if down else None,
            down_vertical=median(row["vertical"] for row in down) if down else None,
        ))
    return ApertureReferences(*result)


def aperture_guard(features, centers, radii, references: ApertureReferences | None,
                   face: FaceMeasurement):
    """Return an override ``(direction, None, reason)`` or defer to iris cores.

    Ratios are per eye and use the same eye's CENTER opening. Both eyes must
    support a DOWN supplement. All intervals are finite in eye-width units;
    the sign of vertical movement comes from the session, not an image-axis
    assumption. ``None`` scores deliberately make no confidence claim.
    """
    unknown = lambda reason: (GazeDirection.UNKNOWN, None, reason)
    if not face.face_present:
        return unknown("face_unavailable")
    diagnostics = face.diagnostics
    if diagnostics is None:
        return unknown("eye_measurements_unavailable")
    eyes = (diagnostics.left_eye, diagnostics.right_eye)
    refs = (references.left, references.right) if references is not None else (None, None)
    # Closure veto precedes iris validity, so even an erroneously valid landmark
    # result or an absent feature vector cannot turn a closure into a direction.
    for eye, ref in zip(eyes, refs):
        if _finite(eye.opening) and eye.opening < .08:
            return unknown("absolute_eye_closure_guard")
        if (ref is not None and _finite(eye.opening)
                and eye.opening / ref.center_opening < .35):
            return unknown("relative_eye_closure_guard")
    if references is None:
        return unknown("calibration_aperture_reference_missing")
    if not diagnostics.valid:
        return unknown("eye_measurements_unavailable")
    if (features is None or len(features) != 4 or not all(_finite(value) for value in features)
            or not _finite(face.quality) or face.quality < .45):
        return unknown("invalid_or_low_quality_eye_measurements")
    for side, eye in zip(("left", "right"), eyes):
        if not _valid_eye(vars(eye)):
            return unknown(f"{side}_eye_unobservable")
    if any(abs((getattr(eyes[0], axis) + getattr(eyes[1], axis)) / 2
               - features[index]) > 1e-6
           for index, axis in enumerate(("horizontal", "vertical"))):
        return unknown("feature_metadata_mismatch")
    if any(ref.down_vertical is None or ref.down_horizontal is None for ref in refs):
        return unknown("calibration_down_aperture_reference_missing")
    center_radius, down_radius = radii.get("CENTER"), radii.get("DOWN")
    if (not _finite(center_radius) or not _finite(down_radius)
            or center_radius <= 0 or down_radius <= 0
            or "CENTER" not in centers or "DOWN" not in centers):
        return unknown("calibrated_iris_support_missing")

    relative_openings = [eye.opening / ref.center_opening for eye, ref in zip(eyes, refs)]
    down_supported = []
    center_supported = []
    for eye, ref in zip(eyes, refs):
        delta = ref.down_vertical - ref.center_vertical
        if abs(delta) <= 1e-9:
            return unknown("calibrated_vertical_displacement_missing")
        signed_shift = math.copysign(1., delta) * (eye.vertical - ref.center_vertical)
        vertical_separation = abs(delta)
        low_horizontal, high_horizontal = sorted((ref.center_horizontal, ref.down_horizontal))
        down_supported.append(
            .35 * vertical_separation <= signed_shift <= vertical_separation + down_radius
            and low_horizontal - down_radius <= eye.horizontal <= high_horizontal + down_radius)
        center_supported.append(
            -center_radius <= signed_shift < .35 * vertical_separation
            and abs(eye.horizontal - ref.center_horizontal) <= center_radius)
    if all(down_supported) and all(value < .70 for value in relative_openings):
        return GazeDirection.DOWN, None, "guarded_aperture_and_vertical_iris_shift"
    if all(center_supported) and all(.40 <= value <= .70 for value in relative_openings):
        return GazeDirection.CENTER, None, "squint_with_calibrated_center_iris_support"
    return None
