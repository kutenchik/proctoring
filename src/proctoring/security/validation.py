"""A local audit prerequisite, not an anti-tamper or authorization boundary.

Real keyboard suppression must not start until the independent native recovery
audit has passed for this Python installation, machine, and source tree.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys


ROOT = Path(__file__).resolve().parents[3]
MANDATORY_CHECKS = frozenset({
    "normal_enable_disable", "emergency_shortcut", "main_graceful_exit",
    "heartbeat_loss", "main_crash", "repeated_enable_disable",
    "pin_dialog_interaction", "owned_helper_forced_release",
})


def source_fingerprint(root: Path = ROOT) -> str:
    """Include recovery code and its UI/controller integration, not credentials."""
    root = Path(root)
    paths = list((root / "src/proctoring/security").glob("*.py"))
    paths += [root / name for name in (
        "src/proctoring/controller.py", "src/proctoring/ui/window.py",
        "src/proctoring/config.py", "src/proctoring/__main__.py",
        "scripts/validate_protection.py",
    )]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def machine_identity() -> dict[str, str]:
    return {
        "system": platform.system(), "release": platform.release(),
        "machine": platform.machine(),
        "host_hash": hashlib.sha256(platform.node().encode("utf-8")).hexdigest(),
        "python_executable": str(Path(sys.executable).resolve()).casefold(),
    }


def require_recovery_validation(path: Path, max_age_hours: float = 24) -> dict:
    """Reject missing, stale, partial, or incompatible native audit reports."""
    if isinstance(max_age_hours, bool) or not math.isfinite(max_age_hours) or max_age_hours <= 0:
        raise ValueError("Recovery validation age must be finite and positive")
    instruction = "Run scripts/validate_protection.py successfully before enabling protection"
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("report must be an object")
        if report.get("schema") != 1 or report.get("mode") != "audit_only":
            raise ValueError("unsupported recovery report")
        if report.get("blocking_enabled") is not False or report.get("passed") is not True:
            raise ValueError("independent audit did not pass")
        if report.get("identity") != machine_identity():
            raise ValueError("machine, Windows version, or Python environment changed")
        if report.get("fingerprint") != source_fingerprint():
            raise ValueError("protection or recovery source changed since the audit")
        generated = datetime.fromisoformat(report["generated_at"])
        if generated.tzinfo is None:
            raise ValueError("audit timestamp has no timezone")
        age = (datetime.now(timezone.utc) - generated).total_seconds()
        if age < -60 or age > max_age_hours * 3600:
            raise ValueError("recovery audit expired or has a future timestamp")
        checks = report.get("checks")
        if not isinstance(checks, list):
            raise ValueError("audit checks missing")
        checked = {}
        for check in checks:
            if not isinstance(check, dict) or not isinstance(check.get("name"), str):
                raise ValueError("malformed audit check")
            if check["name"] in checked:
                raise ValueError("duplicate audit check")
            checked[check["name"]] = check
        for name in MANDATORY_CHECKS:
            check = checked.get(name, {})
            if check.get("passed") is not True or check.get("kind") != "native_audit":
                raise ValueError(f"native audit check incomplete: {name}")
        if any(check.get("passed") is not True for check in checks):
            raise ValueError("an audit check failed")
        return report
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{instruction}: {exc}") from exc
