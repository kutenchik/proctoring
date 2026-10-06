"""Pure shortcut, foreground and watchdog policies; no operating-system calls."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class KeyDecision:
    suppress: bool = False
    action: str | None = None
    emergency: bool = False
    emit: bool = False


class ModifierState:
    """Track modifiers from hook transitions; async key state is stale in hooks."""

    GROUPS = {"ctrl": (0x11, 0xA2, 0xA3), "shift": (0x10, 0xA0, 0xA1),
              "alt": (0x12, 0xA4, 0xA5)}

    def __init__(self, held=()):
        self.held = set(held)

    def update(self, vk: int, is_down: bool) -> None:
        for group in self.GROUPS.values():
            if vk not in group:
                continue
            if is_down:
                self.held.add(vk)
            elif vk == group[0]:
                self.held.difference_update(group)
            else:
                self.held.discard(vk)
                self.held.discard(group[0])
            break

    def values(self) -> dict[str, bool]:
        return {name: bool(self.held.intersection(group)) for name, group in self.GROUPS.items()}


class KeyboardPolicy:
    """Deduplicate held keys, including their key-up suppression.

    The policy never stores typed characters. It retains only virtual key codes
    until release, to decide whether a shortcut already generated an event.
    """

    def __init__(self, blocking: bool = False):
        self.blocking = blocking
        self._down: set[int] = set()
        self._suppressed: set[int] = set()
        self._reported: set[int] = set()

    def evaluate(self, vk: int, is_down: bool, *, ctrl: bool = False,
                 alt: bool = False, shift: bool = False) -> KeyDecision:
        if not is_down:
            suppressed = vk in self._suppressed
            self._down.discard(vk)
            self._suppressed.discard(vk)
            self._reported.discard(vk)
            return KeyDecision(suppress=self.blocking and suppressed)
        self._down.add(vk)
        # Recovery is evaluated before every blocking rule, including repeats.
        if vk == 0x51 and ctrl and alt and shift:
            first = vk not in self._reported
            self._reported.add(vk)
            return KeyDecision(emergency=True, emit=first)
        action = None
        if vk in (0x5B, 0x5C):
            action = "BLOCKED_WINDOWS_KEY"
        elif vk == 0x09 and alt:
            action = "BLOCKED_ALT_TAB"
        elif vk == 0x43 and ctrl:
            action = "BLOCKED_COPY"
        elif vk == 0x56 and ctrl:
            action = "BLOCKED_PASTE"
        elif vk == 0x2D and ctrl:
            action = "BLOCKED_COPY"
        elif vk == 0x2D and shift:
            action = "BLOCKED_PASTE"
        elif vk == 0x2C:
            action = "BLOCKED_SCREENSHOT"
        elif vk == 0x73 and alt:
            action = "BLOCKED_CLOSE"
        elif vk == 0x1B and alt:
            action = "BLOCKED_ALT_ESCAPE"
        elif vk == 0x1B and ctrl and shift:
            action = "BLOCKED_TASK_MANAGER"
        elif vk == 0x1B and ctrl:
            action = "BLOCKED_START_MENU"
        if action:
            first = vk not in self._reported
            self._reported.add(vk)
            if self.blocking:
                self._suppressed.add(vk)
            return KeyDecision(self.blocking, action, emit=first)
        # A modifier released during a held shortcut must not let repeats through.
        return KeyDecision(suppress=self.blocking and vk in self._suppressed)


class WindowPolicy:
    """Only the exact main process is allowed; its modal dialogs share its PID."""

    def __init__(self, parent_pid: int):
        if parent_pid <= 0:
            raise ValueError("Parent PID must be positive")
        self.parent_pid = parent_pid
        self._last_unauthorized: int | None = None

    def allowed(self, pid: int) -> bool:
        return pid == self.parent_pid

    def should_report(self, hwnd: int, pid: int) -> bool:
        if not hwnd or self.allowed(pid):
            self._last_unauthorized = None
            return False
        report = hwnd != self._last_unauthorized
        self._last_unauthorized = hwnd
        return report


class HelperLease:
    """Monotonic lease which never automatically re-arms after release."""

    def __init__(self):
        self.armed = False
        self.blocking_enabled = False
        self.reason: str | None = None
        self.last_heartbeat = 0.0
        self.started_at = 0.0
        self.heartbeat_timeout = 5.0
        self.max_session_seconds: float | None = None

    def arm(self, now: float, *, blocking: bool, heartbeat_timeout: float,
            max_session_seconds: float | None = None) -> None:
        if type(blocking) is not bool:
            raise ValueError("blocking must be a boolean")
        if not math.isfinite(now):
            raise ValueError("Clock must be finite")
        if not math.isfinite(heartbeat_timeout) or not 0.5 <= heartbeat_timeout <= 30:
            raise ValueError("heartbeat_timeout must be between 0.5 and 30 seconds")
        if max_session_seconds is not None and (
            not math.isfinite(max_session_seconds) or not 0 < max_session_seconds <= 600
        ):
            raise ValueError("max_session_seconds must be in (0, 600] or null")
        self.armed = True
        self.blocking_enabled = blocking
        self.reason = None
        self.started_at = self.last_heartbeat = now
        self.heartbeat_timeout = heartbeat_timeout
        self.max_session_seconds = max_session_seconds

    def heartbeat(self, now: float) -> None:
        if self.armed and math.isfinite(now) and now >= self.last_heartbeat:
            self.last_heartbeat = now

    def release(self, reason: str) -> None:
        if self.armed or self.reason is None:
            self.reason = reason
        self.armed = self.blocking_enabled = False

    def expired(self, now: float, *, parent_alive: bool = True,
                input_open: bool = True) -> str | None:
        if not parent_alive:
            return "parent_exited"
        if not input_open:
            return "stdin_eof"
        if not self.armed:
            return None
        if now - self.last_heartbeat >= self.heartbeat_timeout:
            return "heartbeat_timeout"
        if self.max_session_seconds is not None and now - self.started_at >= self.max_session_seconds:
            return "lease_expired"
        return None


class LoopWatchdog:
    """Fail-open backstop for a stalled helper loop, independent of UI leases."""

    def __init__(self, now: float, timeout_seconds: float = 3.0):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Loop watchdog timeout must be finite and positive")
        self.timeout_seconds = timeout_seconds
        self.last_pulse = now

    def pulse(self, now: float) -> None:
        if math.isfinite(now) and now >= self.last_pulse:
            self.last_pulse = now

    def expired(self, now: float) -> bool:
        return now - self.last_pulse >= self.timeout_seconds
