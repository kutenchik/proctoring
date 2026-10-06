"""Validate independent recovery on Windows without suppressing any keys.

Only this script's helper and temporary parent fixture are stopped. No process
allowlist, foreground restoration, or real keyboard blocking is enabled here.
The emergency chord is injected once per emergency check through SendInput;
the script refuses to do so while a relevant physical key is already held.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from proctoring.security.validation import ROOT, machine_identity, source_fingerprint
from proctoring.security.helper_process import OwnedHelperProcess


def parent_fixture() -> int:
    """Create an owned native HWND for graceful-exit/crash recovery tests."""
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication([])
    window = QWidget()
    print(json.dumps({"pid": os.getpid(), "hwnd": int(window.winId())}), flush=True)
    command = sys.stdin.readline().strip()
    if command == "crash":
        os._exit(23)
    window.close()
    app.processEvents()
    return 0


class Helper:
    def __init__(self, pid: int, hwnd: int):
        self.pid, self.hwnd = pid, hwnd
        self.messages: list[dict] = []
        self.incoming: queue.Queue = queue.Queue()
        self.errors: list[str] = []
        self.next_id = 0
        self.owner_process = None
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "proctoring.security.helper", "--parent-pid", str(pid)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=flags,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.error_reader = threading.Thread(target=self._read_errors, daemon=True)
        self.error_reader.start()
        try:
            ready = self.wait(lambda item: item.get("kind") == "ready", timeout=10)
            if ready.get("platform_supported") is not True:
                raise RuntimeError("Native Windows protection helper is unavailable")
            self.owner_process = OwnedHelperProcess(ready.get("pid"), self.process)
        except BaseException:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            try:
                message = json.loads(line)
                self.messages.append(message)
                self.incoming.put(message)
            except ValueError:
                self.errors.append("Helper emitted invalid JSON")

    def _read_errors(self):
        for line in self.process.stderr:
            self.errors.append(line.rstrip())

    def wait(self, predicate, timeout=5) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                item = self.incoming.get(timeout=min(.1, max(.001, deadline - time.monotonic())))
            except queue.Empty:
                if self.process.poll() is not None and not self.reader.is_alive():
                    break
                continue
            if predicate(item):
                return item
        raise RuntimeError(f"Helper response missing; exit={self.process.poll()}, errors={self.errors[-3:]}")

    def send(self, command: str, **kwargs) -> int:
        self.next_id += 1
        message = {"command": command, "request_id": self.next_id, **kwargs}
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        return self.next_id

    def command(self, command: str, **kwargs) -> dict:
        request_id = self.send(command, **kwargs)
        return self.wait(lambda item: item.get("kind") == "status" and item.get("request_id") == request_id)

    def enable(self, timeout=5) -> dict:
        status = self.command("enable", pid=self.pid, hwnd=self.hwnd, blocking=False,
                              heartbeat_timeout=timeout, max_session_seconds=30)
        assert status.get("armed") is True, status
        assert status.get("blocking_enabled") is False, status
        assert status.get("hook_installed") is True, status
        assert status.get("hotkey_registered") is True, status
        return status

    def recovered(self, timeout=5) -> dict:
        status = self.wait(lambda item: item.get("kind") == "status"
                          and item.get("armed") is False, timeout)
        assert_released(status)
        return status

    def close(self):
        if self.process.poll() is None:
            try:
                self.send("shutdown", reason="audit_cleanup")
                self.process.wait(timeout=3)
            except (OSError, BrokenPipeError, subprocess.TimeoutExpired):
                # These are our own audit-only helpers. Process termination also
                # causes Windows to remove their process-owned hooks/hotkeys.
                if self.owner_process is not None:
                    self.owner_process.terminate_and_wait(timeout=1.)
                if self.process.poll() is None:
                    self.process.terminate()
                self.process.wait(timeout=3)
        if self.owner_process is not None and self.owner_process.alive():
            self.owner_process.terminate_and_wait(timeout=1.)
        self.reader.join(timeout=1)
        self.error_reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()
        if self.owner_process is not None:
            self.owner_process.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def assert_released(status: dict):
    assert status.get("armed") is False, status
    assert status.get("blocking_enabled") is False, status
    assert status.get("hook_installed") is False, status
    assert status.get("hotkey_registered") is False, status


def inject_emergency_chord():
    """Exercise RegisterHotKey/WH_KEYBOARD_LL, never a helper RPC stand-in."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetForegroundWindow.restype = wintypes.HWND
    if window_pid(user32.GetForegroundWindow()) != os.getpid():
        raise RuntimeError("Recovery audit refused input: the foreground window does not belong to this audit")
    keys = [0x11, 0x10, 0x12, 0x51]  # Ctrl, Shift, Alt, Q
    if any(user32.GetAsyncKeyState(key) & 0x8000 for key in keys):
        raise RuntimeError("Recovery audit deferred: release Ctrl, Shift, Alt and Q before rerunning")

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("event",)
        _fields_ = [("type", wintypes.DWORD), ("event", UNION)]

    events = [INPUT(type=1, ki=KEYBDINPUT(wVk=key)) for key in keys]
    events += [INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=2)) for key in reversed(keys)]
    batch = (INPUT * len(events))(*events)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    sent = user32.SendInput(len(events), batch, ctypes.sizeof(INPUT))
    if sent != len(events):
        # Always release only the keys this audit attempted to press.
        releases = (INPUT * len(keys))(*events[len(keys):])
        user32.SendInput(len(keys), releases, ctypes.sizeof(INPUT))
        raise RuntimeError(f"SendInput sent {sent}/{len(events)} emergency key events")


