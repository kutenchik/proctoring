"""Parent-side client for a disposable Windows protection helper.

Only Qt progress sends heartbeats. Reader/writer threads cannot renew the lease.
Killing this application's own helper is the last-resort release path; no other
application or Windows process is terminated and no persistent settings change.
"""
from collections import deque
from datetime import datetime, timezone
import json
import os
from queue import Empty, Full, Queue
import subprocess
import sys
import threading
import time
from uuid import uuid4

from .helper_process import OwnedHelperProcess
from .launch import helper_command
from .settings import ProtectionConfig


class WindowsProtection:
    def __init__(self, config: ProtectionConfig, *, test_lease_seconds: float | None = None):
        self.config = config
        self._test_lease_seconds = test_lease_seconds
        self._condition = threading.Condition(threading.RLock())
        self._process = None
        self._helper_process = None
        self._termination_lock = threading.RLock()
        self._outgoing = Queue(maxsize=64)
        self._responses = {}
        self._events = deque(maxlen=1000)
        self._ready = False
        self._last_status = {}
        self._armed = False
        self._status = "INACTIVE"
        self._release_reason = None
        self._error = None
        self._hwnd = None
        self._closed = False
        self._intentional_stop = False
        self._writer_stop = threading.Event()
        self._reader = self._writer = None

    @property
    def blocking_enabled(self) -> bool:
        """Configured intent; status/armed indicate actual helper activation."""
        return self.config.enabled

    @property
    def status(self) -> str:
        with self._condition:
            return self._status

    @property
    def armed(self) -> bool:
        with self._condition:
            return self._armed

    @property
    def release_reason(self):
        with self._condition:
            return self._release_reason

    @property
    def diagnostics(self) -> dict:
        with self._condition:
            return dict(self._last_status)

    def configure_window(self, hwnd: int, pid: int) -> None:
        if type(hwnd) is not int or hwnd <= 0 or pid != os.getpid():
            raise ValueError("Protection requires a window owned by this application process")
        if self.armed:
            raise RuntimeError("Cannot replace the protected window during an active session")
        self._hwnd = hwnd

    def _spawn(self) -> None:
        if self._closed:
            raise RuntimeError("Protection client is closed")
        if self._process is not None:
            if self._process.poll() is not None:
                raise RuntimeError("Protection helper exited; restart the application")
            return
        if sys.platform != "win32":
            raise RuntimeError("Protected demo mode requires Windows")
        self._process = subprocess.Popen(
            helper_command(os.getpid()),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._reader = threading.Thread(target=self._read, name="protection-status", daemon=True)
        self._writer = threading.Thread(target=self._write, name="protection-commands", daemon=True)
        self._reader.start()
        self._writer.start()
        deadline = time.monotonic() + self.config.startup_timeout_seconds
        with self._condition:
            while not self._ready and self._error is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Protection helper startup timed out")
                self._condition.wait(remaining)
            if self._error:
                raise RuntimeError(self._error)

    def _send(self, command: str, **fields) -> None:
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError("Protection helper is unavailable")
        try:
            self._outgoing.put_nowait({"command": command, **fields})
        except Full as error:
            raise RuntimeError("Protection command channel stalled") from error

    def _request(self, command: str, timeout: float = 1., **fields) -> dict:
        request_id = uuid4().hex
        self._send(command, request_id=request_id, **fields)
        deadline = time.monotonic() + timeout
        with self._condition:
            while request_id not in self._responses:
                if self._error is not None:
                    raise RuntimeError(self._error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"Protection {command} acknowledgement timed out")
                self._condition.wait(remaining)
            response = self._responses.pop(request_id)
        if response.get("kind") == "error" or response.get("error"):
            raise RuntimeError(str(response.get("error") or response.get("message") or response.get("reason") or "Protection rejected command"))
        return response

    def arm(self) -> None:
        if not self.config.enabled:
            raise RuntimeError("Real protection was not enabled in configuration")
        if self._hwnd is None:
            raise RuntimeError("Exam window is not configured")
        if self.armed:
            return
        from .validation import require_recovery_validation
        require_recovery_validation(self.config.validation_report,
                                    max_age_hours=self.config.validation_max_age_hours)
        try:
            self._spawn()
            response = self._request(
                "enable", timeout=self.config.startup_timeout_seconds,
                pid=os.getpid(), hwnd=self._hwnd, blocking=True,
                heartbeat_timeout=self.config.heartbeat_timeout_seconds,
                foreground_poll_ms=self.config.foreground_poll_ms,
                max_session_seconds=self._test_lease_seconds,
            )
            if not response.get("armed") or not response.get("blocking_enabled"):
                raise RuntimeError("Helper did not confirm active protection")
        except Exception:
            self._terminate_owned_helper()
            self._recovery("protection_startup_failed")
            raise

    def heartbeat(self) -> None:
        if not self.armed:
            return
        try:
            self._send("heartbeat", sent_at=time.monotonic())
        except RuntimeError:
            self._terminate_owned_helper()
            self._recovery("heartbeat_channel_failed")

    def release(self, reason: str) -> None:
        if not self.armed:
            with self._condition:
                if self._release_reason is None:
                    self._release_reason = reason
            return
        try:
            response = self._request("disable", reason=reason)
            if response.get("armed"):
                raise RuntimeError("Helper did not confirm release")
        except Exception:
            # Never leave a hook active while storage/shutdown continues.
            self._terminate_owned_helper()
            self._recovery(f"release_fallback:{reason}")

    def drain_events(self) -> list[dict]:
        with self._condition:
            result = list(self._events)
            self._events.clear()
            return result

    def _event(self, event_type: str, description: str, details=None) -> None:
        self._events.append({"event_id": uuid4().hex, "event_type": event_type,
                             "timestamp": datetime.now(timezone.utc).isoformat(),
                             "description": description, "details": details or {}})

    def _recovery(self, reason: str) -> None:
        with self._condition:
            was_recovery = self._status == "RECOVERY"
            self._armed = False
            self._status = "RECOVERY"
            self._release_reason = reason
            if not was_recovery:
                self._event("PROTECTION_RECOVERY", "Protection released through independent recovery", {"reason": reason})
            self._condition.notify_all()

    def _consume(self, message: dict) -> None:
        with self._condition:
            kind = message.get("kind")
            if kind == "ready":
                if message.get("platform_supported", True):
                    if self._ready or self._helper_process is not None:
                        raise ValueError("Protection helper sent duplicate process identity")
                    if self._intentional_stop:
                        raise ValueError("Protection helper identity arrived after shutdown")
                    # A Windows venv python.exe may launch the hook-owning
                    # interpreter as its child. Keep that process's exact
                    # handle before allowing any enable command to be sent.
                    self._helper_process = OwnedHelperProcess(message.get("pid"), self._process)
                    self._ready = True
                else:
                    self._error = "Protection helper requires Windows"
            elif kind == "status":
                self._last_status = dict(message)
                self._armed = bool(message.get("armed"))
                self._status = message.get("status", "ACTIVE" if self._armed else "INACTIVE")
                self._release_reason = message.get("reason")
            elif kind == "security":
                self._event(str(message.get("event_type", "SECURITY_EVENT")),
                            str(message.get("description", "Protected environment action")),
                            message.get("details", {}))
            elif kind == "error" and not message.get("request_id"):
                self._error = str(message.get("error") or message.get("message") or message.get("reason") or "Protection helper error")
            if message.get("request_id"):
                # An error may be followed by a disarmed status for the same
                # request. Preserve the error instead of racing away its cause.
                self._responses.setdefault(message["request_id"], message)
            self._condition.notify_all()

    def _read(self) -> None:
        try:
            for line in self._process.stdout:
                if len(line) > 65536:
                    raise ValueError("Invalid protection message size")
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Invalid protection message")
                self._consume(message)
        except Exception as error:
            with self._condition:
                self._error = f"Protection status channel failed: {error}"
        finally:
            with self._condition:
                unexpected = not self._intentional_stop
                if unexpected:
                    self._error = self._error or "Protection helper exited"
                self._condition.notify_all()
            if unexpected:
                self._terminate_owned_helper()
                self._recovery("helper_exited")

    def _write(self) -> None:
        try:
            while not self._writer_stop.is_set():
                try:
                    message = self._outgoing.get(timeout=.1)
                except Empty:
                    continue
                self._process.stdin.write(json.dumps(message) + "\n")
                self._process.stdin.flush()
        except Exception:
            if not self._intentional_stop:
                self._terminate_owned_helper()
                self._recovery("helper_channel_closed")

    def _terminate_owned_helper(self) -> None:
        with self._termination_lock:
            self._intentional_stop = True
            self._writer_stop.set()
            owner = self._helper_process
            if owner is not None:
                # Confirm the native hook owner's death BEFORE reporting
                # recovery or letting storage/window shutdown continue.
                owner.terminate_and_wait(timeout=1.)
                with self._condition:
                    self._last_status.update(armed=False, blocking_enabled=False,
                                             hook_installed=False, hotkey_registered=False,
                                             termination_confirmed=True, helper_pid=owner.pid)
            elif self._armed:
                raise RuntimeError("Cannot confirm release without a verified helper process handle")
            process = self._process
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.)

    def close(self) -> None:
        if self._closed:
            return
        self.release("application_exit")
        self._intentional_stop = True
        try:
            if self._process is not None and self._process.poll() is None:
                self._request("shutdown", timeout=1.)
                self._process.wait(timeout=1.)
        except Exception:
            self._terminate_owned_helper()
        finally:
            self._writer_stop.set()
            self._closed = True
            for thread in (self._reader, self._writer):
                if thread and thread is not threading.current_thread():
                    thread.join(timeout=.2)
            with self._termination_lock:
                if self._helper_process is not None:
                    self._helper_process.close()
            if self._process is not None:
                for pipe in (self._process.stdin, self._process.stdout):
                    if pipe:
                        pipe.close()
