"""Debug candidate collection and scoring; no assertions about human accuracy."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from proctoring.vision.diagnostic_validation import (
    CHALLENGE_TARGETS, DiagnosticValidation, VALIDATION_TARGETS,
)
from proctoring.vision.settings import VisionConfig


CONFIG = replace(VisionConfig(), calibration_samples=3)
REFERENCES = {"CENTER": (.5, .5, .32), "LEFT": (.35, .5, .32),
              "RIGHT": (.65, .5, .32), "DOWN": (.5, .62, .18)}


def metadata(label="CENTER"):
    h, v, opening = REFERENCES[label]
    eye = dict(horizontal=h, vertical=v, opening=opening, width_pixels=50., valid=True, reason="")
    return {"eyes": {"left": dict(eye), "right": dict(eye)}, "frame_size": [640, 480],
            "head_pose_degrees": {"yaw": 0., "pitch": 0., "roll": 0.}}


def attempt():
    snapshot = {"diagnostics": {"ready": False, "targets": {}}, "samples": {},
                "last_accepted_timestamp": 12., "last_recorded_timestamp": 12.}
    timestamp = 0.
    for label, (h, v, _) in REFERENCES.items():
        snapshot["diagnostics"]["targets"][label] = {
            "accepted": 3, "eye_median": [h, v], "head_median_degrees": [0., 0.]}
        rows = []
        for _ in range(3):
            timestamp += 1.
            rows.append({"accepted": True, "timestamp": timestamp, "features": [h, v, 0., 0.],
                         "quality": 1., "rejection_reason": None, **metadata(label)})
        snapshot["samples"][label] = rows
    return snapshot


def collect(sequence, label, start, *, invalid=False):
    source = "CENTER" if label not in REFERENCES else label
    h, v, _ = REFERENCES[source]
    sequence.start_target(label, start, start + 3.)
    for offset in (.5, 1., 1.5):
        sequence.add_sample(None if invalid else (h, v, 0., 0.), start + offset,
                            .1 if invalid else 1., metadata=metadata(source),
                            rejection_reason="iris_unobservable" if invalid else None)
    sequence.finish_target(start + 3.)


def test_candidate_is_opt_in_and_default_sequence_unchanged():
    sequence = DiagnosticValidation(attempt(), CONFIG)
    assert sequence.targets == VALIDATION_TARGETS
    assert sequence.candidate is None
    collect(sequence, "CENTER", 20.)
    assert sequence.report["openness_candidate"] is None
    assert "candidate_predicted_label" not in sequence.report["samples"]["CENTER"][0]


def test_candidate_freezes_same_attempt_and_never_changes_production_readiness():
    snapshot = attempt()
    before = deepcopy(snapshot)
    sequence = DiagnosticValidation(snapshot, CONFIG, include_openness_candidate=True)
    assert sequence.targets == VALIDATION_TARGETS + CHALLENGE_TARGETS
    collect(sequence, "CENTER", 20.)
    assert not sequence.report["production_calibration_ready"]
    assert snapshot == before
    snapshot["samples"]["CENTER"][0]["eyes"]["left"]["opening"] = 999
    assert sequence.reference_snapshot == before
    report = sequence.report
    assert report["openness_candidate"]["prediction_status"] == "DEBUG / UNVALIDATED"
    assert report["samples"]["CENTER"][0]["candidate_predicted_label"] == "CENTER"


def test_closure_unknown_is_abstention_never_counted_as_correct_and_not_blocked_by_valid_sample_quota():
    sequence = DiagnosticValidation(attempt(), CONFIG, include_openness_candidate=True)
    for index, label in enumerate(sequence.targets):
        collect(sequence, label, 20. + 4 * index,
                invalid=label in ("BLINK", "BRIEF_CLOSURE", "SUSTAINED_CLOSURE"))
    report = sequence.report
    assert report["collection_complete"]
    assert report["ready_for_operator_review"]
    for report_targets in (report["targets"], report["openness_candidate"]["targets"]):
        for label in ("BLINK", "BRIEF_CLOSURE", "SUSTAINED_CLOSURE"):
            target = report_targets[label]
            assert target["invalid_measurements"] == 3
            assert target["unknown_rate"] == 1.
            assert target["expected_match_rate"] is None
            assert target["correct_labels"] is None
            assert target["incorrect_labels"] is None
    assert not report["production_calibration_ready"]


def test_reading_unknown_is_not_counted_correct_for_either_classifier():
    sequence = DiagnosticValidation(attempt(), CONFIG, include_openness_candidate=True)
    for index, label in enumerate(VALIDATION_TARGETS):
        collect(sequence, label, 20. + 4 * index, invalid=label == "READING")
    report = sequence.report
    for targets in (report["targets"], report["openness_candidate"]["targets"]):
        assert targets["READING"]["correct_labels"] == 0
        assert targets["READING"]["incorrect_labels"] == 0
        assert targets["READING"]["unknown_measurements"] == 3
        assert targets["READING"]["expected_match_rate"] == 0.


def test_candidate_metadata_is_numeric_only_and_report_is_detached():
    sequence = DiagnosticValidation(attempt(), CONFIG, include_openness_candidate=True)
    sequence.start_target("CENTER", 20., 23.)
    values = metadata()
    values["frame"] = object()
    sequence.add_sample((.5, .5, 0., 0.), 21., 1., metadata=values)
    report = sequence.report
    assert "frame\"" not in json.dumps(report, allow_nan=False)
    report["openness_candidate"]["targets"]["CENTER"]["predicted_labels"]["CENTER"] = 900
    assert sequence.report["openness_candidate"]["targets"]["CENTER"]["predicted_labels"]["CENTER"] == 1


def test_challenge_targets_require_explicit_candidate_opt_in():
    sequence = DiagnosticValidation(attempt(), CONFIG)
    with pytest.raises(ValueError, match="Unknown"):
        sequence.start_target("SQUINT", 20., 23.)
