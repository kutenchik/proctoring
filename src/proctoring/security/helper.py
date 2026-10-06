"""Independent Windows protection helper with JSON-lines IPC.

Run with ``python -m proctoring.security.helper --parent-pid PID``. The main
process sends UI heartbeats; this process never manufactures them. Closing the
pipe, losing the parent, or missing a heartbeat releases the transient hooks.
"""

import argparse
import json
import math
import os
import queue
import sys
import threading
import time
from typing import Callable

from .policy import HelperLease, LoopWatchdog
from .win32_backend import ParentProcess, WindowsBackend


RECOVERY_REASONS = {"emergency_shortcut", "emergency_request", "heartbeat_timeout",
                    "parent_exited", "stdin_eof", "lease_expired", "keyboard_callback_error",
                    "helper_error", "output_closed"}


class HelperRuntime:
    """Testable command/state coordinator; intentionally knows nothing about exams."""

    def __init__(self, parent_pid: int, emit: Callable[[dict], None], *,
                 clock: Callable[[], float] = time.monotonic,
                 backend_factory: Callable = WindowsBackend):
        self.parent_pid, self.emit, self.clock = parent_pid, emit, clock
        self.backend_factory = backend_factory
        self.lease = HelperLease()
        self.backend = None
        self.stop_requested = False
        self.foreground_poll_seconds = 0.1
        self._last_foreground = float("-inf")

    def status(self, request_id=None) -> None:
        recovery = not self.lease.armed and self.lease.reason in RECOVERY_REASONS
        self.emit({"kind": "status", "status": "ACTIVE" if self.lease.armed else (
            "RECOVERY" if recovery else "INACTIVE"), "armed": self.lease.armed,
            "blocking_enabled": self.lease.blocking_enabled, "reason": self.lease.reason,
            "hook_installed": bool(self.backend and self.backend.hook_installed),
            "hotkey_registered": bool(self.backend and self.backend.hotkey_registered),
            "request_id": request_id})

    def security(self, event_type: str, details: dict) -> None:
        if event_type == "PROTECTION_RECOVERY" and self.lease.armed:
            self.release(details.get("reason", "helper_error"))
            return
        self.emit({"kind": "security", "event_type": event_type,
                   "description": self._description(event_type, details),
                   "details": details, "monotonic_timestamp": self.clock()})

    @staticmethod
    def _description(event_type: str, details: dict) -> str:
        if event_type == "EMERGENCY_RELEASE":
            return "Emergency recovery released Windows protection."
        if event_type == "PROTECTION_RECOVERY":
            return "Windows protection released automatically: " + str(details.get("reason", "failure"))
        if event_type == "UNAUTHORIZED_WINDOW":
            return "Attempted to activate a window outside the exam application."
        return ("Observed shortcut in audit mode: " if details.get("audit") else
                "Blocked shortcut: ") + event_type.removeprefix("BLOCKED_").replace("_", " ").lower()

    def release(self, reason: str, request_id=None, *, recovery_event: bool = True) -> None:
        was_armed = self.lease.armed
        # Native release MUST precede status, evidence, or other pipe writes.
        if self.backend is not None:
            self.backend.release()
            self.backend = None
        self.lease.release(reason)
        if was_armed and recovery_event and reason in RECOVERY_REASONS:
            self.security("EMERGENCY_RELEASE" if reason.startswith("emergency") else
                          "PROTECTION_RECOVERY", {"reason": reason})
        # Queue evidence before acknowledgement: the main process may finalize
        # its event journal as soon as it receives the recovery/disable status.
        self.status(request_id)

    def emergency(self) -> None:
        if self.lease.armed:
            self.release("emergency_shortcut")

    def command(self, command: dict) -> None:
        request_id = command.get("request_id")
        try:
            action = command.get("command")
            if action == "enable":
                if self.lease.armed:
                    raise ValueError("Protection is already armed; disable before enabling again")
                if type(command.get("pid")) is not int or command["pid"] != self.parent_pid:
                    raise ValueError("Only the original parent PID can be approved")
                hwnd = command.get("hwnd")
                if type(hwnd) is not int or hwnd <= 0:
                    raise ValueError("A valid positive native HWND is required")
                blocking = command.get("blocking", False)
                heartbeat_timeout = float(command.get("heartbeat_timeout", 5.0))
                maximum = command.get("max_session_seconds")
                maximum = None if maximum is None else float(maximum)
                poll = float(command.get("foreground_poll_ms", 100))
                if not math.isfinite(poll) or not 50 <= poll <= 1000:
                    raise ValueError("foreground_poll_ms must be between 50 and 1000")
                # Validate all lease settings before installing even an audit hook.
                proposed = HelperLease()
                proposed.arm(self.clock(), blocking=blocking, heartbeat_timeout=heartbeat_timeout,
                             max_session_seconds=maximum)
                backend = self.backend_factory(self.parent_pid, hwnd, blocking,
                                               self.security, self.emergency)
                try:
                    backend.enable()
                except BaseException:
                    backend.release()
                    raise
                self.backend = backend
                self.lease = proposed
                self.foreground_poll_seconds = poll / 1000
                self.status(request_id)
            elif action == "heartbeat":
                now = self.clock()
                sent_at = float(command.get("sent_at", now))
                # A delayed pipe message cannot extend a dead UI's lease.
                if not math.isfinite(sent_at) or sent_at > now or now - sent_at >= self.lease.heartbeat_timeout:
                    raise ValueError("Heartbeat timestamp is stale, nonfinite, or in the future")
                self.lease.heartbeat(sent_at)
                if request_id is not None:
                    self.status(request_id)
            elif action == "disable":
                self.release(str(command.get("reason", "disabled")), request_id)
            elif action == "emergency":
                self.release("emergency_request", request_id)
            elif action == "status":
                self.status(request_id)
            elif action == "shutdown":
                self.release("shutdown", request_id)
                self.stop_requested = True
            else:
                raise ValueError("Unknown protection command")
        except Exception as exc:
            self.emit({"kind": "error", "message": str(exc), "request_id": request_id})
            if not self.lease.armed:
                self.status(request_id)

    def tick(self, *, parent_alive: bool = True, input_open: bool = True) -> None:
        reason = self.lease.expired(self.clock(), parent_alive=parent_alive, input_open=input_open)
        if reason is not None:
            self.release(reason)
            if reason in ("parent_exited", "stdin_eof"):
                self.stop_requested = True
            return
        backend = self.backend
        if backend is not None:
            backend.pump()
            # Emergency processing may have removed the backend while pumping.
            if self.backend is backend and self.clock() - self._last_foreground >= self.foreground_poll_seconds:
                self._last_foreground = self.clock()
                backend.poll_foreground()


