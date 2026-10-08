"""Portable executable entry point, including the independent recovery audit."""
from pathlib import Path
import subprocess
import sys


def _config_argument(arguments: list[str]) -> Path:
    from .config import DEFAULT_CONFIG
    for index, value in enumerate(arguments):
        if value == "--config" and index + 1 < len(arguments):
            return Path(arguments[index + 1])
        if value.startswith("--config="):
            return Path(value.split("=", 1)[1])
    return DEFAULT_CONFIG


def ensure_recovery_audit(config) -> None:
    """Fail closed; a source-Python audit cannot authorize a different EXE."""
    from .security.validation import require_recovery_validation
    from .security.launch import audit_command
    if not config.protection.enabled:
        return
    path = config.protection.validation_report
    try:
        require_recovery_validation(path, config.protection.validation_max_age_hours)
        return
    except ValueError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        audit_command(path),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", timeout=90,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    path.with_suffix(".log").write_text(result.stdout or "", encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Recovery validation failed. See {path.with_suffix('.log')}. "
                           "Release Ctrl/Shift/Alt/Q, close other proctoring instances, and retry.")
    require_recovery_validation(path, config.protection.validation_max_age_hours)


def main() -> int:
    arguments = sys.argv[1:]
    # Helper stdin/stdout remain genuine pipes; never enter the GUI or audit again.
    if arguments and arguments[0] == "--protection-helper":
        from .security.helper import main as helper_main
        return helper_main(arguments[1:])
    if arguments and arguments[0] in ("--validate-protection", "--protection-parent-fixture"):
        from .security.audit import main as audit_main
        audit_args = arguments[1:]
        if arguments[0] == "--protection-parent-fixture":
            audit_args = ["--parent-fixture", *audit_args]
        return audit_main(audit_args)
    if arguments and arguments[0] == "--package-smoke-test":
        from .config import load_config
        from .package_smoke import run_package_smoke
        return run_package_smoke(load_config(_config_argument(arguments)), Path(arguments[1]))
    try:
        from .config import load_config
        if "--help" not in arguments and "-h" not in arguments:
            ensure_recovery_audit(load_config(_config_argument(arguments)))
        from .__main__ import main as app_main
        return app_main()
    except Exception as error:
        # A double-clicked console may be hidden. Make startup failures visible.
        message = f"Local Proctoring could not start:\n\n{error}"
        print(message, file=sys.stderr)
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Local Proctoring", 0x10)
        return 2
