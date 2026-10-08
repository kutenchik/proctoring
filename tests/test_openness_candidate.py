"""Synthetic mechanics only; these tests do not establish human gaze accuracy."""
from copy import deepcopy
from dataclasses import replace
import json
import math

import pytest

from proctoring.vision.openness_candidate import OpennessCandidate
from proctoring.vision.settings import VisionConfig


CONFIG = replace(VisionConfig(), calibration_samples=3)
REFERENCE = {
    "CENTER": (.50, .45, .32, .40),
    "LEFT": (.65, .45, .34, .42),
    "RIGHT": (.35, .45, .33, .41),
    "DOWN": (.51, .52, .20, .25),
}


def measurement(label="CENTER", *, horizontal=None, vertical=None, opening=None):
    h, v, left_open, right_open = REFERENCE[label]
    h = h if horizontal is None else horizontal
    v = v if vertical is None else vertical
    openings = (left_open, right_open) if opening is None else opening
    return {
        "features": [h, v, 0., 0.], "quality": 1., "accepted": True,
        "rejection_reason": None,
        "eyes": {
            side: {"horizontal": h, "vertical": v, "opening": aperture,
                   "width_pixels": 40., "valid": True, "reason": ""}
            for side, aperture in zip(("left", "right"), openings)
        },
    }


def attempt(ready=False):
    return {
        "diagnostics": {"ready": ready},
        "samples": {label: [dict(measurement(label), timestamp=float(index))
                            for index in range(CONFIG.calibration_samples)]
                    for label in REFERENCE},
    }


def predict(candidate, row):
    return candidate.predict(row["features"], row, row["quality"], row["rejection_reason"])


@pytest.mark.parametrize("label", REFERENCE)
def test_learned_joint_references_predict_without_production_permission(label):
    source = attempt(False)
    candidate = OpennessCandidate(source, CONFIG)
    assert candidate.fit_report["fit_ready"]
    assert predict(candidate, measurement(label)) == (label, "within_calibrated_joint_eye_support")
    assert source == attempt(False)
    report = candidate.fit_report
    assert report["status"] == "DEBUG / UNVALIDATED"
    assert report["human_validation_status"] == "pending"
    assert "cannot enable exam" in report["production_effects"]
    assert "confidence" not in json.dumps(report)


def test_opening_is_per_eye_center_normalized_and_every_term_uses_same_units():
    report = OpennessCandidate(attempt(), CONFIG).fit_report
    assert report["center_opening_baselines"] == {"left": .32, "right": .40}
    for side, baseline in (("left", .32), ("right", .40)):
        down = report["references"]["DOWN"][side]["opening_normalized"]
        assert down["median"] == pytest.approx(.625)
        assert down["constant_contribution"] == pytest.approx(.03 / baseline)
        assert down["pixel_assumption_comparator_not_used"] == pytest.approx(3 * 2 / 40 / baseline)
        gate = next(g for g in report["gates"] if g["eye"] == side and g["axis"] == "opening_normalized")
        assert gate["separation"] == pytest.approx(.375)
        assert gate["required"] == pytest.approx(.03 / baseline)
        assert gate["units"] == down["units"] == "fraction_of_same_eye_CENTER_opening"
    iris = report["references"]["DOWN"]["left"]["vertical"]
    assert iris["median"] == .52
    assert iris["constant_contribution"] == .03
    assert iris["units"] == "eye_widths"


def test_existing_config_noise_multiplier_is_honored_without_new_tuning_knob():
    config = replace(CONFIG, calibration_min_signal_noise=4.)
    report = OpennessCandidate(attempt(), config).fit_report
    assert report["assumptions"]["constant_floor_multiplier"] == 4.
    ref = report["references"]["DOWN"]["left"]["vertical"]
    assert ref["constant_contribution"] == .04
    assert ref["pixel_assumption_comparator_not_used"] == .1


def test_aperture_support_is_not_a_universal_down_cutoff():
    low_baseline = attempt()
    for rows in low_baseline["samples"].values():
        for row in rows:
            for eye in row["eyes"].values():
                eye["opening"] *= .8
    normal = OpennessCandidate(attempt(), CONFIG)
    scaled = OpennessCandidate(low_baseline, CONFIG)
    assert scaled.fit_report["fit_ready"]
    assert normal.fit_report["center_opening_baselines"] != scaled.fit_report["center_opening_baselines"]
    for side in ("left", "right"):
        assert normal.fit_report["references"]["DOWN"][side]["opening_normalized"]["median"] == pytest.approx(
            scaled.fit_report["references"]["DOWN"][side]["opening_normalized"]["median"])


