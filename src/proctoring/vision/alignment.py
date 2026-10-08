"""Pre-collection face positioning checks, separate from gaze calibration.

All image dimensions are original-frame measurements. The progress indicator
measures a short stable positioning interval; it is not a gaze confidence score.
Passing alignment does not establish distinguishable gaze targets.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .types import VisionResult


@dataclass(frozen=True)
class AlignmentConfig:
    guide: tuple[float, float, float, float] = (.18, .08, .82, .92)
    min_face_width_pixels: float = 140.0
    min_face_height_pixels: float = 160.0
    min_eye_width_pixels: float = 32.0
    min_quality: float = .45
    max_yaw_degrees: float = 15.0
    max_pitch_degrees: float = 15.0
    max_roll_degrees: float = 12.0
    stable_seconds: float = .75
    min_stable_samples: int = 3
    max_center_drift: float = .02
    max_scale_change: float = .10
    max_sample_gap_seconds: float = .5

    def __post_init__(self):
        if (not isinstance(self.guide, (list, tuple)) or len(self.guide) != 4
                or not all(_finite_number(value) for value in self.guide)):
            raise ValueError("The alignment guide needs four finite normalized coordinates")
        x1, y1, x2, y2 = self.guide
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError("The alignment guide must be inside the normalized source frame")
        object.__setattr__(self, "guide", tuple(self.guide))
        for field in ("min_face_width_pixels", "min_face_height_pixels", "min_eye_width_pixels",
                      "max_yaw_degrees", "max_pitch_degrees", "max_roll_degrees", "stable_seconds",
                      "max_center_drift", "max_scale_change", "max_sample_gap_seconds"):
            value = getattr(self, field)
            if not _finite_number(value) or value <= 0:
                raise ValueError(f"{field} must be finite and positive")
        if not _finite_number(self.min_quality) or not 0 <= self.min_quality <= 1:
            raise ValueError("min_quality must be between zero and one")
        if not isinstance(self.min_stable_samples, int) or self.min_stable_samples < 3:
            raise ValueError("At least three unique positioning samples are required")


@dataclass(frozen=True)
class AlignmentStatus:
    ready: bool
    reason: str
    message: str
    progress: float
    guide: tuple[float, float, float, float]
    frame_size: tuple[int, int] | None = None
    face_width_pixels: float | None = None
    face_height_pixels: float | None = None
    left_eye_width_pixels: float | None = None
    right_eye_width_pixels: float | None = None
    yaw_degrees: float | None = None
    pitch_degrees: float | None = None
    roll_degrees: float | None = None
    stable_samples: int = 0
    stable_elapsed_seconds: float = 0.0
    # Position evidence is independent of the current eye/gaze measurement.
    geometry_valid: bool = False
    positioning_stable: bool = False
    geometry_generation: int = 0
    geometry_reset_reason: str | None = None

    @property
    def can_collect(self) -> bool:
        return self.ready


class FaceAlignment:
    """Stateful positioning readiness driven exclusively by capture timestamps.

    Repeated UI polls cannot earn stability time. A fixed window anchor detects
    cumulative motion. Missing face geometry clears positioning history, whereas
    invalid eyes only block eye-sample admission. Head orientation is a
    positioning check, never a replacement gaze feature.
    """

    def __init__(self, config: AlignmentConfig | None = None, max_age: float = .75):
        if not _finite_number(max_age) or max_age <= 0:
            raise ValueError("max_age must be finite and positive")
        self.config = config or AlignmentConfig()
        self.max_age = max_age
        self._geometry_generation = -1
        self._geometry_reset_reason: str | None = None
        self.reset()

    @property
    def status(self) -> AlignmentStatus:
        return self._status

    def reset(self) -> AlignmentStatus:
        self._last_timestamp: float | None = None
        self._geometry_generation += 1
        self._geometry_reset_reason = "reset"
        self._clear_stability()
        self._status = AlignmentStatus(False, "no_face", "Center your face", 0.0, self.config.guide,
                                       geometry_generation=self._geometry_generation,
                                       geometry_reset_reason=self._geometry_reset_reason)
        return self._status

    def _clear_stability(self):
        self._anchor: tuple[float, float, float, float] | None = None
        self._anchor_frame_size: tuple[int, int] | None = None
        self._stable_since: float | None = None
        self._stable_last: float | None = None
        self._stable_samples = 0

    def _invalidate_geometry(self, reason: str):
        # Repeated missing-frame UI polls represent one lost geometry interval,
        # not a new baseline on every refresh.
        if self._anchor is not None:
            self._geometry_generation += 1
            self._geometry_reset_reason = reason
        self._clear_stability()

    def _fail(self, reason: str, message: str, values: dict, *, geometry_reason: str | None = None) -> AlignmentStatus:
        self._invalidate_geometry(geometry_reason or reason)
        self._status = AlignmentStatus(False, reason, message, 0.0, self.config.guide,
                                       geometry_generation=self._geometry_generation,
                                       geometry_reset_reason=self._geometry_reset_reason, **values)
        return self._status

    def update(self, result: VisionResult | None, now: float, healthy: bool) -> AlignmentStatus:
        values: dict = {}
        if not healthy or (result is not None and not result.monitoring_healthy):
            return self._fail("monitoring_unavailable", "Waiting for healthy camera monitoring", values)
        if result is None:
            return self._fail("no_frame", "Waiting for a fresh camera frame", values)
        stamp = result.timestamp
        if (not _finite_number(now) or not _finite_number(stamp) or stamp > now
                or now - stamp >= self.max_age or now - stamp > self.config.max_sample_gap_seconds):
            return self._fail("stale_frame", "Waiting for a fresh camera frame", values)
        if self._last_timestamp is not None and stamp < self._last_timestamp:
            return self._fail("timestamp_regressed", "Waiting for a fresh camera frame", values)
        unique = self._last_timestamp is None or stamp > self._last_timestamp
        self._last_timestamp = stamp
        face = result.face
        if face is None or not result.face_present or not face.face_present or face.box is None:
            return self._fail("no_face", "Center your face", values)
        size = face.frame_size
        if (not isinstance(size, (list, tuple)) or len(size) != 2
                or not all(_finite_number(value) and value > 0 for value in size)):
            return self._fail("source_dimensions_missing", "Waiting for original camera dimensions", values)
        size = tuple(size)
        values["frame_size"] = size
        box = face.box
        coordinates = (box.x1, box.y1, box.x2, box.y2)
        if (not all(_finite_number(value) for value in coordinates)
                or not (0 <= box.x1 < box.x2 <= 1 and 0 <= box.y1 < box.y2 <= 1)):
            return self._fail("face_not_contained", "Center your face", values)
        values.update(face_width_pixels=box.width * size[0], face_height_pixels=box.height * size[1])
        guide = self.config.guide
        if box.x1 < guide[0] or box.y1 < guide[1] or box.x2 > guide[2] or box.y2 > guide[3]:
            return self._fail("face_not_contained", "Center your face", values)
        diagnostics = face.diagnostics
        if diagnostics is not None:
            values.update(left_eye_width_pixels=diagnostics.left_eye.width_pixels,
                          right_eye_width_pixels=diagnostics.right_eye.width_pixels)
        # Record the eye-admission failure, but still inspect this capture's
        # independent face box and pose. A blink must not restart the head's
        # positioning interval when that geometry remains observable and stable.
        eye_failure = None
        if diagnostics is None or not diagnostics.left_eye.valid or not diagnostics.right_eye.valid:
            eye_failure = ("eyes_not_visible", "Keep both eyes visible")
        eye_widths = (() if diagnostics is None else
                      (diagnostics.left_eye.width_pixels, diagnostics.right_eye.width_pixels))
        if eye_failure is None and any(not _finite_number(width) or width <= 0 for width in eye_widths):
            eye_failure = ("eye_size_unavailable", "Keep both eyes visible")
        if (values["face_width_pixels"] < self.config.min_face_width_pixels
                or values["face_height_pixels"] < self.config.min_face_height_pixels):
            return self._fail("face_too_small", "Move closer", values)
        if eye_failure is None and min(eye_widths) < self.config.min_eye_width_pixels:
            eye_failure = ("face_too_small", "Move closer")
        pose = face.head_pose
        if pose is None or not all(_finite_number(value) for value in (pose.yaw, pose.pitch, pose.roll)):
            if eye_failure is not None:
                return self._fail(*eye_failure, values, geometry_reason="head_pose_unavailable")
            return self._fail("head_pose_unavailable", "Face the screen naturally", values)
        values.update(yaw_degrees=pose.yaw, pitch_degrees=pose.pitch, roll_degrees=pose.roll)
        if (abs(pose.yaw) > self.config.max_yaw_degrees
                or abs(pose.pitch) > self.config.max_pitch_degrees
                or abs(pose.roll) > self.config.max_roll_degrees):
            return self._fail("head_not_frontal", "Face the screen naturally", values)
        # The combined feature function also rejects missing head pose while
        # keeping both individual eye diagnostics valid. Check pose first so
        # that this case is not incorrectly described as hidden eyes.
        if eye_failure is None and not diagnostics.valid and diagnostics.reason.startswith("eyes disagree"):
            eye_failure = ("eye_measurements_disagree", "Hold still — eye measurements disagree")
        if eye_failure is None and (not diagnostics.valid or face.features is None or len(face.features) != 4
                or not all(_finite_number(value) for value in face.features)):
            eye_failure = ("eye_measurements_invalid", "Hold still — eye measurements unavailable")
        if eye_failure is None and (not _finite_number(face.quality) or face.quality < self.config.min_quality):
            eye_failure = ("eye_quality_low", "Keep both eyes visible")

        center_x, center_y = box.center
        moved = (self._anchor is not None
                 and (_exceeds(abs(center_x - self._anchor[0]), self.config.max_center_drift)
                      or _exceeds(abs(center_y - self._anchor[1]), self.config.max_center_drift)
                      or _exceeds(abs(box.width / self._anchor[2] - 1), self.config.max_scale_change)
                      or _exceeds(abs(box.height / self._anchor[3] - 1), self.config.max_scale_change)))
        gap = self._stable_last is not None and stamp - self._stable_last > self.config.max_sample_gap_seconds
        size_changed = self._anchor_frame_size is not None and size != self._anchor_frame_size
        if moved or gap or size_changed:
            self._invalidate_geometry("source_dimensions_changed" if size_changed else
                                      "capture_gap" if gap else "face_moved")
        if unique:
            if self._anchor is None:
                self._anchor = (center_x, center_y, box.width, box.height)
                self._anchor_frame_size = size
                self._stable_since = stamp
            self._stable_last = stamp
            self._stable_samples += 1
        elapsed = 0.0 if self._stable_since is None or self._stable_last is None else self._stable_last - self._stable_since
        progress = min(1.0, elapsed / self.config.stable_seconds,
                       self._stable_samples / self.config.min_stable_samples)
        positioning_stable = (elapsed >= self.config.stable_seconds
                              and self._stable_samples >= self.config.min_stable_samples)
        ready = positioning_stable and eye_failure is None
        reason, message = eye_failure or (("aligned", "Face aligned") if ready else ("hold_still", "Hold still"))
        self._status = AlignmentStatus(ready, reason, message, progress,
                                       self.config.guide, stable_samples=self._stable_samples,
                                       stable_elapsed_seconds=elapsed, geometry_valid=True,
                                       positioning_stable=positioning_stable,
                                       geometry_generation=self._geometry_generation,
                                       geometry_reset_reason=self._geometry_reset_reason, **values)
        return self._status


def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _exceeds(value: float, limit: float) -> bool:
    # Preserve inclusive configured boundaries despite normalized-coordinate
    # subtraction/division rounding (for example 0.44 / 0.4 - 1).
    return value > limit and not math.isclose(value, limit, rel_tol=0.0, abs_tol=1e-12)
