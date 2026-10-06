"""Separate duration measurement from human-readable timestamps."""
from datetime import datetime, timezone
import time
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def wall_time(self) -> str: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wall_time(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class FakeClock:
    """Deterministic clock for tests; advancing it never sleeps."""
    def __init__(self, now: float = 0.0):
        self.now = now
        self.timestamp = "2026-10-04T00:00:00+00:00"

    def monotonic(self) -> float:
        return self.now

    def wall_time(self) -> str:
        return self.timestamp

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("Cannot reverse monotonic time")
        self.now += seconds

