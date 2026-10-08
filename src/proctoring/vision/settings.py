from dataclasses import dataclass, field
from pathlib import Path

from .alignment import AlignmentConfig
from .accessories import AccessoriesConfig


@dataclass(frozen=True)
class VisionConfig:
    camera_index: int = 0
    capture_width: int = 1280
    capture_height: int = 720
    capture_fps: int = 30
    camera_backend: str = "auto"
    yolo_model: Path = Path("models/yolo11n.onnx")
    face_model: Path = Path("models/face_landmarker.task")
    yolo_input_size: int = 416
    yolo_fps: float = 5.0
    face_fps: float = 12.0
    prefer_gpu: bool = False
    cpu_threads: int = 2
    phone_confidence: float = .35
    person_confidence: float = .5
    person_min_area: float = .015
    person_min_height: float = .12
    phone_min_area: float = .0005
    nms_iou: float = .45
    face_min_area: float = .01
    # Independent posture evidence; never makes invalid iris measurements valid.
    head_down_pitch_degrees: float = 14.0
    head_down_max_yaw_degrees: float = 15.0
    head_down_max_roll_degrees: float = 12.0
    frame_stale_seconds: float = 2.0
    result_stale_seconds: float = 2.0
    heartbeat_stale_seconds: float = 5.0
    calibration_samples: int = 20
    calibration_max_samples: int = 240
    calibration_preparation_seconds: float = 2.0
    calibration_collection_seconds: float = 3.0
    calibration_max_collection_seconds: float = 6.0
    calibration_debug: bool = False
    alignment: AlignmentConfig = field(default_factory=AlignmentConfig)
    accessories: AccessoriesConfig = field(default_factory=AccessoriesConfig)
    calibration_max_spread: float = .12
    # Legacy mixed eye/head distance. Accepted for old config files only;
    # calibration now checks eye separation against measurement uncertainty.
    calibration_min_separation: float = .08
    calibration_eye_noise_floor: float = .01
    calibration_min_signal_noise: float = 3.0
    # A configurable pixel-resolution assumption, not measured landmark noise.
    calibration_pixel_uncertainty_multiplier: float = .8
    calibration_offscreen_radius_fraction: float = .30
    calibration_center_radius_fraction: float = .45
    raised_face_margin: float = .6
    raised_person_top_fraction: float = .45
