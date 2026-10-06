"""Protection protocol and safe development adapter.

No keyboard hooks, process termination, or window restrictions are installed.
The UI shortcut works while the application receives keyboard input. A heartbeat
watchdog can release this interface from an independent caller, but this module
does not claim a global emergency shortcut or operating-system recovery.
"""

import math
import threading
from typing import Callable, Protocol

from proctoring.clock import Clock


class Protection(Protocol):
    @property
    def status(self) -> str: ...
    @property
    def blocking_enabled(self) -> bool: ...

    @property
    def armed(self) -> bool: ...

    @property
    def release_reason(self) -> str | None: ...

    def arm(self) -> None: ...

    def release(self, reason: str) -> None: ...

    def configure_window(self, hwnd: int, pid: int) -> None: ...

    def heartbeat(self) -> None: ...

    def drain_events(self) -> list[dict]: ...

    def close(self) -> None: ...


class NoOpProtection:
    """Tracks safe-mode lifecycle without installing any restrictions."""

    def __init__(self, blocking_enabled: bool = False):
        if blocking_enabled:
            raise ValueError("Windows restriction hooks are disabled in Stage 1/2")
        self._lock = threading.RLock()
        self._armed = False
        self._release_reason: str | None = None

    @property
    def blocking_enabled(self) -> bool:
        return False

    @property
    def status(self) -> str:
        return "INACTIVE"

    def configure_window(self, hwnd: int, pid: int) -> None:
        pass

    def heartbeat(self) -> None:
        pass

    def drain_events(self) -> list[dict]:
        return []

    def close(self) -> None:
        self.release("application_exit")

    @property
    def armed(self) -> bool:
        with self._lock:
            return self._armed

    @property
    def release_reason(self) -> str | None:
        with self._lock:
            return self._release_reason

    def arm(self) -> None:
        with self._lock:
            self._armed = True
            self._release_reason = None

    def release(self, reason: str) -> None:
        with self._lock:
            # Retain the first release reason until another session is armed.
            if self._armed or self._release_reason is None:
                self._release_reason = reason
            self._armed = False


class EmergencyRelease:
    """Release before UI work, even if the subsequent callback raises.

    Construct a fresh instance per session. Repeated or simultaneous triggers
    invoke the callback once. Exceptions from callbacks propagate to the caller.
    """

    def __init__(self, protection: Protection, callback: Callable[[], None] | None = None):
        self._protection = protection
        self._callback = callback
        self._lock = threading.Lock()
        self._triggered = False

    @property
    def triggered(self) -> bool:
        with self._lock:
            return self._triggered

    def trigger(self, reason: str = "emergency_shortcut") -> bool:
        with self._lock:
            if self._triggered:
                return False
            self._protection.release(reason)
            self._triggered = True
        if self._callback is not None:
            self._callback()
        return True


class HeartbeatWatchdog:
    """Deterministic recovery primitive to be checked outside the UI loop.

    This object starts no thread and installs no hooks. Feed heartbeat() when
    the UI makes progress; an independent timer can call check(). Fresh
    heartbeats never re-arm protection after a timeout.
    """

    def __init__(self, protection: Protection, timeout_seconds: float, clock: Clock):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Watchdog timeout must be finite and positive")
        self._protection = protection
        self._clock = clock
        self._timeout = timeout_seconds
        self._last_heartbeat = clock.monotonic()
        self._lock = threading.Lock()

    def heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat = self._clock.monotonic()

    def check(self) -> bool:
        with self._lock:
            expired = self._clock.monotonic() - self._last_heartbeat >= self._timeout
            if expired and self._protection.armed:
                self._protection.release("heartbeat_timeout")
                return True
            return False
