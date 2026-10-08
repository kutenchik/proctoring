"""Validated application settings unrelated to camera processing."""
from dataclasses import dataclass, field
import math
from urllib.parse import urlsplit
from pathlib import PurePath


def _flags(instance, section, names):
    for name in names:
        if type(getattr(instance, name)) is not bool:
            raise ValueError(f"{section}.{name} must be true or false")


def _number(instance, section, name, minimum=0.0, maximum=None):
    value = getattr(instance, name)
    if (isinstance(value, bool) or not isinstance(value, (float, int))
            or not math.isfinite(value) or value <= minimum
            or (maximum is not None and value > maximum)):
        raise ValueError(f"{section}.{name} must be a positive finite number"
                         + (f" <= {maximum}" if maximum is not None else ""))


@dataclass(frozen=True)
class SystemChecksConfig:
    block_multimonitor: bool = False
    clipboard_guard_enabled: bool = False
    vm_check_enabled: bool = False

    def __post_init__(self):
        _flags(self, "security.system_checks", self.__dataclass_fields__)


@dataclass(frozen=True)
class IdentityConfig:
    selfie_verification_enabled: bool = False
    impersonation_threshold: float = 0.40
    periodic_check_interval_seconds: float = 30.0

    def __post_init__(self):
        _flags(self, "exam.identity", ("selfie_verification_enabled",))
        _number(self, "exam.identity", "impersonation_threshold", maximum=2.0)
        _number(self, "exam.identity", "periodic_check_interval_seconds")


@dataclass(frozen=True)
class AudioConfig:
    enabled: bool = False
    sample_rate: int = 16000
    voice_duration_threshold: float = 2.0
    energy_threshold: float = 0.15
    adaptive_calibration: bool = True
    min_energy_threshold: float = 0.05
    max_energy_threshold: float = 0.40

    def __post_init__(self):
        _flags(self, "audio", ("enabled", "adaptive_calibration"))
        if type(self.sample_rate) is not int or not 8000 <= self.sample_rate <= 192000:
            raise ValueError("audio.sample_rate must be an integer between 8000 and 192000")
        _number(self, "audio", "voice_duration_threshold")
        _number(self, "audio", "energy_threshold", maximum=1.0)
        _number(self, "audio", "min_energy_threshold", maximum=1.0)
        _number(self, "audio", "max_energy_threshold", maximum=1.0)
        if self.min_energy_threshold >= self.max_energy_threshold:
            raise ValueError("audio.min_energy_threshold must be below audio.max_energy_threshold")


@dataclass(frozen=True)
class ReportingConfig:
    generate_pdf_report: bool = False
    send_pdf_to_telegram: bool = False
    report_filename: str = "exam_integrity_report.pdf"

    def __post_init__(self):
        _flags(self, "reporting", ("generate_pdf_report", "send_pdf_to_telegram"))
        name = self.report_filename
        if (not isinstance(name, str) or not name.strip() or name != name.strip()
                or any(character in name for character in '\\/:*?"<>|')
                or any(ord(character) < 32 for character in name)
                or PurePath(name).name != name or not name.lower().endswith(".pdf")
                or name.startswith(".")):
            raise ValueError("reporting.report_filename must be a plain PDF filename")


@dataclass(frozen=True)
class RegistrationConfig:
    enabled: bool = True
    require_group: bool = True

    def __post_init__(self):
        for name in ("enabled", "require_group"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"exam.registration.{name} must be true or false")


@dataclass(frozen=True)
class RemoteConfig:
    enabled: bool = False
    webhook_url: str = field(default="", repr=False)
    webhook_token: str = field(default="", repr=False)
    telegram_enabled: bool = False
    telegram_bot_token: str = field(default="", repr=False)
    telegram_chat_id: str = ""
    max_queue_size: int = 50
    upload_timeout_seconds: float = 5.0

    def __post_init__(self):
        for name in ("enabled", "telegram_enabled"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"remote.{name} must be true or false")
        for name in ("webhook_url", "webhook_token", "telegram_bot_token", "telegram_chat_id"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"remote.{name} must be a string")
            if any(ord(character) < 32 or ord(character) == 127 for character in value):
                raise ValueError(f"remote.{name} must not contain control characters")
            object.__setattr__(self, name, value.strip())
        if type(self.max_queue_size) is not int or self.max_queue_size <= 0:
            raise ValueError("remote.max_queue_size must be a positive integer")
        timeout = self.upload_timeout_seconds
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("remote.upload_timeout_seconds must be a positive finite number")
        object.__setattr__(self, "upload_timeout_seconds", float(timeout))
        if self.webhook_url:
            try:
                url = urlsplit(self.webhook_url)
                valid = (url.scheme in ("http", "https") and bool(url.hostname)
                         and url.username is None and url.password is None
                         and not any(character.isspace() for character in self.webhook_url))
                # Access validates malformed/out-of-range ports too.
                url.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("remote.webhook_url must be an HTTP(S) URL without embedded credentials")
        if self.enabled and self.telegram_enabled:
            if not self.telegram_bot_token or not self.telegram_chat_id:
                raise ValueError("Enabled Telegram delivery requires remote.telegram_bot_token and remote.telegram_chat_id")
        if self.enabled and not (self.webhook_url or self.telegram_enabled):
            raise ValueError("remote.enabled requires a webhook URL or enabled Telegram delivery")

    def public_dict(self) -> dict:
        """Never persist bot credentials or a token-bearing webhook URL."""
        return {
            "enabled": self.enabled,
            "webhook_configured": bool(self.webhook_url),
            "webhook_host": urlsplit(self.webhook_url).hostname if self.webhook_url else None,
            "telegram_enabled": self.telegram_enabled,
            "max_queue_size": self.max_queue_size,
            "upload_timeout_seconds": self.upload_timeout_seconds,
        }
