"""Synthetic tests check diagnostic mechanics, not human gaze accuracy."""
from copy import deepcopy
from dataclasses import replace
import json
import math

import pytest

from proctoring.vision.calibration import Calibration, DIRECTIONS
from proctoring.vision.diagnostic_validation import (
    DEBUG_LABEL, DiagnosticValidation, VALIDATION_TARGETS,
)
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import GazeDirection


REFERENCES = {
    "CENTER": (.5, .5, 0., 0.),
    "LEFT": (.42, .5, 0., 0.),
    "RIGHT": (.58, .5, 0., 0.),
    "DOWN": (.5, .56, 0., 0.),
}
CONFIG = replace(VisionConfig(), calibration_samples=3)


def attempt(ready=False):
    return {
        "diagnostics": {
            "ready": ready, "fit_message": "Synthetic pixel gate rejection",
            "targets": {
                label: {"accepted": 3, "eye_median": list(row[:2]),
                        "head_median_degrees": [value * 60 for value in row[2:]]}
                for label, row in REFERENCES.items()
            },
        },
        "last_accepted_timestamp": 10., "last_recorded_timestamp": 12.,
        "samples": {"DOWN": [{"timestamp": 11., "accepted": False}]},
    }


def validator(ready=False, config=CONFIG):
    return DiagnosticValidation(attempt(ready), config)


def collect(sequence, label, start, features=None, invalid=False):
    features = REFERENCES["CENTER" if label == "READING" else label] if features is None else features
    sequence.start_target(label, start, start + 3)
    for offset in (.5, 1., 1.5):
        sequence.add_sample(features, start + offset, 1.,
                            rejection_reason="blink_or_occlusion" if invalid else None)
    sequence.finish_target(start + 3)


@pytest.mark.parametrize("label", tuple(REFERENCES))
def test_failed_attempt_exploratory_labels_are_not_confidences_or_production_permission(label):
    snapshot = attempt()
    sequence = DiagnosticValidation(snapshot, CONFIG)
    assert sequence.predict(REFERENCES[label]) == label
    report = sequence.report
    assert report["prediction_status"] == DEBUG_LABEL
    assert not report["production_calibration_ready"]
    assert report["human_validation_status"] == "pending"
    assert "confidence" not in json.dumps(report)
    assert snapshot == attempt()


def test_frozen_training_snapshot_cannot_be_changed_by_later_calibration_retry_or_export_edits():
    snapshot = attempt()
    sequence = DiagnosticValidation(snapshot, CONFIG)
    snapshot["diagnostics"]["targets"]["LEFT"]["eye_median"][0] = 99
    sequence.reference_snapshot["diagnostics"]["targets"]["LEFT"]["eye_median"][0] = 99
    assert sequence.predict(REFERENCES["LEFT"]) == "LEFT"
    assert sequence.reference_snapshot["diagnostics"]["targets"]["LEFT"]["eye_median"] == [.42, .5]


def test_training_cutoff_includes_rejected_samples_and_highest_recorded_timestamp():
    snapshot = attempt()
    snapshot["samples"]["DOWN"].append({"timestamp": 14., "accepted": False})
    sequence = DiagnosticValidation(snapshot, CONFIG)
    assert sequence.training_cutoff == 14.
    with pytest.raises(ValueError, match="later than training"):
        sequence.start_target("CENTER", 14., 16.)
    sequence.start_target("CENTER", 15., 18.)
    assert not sequence.add_sample(REFERENCES["CENTER"], 14., 1.)
    assert sequence.report["targets"]["CENTER"]["rejection_reasons"] == {"training_measurement_reused": 1}


@pytest.mark.parametrize("start,end", [(12., 15.), (13., 13.), (15., 13.),
                                       (math.nan, 15.), (13., math.inf)])
def test_collection_window_is_finite_positive_and_after_training(start, end):
    with pytest.raises(ValueError):
        validator().start_target("CENTER", start, end)


