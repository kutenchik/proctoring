"""Optional, unvalidated ear-adjacent appearance heuristic for operator review.

Face Mesh has no true ear-canal/tragus landmarks. Supplied regions are small
patches adjacent to the outer cheek contour, not verified ear anatomy. Hair,
glasses, lighting and skin can produce the same appearance as an accessory.
"""
from dataclasses import dataclass
import math

import numpy as np

from .types import FaceMeasurement


@dataclass(frozen=True)
class AccessoriesConfig:
    earphone_detection_enabled: bool = False
    min_ear_yaw_trigger: float = 12.

    def __post_init__(self):
        if type(self.earphone_detection_enabled) is not bool:
            raise ValueError("vision.accessories.earphone_detection_enabled must be true or false")
        value = self.min_ear_yaw_trigger
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value < 35:
            raise ValueError("vision.accessories.min_ear_yaw_trigger must be in [0, 35)")


@dataclass(frozen=True)
class AccessoryObservation:
    suspected: bool = False
    status: str = "Ear-adjacent appearance heuristic disabled"
    consecutive_anomalies: int = 0


def patch_anomaly(patch) -> bool:
    """Conservative contrast + minority light/dark patch rule, not recognition."""
    import cv2
    if patch is None or patch.ndim != 3 or min(patch.shape[:2]) < 8 or patch.shape[2] != 3:
        return False
    if not np.isfinite(patch).all() or patch.dtype != np.uint8:
        return False
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float64) / 255.
    saturated = hsv[..., 1].astype(np.float64) / 255.
    light = float(np.mean((gray > .82) & (saturated < .28)))
    dark = float(np.mean(gray < .16))
    horizontal_edges = np.abs(np.diff(gray, axis=1))
    vertical_edges = np.abs(np.diff(gray, axis=0))
    edge_fraction = float((np.count_nonzero(horizontal_edges > .25) + np.count_nonzero(vertical_edges > .25)) /
                          (horizontal_edges.size + vertical_edges.size))
    return (float(gray.std()) >= .12 and edge_fraction >= .035 and
            (.06 <= light <= .55 or .06 <= dark <= .40))


class EarphoneHeuristicDetector:
    def __init__(self, config: AccessoriesConfig):
        self.config = config
        self.reset()

    def reset(self):
        self._count = 0
        self._last_at = None
        self._side = None

    def observe(self, frame, face: FaceMeasurement, timestamp: float) -> AccessoryObservation:
        if not self.config.earphone_detection_enabled:
            self.reset()
            return AccessoryObservation()
        previous = self._last_at
        if not math.isfinite(timestamp) or (previous is not None and timestamp <= previous):
            self.reset()
            return AccessoryObservation(status="Ear appearance requires a fresh frame")
        self._last_at = timestamp
        if previous is not None and timestamp - previous >= 2.:
            self._count = 0
        pose = face.head_pose
        if (not face.face_present or face.detected_face_count != 1 or pose is None
                or not all(math.isfinite(x) for x in (pose.yaw, pose.pitch, pose.roll))
                or not self.config.min_ear_yaw_trigger < abs(pose.yaw) <= 35
                or abs(pose.pitch) > 20 or abs(pose.roll) > 15):
            self._count = 0
            return AccessoryObservation(status="Ear appearance unavailable at this face pose")
        side = 0 if pose.yaw > 0 else 1
        if side != self._side:
            self._count = 0
            self._side = side
        if (frame is None or frame.ndim != 3 or tuple(frame.shape[1::-1]) != face.frame_size
                or len(face.ear_regions) != 2):
            self._count = 0
            return AccessoryObservation(status="Matching ear-adjacent source patch unavailable")
        region = face.ear_regions[side]
        if (not all(math.isfinite(x) for x in (region.x1, region.y1, region.x2, region.y2))
                or region.x1 < 0 or region.y1 < 0 or region.x2 > 1 or region.y2 > 1):
            self._count = 0
            return AccessoryObservation(status="Ear-adjacent patch clipped by camera frame")
        height, width = frame.shape[:2]
        patch = frame[round(region.y1 * height):round(region.y2 * height),
                      round(region.x1 * width):round(region.x2 * width)]
        anomaly = patch_anomaly(patch)
        self._count = self._count + 1 if anomaly else 0
        return AccessoryObservation(self._count >= 5,
                                    "Ear-adjacent contrast anomaly; unvalidated accessory suspicion" if anomaly else
                                    "No persistent ear-adjacent appearance anomaly",
                                    self._count)
