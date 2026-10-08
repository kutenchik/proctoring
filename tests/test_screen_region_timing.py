"""Timing mechanics on synthetic rows; not human classification validation."""
import math

import pytest

from proctoring.domain import EventType
from proctoring.vision.screen_region_timing import summarize_timing


def rows(labels, *, step=.5, received_delay=None, start=10., key="region_predicted_label"):
    values = []
    for index, label in enumerate(labels):
        row = {"timestamp": start + index * step, key: label, "accepted": True}
        if received_delay is not None:
            row.update(received_at=row["timestamp"] + received_delay,
                       face_latency_ms=21.)
        values.append(row)
    return values


def report(values, expected="ON_SCREEN", **kwargs):
    return summarize_timing(values, "region_predicted_label", expected, **kwargs)


def test_three_seconds_reuses_existing_engine_and_separates_delivery_latency():
    result = report(rows(["LEFT"] * 9, received_delay=.12))
    assert result["event_count"] == result["false_direction_event_count"] == 1
    event = result["events"][0]
    assert event["capture_duration_at_activation_seconds"] == 3.
    assert event["sampling_overshoot_seconds"] == 0.
    assert event["activation_received_at"] == pytest.approx(13.12)
    assert event["delivery_after_threshold_seconds"] == pytest.approx(.12)
    assert event["activation_face_latency_ms"] == 21.
    assert event["duration_seconds"] == 4.
    assert result["longest_false_direction_run_seconds"] == 4.
    assert result["capture_to_receive_latency_ms"]["median"] == pytest.approx(120.)
    assert result["face_inference_latency_ms"]["median"] == 21.
    assert result["events"][0]["close_reason"] == "diagnostic_window_ended"


def test_sampling_overshoot_is_reported_without_claiming_exact_threshold_delivery():
    result = report(rows(["DOWN"] * 7, step=.7, received_delay=.09), expected="DOWN")
    event = result["events"][0]
    assert event["capture_duration_at_activation_seconds"] == 3.5
    assert event["sampling_overshoot_seconds"] == .5
    assert event["delivery_after_threshold_seconds"] == pytest.approx(.59)
    assert result["false_direction_event_count"] == 0
    assert result["longest_false_direction_run_seconds"] == 0.


def test_short_collection_never_invents_threshold_evidence_or_end_of_window_tail():
    result = report(rows(["RIGHT"] * 6))
    assert result["observed_span_seconds"] == 2.5
    assert result["event_count"] == 0
    assert result["longest_false_direction_run_seconds"] == 2.5


@pytest.mark.parametrize("break_label", ["ON_SCREEN", "CENTER", "UNKNOWN", "RIGHT"])
def test_candidates_restart_on_an_intervening_complete_negative_sample(break_label):
    result = report(rows(["LEFT"] * 6 + [break_label] + ["LEFT"] * 6))
    assert result["event_count"] == 0
    assert result["longest_false_direction_run_seconds"] == 2.5


def test_invalid_directional_prediction_is_unknown_and_resets_candidates():
    values = rows(["DOWN"] * 13)
    values[6]["accepted"] = False
    result = report(values)
    assert result["invalid_measurements"] == 1
    assert result["unknown_measurements"] == 1
    assert result["unknown_rate"] == pytest.approx(1 / 13)
    assert result["event_count"] == 0
    assert result["longest_false_direction_run_seconds"] == 2.5


def test_active_hysteresis_can_bridge_a_short_unknown_while_strict_run_cannot():
    values = rows(["LEFT"] * 8 + ["UNKNOWN", "LEFT", "LEFT"])
    result = report(values)
    assert result["event_count"] == 1
    assert result["events"][0]["duration_seconds"] == 5.
    assert result["longest_false_direction_run_seconds"] == 3.5
    assert [r["observed_duration_seconds"] for r in result["direction_runs"]] == [3.5, .5]
    assert "clearing" in [change["action"] for change in result["event_changes"]]


def test_clearing_boundary_closes_existing_event_before_new_positive_candidate():
    values = rows(["LEFT"] * 8)
    values += rows(["UNKNOWN"], start=14.)
    values += rows(["LEFT"] * 7, start=14.75)
    result = report(values)
    assert result["event_count"] == 2
    assert result["events"][0]["duration_seconds"] == 3.5
    assert result["events"][0]["close_reason"] == "condition_cleared"
    assert result["events"][1]["first_positive_capture_timestamp"] == 14.75