def test_squint_with_center_iris_is_unknown_not_down_or_center():
    row = measurement("CENTER", opening=(.20, .25))
    assert predict(OpennessCandidate(attempt(), CONFIG), row)[0] == "UNKNOWN"


def test_down_iris_without_supporting_aperture_is_unknown():
    row = measurement("DOWN", opening=(.32, .40))
    assert predict(OpennessCandidate(attempt(), CONFIG), row)[0] == "UNKNOWN"


def test_either_eye_without_vertical_support_prevents_down():
    row = measurement("DOWN")
    row["eyes"]["left"]["vertical"] = .45
    row["features"][1] = (.45 + .52) / 2
    assert predict(OpennessCandidate(attempt(), CONFIG), row)[0] == "UNKNOWN"


@pytest.mark.parametrize("aperture", [.0, .08, .099, .11])
def test_closure_and_untrained_extreme_narrowing_cannot_become_down(aperture):
    candidate = OpennessCandidate(attempt(), CONFIG)
    row = measurement("DOWN", opening=(aperture, aperture))
    # Even erroneously nominal iris coordinates/valid flags cannot rescue
    # closure; repeated calls also cannot reuse the preceding DOWN decision.
    assert predict(candidate, measurement("DOWN"))[0] == "DOWN"
    for _ in range(10):
        assert predict(candidate, row)[0] == "UNKNOWN"


def test_unobservable_eye_is_unknown_even_with_down_iris_and_opening_numbers():
    row = measurement("DOWN")
    row["eyes"]["left"]["valid"] = False
    assert predict(OpennessCandidate(attempt(), CONFIG), row) == ("UNKNOWN", "left_eye_unobservable")


def test_external_blink_rejection_is_not_overridden_by_candidate_direction():
    row = measurement("DOWN")
    row["rejection_reason"] = "operator_confirmed_closure"
    assert predict(OpennessCandidate(attempt(), CONFIG), row) == ("UNKNOWN", "operator_confirmed_closure")


@pytest.mark.parametrize("field,value", [("vertical", math.nan), ("opening", None),
                                         ("horizontal", math.inf), ("width_pixels", 0.),
                                         ("horizontal", .999), ("vertical", .9)])
def test_bad_eye_metadata_cannot_fall_back_to_pooled_iris_features(field, value):
    row = measurement("DOWN")
    row["eyes"]["right"][field] = value
    assert predict(OpennessCandidate(attempt(), CONFIG), row)[0] == "UNKNOWN"


def test_feature_and_eye_metadata_must_describe_same_measurement():
    row = measurement("DOWN")
    row["features"] = measurement("CENTER")["features"]
    assert predict(OpennessCandidate(attempt(), CONFIG), row) == ("UNKNOWN", "feature_metadata_mismatch")


@pytest.mark.parametrize("features", [None, [.5, .5], [.5, .5, math.nan, 0.]])
def test_missing_features_cannot_be_reconstructed_from_eye_diagnostics(features):
    row = measurement("DOWN")
    row["features"] = features
    assert predict(OpennessCandidate(attempt(), CONFIG), row)[0] == "UNKNOWN"


def test_poor_quality_is_unknown_and_no_last_label_is_reused():
    candidate = OpennessCandidate(attempt(), CONFIG)
    assert predict(candidate, measurement("DOWN"))[0] == "DOWN"
    row = measurement("DOWN")
    row["quality"] = .44
    assert predict(candidate, row) == ("UNKNOWN", "insufficient_measurement_quality")


def test_head_pose_only_vetoes_and_cannot_rescue_center_iris_squint():
    candidate = OpennessCandidate(attempt(), CONFIG)
    row = measurement("CENTER", opening=(.20, .25))
    row["features"][3] = .10
    assert predict(candidate, row)[0] == "UNKNOWN"
    row = measurement("DOWN")
    row["features"][3] = 1.
    assert predict(candidate, row) == ("UNKNOWN", "head_pose_outside_reference_coverage")