def test_reuse_out_of_order_and_outside_interval_are_excluded_from_prediction_denominators():
    sequence = validator()
    sequence.start_target("CENTER", 20., 23.)
    assert not sequence.add_sample(REFERENCES["CENTER"], 19.9, 1.)
    assert sequence.add_sample(REFERENCES["CENTER"], 20., 1.)
    assert not sequence.add_sample(REFERENCES["CENTER"], 20., 1.)
    assert sequence.add_sample(REFERENCES["CENTER"], 21., 1.)
    assert not sequence.add_sample(REFERENCES["CENTER"], 20.5, 1.)
    assert not sequence.add_sample(REFERENCES["CENTER"], 23.1, 1.)
    assert not sequence.add_sample(REFERENCES["CENTER"], math.nan, 1.)
    report = sequence.report["targets"]["CENTER"]
    assert report["collected"] == 2
    assert report["unknown_rate"] == 0.
    assert report["rejection_reasons"] == {
        "outside_validation_window": 2, "reused_or_out_of_order_measurement": 2,
        "nonfinite_timestamp": 1,
    }


def test_fresh_invalid_eyes_are_unknown_and_counted_in_rates():
    sequence = validator()
    sequence.start_target("CENTER", 20., 23.)
    assert sequence.add_sample(REFERENCES["CENTER"], 20., 1.)
    assert not sequence.add_sample(None, 21., .1, rejection_reason="narrow_eye_or_blink")
    assert not sequence.add_sample(REFERENCES["CENTER"], 22., .1)
    report = sequence.report["targets"]["CENTER"]
    assert report["collected"] == 3
    assert report["usable_measurements"] == 1
    assert report["invalid_measurements"] == 2
    assert report["unknown_rate"] == pytest.approx(2 / 3)
    assert report["expected_match_rate"] == pytest.approx(1 / 3)
    assert report["rejection_reasons"] == {
        "narrow_eye_or_blink": 1, "insufficient_measurement_quality": 1,
    }


def test_separate_sequence_reports_confusion_and_reading_false_offscreen_predictions():
    sequence = validator()
    collect(sequence, "CENTER", 20.)
    collect(sequence, "LEFT", 24., REFERENCES["RIGHT"])
    collect(sequence, "RIGHT", 28.)
    collect(sequence, "DOWN", 32., invalid=True)
    sequence.start_target("READING", 36., 39.)
    sequence.add_sample(REFERENCES["CENTER"], 36., 1.)
    sequence.add_sample(REFERENCES["LEFT"], 37., 1.)
    sequence.add_sample((9., 9., 0., 0.), 38., 1.)
    sequence.finish_target(39.)
    report = sequence.report
    assert report["collection_complete"]
    assert not report["ready_for_operator_review"]  # DOWN has no usable samples.
    assert report["human_validation_status"] == "pending"
    assert report["confusion_matrix"]["LEFT"]["RIGHT"] == 3
    assert report["confusion_matrix"]["DOWN"]["UNKNOWN"] == 3
    assert report["targets"]["READING"]["expected_label"] == "CENTER"
    assert report["targets"]["READING"]["expected_match_rate"] == pytest.approx(1 / 3)
    assert report["targets"]["READING"]["unknown_rate"] == pytest.approx(1 / 3)
    assert report["reading_offscreen_prediction_rate"] == pytest.approx(1 / 3)
    assert report["overall_unknown_rate"] == pytest.approx(4 / 15)


def test_even_perfect_synthetic_sequence_does_not_claim_human_validation_or_fit():
    sequence = validator()
    for index, label in enumerate(VALIDATION_TARGETS):
        collect(sequence, label, 20. + index * 4)
    report = sequence.report
    assert report["ready_for_operator_review"]
    assert report["human_validation_status"] == "operator_review_required"
    assert not report["production_calibration_ready"]
    assert report["prediction_status"] == DEBUG_LABEL
    assert report["reading_offscreen_prediction_rate"] == 0.
    assert "passed" not in report


def test_no_measurements_never_becomes_ready_or_reports_zero_unknown():
    sequence = validator()
    assert sequence.report["overall_unknown_rate"] is None
    for index, label in enumerate(VALIDATION_TARGETS):
        start = 20. + index * 4
        sequence.start_target(label, start, start + 3)
        sequence.finish_target(start + 3)
    report = sequence.report
    assert not report["ready_for_operator_review"]
    assert report["human_validation_status"] == "pending"
    assert report["targets"]["CENTER"]["status"] == "completed_no_samples"
    assert report["overall_unknown_rate"] is None


