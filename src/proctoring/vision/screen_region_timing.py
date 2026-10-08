"""Numerical DEBUG timing reports using an isolated copy of the event engine.

This module cannot write evidence, alter a session, or emit UI alerts. Capture
timestamps establish evidence duration; optional delivery timestamps describe
latency. The face-cadence debug stream is not the production YOLO cadence.
"""
from __future__ import annotations

from collections import Counter
import math
from statistics import median

from ..clock import FakeClock
from ..domain import EventType, Observation
from ..events import EventEngine


_DIRECTIONS = {
    "LEFT": EventType.GAZE_LEFT,
    "RIGHT": EventType.GAZE_RIGHT,
    "DOWN": EventType.GAZE_DOWN,
}


def _number(value):
    return (float(value) if isinstance(value, (int, float))
            and not isinstance(value, bool) and math.isfinite(value) else None)


def _distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0, "min": None, "median": None, "p95": None, "max": None}
    index = .95 * (len(values) - 1)
    low = math.floor(index)
    high = math.ceil(index)
    p95 = values[low] + (values[high] - values[low]) * (index - low)
    return {"count": len(values), "min": values[0], "median": median(values),
            "p95": p95, "max": values[-1]}


def summarize_timing(rows, prediction_key, expected_label, *, thresholds=None,
                     clearing_seconds=.75, max_observation_gap=2.0):
    """Summarize one held-out window, never bridging another target/window.

    Invalid measurements and UNKNOWN are false for every directional event.
    A strict directional run ends on either of them. An already active engine
    event follows the real clearing hysteresis instead, so its duration may
    include a short clearing interval. No unobserved tail is added to a run.

    ``expected_label=None`` leaves blink/closure-transition correctness unscored:
    direction runs remain visible but are not automatically called false.
    Missing receive/inference telemetry remains null, never zero latency.
    """
    defaults = {kind: 3.0 for kind in _DIRECTIONS.values()}
    configured = defaults if thresholds is None else {EventType(k): v for k, v in thresholds.items()}
    selected = {kind: configured[kind] for kind in _DIRECTIONS.values()}
    clock = FakeClock()
    engine = EventEngine(selected, clearing_seconds, clock,
                         max_observation_gap=max_observation_gap)
    exclusions = Counter()
    counts = Counter()
    used = []
    gaps, receive_delays, inference_delays = [], [], []
    runs = []
    run = None
    activations = {}
    changes = []
    last_capture = None
    invalid = 0

    def finish_run():
        nonlocal run
        if run is not None:
            run["observed_duration_seconds"] = run["last_capture_timestamp"] - run["first_capture_timestamp"]
            run["incorrect_direction"] = (run["direction"] != expected_label
                                            if expected_label is not None else None)
            runs.append(run)
            run = None

    for row in rows:
        stamp = _number(row.get("timestamp"))
        if stamp is None:
            exclusions["nonfinite_capture_timestamp"] += 1
            continue
        if last_capture is not None and stamp <= last_capture:
            exclusions["duplicate_or_out_of_order_capture"] += 1
            continue
        gap = stamp - last_capture if last_capture is not None else None
        if gap is not None:
            gaps.append(gap)
        received = _number(row.get("received_at"))
        if received is not None and received < stamp:
            exclusions["receive_timestamp_before_capture"] += 1
            received = None
        if received is not None and used and received < clock.now:
            exclusions["nonmonotonic_receive_timestamp"] += 1
            received = None
        receive_delay = (1000 * (received - stamp) if received is not None
                         else _number(row.get("receive_latency_ms")))
        if receive_delay is not None and receive_delay < 0:
            receive_delay = None
        face_delay = _number(row.get("face_latency_ms"))
        if face_delay is not None and face_delay < 0:
            face_delay = None
        if receive_delay is not None:
            receive_delays.append(receive_delay)
        if face_delay is not None:
            inference_delays.append(face_delay)
        predicted = row.get(prediction_key, "UNKNOWN")
        if row.get("accepted") is False:
            invalid += 1
            predicted = "UNKNOWN"
        if predicted not in (*_DIRECTIONS, "ON_SCREEN", "CENTER", "UNKNOWN"):
            predicted = "UNKNOWN"
        counts[predicted] += 1
        # The current classifier's ON_SCREEN label is not a direction. Neither
        # it nor its legacy CENTER adapter enters directional event conditions.
        if (run is not None and (predicted != run["direction"]
                                 or gap > max_observation_gap)):
            finish_run()
        if predicted in _DIRECTIONS:
            if run is None:
                run = {"direction": predicted, "first_capture_timestamp": stamp,
                       "last_capture_timestamp": stamp, "samples": 1}
            else:
                run["last_capture_timestamp"] = stamp
                run["samples"] += 1

        # Accepted collection rows have monotonic receipt time. A malformed
        # replay receipt cannot reverse the engine clock; record its absence.
        clock.now = max(clock.now if used else stamp, received if received is not None else stamp)
        conditions = {_DIRECTIONS[predicted]: None} if predicted in _DIRECTIONS else {}
        for change in engine.observe(Observation(stamp, conditions, source="debug-screen-region-timing")):
            record = {"event_id": change["event_id"], "event_type": change["event_type"],
                      "action": change["action"], "capture_timestamp": stamp,
                      "received_at": received}
            changes.append(record)
            if change["action"] == "activated":
                duration = change["duration_seconds"]
                first = stamp - duration
                threshold = selected[EventType(change["event_type"])]
                activations[change["event_id"]] = {
                    "first_positive_capture_timestamp": first,
                    "activation_capture_timestamp": stamp,
                    "activation_received_at": received,
                    "capture_duration_at_activation_seconds": duration,
                    "threshold_seconds": threshold,
                    "sampling_overshoot_seconds": duration - threshold,
                    "capture_to_activation_delivery_seconds": received - first if received is not None else None,
                    "delivery_after_threshold_seconds": received - first - threshold if received is not None else None,
                    "activation_receive_latency_ms": receive_delay,
                    "activation_face_latency_ms": face_delay,
                }
        used.append(stamp)
        last_capture = stamp
    finish_run()
    engine.close_all("diagnostic_window_ended")
    events = []
    direction_by_type = {kind.value: label for label, kind in _DIRECTIONS.items()}
    for event in engine.events:
        direction = direction_by_type[event["event_type"]]
        events.append({"event_id": event["event_id"], "direction": direction,
                       "duration_seconds": event["duration_seconds"],
                       "close_reason": event["close_reason"],
                       "incorrect_direction": direction != expected_label if expected_label is not None else None,
                       **activations[event["event_id"]]})
    incorrect_runs = [run for run in runs if run["incorrect_direction"] is True]
    return {
        "status": "DEBUG / UNVALIDATED: isolated numerical event-engine simulation",
        "production_effects": "none: no session, evidence records, snapshots or alerts",
        "stream": "face-cadence diagnostic measurements; not production combined-YOLO delivery timing",
        "expected_label": expected_label,
        "collected": len(used), "invalid_measurements": invalid,
        "predicted_labels": {label: counts[label] for label in ("ON_SCREEN", "CENTER", "LEFT", "RIGHT", "DOWN", "UNKNOWN")},
        "unknown_measurements": counts["UNKNOWN"],
        "unknown_rate": counts["UNKNOWN"] / len(used) if used else None,
        "exclusions": dict(exclusions),
        "observation_gap_seconds": _distribution(gaps),
        "capture_to_receive_latency_ms": _distribution(receive_delays),
        "face_inference_latency_ms": _distribution(inference_delays),
        "first_capture_timestamp": used[0] if used else None,
        "last_capture_timestamp": used[-1] if used else None,
        "observed_span_seconds": used[-1] - used[0] if used else 0.,
        "direction_runs": runs,
        "longest_direction_run_seconds": max((r["observed_duration_seconds"] for r in runs), default=0.),
        "longest_false_direction_run_seconds": (max((r["observed_duration_seconds"] for r in incorrect_runs), default=0.)
                                                  if expected_label is not None else None),
        "run_duration_policy": "first to last same-direction capture only; invalid, UNKNOWN, changed label or stale gap ends a run; no unseen tail",
        "thresholds_seconds": {kind.value: value for kind, value in selected.items()},
        "clearing_seconds": clearing_seconds,
        "max_observation_gap_seconds": max_observation_gap,
        "events": events, "event_changes": changes,
        "event_count": len(events),
        "false_direction_event_count": (sum(e["incorrect_direction"] is True for e in events)
                                         if expected_label is not None else None),
        "event_duration_policy": "existing engine hysteresis can bridge brief clearing after activation; candidate false/UNKNOWN resets immediately",
        "latency_limitations": "null means unavailable; no requirement to alert exactly at threshold; face latency excludes capture and UI delay",
    }
