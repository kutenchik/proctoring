"""Synthetic mechanics, not evidence of human gaze accuracy."""
from copy import deepcopy
from dataclasses import replace
import json
import math

import pytest

from proctoring.vision.screen_region import PROTOCOL, ScreenRegionCandidate
from proctoring.vision.settings import VisionConfig


CONFIG = replace(VisionConfig(), calibration_samples=3)
TARGETS = {
    "CENTER_START": ((.5, .5), (.5, .45), "ON_SCREEN"),
    "SCREEN_LEFT": ((.1, .5), (.60, .45), "ON_SCREEN"),
    "SCREEN_RIGHT": ((.9, .5), (.40, .45), "ON_SCREEN"),
    "SCREEN_UPPER": ((.5, .1), (.5, .35), "ON_SCREEN"),
    "SCREEN_LOWER": ((.5, .9), (.5, .55), "ON_SCREEN"),
    "OFF_LEFT": (None, (.76, .45), "LEFT"),
    "OFF_RIGHT": (None, (.24, .45), "RIGHT"),
    "OFF_DOWN": (None, (.5, .72), "DOWN"),
    "CENTER_END": ((.5, .5), (.5, .45), "ON_SCREEN"),
}


def measurement(h=.5, v=.45, *, opening=.32, width=35., timestamp=1.):
    return {"timestamp": timestamp, "features": [h, v, 0., 0.], "quality": 1.,
            "accepted": True, "rejection_reason": None,
            "eyes": {side: {"horizontal": h, "vertical": v, "opening": opening,
                             "valid": True, "width_pixels": width, "reason": ""}
                     for side in ("left", "right")}}


def attempt():
    definitions, samples = [], {}
    for index, (target, (position, point, label)) in enumerate(TARGETS.items()):
        definition = {"id": target, "expected_label": label,
                      "role": "on_screen_calibration" if position else "off_screen_calibration"}
        if position:
            definition["position"] = dict(zip(("x_normalized", "y_normalized"), position))
        definitions.append(definition)
        samples[target] = [measurement(*point, timestamp=index * 10 + i) for i in range(CONFIG.calibration_samples)]
    return {"protocol": PROTOCOL, "attempt_id": "example/1", "baseline_id": "example",
            "target_definitions": definitions, "samples": samples,
            "diagnostics": {"ready": False}}


def predict(candidate, row):
    return candidate.predict(row["features"], row, row["quality"], row["rejection_reason"])


def move_target(source, target, *, h=None, v=None, side=None):
    for row in source["samples"][target]:
        for name in ((side,) if side else ("left", "right")):
            if h is not None:
                row["eyes"][name]["horizontal"] = h
            if v is not None:
                row["eyes"][name]["vertical"] = v
        row["features"][:2] = [sum(eye[axis] for eye in row["eyes"].values()) / 2
                                for axis in ("horizontal", "vertical")]


@pytest.mark.parametrize("target", TARGETS)
def test_positive_training_support_has_own_fit_without_production_permission(target):
    source = attempt()
    before = deepcopy(source)
    candidate = ScreenRegionCandidate(source, CONFIG)
    assert candidate.fit_report["fit_ready"], candidate.fit_report["failures"]
    _, point, label = TARGETS[target]
    assert predict(candidate, measurement(*point))[0] == label
    assert source == before
    assert source["diagnostics"]["ready"] is False
    assert candidate.fit_report["status"] == "DEBUG / UNVALIDATED"
    assert candidate.fit_report["human_validation_status"] == "pending"
    assert "cannot enable exam" in candidate.fit_report["production_effects"]


def test_old_four_target_snapshot_cannot_invent_screen_boundaries_from_validation():
    legacy = {"samples": {"CENTER": [measurement()] * 100},
              "validation": {"READING": [measurement(.4, .52)] * 100}, "ready": True}
    candidate = ScreenRegionCandidate(legacy, CONFIG)
    assert not candidate.fit_report["fit_ready"]
    assert "legacy" in candidate.fit_report["failures"][0]
    assert predict(candidate, measurement()) == ("UNKNOWN", "screen_region_fit_rejected")