def test_unseen_stale_gap_breaks_run_and_candidate_instead_of_counting_outage():
    values = rows(["LEFT"] * 6) + rows(["LEFT"] * 6, start=20.)
    result = report(values)
    assert result["event_count"] == 0
    assert result["longest_false_direction_run_seconds"] == 2.5
    assert len(result["direction_runs"]) == 2
    assert result["observation_gap_seconds"]["max"] == 7.5


def test_each_call_isolated_from_other_validation_windows_or_classifiers():
    first = report(rows(["LEFT"] * 6))
    second = report(rows(["LEFT"] * 6, start=13.))
    assert first["event_count"] == second["event_count"] == 0


def test_absent_telemetry_stays_null_and_unknown_is_not_correct():
    result = report(rows(["UNKNOWN", "ON_SCREEN", "UNKNOWN"]))
    assert result["unknown_rate"] == pytest.approx(2 / 3)
    assert result["capture_to_receive_latency_ms"]["count"] == 0
    assert result["capture_to_receive_latency_ms"]["median"] is None
    assert result["face_inference_latency_ms"]["median"] is None
    result = report(rows(["RIGHT"] * 7))
    assert result["events"][0]["activation_received_at"] is None
    assert result["events"][0]["delivery_after_threshold_seconds"] is None
    assert result["events"][0]["activation_receive_latency_ms"] is None


def test_blink_or_closure_interval_is_not_automatically_scored_unknown_correct():
    result = report(rows(["ON_SCREEN", "UNKNOWN"] + ["DOWN"] * 8), expected=None)
    assert result["unknown_measurements"] == 1
    assert result["longest_false_direction_run_seconds"] is None
    assert result["false_direction_event_count"] is None
    assert result["direction_runs"][0]["incorrect_direction"] is None
    assert result["events"][0]["incorrect_direction"] is None
    assert result["event_count"] == 1  # Still exposed for operator review.


def test_wrong_offscreen_direction_is_distinct_from_unknown_and_correct_direction():
    result = report(rows(["RIGHT"] * 8 + ["UNKNOWN"] + ["LEFT"] * 8), expected="LEFT")
    assert result["event_count"] == 2
    assert result["false_direction_event_count"] == 1
    assert result["longest_false_direction_run_seconds"] == 3.5


def test_supplied_application_thresholds_and_clearing_are_used_without_changes():
    thresholds = {EventType.GAZE_LEFT: 4., EventType.GAZE_RIGHT: 4.,
                  EventType.GAZE_DOWN: 4., EventType.PHONE_VISIBLE: 1.}
    result = report(rows(["LEFT"] * 8), thresholds=thresholds, clearing_seconds=1.)
    assert result["event_count"] == 0
    assert result["thresholds_seconds"]["gaze_left"] == 4.
    assert result["clearing_seconds"] == 1.
    assert EventType.PHONE_VISIBLE not in result["thresholds_seconds"]


def test_timestamp_duplicates_nonfinite_and_reordered_deliveries_do_not_extend_runs():
    values = rows(["LEFT"] * 3)
    values.extend([dict(values[-1]), {"timestamp": math.nan}, dict(values[0])])
    result = report(values)
    assert result["collected"] == 3
    assert result["longest_false_direction_run_seconds"] == 1.
    assert result["exclusions"] == {"duplicate_or_out_of_order_capture": 2,
                                     "nonfinite_capture_timestamp": 1}


def test_malformed_latency_never_fabricates_negative_or_zero_measurement():
    values = rows(["LEFT"] * 7)
    values[-1].update(received_at=values[-1]["timestamp"] - .1,
                      receive_latency_ms=-4., face_latency_ms=math.inf)
    result = report(values)
    assert result["events"][0]["activation_received_at"] is None
    assert result["events"][0]["activation_receive_latency_ms"] is None
    assert result["face_inference_latency_ms"]["count"] == 0
    assert result["exclusions"] == {"receive_timestamp_before_capture": 1}


def test_empty_report_has_no_accuracy_claims_or_invented_latency():
    result = report([])
    assert result["collected"] == result["event_count"] == 0
    assert result["unknown_rate"] is None
    assert result["first_capture_timestamp"] is None
    assert result["capture_to_receive_latency_ms"]["count"] == 0
    assert "no session" in result["production_effects"]


def test_report_uses_requested_classifier_without_modifying_source_rows():
    values = rows(["LEFT"] * 7)
    for row in values:
        row["predicted_label"] = "CENTER"
    assert report(values)["event_count"] == 1
    baseline = summarize_timing(values, "predicted_label", "CENTER")
    assert baseline["event_count"] == 0
    assert values[0]["region_predicted_label"] == "LEFT"
