"""Bounded Windows integration rehearsal using real protection and a fake camera.

This script uses the actual MainWindow, AppController and independent protection
helper. Monitoring observations and monotonic exam time are deterministic test
inputs. It does not claim to test a physical webcam disconnect or real gaze.
Each helper has an independent five-second maximum lease. No unrelated window
receives input, and no unrelated process is terminated.
"""
import argparse
import ctypes
from ctypes import wintypes
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback

from proctoring.clock import FakeClock
from proctoring.config import DEFAULT_CONFIG, load_config
from proctoring.controller import AppController
from proctoring.domain import Observation
from proctoring.security.validation import require_recovery_validation, source_fingerprint
from proctoring.security.windows import WindowsProtection
from proctoring.vision.calibration import Calibration
from proctoring.vision.types import GazeDirection, HealthStatus


class TestCamera:
    """An explicitly injected test adapter; production camera gates stay intact."""

    def __init__(self, settings):
        self.available = True
        self.stopped = False
        self.latest_frame = self.latest_result = self.delivered_result = None
        self.metrics = {}
        self.calibration = Calibration(settings)
        vectors = ((.5, .5, 0., 0.), (.2, .5, -.25, 0.),
                   (.8, .5, .25, 0.), (.5, .8, 0., .3))
        stamp = 0.
        for direction, features in zip((GazeDirection.CENTER, GazeDirection.LEFT,
                                        GazeDirection.RIGHT, GazeDirection.DOWN), vectors):
            for _ in range(settings.calibration_samples):
                stamp += .1
                self.calibration.add_sample(direction, features, stamp, 1.)
        assert self.calibration.fit()[0], "Test calibration setup failed"

    def health(self, now):
        healthy = self.available and not self.stopped
        return HealthStatus(healthy, "Healthy injected test observations" if healthy else
                            "Simulated camera disconnect (no physical camera)")

    def sample(self, now):
        return Observation(now, source="camera") if self.health(now).healthy else None

    def start(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def user32():
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.SetForegroundWindow.restype = wintypes.BOOL
    return user


def foreground_pid(user):
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


def window_pid(user, hwnd):
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def belongs_to_fixture(pid, launched_pid):
    # Windows venv python.exe may be a redirector whose child owns the Qt HWND.
    # Accept descendants only after checking the actual live process lineage.
    import psutil
    if pid == launched_pid:
        return True
    try:
        return any(parent.pid == launched_pid for parent in psutil.Process(pid).parents())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def fixture_main(directory):
    """A hidden, owned child window, used only for a foreign-PID focus attempt."""
    os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication([])
    window = QLabel("Owned proctoring test fixture — closes after the bounded test")
    window.setWindowTitle("Proctoring owned foreign-window fixture")
    window.resize(500, 100)
    directory = Path(directory)
    ready = directory / "fixture.tmp"
    ready.write_text(json.dumps({"pid": os.getpid(), "hwnd": int(window.winId())}), encoding="utf-8")
    ready.replace(directory / "fixture.json")
    timer = QTimer()
    timer.timeout.connect(lambda: app.quit() if (directory / "stop").exists() else None)
    timer.start(50)
    QTimer.singleShot(30000, app.quit)
    return app.exec()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly run bounded real-protection integration tests")
    parser.add_argument("--output", type=Path, default=Path("artifacts/protected-session-tests.json"))
    parser.add_argument("--foreign-fixture", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.foreign_fixture:
        return fixture_main(args.foreign_fixture)
    if not args.run:
        parser.error("Use --run after the independent recovery audit has passed")
    if os.name != "nt":
        parser.error("Native integration tests require Windows")
    config = load_config(DEFAULT_CONFIG.with_name("protected-demo.toml"))
    require_recovery_validation(config.protection.validation_report,
                                max_age_hours=config.protection.validation_max_age_hours)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from proctoring.ui.window import MainWindow
    from validate_protection import activate_own_window

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    native = user32()
    checks = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="protected-session-test-", dir=args.output.parent) as temporary:
        temporary = Path(temporary)
        fixture = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--foreign-fixture", str(temporary)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        fixture_info = None
        deadline = time.monotonic() + 3.
        while time.monotonic() < deadline:
            if (temporary / "fixture.json").exists():
                fixture_info = json.loads((temporary / "fixture.json").read_text(encoding="utf-8"))
                break
            app.processEvents()
            time.sleep(.01)

        def run_case(name, exercise, *, duration=600.):
            result = {"name": name, "kind": "native_application_integration", "passed": False,
                      "restored": False, "camera": "injected_test_adapter", "exam_clock": "FakeClock"}
            clock = FakeClock()
            case_config = replace(config, sessions_dir=temporary / "sessions", snapshots_enabled=False,
                                  duration_seconds=duration)
            monitor = TestCamera(case_config.vision)
            protector = WindowsProtection(case_config.protection, test_lease_seconds=5.)
            controller = AppController(case_config, clock, mode="camera", monitor=monitor, protection=protector)
            window = MainWindow(controller, enable_watchdog=False)
            armed = False

            def pump(seconds=.15):
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    # _tick is called on the UI thread. Background test code
                    # never renews the independent protection lease.
                    app.processEvents()
                    window._tick()
                    time.sleep(.01)

            try:
                result["stage"] = "activate_owned_exam"
                window.show()
                activate_own_window(app, window)
                if foreground_pid(native) != os.getpid():
                    raise RuntimeError("Cannot safely begin: foreground is not the owned exam window")
                result["stage"] = "start_protected_session"
                window._start()
                assert protector.armed and controller.session.running, (
                    f"Start failed: {window.setup_error.text()}; diagnostics={protector.diagnostics}; "
                    f"session_started={controller.session.started}, running={controller.session.running}")
                armed = True
                assert window.isFullScreen(), "Protected MainWindow did not enter fullscreen"
                result["stage"] = "exercise"
                exercise(window, controller, protector, clock, pump, result)
                result["passed"] = True
                result["stage"] = "completed"
            except Exception as error:
                result["error"] = f"{type(error).__name__}: {error}"
                result["error_traceback"] = traceback.format_exc()
            finally:
                # Unhook before evidence finalization, window close, or cleanup.
                protector.release("integration_test_complete")
                try:
                    if controller.session.started and not controller.session.ended:
                        controller.end("integration_test_complete")
                    window._refresh()
                    result["restored"] = (not protector.armed
                                          and protector.diagnostics.get("hook_installed") is False
                                          and protector.diagnostics.get("hotkey_registered") is False)
                    if armed:
                        assert result["restored"], protector.diagnostics
                        assert not window.isFullScreen(), "Exam fullscreen state was not restored"
                    else:
                        result["restored"] = None
                    result["security_event_types"] = [e["event_type"] for e in controller.security_events]
                except Exception as error:
                    result["passed"] = False
                    result["restore_error"] = str(error)
                finally:
                    window.shutdown_ui()
                    window.close()
                    app.processEvents()
            checks.append(result)
            print(json.dumps(result), flush=True)
            return result["passed"]

        def close_and_pin(window, controller, protector, clock, pump, result):
            window.showMinimized()
            pump()
            assert window.isFullScreen() and not window.isMinimized()
            assert any(e["event_type"] == "WINDOW_MINIMIZE_ATTEMPT" for e in controller.security_events)
            QTimer.singleShot(0, lambda: window.active_pin_dialog.reject())
            window.close()
            assert protector.armed and controller.session.running and window.isVisible()
            assert any(e["event_type"] == "WINDOW_CLOSE_ATTEMPT" for e in controller.security_events)

            def authorize():
                assert protector.armed
                dialog = window.active_pin_dialog
                dialog.pin_edit.setText(controller.config.proctor_pin)
                dialog._check()

            QTimer.singleShot(0, authorize)
            window._end_with_pin()
            assert controller.session.end_reason == "proctor_ended" and not protector.armed

        def recovery(outage):
            def exercise(window, controller, protector, clock, pump, result):
                clock.advance(.5)
                window._tick()
                controller.monitor.available = False
                window._tick()
                before = controller.session.remaining_seconds
                assert not controller.session.running and protector.armed
                clock.advance(outage)
                window._tick()
                assert protector.armed and controller.session.remaining_seconds == before
                controller.monitor.available = True
                window._tick()
                assert protector.armed
                assert controller.session.recovery_pin_required is (outage >= 15.)
                assert controller.session.running is (outage < 15.)
                if outage >= 15.:
                    assert not controller.resume("invalid")
                    assert controller.resume(controller.config.proctor_pin)
                assert controller.session.running
                result["simulated_interruption_seconds"] = outage
                result["actual_elapsed_time_is_not_interruption_duration"] = True
            return exercise

        def proctor_pause(window, controller, protector, clock, pump, result):
            assert controller.pause(controller.config.proctor_pin)
            before = controller.session.remaining_seconds
            for _ in range(3):
                clock.advance(1.)
                window._tick()
            assert protector.armed and controller.session.remaining_seconds == before
            assert not controller.session.running
            assert controller.resume(controller.config.proctor_pin)
            assert controller.session.running and protector.armed

        def completion(window, controller, protector, clock, pump, result):
            for _ in range(3):
                clock.advance(1.)
                window._tick()
            assert controller.session.end_reason == "time_expired"
            assert not protector.armed and window.stack.currentWidget() is window.summary_page

        def shutdown(window, controller, protector, clock, pump, result):
            # The normal __main__ finally path, with the same production objects.
            protector.release("application_exit")
            controller.end("application_exit")
            window.shutdown_ui()
            window._refresh()
            assert controller.session.end_reason == "application_exit" and not protector.armed

        def emergency(paused):
            def exercise(window, controller, protector, clock, pump, result):
                if paused:
                    controller.monitor.available = False
                    window._tick()
                    assert not controller.session.running and protector.armed
                window.raise_()
                window.activateWindow()
                app.processEvents()
                if foreground_pid(native) != os.getpid():
                    raise RuntimeError("Emergency shortcut input skipped: owned exam lost foreground")
                # QtTest delivers directly to our widget. The separately run
                # native-shortcut suite verifies global emergency interception.
                QTest.keyClick(window, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier
                               | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier)
                pump(.1)
                assert controller.session.end_reason == "emergency_shortcut"
                assert not protector.armed
                result["shortcut_delivery"] = "QtTest directed at owned MainWindow"
            return exercise

        def foreground(window, controller, protector, clock, pump, result):
            if fixture_info is None or fixture.poll() is not None:
                raise RuntimeError("Owned foreign-window fixture did not start")
            actual_pid = fixture_info["pid"]
            result["fixture_launcher_pid"] = fixture.pid
            result["fixture_window_pid"] = actual_pid
            result["stage"] = "verify_owned_child_window"
            assert actual_pid != os.getpid(), "Foreign test fixture unexpectedly uses the exam process PID"
            assert belongs_to_fixture(actual_pid, fixture.pid), (
                f"Fixture window PID {actual_pid} is not the launched process {fixture.pid} or its descendant")
            hwnd = fixture_info["hwnd"]
            assert window_pid(native, hwnd) == actual_pid, "Fixture HWND ownership no longer matches its process"
            result["stage"] = "activate_owned_child_window"
            native.ShowWindow(hwnd, 5)
            requested = bool(native.SetForegroundWindow(hwnd))
            observed = foreground_pid(native) == actual_pid
            result["windows_accepted_foreground_request"] = requested
            result["foreign_foreground_observed"] = observed
            if not requested and not observed:
                result["not_exercised"] = "Windows refused to foreground the owned child window"
                raise RuntimeError(result["not_exercised"])
            result["stage"] = "observe_foreground_violation"
            pump(.35)
            events = [e for e in controller.security_events if e["event_type"] == "UNAUTHORIZED_WINDOW"]
            assert events, "No unauthorized-window event recorded after accepted foreground change"
            result["restored_exam_foreground"] = foreground_pid(native) == os.getpid()
            result["foreground_security_details"] = [event["details"] for event in events]
            assert protector.armed and controller.session.running, (
                f"Protection/session stopped during focus attempt: {protector.diagnostics}; "
                f"end_reason={controller.session.end_reason}")
            if not result["restored_exam_foreground"]:
                result["limitation"] = "Windows refused best-effort foreground restoration"
            native.ShowWindow(hwnd, 0)

        scenarios = [
            ("fullscreen_minimize_close_and_proctor_pin", close_and_pin, 600.),
            ("unauthorized_owned_foreground_window", foreground, 600.),
            ("monitoring_recovery_14_9_seconds", recovery(14.9), 600.),
            ("monitoring_recovery_15_0_seconds", recovery(15.), 600.),
            ("proctor_pause_keeps_protection", proctor_pause, 600.),
            ("normal_timer_completion", completion, 3.),
            ("application_shutdown_cleanup", shutdown, 600.),
            ("emergency_in_active_quiz", emergency(False), 600.),
            ("emergency_during_monitoring_pause", emergency(True), 600.),
        ]
        try:
            for name, exercise, duration in scenarios:
                if not run_case(name, exercise, duration=duration):
                    break
        finally:
            (temporary / "stop").touch()
            try:
                fixture.wait(timeout=2.)
            except subprocess.TimeoutExpired:
                fixture.terminate()  # Only the child fixture created by this script.
                fixture.wait(timeout=2.)

    report = {
        "passed": len(checks) == len(scenarios) and all(check["passed"] for check in checks),
        "generated_at": datetime.now(timezone.utc).isoformat(), "fingerprint": source_fingerprint(),
        "kind": "native_application_integration", "max_lease_seconds": 5.,
        "wall_duration_seconds": round(time.monotonic() - started, 3), "checks": checks,
        "limitations": ["Monitoring outages and gaze calibration use an injected test adapter and FakeClock.",
                        "No physical webcam disconnect or real calibrated-camera rehearsal was performed.",
                        "QtTest shortcuts target owned widgets; global emergency interception is covered by the native shortcut suite.",
                        "Restoration confirms hook/hotkey removal and window state; native copy-after-release is checked by the separate native shortcut suite."]}
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