def test_spread_is_within_target_not_intentional_span_between_screen_targets():
    report = ScreenRegionCandidate(attempt(), CONFIG).fit_report
    refs = report["references"]
    assert refs["SCREEN_LEFT"]["left"]["horizontal"]["median"] - refs["SCREEN_RIGHT"]["left"]["horizontal"]["median"] == pytest.approx(.2)
    for target in refs.values():
        for eye in target.values():
            for axis in eye.values():
                assert axis["spread_p90"] == 0
                assert axis["radius"] == pytest.approx(.03)
                assert axis["units"] == "eye_widths"
                assert axis["pixel_assumption_comparator_not_used"] == pytest.approx(3 / 35)


def test_boundary_gate_compares_lower_screen_not_only_center_to_down():
    report = ScreenRegionCandidate(attempt(), CONFIG).fit_report
    down = next(g for g in report["boundary_gates"] if g["eye"] == "left" and g["label"] == "DOWN")
    assert down["axis"] == "vertical"
    assert down["screen_boundary_target_ids"] == ["SCREEN_LOWER"]
    assert down["screen_outer_signed"] == pytest.approx(.58)
    assert down["off_inner_signed"] == pytest.approx(.69)
    assert down["uncertainty_gap"] == pytest.approx(.11)
    assert down["accepted"]


@pytest.mark.parametrize("label,point", [("LEFT", (.76, .55)), ("RIGHT", (.24, .35)), ("DOWN", (.40, .72))])
def test_irrelevant_axis_is_not_restricted_to_narrow_target_core(label, point):
    assert predict(ScreenRegionCandidate(attempt(), CONFIG), measurement(*point))[0] == label


def test_inside_feature_rectangle_without_convex_screen_support_is_unknown():
    # Cross-shaped targets form an expanded diamond; (.61,.56) is inside its
    # bounding rectangle but beyond the sampled convex support.
    candidate = ScreenRegionCandidate(attempt(), CONFIG)
    assert predict(candidate, measurement(.61, .56)) == ("UNKNOWN", "uncertainty_band_or_unsupported_region")
    assert predict(candidate, measurement(.54, .49))[0] == "ON_SCREEN"


@pytest.mark.parametrize("point", [(.67, .45), (.33, .45), (.5, .63)])
def test_explicit_boundary_uncertainty_band_does_not_fall_back_to_center(point):
    assert predict(ScreenRegionCandidate(attempt(), CONFIG), measurement(*point)) == (
        "UNKNOWN", "uncertainty_band_or_unsupported_region")


@pytest.mark.parametrize("point", [(.5, .20), (.90, .45), (.1, .45), (.5, .80)])
def test_uncalibrated_up_and_directions_beyond_operating_domain_are_unknown(point):
    assert predict(ScreenRegionCandidate(attempt(), CONFIG), measurement(*point)) == (
        "UNKNOWN", "outside_calibrated_operating_domain")


def test_horizontal_offscreen_target_cannot_extend_upper_domain():
    source = attempt()
    move_target(source, "OFF_LEFT", v=.20)
    candidate = ScreenRegionCandidate(source, CONFIG)
    assert not candidate.fit_report["fit_ready"]
    # Lateral gate stays horizontal, but UP is unsupported even when incidentally
    # present in a single operator LEFT sample set.
    assert predict(candidate, measurement(.76, .20))[0] == "UNKNOWN"
    assert any(row["target_id"] == "OFF_LEFT" and row["reason"] == "outside_calibrated_operating_domain"
               for row in candidate.fit_report["training_reference_support"])


def test_diagonal_overlapping_direction_support_is_unknown():
    candidate = ScreenRegionCandidate(attempt(), CONFIG)
    assert predict(candidate, measurement(.76, .72)) == ("UNKNOWN", "overlapping_directional_support")


def test_eyes_must_agree_on_region_in_addition_to_basic_geometry():
    row = measurement(.68, .45)
    row["eyes"]["left"]["horizontal"] = .76
    row["eyes"]["right"]["horizontal"] = .60
    assert predict(ScreenRegionCandidate(attempt(), CONFIG), row) == (
        "UNKNOWN", "eyes_disagree_about_supported_region")


