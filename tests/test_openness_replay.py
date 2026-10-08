"""Provenance checks protect development replay from mixing frozen attempts."""
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "replay_openness", Path(__file__).parents[1] / "scripts" / "replay_openness_candidate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def payload():
    identity = {"attempt_id": "A", "baseline_id": "session-A", "calibration_sha256": "digest"}
    return {"attempt_identity": dict(identity),
            "validation": {"source_attempt_identity": dict(identity)}}


def test_matching_ids_and_computed_hash_are_verified():
    assert module._provenance(payload(), "digest").startswith("verified")


@pytest.mark.parametrize("key", ("attempt_id", "baseline_id", "calibration_sha256"))
def test_replay_rejects_mismatched_source(key):
    value = payload()
    value["validation"]["source_attempt_identity"][key] = "different"
    with pytest.raises(ValueError):
        module._provenance(value, "digest")


def test_matching_but_forged_hashes_are_rejected():
    with pytest.raises(ValueError, match="hash"):
        module._provenance(payload(), "actual-other-digest")


@pytest.mark.parametrize("value", ({}, {"validation": None}, {"attempt_identity": {"attempt_id": "A"}}))
def test_legacy_missing_provenance_is_not_falsely_verified(value):
    assert module._provenance(value, "digest").startswith("unverified")
