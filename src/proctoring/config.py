"""Validated, local TOML configuration for the staged prototype."""
from dataclasses import asdict, dataclass, field
import math
from pathlib import Path
import tomllib

from .domain import EventType
from .vision.settings import VisionConfig
from .vision.alignment import AlignmentConfig
from .security.settings import ProtectionConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "default.toml"


@dataclass(frozen=True)
class AppConfig:
    duration_seconds: float
    quiz_path: Path
    thresholds: dict[EventType, float]
    clearing_seconds: float
    recovery_seconds: float
    stale_seconds: float
    synthetic_interval_ms: int
    sessions_dir: Path
    snapshots_enabled: bool
    proctor_pin: str
    blocking_enabled: bool = False
    vision: VisionConfig = field(default_factory=VisionConfig)
    protection: ProtectionConfig = field(default_factory=ProtectionConfig)

    def public_dict(self) -> dict:
        return {
            "mode": "synthetic", "duration_seconds": self.duration_seconds,
            "thresholds": {key.value: value for key, value in self.thresholds.items()},
            "clearing_seconds": self.clearing_seconds,
            "recovery_seconds": self.recovery_seconds, "stale_seconds": self.stale_seconds,
            "synthetic_interval_ms": self.synthetic_interval_ms,
            "snapshots_enabled": self.snapshots_enabled,
            "snapshots_available": False, "blocking_enabled": self.protection.enabled,
            "protection": {key: str(value) if isinstance(value, Path) else value
                           for key, value in asdict(self.protection).items()},
            "vision": {key: str(value) if isinstance(value, Path) else value
                       for key, value in asdict(self.vision).items()},
        }


def _positive(section: dict, key: str) -> float:
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a positive finite number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{key} must be a positive finite number")
    return float(value)


def load_config(path: Path = DEFAULT_CONFIG) -> AppConfig:
    path = Path(path).resolve()
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    try:
        exam, events = data["exam"], data["events"]
        monitoring, storage, security = data["monitoring"], data["storage"], data["security"]
        if security.get("blocking_enabled") is not False:
            raise ValueError("Legacy security.blocking_enabled must be false; opt in through protection.enabled")
        pin = security["proctor_pin"]
        if not isinstance(pin, str) or not pin.isascii() or not pin.isdigit() or not 4 <= len(pin) <= 64:
            raise ValueError("proctor_pin must be a quoted string of 4–64 digits")
        snapshots = storage["snapshots_enabled"]
        if not isinstance(snapshots, bool):
            raise ValueError("snapshots_enabled must be true or false")
        interval = monitoring["synthetic_interval_ms"]
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < 10:
            raise ValueError("synthetic_interval_ms must be an integer >= 10")
        stale = _positive(monitoring, "stale_seconds")
        if stale <= interval / 1000:
            raise ValueError("stale_seconds must exceed the synthetic sample interval")
        gaze = _positive(events, "gaze_deviation")
        thresholds = {
            EventType.PHONE_VISIBLE: _positive(events, "phone_visible"),
            EventType.SECOND_PERSON: _positive(events, "second_person"),
            EventType.PHONE_RAISED: _positive(events, "phone_raised"),
            EventType.GAZE_DOWN: gaze, EventType.GAZE_LEFT: gaze, EventType.GAZE_RIGHT: gaze,
            EventType.FACE_ABSENT: _positive(events, "face_absent"),
        }
        return AppConfig(
            duration_seconds=_positive(exam, "duration_seconds"),
            quiz_path=(path.parent / exam["quiz_path"]).resolve(), thresholds=thresholds,
            clearing_seconds=_positive(events, "clearing_seconds"),
            recovery_seconds=_positive(monitoring, "recovery_seconds"), stale_seconds=stale,
            synthetic_interval_ms=interval,
            sessions_dir=(path.parent / storage["sessions_dir"]).resolve(),
            snapshots_enabled=snapshots, proctor_pin=pin,
            vision=_load_vision(data.get("vision", {}), path.parent),
            protection=_load_protection(data.get("protection", {}), path.parent),
        )
    except KeyError as error:
        raise ValueError(f"Missing configuration key: {error.args[0]}") from error


