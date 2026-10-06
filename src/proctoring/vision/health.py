"""Freshness and worker failure checks, independent of suspicious observations."""
import math

from .settings import VisionConfig
from .types import HealthStatus


def assess_health(*, config: VisionConfig, now: float, started_at: float | None,
                  frame_at: float | None, result_at: float | None,
                  heartbeat_at: float | None, error: str | None = None,
                  error_at: float | None = None, stopped: bool = False) -> HealthStatus:
    """Return the earliest expired deadline so late UI ticks preserve outage time."""
    if stopped:
        return HealthStatus(False, "Monitoring stopped", error_at if error_at is not None else now)
    if started_at is None:
        return HealthStatus(False, "Monitoring has not started", now)
    if not math.isfinite(now):
        return HealthStatus(False, "Invalid monitoring clock", started_at)
    failures: list[tuple[float, str]] = []
    if error:
        failures.append((error_at if error_at is not None else now, error))
    fields = ((frame_at, config.frame_stale_seconds, "Camera frames"),
              (heartbeat_at, config.heartbeat_stale_seconds, "Vision worker heartbeat"),
              (result_at, config.result_stale_seconds, "Vision results"))
    for timestamp, timeout, label in fields:
        if timestamp is None:
            failures.append((started_at, f"Waiting for {label.lower()}"))
        elif not math.isfinite(timestamp) or timestamp > now + 1e-6:
            failures.append((now, f"Invalid {label.lower()} timestamp"))
        elif now >= timestamp + timeout:
            failures.append((timestamp + timeout, f"{label} stale"))
    if failures:
        # Show a concrete exception while retaining the earliest outage boundary.
        since, reason = min(failures, key=lambda item: item[0])
        return HealthStatus(False, error or reason, since)
    return HealthStatus(True, "Monitoring healthy", None)
