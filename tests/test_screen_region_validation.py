"""Complete numerical region collections, comparison and replay mechanics."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from proctoring.vision.diagnostic_validation import DiagnosticValidation
from proctoring.vision.settings import VisionConfig

CONFIG = replace(VisionConfig(), calibration_samples=3)
ANCHORS = {"quiz": (.25, .3), "options": (.3, .6), "controls": (.85, .1), "monitor": (.75, .45)}


def position(spec):
    if spec["position_kind"] == "widget":
        x, y = ANCHORS[spec["widget_anchor"]]
    else:
        requested = spec.get("requested_position", {})
        x, y = requested.get("x_normalized", .5), requested.get("y_normalized", .5)
    return {"x_normalized": x, "y_normalized": y, "rendered": True}


def measurement(spec, stamp):
    expected = spec.get("expected_label")
    if expected in ("LEFT", "RIGHT", "DOWN"):
        h, v = {"LEFT": (.8, .45), "RIGHT": (.2, .45), "DOWN": (.5, .75)}[expected]
    else:
        p = position(spec)
        h, v = .5 - .25 * (p["x_normalized"] - .5), .45 + .25 * (p["y_normalized"] - .5)
    return {"features": [h, v, 0., 0.], "quality": 1., "received_at": stamp + .12,
            "face_latency_ms": 17.5, "frame_size": [640, 480],
            "eyes": {side: {"horizontal": h, "vertical": v, "opening": .3, "width_pixels": 40.,
                            "valid": True, "reason": ""} for side in ("left", "right")}}


def collect(sequence, target, start, *, duration=3., invalid=False):
    spec = sequence.target_specs[target]
    sequence.set_target_position(target, position(spec))
    sequence.start_target(target, start, start + duration)
    for index in range(int(duration * 10)):
        stamp = start + index * .1
        row = measurement(spec, stamp)
        sequence.add_sample(None if invalid else row["features"], stamp, .1 if invalid else 1.,
                            metadata=row, rejection_reason="iris_unobservable" if invalid else None)
    sequence.finish_target(start + duration)


def trained():
    sequence = DiagnosticValidation({}, CONFIG, screen_region_phase="training", started_at=0.)
    for index, target in enumerate(sequence.targets):
        collect(sequence, target, 1. + 4 * index)
    return sequence.training_snapshot()


def test_complete_training_has_actual_positions_and_own_fit_without_production_permission():
    snapshot = trained()
    assert snapshot["region_fit"]["fit_ready"], snapshot["region_fit"]["failures"]
    assert snapshot["diagnostics"]["ready"] is False
    assert snapshot["collection_complete"]
    assert len(snapshot["target_definitions"]) == 13
    assert snapshot["fit_configuration"]["calibration_samples"] == 3
    assert snapshot["last_accepted_timestamp"] == pytest.approx(51.9)
    assert snapshot["samples"]["CENTER_START"][0]["target_role"] == "on_screen_calibration"
    assert snapshot["samples"]["CENTER_START"][0]["target_definition_id"] == "CENTER_START"
    assert snapshot["target_definitions"][0]["position"]["rendered"]
    assert snapshot["baseline_reference"]["diagnostics"]["targets"]["CENTER"]["accepted"] == 30
    assert "classifier_policy" not in snapshot["baseline_reference"]
    assert snapshot["baseline_comparison_policy"] == "legacy_iris_point_cores"


def test_separate_validation_freezes_references_scores_unknown_and_simulates_events():
    snapshot = trained()
    before = deepcopy(snapshot)
    sequence = DiagnosticValidation(snapshot, CONFIG)
    assert sequence.candidate is None  # No additional eyelid membership.
    assert len(sequence.targets) == 17
    for index, target in enumerate(sequence.targets):
        collect(sequence, target, 60. + 7 * index, duration=6., invalid=target == "SUSTAINED_CLOSURE")
    report = sequence.report
    assert snapshot == before
    assert not report["production_calibration_ready"]
    assert report["collection_complete"]
    assert report["screen_region_candidate"]["fit_ready"]
    down = report["comparison"]["screen_region"]["targets"]["DOWN_1"]
    assert down["correct_labels"] == 60
    assert down["unknown_measurements"] == 0
    assert down["timing"]["event_count"] == 1
    event = down["timing"]["events"][0]
    assert event["capture_duration_at_activation_seconds"] >= 3.
    assert event["sampling_overshoot_seconds"] <= .100001
    assert event["activation_face_latency_ms"] == 17.5
    assert down["timing"]["events"] == sequence.report["comparison"]["screen_region"]["targets"]["DOWN_1"]["timing"]["events"]
    closed = report["comparison"]["screen_region"]["targets"]["SUSTAINED_CLOSURE"]
    assert closed["invalid_measurements"] == 60
    assert closed["unknown_measurements"] == 60
    assert closed["correct_labels"] == 0
    assert closed["scored_measurements"] == 0
    assert closed["timing"]["event_count"] == 0
    blink = report["comparison"]["screen_region"]["targets"]["BLINK"]
    assert blink["scored_measurements"] == 40  # Open portions expect ON_SCREEN.
    assert blink["correct_labels"] == 40
    assert blink["unscored_transition_measurements"] == 20
    assert "frame\"" not in json.dumps(report, allow_nan=False)


def test_unknown_reading_never_counts_correct_and_no_target_moves_after_samples():
    sequence = DiagnosticValidation(trained(), CONFIG)
    for index, target in enumerate(sequence.targets[:6]):
        collect(sequence, target, 60. + 7 * index, duration=6., invalid=target == "READING_1")
    result = sequence.report["comparison"]["screen_region"]["targets"]["READING_1"]
    assert result["correct_labels"] == 0
    assert result["incorrect_labels"] == 0
    assert result["unknown_measurements"] == 60
    with pytest.raises(ValueError, match="move"):
        sequence.set_target_position(sequence.targets[0], {"x_normalized": .9})


def test_replay_requires_real_boundary_training_and_preserves_source_configuration():
    spec = importlib.util.spec_from_file_location("region_replay", Path(__file__).parents[1] / "scripts" / "replay_openness_candidate.py")
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    legacy = {"calibration": {"diagnostics": {"ready": True}}, "validation": None}
    output = replay.replay(legacy, candidate="screen-region")
    assert not output["candidate_calibration"]["fit_ready"]
    assert output["candidate_comparison"] is None
    assert "missing" in output["comparison_status"]
    snapshot = trained()
    seq = DiagnosticValidation(snapshot, CONFIG)
    collect(seq, seq.targets[0], 60., duration=6.)
    output = replay.replay({"calibration": snapshot, "validation": seq.report}, candidate="screen-region")
    assert output["candidate_calibration"]["fit_ready"]
    assert output["candidate_comparison"]["comparison"]["screen_region"]["targets"][seq.targets[0]]["correct_labels"] == 60


def test_openness_cannot_be_composed_and_training_requires_monotonic_start():
    with pytest.raises(ValueError, match="excludes"):
        DiagnosticValidation({}, CONFIG, screen_region_phase="training", started_at=0., include_openness_candidate=True)
    with pytest.raises(ValueError, match="monotonic"):
        DiagnosticValidation({}, CONFIG, screen_region_phase="training")


def test_live_prediction_is_limited_to_active_window_and_summary_omits_raw_rows():
    sequence = DiagnosticValidation(trained(), CONFIG)
    target = sequence.targets[0]
    assert sequence.latest_region_prediction is None
    sequence.start_target(target, 60., 66.)
    row = measurement(sequence.target_specs[target], 61.)
    sequence.add_sample(row["features"], 61., 1., metadata=row)
    assert sequence.latest_region_prediction["region_predicted_label"] == "ON_SCREEN"
    assert "samples" not in sequence.summary_report
    assert sequence.report["samples"][target][0]["timestamp"] == 61.
    sequence.finish_target(66.)
    assert sequence.latest_region_prediction is None
