"""Frozen Electron backend entry point. Private child modes precede Qt startup."""
import multiprocessing
import sys


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if not arguments:
        print("Launch LocalProctoring-Electron.exe, not this private backend.", file=sys.stderr)
        return 2
    mode, *remaining = arguments
    if mode == "--packaged-startup-check":
        from proctoring.security.packaged_startup import main as child
    elif mode == "--protection-helper":
        from proctoring.security.helper import main as child
    elif mode == "--protection-guardian":
        from proctoring.security.guardian import main as child
    elif mode == "--protection-parent-fixture":
        from proctoring.security.audit import main as child
        remaining = ["--parent-fixture", *remaining]
    elif mode == "--desktop-bridge":
        from proctoring.desktop_bridge.__main__ import main as child
    elif mode == "--desktop-supervisor":
        from proctoring.desktop_bridge.supervisor import main as child
    elif mode == "--electron-recovery-audit":
        from proctoring.security.electron_audit import main as child
    elif mode == "--electron-protected-test":
        from proctoring.security.electron_protected_test import main as child
    else:
        print("Unknown private backend mode.", file=sys.stderr)
        return 2
    return child(remaining)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