def test_incomplete_references_allow_collection_but_only_unknown_predictions():
    snapshot = attempt()
    snapshot["diagnostics"]["targets"]["DOWN"]["accepted"] = 1
    sequence = DiagnosticValidation(snapshot, CONFIG)
    collect(sequence, "CENTER", 20.)
    assert sequence.predict(REFERENCES["CENTER"]) == "UNKNOWN"
    report = sequence.report
    assert not report["reference_available"]
    assert report["missing_reference_targets"] == ["DOWN"]
    assert report["samples"]["CENTER"][0]["prediction_reason"] == "incomplete_training_references"


def test_overlapping_reference_cores_remain_unknown_instead_of_fabricating_center():
    snapshot = attempt()
    snapshot["diagnostics"]["targets"]["DOWN"]["eye_median"] = [.5, .5]
    sequence = DiagnosticValidation(snapshot, CONFIG)
    assert sequence.predict(REFERENCES["CENTER"]) == "UNKNOWN"


def test_head_pose_can_only_veto_and_never_substitute_for_eye_movement():
    sequence = validator()
    assert sequence.predict((.5, .5, .1, .1)) == "CENTER"
    assert sequence.predict((.5, .5, 0., .6)) == "UNKNOWN"
    assert sequence.predict((.5, .56, 0., 0.)) == "DOWN"
    assert sequence.predict((.5, .56, 0., 1.)) == "UNKNOWN"


@pytest.mark.parametrize("features", [None, (.5, .5), (math.nan, .5, 0., 0.),
                                     (.5, math.inf, 0., 0.)])
def test_invalid_features_never_gain_a_label(features):
    assert validator().predict(features) == "UNKNOWN"


def test_window_order_finish_and_aborted_retry_preserve_freshness():
    sequence = validator()
    with pytest.raises(ValueError):
        sequence.start_target("LEFT", 20., 23.)
    sequence.start_target("CENTER", 20., 23.)
    sequence.add_sample(REFERENCES["CENTER"], 21., 1.)
    with pytest.raises(ValueError):
        sequence.start_target("LEFT", 24., 27.)
    with pytest.raises(ValueError):
        sequence.finish_target(22.)
    sequence.cancel_target("monitoring_unavailable")
    assert sequence.report["targets"]["CENTER"]["collected"] == 0
    assert sequence.report["targets"]["CENTER"]["status"] == "pending"
    assert sequence.active_target is None
    with pytest.raises(ValueError):
        sequence.start_target("CENTER", 20., 23.)
    collect(sequence, "CENTER", 24.)
    with pytest.raises(ValueError):
        sequence.start_target("LEFT", 27., 30.)
    collect(sequence, "LEFT", 28.)


def test_report_is_detached_and_exports_only_whitelisted_numerical_measurements():
    sequence = validator()
    sequence.start_target("CENTER", 20., 23.)
    sequence.add_sample(REFERENCES["CENTER"], 21., 1., metadata={
        "frame_size": [640, 480], "frame": object(), "raw_image": object(),
        "eyes": {"left": {"width_pixels": 35.125, "horizontal": .51, "vertical": .52,
                          "opening": .17, "valid": True, "reason": "valid"}},
        "head_pose_degrees": {"yaw": 1.25, "pitch": math.nan, "roll": .125},
    })
    report = sequence.report
    exported = json.dumps(report, allow_nan=False)
    assert "raw_image" not in exported
    row = report["samples"]["CENTER"][0]
    assert row["frame_size"] == [640., 480.]
    assert row["eyes"]["left"]["width_pixels"] == 35.125
    assert row["head_pose_degrees"]["pitch"] is None
    row["features"][0] = 999
    report["targets"]["CENTER"]["predicted_labels"]["CENTER"] = 999
    assert sequence.report["samples"]["CENTER"][0]["features"][0] == .5
    assert sequence.report["targets"]["CENTER"]["predicted_labels"]["CENTER"] == 1


def test_sample_storage_is_bounded():
    sequence = validator(config=replace(CONFIG, calibration_max_samples=3))
    sequence.start_target("CENTER", 20., 23.)
    for index in range(10):
        sequence.add_sample(REFERENCES["CENTER"], 20. + index * .1, 1.)
    assert len(sequence.report["samples"]["CENTER"]) == 3
    assert sequence.report["targets"]["CENTER"]["rejection_reasons"]["sample_capacity_reached"] == 7