def test_horizontal_sign_is_learned_but_must_agree_between_eyes():
    source = attempt()
    source["samples"]["LEFT"], source["samples"]["RIGHT"] = source["samples"]["RIGHT"], source["samples"]["LEFT"]
    candidate = OpennessCandidate(source, CONFIG)
    assert candidate.fit_report["fit_ready"]
    assert predict(candidate, measurement("RIGHT"))[0] == "LEFT"
    bad = attempt()
    for label in ("LEFT", "RIGHT"):
        for row in bad["samples"][label]:
            row["eyes"]["left"]["horizontal"] = 1 - row["eyes"]["left"]["horizontal"]
            row["features"][0] = sum(e["horizontal"] for e in row["eyes"].values()) / 2
    assert not OpennessCandidate(bad, CONFIG).fit_report["fit_ready"]


@pytest.mark.parametrize("axis", ["vertical", "opening"])
def test_down_fit_requires_both_iris_and_openness_separation(axis):
    source = attempt(ready=True)
    for row in source["samples"]["DOWN"]:
        for side in ("left", "right"):
            row["eyes"][side][axis] = measurement()["eyes"][side][axis]
        row["features"][1] = sum(e["vertical"] for e in row["eyes"].values()) / 2
    candidate = OpennessCandidate(source, CONFIG)
    assert not candidate.fit_report["fit_ready"]
    assert predict(candidate, measurement("DOWN")) == ("UNKNOWN", "candidate_fit_rejected")
    assert source["diagnostics"]["ready"] is True  # Candidate never changes production state.


def test_wrong_vertical_direction_rejects_fit_instead_of_relabelling_up_as_down():
    source = attempt()
    for row in source["samples"]["DOWN"]:
        row["features"][1] = .38
        for eye in row["eyes"].values():
            eye["vertical"] = .38
    assert not OpennessCandidate(source, CONFIG).fit_report["fit_ready"]


def test_observed_spread_rejects_unstable_candidate_even_with_good_medians():
    source = attempt()
    for row, value in zip(source["samples"]["DOWN"], (.11, .20, .29)):
        row["eyes"]["left"]["opening"] = value
    report = OpennessCandidate(source, CONFIG).fit_report
    gate = next(g for g in report["gates"] if g["eye"] == "left" and g["axis"] == "opening_normalized")
    assert gate["dominant_term"] == "spread"
    assert not gate["accepted"]
    assert not report["fit_ready"]


def test_insufficient_valid_samples_rejects_fit_even_if_production_says_ready():
    source = attempt(True)
    source["samples"]["DOWN"][0]["eyes"]["left"]["valid"] = False
    report = OpennessCandidate(source, CONFIG).fit_report
    assert report["accepted_training_counts"]["DOWN"] == 2
    assert report["excluded_training_reasons"]["DOWN"] == {"left_eye_unobservable": 1}
    assert not report["fit_ready"]


def test_attempt_and_returned_report_are_frozen_and_json_safe():
    source = attempt()
    candidate = OpennessCandidate(source, CONFIG)
    original = deepcopy(candidate.fit_report)
    source["samples"]["DOWN"].clear()
    candidate.fit_report["references"]["DOWN"]["left"]["vertical"]["median"] = -999.
    assert candidate.fit_report == original
    json.dumps(candidate.fit_report, allow_nan=False)
    assert predict(candidate, measurement("DOWN"))[0] == "DOWN"


def test_rejected_training_deliveries_are_not_used_to_expand_envelopes():
    source = attempt()
    invalid = measurement("DOWN", opening=(.12, .12))
    invalid["accepted"] = False
    source["samples"]["DOWN"].append(invalid)
    assert OpennessCandidate(source, CONFIG).fit_report == OpennessCandidate(attempt(), CONFIG).fit_report


def test_unsupported_but_valid_iris_position_remains_unknown():
    row = measurement("DOWN", vertical=.8)
    assert predict(OpennessCandidate(attempt(), CONFIG), row) == ("UNKNOWN", "outside_calibrated_joint_eye_support")


def test_disagreeing_eyes_do_not_average_into_center():
    row = measurement("CENTER")
    row["eyes"]["left"]["horizontal"] = .65
    row["eyes"]["right"]["horizontal"] = .35
    assert predict(OpennessCandidate(attempt(), CONFIG), row)[0] == "UNKNOWN"


def test_overlapping_supported_classes_return_unknown_not_nearest_or_default_center():
    source = attempt()
    for row in source["samples"]["LEFT"]:
        row["features"][0] = .55
        for eye in row["eyes"].values():
            eye["horizontal"] = .55
    candidate = OpennessCandidate(source, CONFIG)
    assert candidate.fit_report["fit_ready"]
    assert predict(candidate, measurement("CENTER", horizontal=.526)) == (
        "UNKNOWN", "ambiguous_candidate_support")
