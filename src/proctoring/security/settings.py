"""Explicit opt-in settings for transient Windows demo restrictions."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProtectionConfig:
    enabled: bool = False
    heartbeat_timeout_seconds: float = 5.0
    startup_timeout_seconds: float = 5.0
    foreground_poll_ms: int = 100
    validation_report: Path = Path("artifacts/protection-validation.json")
    validation_max_age_hours: float = 24.0
