from datetime import datetime, timedelta, timezone
import json

import pytest

from proctoring.security import validation


@pytest.fixture
def audit(tmp_path, monkeypatch):
    monkeypatch.setattr(validation, "source_fingerprint", lambda: "current-source")
    monkeypatch.setattr(validation, "machine_identity", lambda: {"host_hash": "current-host"})
    path = tmp_path / "audit.json"
    report = {
        "schema": 1, "mode": "audit_only", "blocking_enabled": False, "passed": True,
        "identity": validation.machine_identity(), "fingerprint": "current-source",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": [{"name": name, "passed": True, "kind": "native_audit"}
                   for name in sorted(validation.MANDATORY_CHECKS)],
    }
    return path, report


def write(path, report):
    path.write_text(json.dumps(report), encoding="utf-8")


def test_accepts_complete_current_native_recovery_audit(audit):
    path, report = audit
    write(path, report)
    assert validation.require_recovery_validation(path) == report


@pytest.mark.parametrize("key,value", [
    ("schema", 2), ("mode", "simulated"), ("blocking_enabled", True),
    ("passed", False), ("fingerprint", "old-source"), ("identity", {"host_hash": "other"}),
    ("generated_at", "bad-date"), ("generated_at", "2026-01-01T00:00:00"),
    ("checks", None),
])
def test_rejects_incompatible_report(audit, key, value):
    path, report = audit
    report[key] = value
    write(path, report)
    with pytest.raises(ValueError, match="Run scripts/validate_protection.py"):
        validation.require_recovery_validation(path)


@pytest.mark.parametrize("hours", [-1, 25])
def test_rejects_future_or_expired_audit(audit, hours):
    path, report = audit
    report["generated_at"] = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    write(path, report)
    with pytest.raises(ValueError):
        validation.require_recovery_validation(path)


@pytest.mark.parametrize("change", ["missing", "failed", "unit_only", "duplicate"])
def test_all_mandatory_native_checks_are_required(audit, change):
    path, report = audit
    if change == "missing":
        report["checks"].pop()
    elif change == "failed":
        report["checks"][0]["passed"] = False
    elif change == "unit_only":
        report["checks"][0]["kind"] = "unit"
    else:
        report["checks"].append(report["checks"][0])
    write(path, report)
    with pytest.raises(ValueError):
        validation.require_recovery_validation(path)


def test_missing_file_does_not_enable_real_protection(tmp_path):
    with pytest.raises(ValueError):
        validation.require_recovery_validation(tmp_path / "missing.json")


@pytest.mark.parametrize("value", [0, -1, True, float("inf"), float("nan")])
def test_invalid_max_age_rejected(audit, value):
    with pytest.raises(ValueError):
        validation.require_recovery_validation(audit[0], value)


def test_fingerprint_includes_integration_and_validation_source(tmp_path):
    security = tmp_path / "src/proctoring/security"
    security.mkdir(parents=True)
    (security / "helper.py").write_text("hook = False", encoding="utf-8")
    for name in ("src/proctoring/controller.py", "src/proctoring/ui/window.py",
                 "src/proctoring/config.py", "src/proctoring/__main__.py",
                 "scripts/validate_protection.py"):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("pass", encoding="utf-8")
    before = validation.source_fingerprint(tmp_path)
    (tmp_path / "src/proctoring/controller.py").write_text("release_first()", encoding="utf-8")
    assert validation.source_fingerprint(tmp_path) != before
