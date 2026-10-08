"""Synthetic geometry regressions; these do not establish human gaze accuracy."""
from copy import deepcopy
from dataclasses import replace
import math

import pytest

from proctoring.vision.calibration import Calibration, _bounded_down_extension
from proctoring.vision.diagnostic_validation import DiagnosticValidation
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import GazeDirection


CONFIG = replace(VisionConfig(), calibration_samples=3)
REFERENCES = {
    "CENTER": (.50, .43, 0., 0.),
    "LEFT": (.63, .44, 0., 0.),
    "RIGHT": (.37, .44, 0., 0.),
    "DOWN": (.54, .51, 0., 0.),
}
NEAR_REFERENCE = {
    "CENTER": (0., 0., 0., 0.),
    "LEFT": (-1., 0., 0., 0.),
    "RIGHT": (1., 0., 0., 0.),
    "DOWN": (2., .2, 0., 0.),
}


def collect(references=REFERENCES, *, noise_floor=None):
    calibration = Calibration(CONFIG)
    timestamp = 1.
    for label, reference in references.items():
        for _ in range(CONFIG.calibration_samples):
            assert calibration.add_sample(GazeDirection(label), reference, timestamp, 1.,
                                          noise_floor=noise_floor)
            timestamp += 1.
    return calibration


def fitted(references=REFERENCES):
    calibration = collect(references)
    assert calibration.fit()[0]
    return calibration


def original_point_prediction(features, centers, radii):
    """Frozen pre-patch point-core behavior, used to check preservation."""
    ranked = sorted((math.sqrt(sum((a - b) ** 2 for a, b in zip(features[:2], reference[:2]))), label)
                    for label, reference in centers.items())
    distance, label = ranked[0]
    second = ranked[1][0]
    radius = radii[label]
    if radius <= 0 or distance > radius:
        return "UNKNOWN", None
    margin = (second - distance) / max(second, 1e-9)
    if margin < .12:
        return "UNKNOWN", None
    return label, min(1., max(0., margin * (1. - .5 * distance / radius)))


@pytest.mark.parametrize("reverse", [False, True])
def test_straight_down_offset_accepts_only_a_bounded_training_segment(reverse):
    def mirror(row):
        return (1.04 - row[0], *row[1:]) if reverse else row

    references = {label: mirror(row) for label, row in REFERENCES.items()}
    calibration = fitted(references)
    sample = mirror((.50, .51, 0., 0.))
    assert original_point_prediction(sample, references, calibration._radii)[0] == "UNKNOWN"
    label, similarity = calibration.classify(sample)
    assert label == GazeDirection.DOWN
    assert similarity is not None and math.isfinite(similarity) and 0 <= similarity <= 1
    for row in ((.472, .51, 0., 0.), (.568, .51, 0., 0.), (.52, .538, 0., 0.)):
        assert calibration.classify(mirror(row)) == (GazeDirection.UNKNOWN, None)


def test_extension_does_not_mutate_frozen_references_or_original_radii():
    calibration = fitted()
    centers, radii = deepcopy(calibration._centers), dict(calibration._radii)
    before = calibration.export_snapshot()
    for sample in ((.50, .51, 0., 0.), (.52, .51, 0., 0.), (.472, .51, 0., 0.)):
        calibration.classify(sample)
    assert calibration._centers == centers
    assert calibration._radii == radii
    assert calibration.export_snapshot() == before


def test_nearby_reference_caps_extension_but_preserves_original_down_disk():
    calibration = fitted(NEAR_REFERENCE)
    # Segment is .2 from CENTER/RIGHT, so its cap is .08, while the old disk
    # remains larger than .4. A .1 vertical offset cannot enter the extension.
    assert calibration._radii["DOWN"] > .4
    assert calibration.classify((.5, .3, 0., 0.)) == (GazeDirection.UNKNOWN, None)
    assert calibration.classify((1.5, .2, 0., 0.))[0] == GazeDirection.DOWN
    assert calibration.classify((1.9, .4, 0., 0.))[0] == GazeDirection.DOWN


def test_overlap_with_accepted_center_is_unknown_without_similarity():
    calibration = fitted(NEAR_REFERENCE)
    point = (.1, .15, 0., 0.)
    assert original_point_prediction(point, calibration._centers, calibration._radii)[0] == "CENTER"
    assert _bounded_down_extension(point, calibration._centers, calibration._radii) == (
        "UNKNOWN", None, "overlapping_reference_cores")
    assert calibration.classify(point) == (GazeDirection.UNKNOWN, None)


