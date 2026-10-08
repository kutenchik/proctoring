"""Replay an explicit numerical export for development, never human validation.

No webcam, image/video persistence, session events or production fit is
involved. Screen-region mode can replay the existing event engine in isolation.
The candidate learns only from that export's accepted calibration
rows. Existing validation rows are reused solely to reveal development errors
and distribution shift; a new operator pass is required after any changes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from proctoring.vision.diagnostic_validation import DiagnosticValidation
from proctoring.vision.settings import VisionConfig
from proctoring.vision.screen_region import ScreenRegionCandidate
from proctoring.vision.screen_region_protocol import TRAINING_PROTOCOL


def _provenance(payload, digest):
    attempt = payload.get("attempt_identity") or {}
    source = (payload.get("validation") or {}).get("source_attempt_identity") or {}
    for identity in (attempt, source):
        claimed = identity.get("calibration_sha256")
        if claimed is not None and claimed != digest:
            raise ValueError("Claimed calibration hash does not match the calibration object")
    for key in ("attempt_id", "baseline_id", "calibration_sha256"):
        if key in attempt and key in source and attempt[key] != source[key]:
            raise ValueError(f"Validation source does not match selected calibration: {key}")
    verified = (bool(attempt.get("attempt_id")) and source.get("attempt_id") == attempt["attempt_id"]
                and attempt.get("calibration_sha256") == source.get("calibration_sha256") == digest)
    return ("verified matching attempt IDs and calibration hashes" if verified else
            "unverified: legacy or incomplete source identity; filenames do not establish matching eyewear")


def replay(payload, config=None, *, candidate="openness"):
    calibration = payload["calibration"]
    digest = hashlib.sha256(json.dumps(calibration, sort_keys=True, separators=(",", ":"),
                                      allow_nan=False).encode("utf-8")).hexdigest()
    provenance = _provenance(payload, digest)
    if candidate == "screen-region":
        return replay_region(payload, digest, provenance, config)
    sequence = DiagnosticValidation(calibration, config or VisionConfig(), include_openness_candidate=True)
    original = payload.get("validation")
    result = {
        "purpose": "DEVELOPMENT REPLAY / UNVALIDATED; not a new human test",
        "source_attempt_identity": payload.get("attempt_identity"),
        "calibration_sha256": digest,
        "provenance": provenance,
        "configuration": "current VisionConfig defaults unless supplied programmatically",
        "shared_baseline_warning": "Equal hashes are the same baseline regardless of filenames or eyewear labels",
        "candidate_calibration": sequence.candidate.fit_report,
        "stored_default_predictions": {},
        "validation_present": original is not None,
    }
    if original is None:
        return result
    for label in sequence.targets:
        target = original.get("targets", {}).get(label)
        if target is None or target.get("window") is None:
            break  # Historical exports have five targets, not closure challenges.
        window = target["window"]
        sequence.start_target(label, window["starts_at"], window["ends_at"])
        rows = original["samples"][label]
        result["stored_default_predictions"][label] = dict(Counter(row["predicted_label"] for row in rows))
        for row in rows:
            sequence.add_sample(row.get("features"), row["timestamp"], row.get("quality"),
                                metadata=row, rejection_reason=row.get("rejection_reason"))
        sequence.finish_target(window["ends_at"])
    report = sequence.report
    result["default_replay_targets"] = report["targets"]
    result["candidate_replay"] = report["openness_candidate"]
    result["missing_challenge_targets"] = [label for label in sequence.targets
                                           if label not in original.get("targets", {})]
    result["new_operator_validation_required"] = True
    return result


def replay_region(payload, digest, provenance, config=None):
    calibration = payload["calibration"]
    config = config or replace(VisionConfig(), **calibration.get("fit_configuration", {}))
    fit = ScreenRegionCandidate(calibration, config).fit_report
    original = payload.get("validation")
    result = {
        "purpose": "DEVELOPMENT REPLAY / UNVALIDATED; not a new human test",
        "calibration_sha256": digest, "provenance": provenance,
        "source_attempt_identity": payload.get("attempt_identity"),
        "candidate_calibration": fit, "new_operator_validation_required": True,
    }
    if calibration.get("protocol") != TRAINING_PROTOCOL:
        result.update(comparison_status="unavailable: missing multipoint on-screen training",
                      missing_training="actual on-screen boundary/layout fixations and repeated CENTER anchor",
                      stored_default_targets=(original or {}).get("targets"),
                      candidate_comparison=None)
        return result
    if original is None:
        result.update(comparison_status="pending separate validation", candidate_comparison=None)
        return result
    timing = original.get("event_timing_config", {})
    sequence = DiagnosticValidation(calibration, config, screen_region_phase="validation",
                                    event_thresholds=timing.get("thresholds_seconds"),
                                    clearing_seconds=timing.get("clearing_seconds", .75))
    specs = {spec["id"]: spec for spec in original.get("target_definitions", [])}
    for label in sequence.targets:
        target = original.get("targets", {}).get(label)
        if target is None or target.get("window") is None:
            break
        window = target["window"]
        if label in specs and specs[label].get("position"):
            sequence.set_target_position(label, specs[label]["position"])
        sequence.start_target(label, window["starts_at"], window["ends_at"])
        for row in original["samples"][label]:
            sequence.add_sample(row.get("features"), row["timestamp"], row.get("quality"),
                                metadata=row, rejection_reason=row.get("rejection_reason"))
        sequence.finish_target(window["ends_at"])
    result.update(comparison_status="development replay only", candidate_comparison=sequence.report)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--candidate", choices=("openness", "screen-region"), default="openness")
    parser.add_argument("--output", type=Path, help="Optional explicit numerical report destination")
    args = parser.parse_args()
    payload = json.loads(args.export.read_text(encoding="utf-8"))
    result = replay(payload, candidate=args.candidate)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        # Do not accidentally overwrite the human-collected source data.
        if args.output.resolve() == args.export.resolve():
            parser.error("Output must differ from the source export")
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Development replay saved: {args.output}")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
