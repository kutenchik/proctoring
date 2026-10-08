"""Frozen process routing and audit identity tests; never install native hooks."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

from proctoring.security import audit, launch, validation


@pytest.fixture
def frozen_exe(tmp_path, monkeypatch):
    executable = tmp_path / "Build with spaces" / "LocalProctoring.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"test executable and bundled recovery code")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    return executable


def complete_report():
    return {
        "schema": 1, "mode": "audit_only", "blocking_enabled": False,
        "passed": True, "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": validation.machine_identity(),
        "fingerprint": validation.source_fingerprint(),
        "checks": [{"name": name, "kind": "native_audit", "passed": True}
                   for name in sorted(validation.MANDATORY_CHECKS)],
    }


def test_frozen_private_routes_use_same_exe_without_python_module_switch(frozen_exe, tmp_path):
    assert launch.helper_command(123) == [str(frozen_exe), "--protection-helper", "--parent-pid", "123"]
    assert launch.parent_fixture_command() == [str(frozen_exe), "--protection-parent-fixture"]
    output = tmp_path / "report with spaces.json"
    assert launch.audit_command(output) == [str(frozen_exe), "--validate-protection", "--output", str(output)]


def test_source_routes_still_use_python_modules(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert launch.helper_command(123) == [sys.executable, "-m", "proctoring.security.helper", "--parent-pid", "123"]
    assert launch.parent_fixture_command() == [sys.executable, "-m", "proctoring.security.audit", "--parent-fixture"]
    assert launch.audit_command(Path("report.json")) == [sys.executable, "-m", "proctoring.security.audit", "--output", "report.json"]


def test_frozen_fingerprint_tracks_actual_binary_not_extraction_directory(frozen_exe, monkeypatch):
    before = validation.source_fingerprint()
    monkeypatch.setattr(sys, "_MEIPASS", "/different/extraction", raising=False)
    assert validation.source_fingerprint() == before
    # Same-length replacement also invalidates the audit; no stale hash cache.
    original = frozen_exe.read_bytes()
    frozen_exe.write_bytes(b"X" + original[1:])
    assert validation.source_fingerprint() != before


def test_frozen_audit_requires_exact_binary_and_executable_path(frozen_exe, tmp_path, monkeypatch):
    report = complete_report()
    output = tmp_path / "audit.json"
    output.write_text(json.dumps(report), encoding="utf-8")
    assert validation.require_recovery_validation(output) == report
    replacement = frozen_exe.with_name("Moved.exe")
    replacement.write_bytes(frozen_exe.read_bytes())
    monkeypatch.setattr(sys, "executable", str(replacement))
    with pytest.raises(ValueError, match="machine, Windows version, or Python environment changed"):
        validation.require_recovery_validation(output)
    monkeypatch.setattr(sys, "executable", str(frozen_exe))
    frozen_exe.write_bytes(b"changed")
    with pytest.raises(ValueError, match="source changed"):
        validation.require_recovery_validation(output)


def test_missing_frozen_audit_fails_closed_with_packaged_instruction(frozen_exe, tmp_path):
    with pytest.raises(ValueError, match="--validate-protection"):
        validation.require_recovery_validation(tmp_path / "missing.json")


def test_parent_fixture_entry_accepts_forwarded_arguments(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(audit, "parent_fixture", lambda: 17)
    assert audit.main(["--parent-fixture"]) == 17


def test_moving_native_audit_into_package_remains_source_fingerprinted(tmp_path):
    security = tmp_path / "src/proctoring/security"
    security.mkdir(parents=True)
    for name in ("src/proctoring/controller.py", "src/proctoring/ui/window.py",
                 "src/proctoring/config.py", "src/proctoring/__main__.py",
                 "scripts/validate_protection.py", "src/proctoring/security/audit.py",
                 "src/proctoring/security/launch.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original", encoding="utf-8")
    before = validation.source_fingerprint(tmp_path)
    (security / "audit.py").write_text("changed audit", encoding="utf-8")
    assert validation.source_fingerprint(tmp_path) != before