class OutputQueue:
    """Never block a native hook or watchdog on a parent that stopped reading."""

    def __init__(self):
        self.messages: queue.Queue = queue.Queue(maxsize=512)
        self.failed = threading.Event()
        self.thread = threading.Thread(target=self._write, name="protection-output", daemon=True)
        self.thread.start()

    def emit(self, value: dict) -> None:
        try:
            self.messages.put_nowait(value)
        except queue.Full:
            self.failed.set()

    def _write(self) -> None:
        while True:
            value = self.messages.get()
            try:
                if value is None:
                    return
                sys.stdout.write(json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, OSError, ValueError):
                self.failed.set()
                return
            finally:
                self.messages.task_done()

    def close(self) -> None:
        try:
            self.messages.put_nowait(None)
        except queue.Full:
            pass
        self.thread.join(timeout=0.3)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    output = OutputQueue()
    parent = None
    runtime = None
    sentinel_stop = threading.Event()
    try:
        if os.name != "nt":
            output.emit({"kind": "ready", "pid": os.getpid(), "platform_supported": False})
            output.emit({"kind": "error", "message": "Windows protection requires Windows"})
            return 2
        parent = ParentProcess(args.parent_pid)
        if not parent.alive():
            raise RuntimeError("The approved parent process has already exited")
        runtime = HelperRuntime(args.parent_pid, output.emit)
        loop_watchdog = LoopWatchdog(time.monotonic())

        def monitor_helper_loop():
            while not sentinel_stop.wait(0.1):
                if loop_watchdog.expired(time.monotonic()):
                    # Terminate only this helper, never the exam or another
                    # application. Windows removes its hooks/hotkey on exit.
                    # No IO or native focus calls can delay this last resort.
                    os._exit(3)

        threading.Thread(target=monitor_helper_loop, name="protection-sentinel", daemon=True).start()
        commands: queue.Queue = queue.Queue(maxsize=512)
        input_closed = threading.Event()

        def read_commands():
            try:
                while True:
                    line = sys.stdin.readline(16385)
                    if not line:
                        break
                    if len(line) > 16384 or not line.endswith("\n"):
                        break
                    try:
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            raise ValueError("JSON command must be an object")
                        commands.put_nowait(value)
                    except (ValueError, queue.Full):
                        break
            except (OSError, ValueError):
                pass
            finally:
                input_closed.set()

        threading.Thread(target=read_commands, name="protection-input", daemon=True).start()
        output.emit({"kind": "ready", "pid": os.getpid(), "platform_supported": True})
        while not runtime.stop_requested:
            loop_watchdog.pulse(time.monotonic())
            runtime.tick(parent_alive=parent.alive(), input_open=not input_closed.is_set())
            if runtime.stop_requested:
                break
            if output.failed.is_set():
                runtime.release("output_closed")
                break
            # Check the watchdog before queued heartbeats, so already-expired
            # leases cannot be renewed by delayed queue processing.
            for _ in range(32):
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    break
                runtime.command(command)
                if runtime.stop_requested:
                    break
            time.sleep(0.01)
        return 0
    except BaseException as exc:
        if runtime is not None:
            runtime.release("helper_error")
        output.emit({"kind": "error", "message": f"{type(exc).__name__}: {exc}"})
        return 1
    finally:
        if runtime is not None:
            runtime.release(runtime.lease.reason or "shutdown", recovery_event=False)
        if parent is not None:
            parent.close()
        output.close()
        sentinel_stop.set()


if __name__ == "__main__":
    raise SystemExit(main())
