"""Bounded native shortcut tests against an owned temporary Windows test window.

Run the audit-only validate_protection.py FIRST. This script then briefly enables
real restrictions; every enable has an independent five-second maximum lease.
It never opens, kills, or sends input to an unrelated application.
"""
import argparse
import ctypes
from ctypes import wintypes
from dataclasses import replace
import json
import os
from pathlib import Path
import time

from proctoring.config import DEFAULT_CONFIG, load_config
from proctoring.security.validation import require_recovery_validation, source_fingerprint
from proctoring.security.windows import WindowsProtection


def inject(keys, repeat_last=1):
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(pid))
    if pid.value != os.getpid():
        raise RuntimeError("Input skipped: the foreground window is not owned by this test")
    user.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user.GetAsyncKeyState.restype = ctypes.c_short
    if any(user.GetAsyncKeyState(key) & 0x8000 for key in {*keys, 0x11, 0x10, 0x12, 0x5B, 0x5C}):
        raise RuntimeError("Input skipped: a relevant key is already held")
    class K(ctypes.Structure):
        _fields_ = [("vk", wintypes.WORD), ("scan", wintypes.WORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]
    class M(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG), ("data", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]
    class U(ctypes.Union):
        _fields_ = [("keyboard", K), ("mouse", M)]
    class I(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("payload", U)]
    def item(key, up=False):
        # Distinguish the dedicated Insert key from the numpad's Insert/0 key.
        # Without EXTENDEDKEY, Shift changes the generated key into numpad 0.
        flags = (2 if up else 0) | (1 if key in (0x2D, 0x2C, 0x5B, 0x5C) else 0)
        return I(1, U(keyboard=K(key, 0, flags, 0, 0)))
    values = [item(k) for k in keys] + [item(keys[-1]) for _ in range(repeat_last - 1)]
    values += [item(k, True) for k in reversed(keys)]
    batch = (I * len(values))(*values)
    user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(I), ctypes.c_int]
    user.SendInput.restype = wintypes.UINT
    sent = user.SendInput(len(values), batch, ctypes.sizeof(I))
    if sent != len(values):
        releases = (I * len(keys))(*[item(k, True) for k in reversed(keys)])
        user.SendInput(len(keys), releases, ctypes.sizeof(I))
        raise RuntimeError(f"Only {sent}/{len(values)} native input events were accepted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly enable bounded real suppression tests")
    parser.add_argument("--output", type=Path, default=Path("artifacts/protection-native-tests.json"))
    args = parser.parse_args()
    if not args.run:
        parser.error("Use --run after completing the recovery audit")
    config = load_config(DEFAULT_CONFIG.with_name("protected-demo.toml"))
    require_recovery_validation(config.protection.validation_report)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget
    from validate_protection import activate_own_window
    app = QApplication([])
    window = QWidget()
    window.setWindowTitle("Proctoring bounded native protection tests")
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel("Controlled shortcut tests — temporary window\nEach restriction lease expires within 5 seconds."))
    edit = QLineEdit("proctoring-test-copy")
    layout.addWidget(edit)
    window.resize(540, 160)
    results = []
    # Copy the complete clipboard MIME data so test copy/paste does not discard it.
    from PySide6.QtCore import QMimeData
    saved_clipboard = QMimeData()
    current = app.clipboard().mimeData()
    if current:
        for fmt in current.formats():
            saved_clipboard.setData(fmt, current.data(fmt))
    protector = WindowsProtection(replace(config.protection, heartbeat_timeout_seconds=2.), test_lease_seconds=5.)
    protector.configure_window(int(window.winId()), os.getpid())

    def pump(seconds=.15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            protector.heartbeat()
            time.sleep(.01)

    def focus_edit():
        activate_own_window(app, window)
        edit.setFocus()
        edit.setText("proctoring-test-copy")
        edit.selectAll()
        pump(.05)

    def restored():
        assert not protector.armed, protector.diagnostics
        assert protector.diagnostics.get("hook_installed") is False, protector.diagnostics
        assert protector.diagnostics.get("hotkey_registered") is False, protector.diagnostics
        focus_edit()
        app.clipboard().setText("sentinel")
        inject([0x11, 0x43])
        pump()
        assert app.clipboard().text() == "proctoring-test-copy", "Native copy was not restored after release"

    cases = [
        ("Alt+Tab", [0x12, 0x09], "BLOCKED_ALT_TAB"),
        ("Alt+Shift+Tab", [0x12, 0x10, 0x09], "BLOCKED_ALT_TAB"),
        ("Left Windows key", [0x5B], "BLOCKED_WINDOWS_KEY"),
        ("Right Windows key", [0x5C], "BLOCKED_WINDOWS_KEY"),
        ("Ctrl+C held", [0x11, 0x43], "BLOCKED_COPY"),
        ("Ctrl+V", [0x11, 0x56], "BLOCKED_PASTE"),
        ("Ctrl+Insert", [0x11, 0x2D], "BLOCKED_COPY"),
        ("Shift+Insert", [0x10, 0x2D], "BLOCKED_PASTE"),
        ("PrintScreen", [0x2C], "BLOCKED_SCREENSHOT"),
        ("Alt+F4", [0x12, 0x73], "BLOCKED_CLOSE"),
        ("Alt+Esc", [0x12, 0x1B], "BLOCKED_ALT_ESCAPE"),
        ("Ctrl+Esc", [0x11, 0x1B], "BLOCKED_START_MENU"),
    ]
    try:
        for name, keys, expected in cases:
            check = {"name": name, "kind": "native_automated", "passed": False, "restored": False}
            armed_this_check = False
            try:
                focus_edit()
                app.clipboard().setText("sentinel")
                protector.arm()
                armed_this_check = True
                protector.drain_events()
                inject(keys, repeat_last=3 if "held" in name else 1)
                pump()
                events = [e for e in protector.drain_events() if e["event_type"] == expected]
                assert len(events) == 1 and events[0]["details"].get("suppressed") is True, events
                if expected == "BLOCKED_COPY":
                    assert app.clipboard().text() == "sentinel"
                if expected == "BLOCKED_PASTE":
                    assert edit.text() == "proctoring-test-copy"
                check["passed"] = True
            except Exception as error:
                check["error"] = f"{type(error).__name__}: {error}"
            finally:
                protector.release("native_test_complete")
                if armed_this_check:
                    try:
                        restored()
                        check["restored"] = True
                    except Exception as error:
                        check["restore_error"] = str(error)
                        check["passed"] = False
                else:
                    check.update(input_not_run=True, restored=None)
            results.append(check)
            print(json.dumps(check), flush=True)
            if not check["passed"]:
                break
        if all(c["passed"] for c in results):
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QDialog, QDialogButtonBox
            from proctoring.security.pin import PinVerifier
            from proctoring.ui.window import PinDialog
            import secrets
            pin = str(secrets.randbelow(900000) + 100000)
            dialog = PinDialog(PinVerifier(pin), "Bounded native protection test", window)
            check = {"name": "PIN dialog and emergency during real protection", "kind": "native_automated", "passed": False}
            try:
                focus_edit()
                protector.arm()
                dialog.setModal(True)
                activate_own_window(app, dialog)
                QTest.keyClicks(dialog.pin_edit, "invalid")
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
                assert dialog.result() != QDialog.DialogCode.Accepted
                QTest.keyClicks(dialog.pin_edit, pin)
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
                assert dialog.result() == QDialog.DialogCode.Accepted
                activate_own_window(app, dialog)
                inject([0x11, 0x10, 0x12, 0x51])
                pump(.3)
                assert protector.status == "RECOVERY" and not protector.armed
                dialog.close()
                restored()
                check.update(passed=True, restored=True)
            except Exception as error:
                check["error"] = f"{type(error).__name__}: {error}"
            finally:
                protector.release("native_pin_cleanup")
                dialog.close()
            results.append(check)
            print(json.dumps(check), flush=True)
        if all(c["passed"] for c in results):
            check = {"name": "Ctrl+Shift+Alt+Q during real protection", "kind": "native_automated", "passed": False}
            try:
                focus_edit()
                protector.arm()
                # Alt+Tab is attempted while all recovery modifiers are held;
                # Q must release protection even during another blocked action.
                inject([0x11, 0x10, 0x12, 0x09, 0x51])
                pump(.3)
                assert protector.status == "RECOVERY" and not protector.armed, protector.diagnostics
                restored()
                check.update(passed=True, restored=True)
            except Exception as error:
                check["error"] = f"{type(error).__name__}: {error}"
            finally:
                protector.release("native_emergency_test_cleanup")
            results.append(check)
            print(json.dumps(check), flush=True)
    finally:
        protector.close()
        app.clipboard().setMimeData(saved_clipboard)
        window.close()
        app.processEvents()
    report = {"passed": len(results) == len(cases) + 2 and all(c["passed"] for c in results),
              "kind": "native_automated", "max_lease_seconds": 5, "fingerprint": source_fingerprint(),
              "checks": results,
              "limitations": ["Injected input into an owned test window; physical-key checks remain manual.",
                              "CV disconnect and calibrated protected exam rehearsal are separate checks."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
