"""Normalized vision measurements; no alert or timer decisions live here."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GazeDirection(str, Enum):
    CENTER = "CENTER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float = 1.0
    class_id: int = -1

    @property
    def width(self): return max(0.0, self.x2 - self.x1)
    @property
    def height(self): return max(0.0, self.y2 - self.y1)
    @property
    def area(self): return self.width * self.height
    @property
    def center(self): return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)


@dataclass(frozen=True)
class HeadPose:
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0


@dataclass(frozen=True)
class EyeDiagnostic:
    """Eye-local features in camera coordinates, not gaze classifications.

    Horizontal increases towards image right; vertical increases downwards.
    Both use eye-corner width, and vertical is offset by 0.5 at the corner axis.
    Opening is eyelid aperture divided by that same width. Values may remain
    available for a rejected measurement so a developer can inspect its cause.
    """

    horizontal: float | None = None
    vertical: float | None = None
    opening: float | None = None
    valid: bool = False
    reason: str = "not measured"
    width_pixels: float | None = None


@dataclass(frozen=True)
class GazeDiagnostics:
    """Left/right names follow MediaPipe's face connection constants.

    These names are not exchanged when a UI mirrors the preview. Classification
    uses session targets; it does not infer anatomical directions from signs.
    """

    left_eye: EyeDiagnostic = field(default_factory=EyeDiagnostic)
    right_eye: EyeDiagnostic = field(default_factory=EyeDiagnostic)
    valid: bool = False
    reason: str = "not measured"


@dataclass(frozen=True)
class FaceMeasurement:
    face_present: bool
    box: Box | None = None
    landmarks: tuple[tuple[float, float], ...] = ()
    features: tuple[float, ...] | None = None
    head_pose: HeadPose | None = None
    quality: float = 0.0
    diagnostics: GazeDiagnostics | None = None
    # Dimensions of the original frame supplied to FaceAnalyzer, not a resized
    # preview, requested camera mode, or YOLO tensor.
    frame_size: tuple[int, int] | None = None


@dataclass(frozen=True)
class VisionResult:
    timestamp: float
    phone_visible: bool = False
    phone_confidence: float | None = None
    person_count: int = 0
    face_present: bool = False
    gaze_direction: GazeDirection = GazeDirection.UNKNOWN
    gaze_confidence: float | None = None
    head_pose: HeadPose | None = None
    phone_raised: bool = False
    monitoring_healthy: bool = True
    persons: tuple[Box, ...] = ()
    phones: tuple[Box, ...] = ()
    face: FaceMeasurement | None = None
    # Real frame associated with this result; never serialized into the journal.
    frame: Any = field(default=None, repr=False, compare=False)
    yolo_latency_ms: float = 0.0
    face_latency_ms: float = 0.0


@dataclass(frozen=True)
class HealthStatus:
    healthy: bool
    reason: str
    since: float | None = None

