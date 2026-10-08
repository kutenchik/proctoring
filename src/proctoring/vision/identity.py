"""Optional landmark-shape consistency heuristic, not biometric authentication.

MediaPipe's face mesh is not a trained identity embedding. Rigidly aligned face
shape can be an operator-review cue, but neither a match nor a mismatch proves
identity. All comparisons and baseline JPEG encoding run on the vision worker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

from .types import FaceMeasurement


def normalized_points(points) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or len(values) < 8 or not np.isfinite(values).all():
        raise ValueError("Face shape landmarks are missing or invalid")
    centered = values - values.mean(axis=0)
    scale = float(np.sqrt(np.mean(np.sum(centered ** 2, axis=1))))
    if scale < 1e-8 or np.linalg.matrix_rank(centered, tol=1e-8) < 2:
        raise ValueError("Face shape landmarks are degenerate")
    return centered / scale


def procrustes_distance(reference, current) -> float:
    """RMS residual / face RMS radius, after translation, scale and rotation.

    Reflections are deliberately not aligned away. This unitless shape distance
    is not a probability and must not be presented as identity confidence.
    """
    baseline, observed = normalized_points(reference), normalized_points(current)
    if baseline.shape != observed.shape:
        raise ValueError("Face shape landmark counts differ")
    left, _, right = np.linalg.svd(observed.T @ baseline)
    correction = np.eye(3)
    correction[-1, -1] = 1. if np.linalg.det(left @ right) >= 0 else -1.
    rotation = left @ correction @ right
    return float(np.sqrt(np.mean(np.sum((observed @ rotation - baseline) ** 2, axis=1))))


def face_quality_reason(face: FaceMeasurement) -> str | None:
    if not face.face_present or face.box is None:
        return "No valid face for identity comparison"
    if face.detected_face_count != 1:
        return "Exactly one face is required for identity comparison"
    pose = face.head_pose
    if pose is None or not all(math.isfinite(x) for x in (pose.yaw, pose.pitch, pose.roll)):
        return "Face pose unavailable for identity comparison"
    if abs(pose.yaw) > 15 or abs(pose.pitch) > 15 or abs(pose.roll) > 12:
        return "Face approximately forward for identity comparison"
    box = face.box
    if not all(math.isfinite(x) for x in (box.x1, box.y1, box.x2, box.y2)):
        return "Face region invalid for identity comparison"
    if box.x1 <= .005 or box.y1 <= .005 or box.x2 >= .995 or box.y2 >= .995:
        return "Full face must remain in the source image"
    if face.frame_size is None or box.width * face.frame_size[0] < 80 or box.height * face.frame_size[1] < 80:
        return "Face too small for identity comparison"
    try:
        normalized_points(face.identity_points)
    except (TypeError, ValueError, np.linalg.LinAlgError):
        return "Face shape landmarks unavailable or unreliable"
    return None


@dataclass(frozen=True)
class IdentityBaseline:
    jpeg_bytes: bytes = field(repr=False)
    points: tuple[tuple[float, float, float], ...] = field(repr=False)
    timestamp: float
    frame_size: tuple[int, int]
    crop_box: tuple[int, int, int, int]

    @property
    def metadata(self) -> dict:
        # Shape coordinates deliberately remain only in session memory.
        return {"captured_monotonic": self.timestamp, "source_frame_size": list(self.frame_size),
                "crop_box_pixels": list(self.crop_box), "image_size": [256, 256],
                "algorithm": "normalized_procrustes_face_shape_v1",
                "purpose": "Unvalidated face-shape consistency review; not identity authentication"}


@dataclass(frozen=True)
class IdentityObservation:
    suspected: bool = False
    distance: float | None = None
    status: str = "Identity comparison disabled"
    checked: bool = False
    consecutive_mismatches: int = 0


class IdentityVerifier:
    def __init__(self, *, threshold: float = .4, interval_seconds: float = 30.):
        if not math.isfinite(threshold) or threshold <= 0 or not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("Identity threshold and interval must be positive and finite")
        self.threshold = threshold
        self.interval_seconds = interval_seconds
        self.baseline: IdentityBaseline | None = None
        self.reset_checks()

    def reset_checks(self) -> None:
        self._last_check: float | None = None
        self._last_frame: float | None = None
        self._mismatches = 0
        self._suspected = False

    def capture_baseline(self, frame, face: FaceMeasurement, timestamp: float) -> IdentityBaseline:
        import cv2
        if not math.isfinite(timestamp):
            raise ValueError("Baseline timestamp must be finite")
        reason = face_quality_reason(face)
        if reason:
            raise ValueError(reason)
        if frame is None or frame.ndim != 3 or tuple(frame.shape[1::-1]) != face.frame_size:
            raise ValueError("Baseline needs the matching source frame")
        height, width = frame.shape[:2]
        box = face.box
        margin_x, margin_y = box.width * .08, box.height * .08
        x1 = max(0, int((box.x1 - margin_x) * width))
        y1 = max(0, int((box.y1 - margin_y) * height))
        x2 = min(width, int(math.ceil((box.x2 + margin_x) * width)))
        y2 = min(height, int(math.ceil((box.y2 + margin_y) * height)))
        crop = frame[y1:y2, x1:x2]
        scale = 256 / max(crop.shape[:2])
        resized = cv2.resize(crop, (max(1, round(crop.shape[1] * scale)),
                                    max(1, round(crop.shape[0] * scale))))
        image = np.zeros((256, 256, 3), dtype=np.uint8)
        top, left = (256 - resized.shape[0]) // 2, (256 - resized.shape[1]) // 2
        image[top:top + resized.shape[0], left:left + resized.shape[1]] = resized
        success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not success:
            raise ValueError("Reference face JPEG encoding failed")
        points = tuple(tuple(float(value) for value in row) for row in normalized_points(face.identity_points))
        self.baseline = IdentityBaseline(encoded.tobytes(), points, timestamp, face.frame_size, (x1, y1, x2, y2))
        self.reset_checks()
        return self.baseline

    def observe(self, face: FaceMeasurement, timestamp: float) -> IdentityObservation:
        if self.baseline is None:
            return IdentityObservation(status="Reference face not captured")
        if not math.isfinite(timestamp) or (self._last_frame is not None and timestamp <= self._last_frame):
            return IdentityObservation(status="Identity comparison requires a fresh frame")
        self._last_frame = timestamp
        reason = face_quality_reason(face)
        if reason:
            self._mismatches = 0
            self._suspected = False
            return IdentityObservation(status=reason)
        if self._last_check is not None and timestamp - self._last_check < self.interval_seconds:
            return IdentityObservation(self._suspected, status="Waiting for next identity comparison",
                                       consecutive_mismatches=self._mismatches)
        self._last_check = timestamp
        try:
            distance = procrustes_distance(self.baseline.points, face.identity_points)
        except (TypeError, ValueError, np.linalg.LinAlgError):
            self._mismatches = 0
            self._suspected = False
            return IdentityObservation(status="Face shape comparison unavailable")
        self._mismatches = self._mismatches + 1 if distance > self.threshold else 0
        self._suspected = self._mismatches > 3
        status = ("Face shape differs repeatedly; operator review required" if self._suspected else
                  "Face shape mismatch pending repeat checks" if self._mismatches else
                  "Face shape consistent; identity not authenticated")
        return IdentityObservation(self._suspected, distance, status, True, self._mismatches)