def test_outside_capped_extension_retains_original_center_even_when_segment_is_nearer():
    calibration = fitted(NEAR_REFERENCE)
    point = (.1, .1, 0., 0.)
    # Distance to segment=.1, point CENTER=sqrt(.02), but the segment's .08
    # core rejects it. Re-ranking against the segment would lose this CENTER.
    assert _bounded_down_extension(point, calibration._centers, calibration._radii) is None
    expected = original_point_prediction(point, calibration._centers, calibration._radii)
    assert expected[0] == "CENTER"
    assert calibration.classify(point) == expected


def test_segment_touching_another_reference_adds_no_labels_and_keeps_original_disk():
    references = dict(NEAR_REFERENCE, RIGHT=(1., .2, 0., 0.))
    calibration = fitted(references)
    point = (1.5, .2, 0., 0.)
    assert _bounded_down_extension(point, calibration._centers, calibration._radii) is None
    assert calibration.classify(point) == (GazeDirection.UNKNOWN, None)
    assert calibration.classify((1.9, .2, 0., 0.))[0] == GazeDirection.DOWN


def test_equal_horizontal_endpoints_keep_original_point_classifier():
    calibration = fitted(dict(REFERENCES, DOWN=(.5, .51, 0., 0.)))
    for point in ((.5, .51, 0., 0.), (.52, .52, 0., 0.), (.55, .51, 0., 0.)):
        assert _bounded_down_extension(point, calibration._centers, calibration._radii) is None
        assert calibration.classify(point) == original_point_prediction(
            point, calibration._centers, calibration._radii)


def test_all_coincident_references_stay_unknown_in_failed_production_and_debug():
    calibration = collect({label: (.5, .5, 0., 0.) for label in REFERENCES})
    assert not calibration.fit()[0]
    debug = DiagnosticValidation(calibration.export_snapshot(), CONFIG)
    for point in ((.5, .5, 0., 0.), (.6, .6, 0., 0.)):
        assert calibration.classify(point) == (GazeDirection.UNKNOWN, None)
        assert debug.predict(point) == "UNKNOWN"
    assert not calibration.ready


def test_pixel_gate_failure_cannot_be_bypassed_by_debug_down_extension():
    # A sufficiently small source eye still fails the configured .8 pixel gate.
    calibration = collect(noise_floor=.12)
    assert not calibration.fit()[0]
    gate = calibration.diagnostics["pairs"]["CENTER_DOWN"]
    assert not gate["passed"]
    assert gate["dominant_contributions"] == ["pixel_noise_floor"]
    assert gate["required_eye_separation"] == pytest.approx(.096)
    debug = DiagnosticValidation(calibration.export_snapshot(), CONFIG)
    assert debug.predict((.50, .51, 0., 0.)) == "DOWN"
    assert calibration.classify((.50, .51, 0., 0.)) == (GazeDirection.UNKNOWN, None)
    assert not calibration.ready
    assert not debug.report["production_calibration_ready"]
    assert debug.report["prediction_status"] == "DEBUG / UNVALIDATED"


@pytest.mark.parametrize("axis", [2, 3])
@pytest.mark.parametrize("sign", [-1, 1])
def test_head_veto_precedes_down_extension_and_never_substitutes_a_direction(axis, sign):
    calibration = fitted()
    debug = DiagnosticValidation(calibration.export_snapshot(), CONFIG)
    point = [.50, .51, 0., 0.]
    point[axis] = sign * 11. / 60.
    assert calibration.classify(tuple(point)) == (GazeDirection.UNKNOWN, None)
    assert debug._prediction(point) == ("UNKNOWN", "head_pose_outside_reference_coverage")


@pytest.mark.parametrize("features", [None, (.5, .51), (.5, math.nan, 0., 0.),
                                       (.5, .51, math.inf, 0.)])
def test_invalid_features_never_enter_extension_or_receive_similarity(features):
    calibration = fitted()
    debug = DiagnosticValidation(calibration.export_snapshot(), CONFIG)
    assert calibration.classify(features) == (GazeDirection.UNKNOWN, None)
    assert debug.predict(features) == "UNKNOWN"


@pytest.mark.parametrize("references", [REFERENCES, NEAR_REFERENCE])
def test_production_debug_parity_and_unchanged_point_decisions_outside_extension(references):
    calibration = fitted(references)
    debug = DiagnosticValidation(calibration.export_snapshot(), CONFIG)
    checked_outside = 0
    for x_step in range(-10, 81):
        for y_step in range(-5, 31):
            point = (x_step * .025, y_step * .025, 0., 0.)
            actual = calibration.classify(point)
            assert debug.predict(point) == actual[0]
            if actual[0] == GazeDirection.UNKNOWN:
                assert actual[1] is None
            else:
                assert math.isfinite(actual[1]) and 0 <= actual[1] <= 1
            if _bounded_down_extension(point, calibration._centers, calibration._radii) is None:
                checked_outside += 1
                assert actual == original_point_prediction(point, calibration._centers,
                                                            calibration._radii)
    assert checked_outside > 1000