def _load_vision(values: dict, base: Path) -> VisionConfig:
    defaults = asdict(VisionConfig())
    unknown = set(values) - set(defaults)
    if unknown:
        raise ValueError(f"Unknown vision settings: {', '.join(sorted(unknown))}")
    data = {**defaults, **values}
    for key in ("yolo_model", "face_model"):
        # Defaults also resolve relative to project root when section is absent.
        value = values.get(key, str(PROJECT_ROOT / defaults[key]))
        data[key] = (base / value).resolve()
    integer_fields = ("camera_index", "capture_width", "capture_height", "capture_fps", "yolo_input_size",
                      "cpu_threads", "calibration_samples", "calibration_max_samples")
    for key in integer_fields:
        value = data[key]
        minimum = 0 if key == "camera_index" else 1
        if type(value) is not int or value < minimum:
            raise ValueError(f"vision.{key} must be an integer >= {minimum}")
    if data["yolo_input_size"] % 32 or data["yolo_input_size"] < 128:
        raise ValueError("yolo_input_size must be >=128 and divisible by 32")
    if data["calibration_samples"] < 5:
        raise ValueError("calibration_samples must be at least 5")
    if not data["calibration_samples"] <= data["calibration_max_samples"] <= 4096:
        raise ValueError("calibration_max_samples must be >= calibration_samples and <= 4096")
    for key in ("prefer_gpu", "calibration_debug"):
        if type(data[key]) is not bool:
            raise ValueError(f"{key} must be true or false")
    if data["camera_backend"] not in ("auto", "msmf", "dshow", "any"):
        raise ValueError("camera_backend must be auto, msmf, dshow, or any")
    for key, default in defaults.items():
        if isinstance(default, float):
            data[key] = _positive(data, key)
    for key in ("phone_confidence", "person_confidence", "person_min_area", "person_min_height",
                "phone_min_area", "nms_iou", "face_min_area", "raised_person_top_fraction"):
        if data[key] > 1:
            raise ValueError(f"vision.{key} must not exceed 1")
    if data["result_stale_seconds"] <= 1 / data["yolo_fps"]:
        raise ValueError("result_stale_seconds must exceed the YOLO sampling interval")
    if not .5 <= data["calibration_preparation_seconds"] <= 15:
        raise ValueError("calibration_preparation_seconds must be between 0.5 and 15")
    if not 1 <= data["calibration_collection_seconds"] <= 30:
        raise ValueError("calibration_collection_seconds must be between 1 and 30")
    if data["calibration_samples"] > data["face_fps"] * data["calibration_collection_seconds"]:
        raise ValueError("calibration interval is too short for calibration_samples at configured face_fps")
    if not .001 <= data["calibration_eye_noise_floor"] <= .1:
        raise ValueError("calibration_eye_noise_floor must be between .001 and .1 eye widths")
    if data["calibration_min_signal_noise"] < 3:
        raise ValueError("calibration_min_signal_noise must be at least 3")
    for key in ("calibration_offscreen_radius_fraction", "calibration_center_radius_fraction"):
        if not 0 < data[key] < .5:
            raise ValueError(f"{key} must be between 0 and .5 (exclusive)")
    alignment_values = data["alignment"]
    if not isinstance(alignment_values, dict):
        raise ValueError("vision.alignment must be a settings table")
    try:
        alignment_values = {**defaults["alignment"], **alignment_values}
        alignment_values["guide"] = tuple(alignment_values["guide"])
        data["alignment"] = AlignmentConfig(**alignment_values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid vision.alignment: {exc}") from exc
    return VisionConfig(**data)


def _load_protection(values: dict, base: Path) -> ProtectionConfig:
    defaults = asdict(ProtectionConfig())
    unknown = set(values) - set(defaults)
    if unknown:
        raise ValueError(f"Unknown protection settings: {', '.join(sorted(unknown))}")
    data = {**defaults, **values}
    if type(data["enabled"]) is not bool:
        raise ValueError("protection.enabled must be true or false")
    for key in ("heartbeat_timeout_seconds", "startup_timeout_seconds", "validation_max_age_hours"):
        data[key] = _positive(data, key)
    if not .5 <= data["heartbeat_timeout_seconds"] <= 30:
        raise ValueError("protection.heartbeat_timeout_seconds must be between 0.5 and 30")
    if data["startup_timeout_seconds"] > 15:
        raise ValueError("protection.startup_timeout_seconds must not exceed 15")
    if data["validation_max_age_hours"] > 168:
        raise ValueError("protection.validation_max_age_hours must not exceed 168")
    if type(data["foreground_poll_ms"]) is not int or not 50 <= data["foreground_poll_ms"] <= 1000:
        raise ValueError("protection.foreground_poll_ms must be between 50 and 1000")
    report = values.get("validation_report", str(PROJECT_ROOT / defaults["validation_report"]))
    if not isinstance(report, str) or not report.strip():
        raise ValueError("protection.validation_report must be a local file path")
    data["validation_report"] = (base / report).resolve()
    return ProtectionConfig(**data)