def test_both_mirroring_and_vertical_conventions_are_learned_from_labels():
    source = attempt()
    for rows in source["samples"].values():
        for row in rows:
            for eye in row["eyes"].values():
                eye["horizontal"] = 1 - eye["horizontal"]
                eye["vertical"] = 1 - eye["vertical"]
            row["features"][:2] = [1 - row["features"][0], 1 - row["features"][1]]
    candidate = ScreenRegionCandidate(source, CONFIG)
    assert candidate.fit_report["fit_ready"]
    assert predict(candidate, measurement(.24, .55))[0] == "LEFT"
    assert predict(candidate, measurement(.76, .55))[0] == "RIGHT"
    assert predict(candidate, measurement(.5, .28))[0] == "DOWN"
    assert predict(candidate, measurement(.5, .80))[0] == "UNKNOWN"  # uncalibrated UP


def test_no_aperture_membership_is_added_for_screen_or_directions():
    candidate = ScreenRegionCandidate(attempt(), CONFIG)
    for aperture in (.101, .2, .32, .60):
        for point, label in (((.5, .45), "ON_SCREEN"), ((.76, .45), "LEFT"),
                             ((.24, .45), "RIGHT"), ((.5, .72), "DOWN")):
            assert predict(candidate, measurement(*point, opening=aperture))[0] == label


@pytest.mark.parametrize("aperture", [0., .099, .751])
def test_invalid_aperture_does_not_become_down_or_reuse_last_decision(aperture):
    candidate = ScreenRegionCandidate(attempt(), CONFIG)
    assert predict(candidate, measurement(.5, .72))[0] == "DOWN"
    assert predict(candidate, measurement(.5, .72, opening=aperture)) == ("UNKNOWN", "left_eye_aperture_unobservable")


@pytest.mark.parametrize("field,value", [("vertical", math.nan), ("opening", None),
                                         ("width_pixels", 7.), ("horizontal", .99)])
def test_invalid_eye_metadata_returns_unknown(field, value):
    row = measurement(.5, .72)
    row["eyes"]["right"][field] = value
    assert predict(ScreenRegionCandidate(attempt(), CONFIG), row)[0] == "UNKNOWN"


@pytest.mark.parametrize("reason", ["stale_measurement", "camera_unhealthy", "iris_unobservable", "closure"])
def test_upstream_invalidity_is_not_overridden(reason):
    row = measurement(.5, .72)
    row["rejection_reason"] = reason
    assert predict(ScreenRegionCandidate(attempt(), CONFIG), row) == ("UNKNOWN", reason)


def test_head_pose_is_only_an_operating_coverage_veto():
    candidate = ScreenRegionCandidate(attempt(), CONFIG)
    row = measurement()
    row["features"][3] = .15
    assert predict(candidate, row)[0] == "ON_SCREEN"
    row["features"][3] = .30
    assert predict(candidate, row) == ("UNKNOWN", "head_pose_outside_reference_coverage")


def test_aperture_cannot_rescue_nonfinite_head_or_feature_metadata_mismatch():
    candidate = ScreenRegionCandidate(attempt(), CONFIG)
    row = measurement()
    row["features"][3] = math.nan
    assert predict(candidate, row)[0] == "UNKNOWN"
    row = measurement()
    row["features"][0] = .72
    assert predict(candidate, row) == ("UNKNOWN", "feature_metadata_mismatch")


def test_lower_screen_overlap_rejects_fit_even_when_center_down_well_separated():
    source = attempt()
    move_target(source, "OFF_DOWN", v=.59)
    candidate = ScreenRegionCandidate(source, CONFIG)
    assert not candidate.fit_report["fit_ready"]
    assert any("boundary and off-screen support overlap" in message for message in candidate.fit_report["failures"])
    assert predict(candidate, measurement(.5, .59)) == ("UNKNOWN", "screen_region_fit_rejected")