def test_same_core_predictions_as_production_for_a_successfully_fitted_snapshot():
    calibration = Calibration(CONFIG)
    timestamp = 1.
    for direction in DIRECTIONS:
        for _ in range(3):
            calibration.add_sample(direction, REFERENCES[direction.value], timestamp, 1.)
            timestamp += .1
    assert calibration.fit()[0]
    snapshot = attempt(True)
    snapshot["diagnostics"] = calibration.diagnostics
    sequence = DiagnosticValidation(snapshot, CONFIG)
    # Deterministic sweep includes target cores, reading-like positions, and
    # unsupported poses. It tests implementation parity, not human accuracy.
    for horizontal in (.3, .42, .47, .5, .53, .58, .7):
        for vertical in (.45, .5, .53, .56, .7):
            for pitch in (0., .1, 1.):
                row = (horizontal, vertical, 0., pitch)
                assert sequence.predict(row) == calibration.classify(row)[0].value
    assert calibration.ready


def guarded_attempt():
    """Synthetic session with measured per-eye openness and a versioned policy."""
    snapshot = attempt(True)
    snapshot["classifier_policy"] = {
        "version": "guarded_aperture_down_v1", "required_samples": 3,
        "center_radius_fraction": CONFIG.calibration_center_radius_fraction,
        "offscreen_radius_fraction": CONFIG.calibration_offscreen_radius_fraction,
        "pixel_uncertainty_multiplier": .8,
    }
    for label, features in REFERENCES.items():
        opening = .18 if label == "DOWN" else .32
        snapshot["samples"][label] = [
            {"accepted": True, "timestamp": 1. + index, "features": list(features),
             "quality": 1., **guarded_metadata(features, opening)} for index in range(3)]
    return snapshot


def guarded_metadata(features, opening, *, valid=True):
    return {"eyes": {side: {"horizontal": features[0], "vertical": features[1],
                            "opening": opening, "width_pixels": 40., "valid": valid,
                            "reason": "" if valid else "iris_unobservable"}
                     for side in ("left", "right")}}


def test_guarded_policy_is_frozen_and_applies_current_per_eye_metadata():
    snapshot = guarded_attempt()
    before = deepcopy(snapshot)
    sequence = DiagnosticValidation(snapshot, CONFIG)
    borderline = (.5, .524, 0., 0.)
    sequence.start_target("CENTER", 20., 23.)
    sequence.add_sample(borderline, 20., 1., metadata=guarded_metadata(borderline, .18))
    sequence.add_sample(borderline, 20.1, 1., metadata=guarded_metadata(borderline, .10))
    sequence.add_sample(borderline, 20.2, 1., metadata=guarded_metadata(borderline, .07))
    sequence.add_sample(REFERENCES["CENTER"], 20.3, 1.,
                        metadata=guarded_metadata(REFERENCES["CENTER"], .18))
    sequence.add_sample(borderline, 20.4, 1.)  # No stale openness from the earlier rows.
    sequence.add_sample(None, 20.5, 0., metadata=guarded_metadata(borderline, .07, valid=False),
                        rejection_reason="iris_unobservable")
    report = sequence.report
    rows = report["samples"]["CENTER"]
    assert [row["predicted_label"] for row in rows] == ["DOWN", "UNKNOWN", "UNKNOWN", "CENTER", "UNKNOWN", "UNKNOWN"]
    assert report["targets"]["CENTER"]["correct_labels"] == 1
    assert report["targets"]["CENTER"]["incorrect_labels"] == 1
    assert report["targets"]["CENTER"]["unknown_measurements"] == 4
    assert report["targets"]["CENTER"]["invalid_measurements"] >= 1
    assert report["source_classifier_policy"] == snapshot["classifier_policy"]
    assert report["guarded_aperture_enabled"]
    assert snapshot == before
    snapshot["classifier_policy"]["version"] = "modified_outside_validator"
    assert sequence.report["source_classifier_policy"] == before["classifier_policy"]


def test_legacy_snapshot_keeps_iris_only_predictions_with_current_eye_metadata():
    snapshot = guarded_attempt()
    snapshot.pop("classifier_policy")
    sequence = DiagnosticValidation(snapshot, CONFIG)
    sequence.start_target("CENTER", 20., 23.)
    sequence.add_sample(REFERENCES["DOWN"], 20., 1.,
                        metadata=guarded_metadata(REFERENCES["DOWN"], .07))
    assert sequence.report["samples"]["CENTER"][0]["predicted_label"] == "DOWN"
    assert not sequence.report["guarded_aperture_enabled"]
    assert sequence.report["source_classifier_policy"] is None