def window_pid(hwnd: int) -> int:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def activate_own_window(app, window):
    """Only activate an audit-owned window, and verify before injecting keys."""
    window.showNormal()
    window.raise_()
    window.activateWindow()
    deadline = time.monotonic() + 1
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    while time.monotonic() < deadline:
        app.processEvents()
        if window_pid(user32.GetForegroundWindow()) == os.getpid():
            return
        time.sleep(.02)
    raise RuntimeError("Windows did not activate the audit window; native key injection was skipped")


def run_checks(app, owner) -> list[dict]:
    checks = []
    pid, hwnd = os.getpid(), int(owner.winId())

    def record(name, operation):
        started = time.monotonic()
        try:
            detail = operation()
            check = {"name": name, "kind": "native_audit", "passed": True, "detail": detail}
        except Exception as exc:
            check = {"name": name, "kind": "native_audit", "passed": False,
                     "detail": f"{type(exc).__name__}: {exc}"}
        check["duration_seconds"] = round(time.monotonic() - started, 3)
        checks.append(check)
        print(f"{'PASS' if check['passed'] else 'FAIL'} {name}: {check['detail']}", flush=True)

    def normal():
        with Helper(pid, hwnd) as helper:
            helper.enable()
            assert_released(helper.command("disable", reason="normal_disable"))
        return "Native hook/hotkey installed in audit mode, then both removed by disable."

    def emergency():
        with Helper(pid, hwnd) as helper:
            helper.enable()
            activate_own_window(app, owner)
            inject_emergency_chord()
            recovered = helper.recovered()
            assert "emergency" in recovered.get("reason", "").lower(), recovered
        return "SendInput Ctrl+Shift+Alt+Q reached native recovery; hook and hotkey removed."

    def heartbeat_loss():
        with Helper(pid, hwnd) as helper:
            helper.enable(timeout=.75)
            recovered = helper.recovered(timeout=3)
            assert "heartbeat" in recovered.get("reason", "").lower(), recovered
        return "Independent helper removed its hook/hotkey after 0.75 s without a heartbeat."

    def repeated():
        with Helper(pid, hwnd) as helper:
            for _ in range(5):
                helper.enable()
                assert_released(helper.command("disable", reason="repeat_cycle"))
        return "Five enable/disable cycles; every cycle removed hook and hotkey."

    def forced_release():
        from proctoring.security.settings import ProtectionConfig
        from proctoring.security.windows import WindowsProtection
        client = WindowsProtection(ProtectionConfig(enabled=True), test_lease_seconds=5.)
        try:
            client.configure_window(hwnd, pid)
            client._spawn()
            # Explicit audit-only enable: never call arm(), which requests real
            # suppression. This validates the production fallback before the
            # recovery report permits real suppression.
            status = client._request("enable", pid=pid, hwnd=hwnd, blocking=False,
                                     heartbeat_timeout=2., max_session_seconds=5.,
                                     foreground_poll_ms=100)
            assert status.get("armed") is True and status.get("blocking_enabled") is False, status
            assert status.get("hook_installed") is True and status.get("hotkey_registered") is True, status
            owner_process = client._helper_process
            assert owner_process is not None and owner_process.alive()
            original = client._request

            def unavailable_ack(command, *args, **kwargs):
                if command == "disable":
                    raise RuntimeError("Simulated missing disable acknowledgement")
                return original(command, *args, **kwargs)

            client._request = unavailable_ack
            client.release("audit_forced_release")
            assert not owner_process.alive(), "Actual hook-owning helper still alive after fallback"
            assert client._process.poll() is not None, "Owned launcher still alive after fallback"
            assert not client.armed and client.status == "RECOVERY"
            with Helper(pid, hwnd) as replacement:
                replacement.enable()
                assert_released(replacement.command("disable", reason="post_fallback_check"))
            return "Missing disable acknowledgement terminated the retained hook owner and launcher before returning; a new audit helper reacquired and released the hotkey/hook."
        finally:
            client.close()

    def parent_exit(crash):
        fixture = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--parent-fixture"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        info_queue = queue.Queue()
        fixture_owner = None
        threading.Thread(target=lambda: info_queue.put(fixture.stdout.readline()), daemon=True).start()
        try:
            info = json.loads(info_queue.get(timeout=10))
            fixture_owner = OwnedHelperProcess(info["pid"], fixture)
            with Helper(info["pid"], info["hwnd"]) as helper:
                helper.enable(timeout=5)
                fixture.stdin.write("crash\n" if crash else "exit\n")
                fixture.stdin.flush()
                fixture.wait(timeout=5)
                expected = 23 if crash else 0
                assert fixture.returncode == expected, fixture.returncode
                released = helper.recovered(timeout=3)
                assert "parent" in released.get("reason", "").lower(), released
                helper.process.wait(timeout=3)
            return f"Owned parent fixture exited with code {expected}; helper detected parent death and removed hooks."
        finally:
            if fixture_owner is not None:
                if fixture_owner.alive():
                    fixture_owner.terminate_and_wait(timeout=1.)
                fixture_owner.close()
            if fixture.poll() is None:
                fixture.terminate()
                fixture.wait(timeout=3)
            for stream in (fixture.stdin, fixture.stdout, fixture.stderr):
                stream.close()

    def pin_dialog():
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        from proctoring.security.pin import PinVerifier
        from proctoring.ui.window import PinDialog
        import secrets
        pin = str(secrets.randbelow(900000) + 100000)
        dialog = PinDialog(PinVerifier(pin), "Recovery audit — no restrictions", owner)
        # Native input is only permitted while our own audit dialog is foreground.
        # The existing proctoring application and other user windows are untouched.
        dialog.setModal(True)
        try:
            with Helper(pid, hwnd) as helper:
                helper.enable()
                activate_own_window(app, dialog)
                assert window_pid(int(dialog.winId())) == pid
                QTest.keyClicks(dialog.pin_edit, "invalid")
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
                assert dialog.result() != QDialog.DialogCode.Accepted
                QTest.keyClicks(dialog.pin_edit, pin)
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
                assert dialog.result() == QDialog.DialogCode.Accepted
                # Exercise the global recovery route with the native PIN window
                # open again; its modal Qt loop is irrelevant to helper recovery.
                activate_own_window(app, dialog)
                inject_emergency_chord()
                released = helper.recovered()
                assert "emergency" in released.get("reason", "").lower(), released
        finally:
            dialog.close()
            app.processEvents()
        return "Native same-process PIN HWND accepted/rejected PIN via QtTest; native emergency chord released the helper with dialog open."

    record("normal_enable_disable", normal)
    record("emergency_shortcut", emergency)
    record("main_graceful_exit", lambda: parent_exit(False))
    record("heartbeat_loss", heartbeat_loss)
    record("main_crash", lambda: parent_exit(True))
    record("repeated_enable_disable", repeated)
    record("pin_dialog_interaction", pin_dialog)
    record("owned_helper_forced_release", forced_release)
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/protection-validation.json")
    parser.add_argument("--parent-fixture", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Native recovery validation must run on the demonstration Windows machine")
    # Do not inherit offscreen mode from a unit-test shell; native HWNDs and the
    # Windows hook/hotkey APIs must genuinely be exercised for this report.
    os.environ["QT_QPA_PLATFORM"] = "windows"
    if args.parent_fixture:
        return parent_fixture()
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    app = QApplication([])
    owner = QWidget()
    owner.setWindowTitle("Proctoring independent recovery audit")
    owner.resize(430, 150)
    layout = QVBoxLayout(owner)
    layout.addWidget(QLabel("Independent recovery audit\n\nKeyboard blocking is disabled.\nThis temporary test window closes automatically."))
    before = source_fingerprint()
    checks = run_checks(app, owner)
    after = source_fingerprint()
    if before != after:
        checks.append({"name": "source_unchanged", "kind": "native_audit", "passed": False,
                       "detail": "Source changed during audit; rerun after implementation finishes."})
    report = {
        "schema": 1, "mode": "audit_only", "blocking_enabled": False,
        "passed": all(check["passed"] for check in checks),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": machine_identity(), "fingerprint": after, "checks": checks,
        "limitations": [
            "No shortcut suppression or foreground containment was enabled.",
            "Injected emergency input and QtTest PIN interaction are automated native checks, not physical user tests.",
            "Manual Windows matrix and hardware monitoring recovery still need separate validation.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    owner.close()
    app.processEvents()
    print(f"Report: {args.output.resolve()}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