def test_repeated_center_drift_is_reported_and_not_silently_corrected():
    source = attempt()
    move_target(source, "CENTER_END", h=.54)
    candidate = ScreenRegionCandidate(source, CONFIG)
    assert not candidate.fit_report["fit_ready"]
    anchor = candidate.fit_report["anchor_repeatability"][0]
    assert anchor["absolute_change"] == pytest.approx(.04)
    assert anchor["allowed_change"] == pytest.approx(.03)
    assert not anchor["accepted"]


def test_unstable_within_fixation_measurement_expands_uncertainty_and_rejects_overlap():
    source = attempt()
    for row, v in zip(source["samples"]["SCREEN_LOWER"], (.50, .55, .65)):
        row["features"][1] = v
        for eye in row["eyes"].values():
            eye["vertical"] = v
    report = ScreenRegionCandidate(source, CONFIG).fit_report
    assert not report["fit_ready"]
    assert report["references"]["SCREEN_LOWER"]["left"]["vertical"]["dominant_term"] == "spread"


@pytest.mark.parametrize("target", ["CENTER_END", "SCREEN_LOWER", "OFF_LEFT"])
def test_missing_required_target_cannot_fit(target):
    source = attempt()
    source["target_definitions"] = [d for d in source["target_definitions"] if d["id"] != target]
    assert not ScreenRegionCandidate(source, CONFIG).fit_report["fit_ready"]


def test_held_out_rows_never_supply_missing_training_data_or_change_fit():
    source = attempt()
    baseline = ScreenRegionCandidate(source, CONFIG).fit_report
    source["target_definitions"].append({"id": "VALIDATION", "role": "held_out_validation", "expected_label": "DOWN"})
    source["samples"]["VALIDATION"] = [measurement(.1, .2, timestamp=500.)]
    report = ScreenRegionCandidate(source, CONFIG).fit_report
    report.pop("target_definitions")
    baseline.pop("target_definitions")
    assert report == baseline


def test_source_timestamp_duplicates_cannot_manufacture_accepted_sample_count():
    source = attempt()
    source["samples"]["OFF_DOWN"][2]["timestamp"] = source["samples"]["OFF_DOWN"][1]["timestamp"]
    report = ScreenRegionCandidate(source, CONFIG).fit_report
    assert not report["fit_ready"]
    assert report["accepted_training_counts"]["OFF_DOWN"] == 2
    assert report["excluded_training_reasons"]["OFF_DOWN"] == {"missing_or_duplicate_source_timestamp": 1}


def test_measured_target_positions_are_required_instead_of_guessed_boundaries():
    source = attempt()
    source["target_definitions"][1].pop("position")
    report = ScreenRegionCandidate(source, CONFIG).fit_report
    assert not report["fit_ready"]
    assert "actual normalized" in report["failures"][0]


def test_same_axis_conventions_or_missing_two_dimensional_support_reject_fit():
    source = attempt()
    move_target(source, "OFF_RIGHT", h=.76)
    assert not ScreenRegionCandidate(source, CONFIG).fit_report["fit_ready"]
    source = attempt()
    for target, (position, _, _) in TARGETS.items():
        if position:
            move_target(source, target, v=.45)
    assert not ScreenRegionCandidate(source, CONFIG).fit_report["fit_ready"]


def test_config_noise_assumptions_are_used_without_tuning_to_validation():
    report = ScreenRegionCandidate(attempt(), replace(CONFIG, calibration_min_signal_noise=4.)).fit_report
    ref = report["references"]["OFF_DOWN"]["left"]["vertical"]
    assert ref["constant_contribution"] == .04
    assert ref["pixel_assumption_comparator_not_used"] == pytest.approx(4 / 35)


def test_input_and_report_are_frozen_and_json_finite():
    source = attempt()
    candidate = ScreenRegionCandidate(source, CONFIG)
    saved = deepcopy(candidate.fit_report)
    source["samples"]["OFF_DOWN"].clear()
    candidate.fit_report["references"].clear()
    assert candidate.fit_report == saved
    assert predict(candidate, measurement(.5, .72))[0] == "DOWN"
    json.dumps(candidate.fit_report, allow_nan=False)
