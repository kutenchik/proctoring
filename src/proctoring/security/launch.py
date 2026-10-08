"""Owned subprocess commands for Python and the bundled Windows executable.

The frozen executable is built with console support so its private helper
routes retain redirected stdin/stdout even when CREATE_NO_WINDOW hides them.
"""
from pathlib import Path
import sys


def helper_command(parent_pid: int) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--protection-helper", "--parent-pid", str(parent_pid)]
    return [sys.executable, "-m", "proctoring.security.helper", "--parent-pid", str(parent_pid)]


def parent_fixture_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--protection-parent-fixture"]
    return [sys.executable, "-m", "proctoring.security.audit", "--parent-fixture"]


def audit_command(output: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--validate-protection", "--output", str(output)]
    return [sys.executable, "-m", "proctoring.security.audit", "--output", str(output)]