def test_versioned_guard_references_and_radii_use_frozen_collection_policy():
    snapshot = guarded_attempt()
    changed_live_config = replace(CONFIG, calibration_samples=30,
                                  calibration_center_radius_fraction=.05,
                                  calibration_offscreen_radius_fraction=.05)
    original = DiagnosticValidation(snapshot, CONFIG)
    changed = DiagnosticValidation(snapshot, changed_live_config)
    assert changed.report["reference_centers"] == original.report["reference_centers"]
    assert changed.report["reference_radii"] == original.report["reference_radii"]
    borderline = (.5, .524, 0., 0.)
    assert changed.predict(borderline, guarded_metadata(borderline, .18)) == "DOWN"


def test_guarded_replay_keeps_existing_head_pose_veto():
    sequence = DiagnosticValidation(guarded_attempt(), CONFIG)
    unsupported_pose = (.5, .524, 1., 1.)
    sequence.start_target("CENTER", 20., 23.)
    sequence.add_sample(unsupported_pose, 20., 1., metadata=guarded_metadata(unsupported_pose, .18))
    row = sequence.report["samples"]["CENTER"][0]
    assert row["predicted_label"] == "UNKNOWN"
    assert row["prediction_reason"] == "head_pose_outside_reference_coverage"


def test_guarded_unknown_during_reading_is_abstention_not_a_correct_screen_label():
    sequence = DiagnosticValidation(guarded_attempt(), CONFIG)
    for index, label in enumerate(VALIDATION_TARGETS[:-1]):
        collect(sequence, label, 20. + index * 4)
    sequence.start_target("READING", 36., 39.)
    sequence.add_sample(REFERENCES["CENTER"], 36.1, 1.,
                        metadata=guarded_metadata(REFERENCES["CENTER"], .10))
    report = sequence.report["targets"]["READING"]
    assert report["correct_labels"] == 0
    assert report["incorrect_labels"] == 0
    assert report["unknown_measurements"] == 1
    assert report["unknown_rate"] == 1.
    assert report["offscreen_prediction_rate"] == 0.


def test_missing_training_timestamp_cannot_silently_allow_reused_training_frames():
    snapshot = attempt()
    snapshot.pop("last_accepted_timestamp")
    snapshot.pop("last_recorded_timestamp")
    snapshot["samples"] = {}
    sequence = DiagnosticValidation(snapshot, CONFIG)
    assert sequence.report["human_validation_status"] == "pending"
    with pytest.raises(ValueError, match="timestamps are missing"):
        sequence.start_target("CENTER", 20., 23.)


def test_real_rejected_calibration_export_stays_rejected_after_debug_collection():
    # An explicitly conservative setting still creates a genuinely failed fit;
    # diagnostic validation must never promote it to production readiness.
    calibration = Calibration(replace(CONFIG, calibration_pixel_uncertainty_multiplier=3.))
    timestamp = 1.
    for direction in DIRECTIONS:
        for _ in range(3):
            calibration.add_sample(direction, REFERENCES[direction.value], timestamp, 1., noise_floor=1 / 30)
            timestamp += .1
    assert not calibration.fit()[0]
    snapshot = calibration.export_snapshot()
    sequence = DiagnosticValidation(snapshot, CONFIG)
    for index, label in enumerate(VALIDATION_TARGETS):
        collect(sequence, label, 20. + index * 4)
    assert sequence.report["ready_for_operator_review"]
    assert not calibration.ready
    assert calibration.export_snapshot() == snapshot
    assert calibration.classify(REFERENCES["DOWN"]) == (GazeDirection.UNKNOWN, None)


def test_heldout_statistics_keep_eye_axes_and_head_pose_separate():
    sequence = validator()
    sequence.start_target("CENTER", 20., 23.)
    for index, horizontal in enumerate((.49, .5, .51)):
        sequence.add_sample((horizontal, .5, .1, .2), 20. + index, 1.)
    target = sequence.report["targets"]["CENTER"]
    assert target["eye_axes"]["horizontal"]["median"] == .5
    assert target["eye_axes"]["horizontal"]["spread_p90"] == pytest.approx(.01)
    assert target["eye_axes"]["vertical"]["spread_p90"] == 0.
    assert target["head_axes_degrees"]["yaw"]["median"] == 6.
    assert target["head_axes_degrees"]["pitch"]["median"] == 12.
    assert target["prediction_reasons"] == {"head_pose_outside_reference_coverage": 3}
