"""Recovery and PIN interfaces; Windows restrictions require explicit opt-in."""

from .protection import EmergencyRelease, HeartbeatWatchdog, NoOpProtection, Protection
from .pin import PinVerifier


def create_protection(config):
    settings = getattr(config, "protection", config)
    if not settings.enabled:
        return NoOpProtection()
    from .windows import WindowsProtection
    return WindowsProtection(settings)

__all__ = [
    "EmergencyRelease", "HeartbeatWatchdog", "NoOpProtection", "PinVerifier", "Protection", "create_protection"
]
