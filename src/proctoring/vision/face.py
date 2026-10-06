"""CPU MediaPipe landmarks and measured eye/head features (not gaze labels).

Face Landmarker returns landmarks and a face transform. Our own geometry derives
features; only the session Calibration object is allowed to assign gaze classes.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from .settings import VisionConfig
from .types import Box, EyeDiagnostic, FaceMeasurement, GazeDiagnostics, HeadPose


def pose_from_matrix(matrix) -> HeadPose | None:
    """Approximate yaw/pitch/roll in degrees from the canonical face transform.

    Axis signs are camera conventions rather than gaze directions. Per-session
    calibration incorporates these signs and each student's neutral head pose.
    """
    try:
        rotation = [[float(matrix[i][j]) for j in range(3)] for i in range(3)]
        if not all(math.isfinite(value) for row in rotation for value in row):
            return None
        # Strip model scale from the columns before extracting Euler angles.
        for column in range(3):
            length = math.sqrt(sum(rotation[row][column] ** 2 for row in range(3)))
            if length < 1e-9:
                return None
            for row in range(3):
                rotation[row][column] /= length
        sy = math.hypot(rotation[0][0], rotation[1][0])
        pitch = math.atan2(rotation[2][1], rotation[2][2]) if sy > 1e-6 else math.atan2(-rotation[1][2], rotation[1][1])
        yaw = math.atan2(-rotation[2][0], sy)
        roll = math.atan2(rotation[1][0], rotation[0][0]) if sy > 1e-6 else 0.0
        return HeadPose(yaw=math.degrees(yaw), pitch=math.degrees(pitch), roll=math.degrees(roll))
    except (IndexError, TypeError, ValueError, OverflowError):
        return None


def _xy(landmark) -> tuple[float, float]:
    if hasattr(landmark, "x"):
        return float(landmark.x), float(landmark.y)
    return float(landmark[0]), float(landmark[1])


def _face_box(landmarks: Sequence) -> Box | None:
    if len(landmarks) < 468:
        return None
    try:
        points = [_xy(point) for point in landmarks[:468]]
        if not all(math.isfinite(value) for point in points for value in point):
            return None
        xs, ys = zip(*points)
        box = Box(max(0.0, min(xs)), max(0.0, min(ys)), min(1.0, max(xs)), min(1.0, max(ys)))
        return box if box.width > 0 and box.height > 0 else None
    except (IndexError, TypeError, ValueError):
        return None


def choose_primary_face(faces: Sequence[Sequence], min_area: float,
                        previous_box: Box | None = None) -> tuple[int, Box] | None:
    """Prefer the nearby previous primary, otherwise a large central face."""
    candidates = [(index, box) for index, face in enumerate(faces)
                  if (box := _face_box(face)) is not None and box.area >= min_area]
    if not candidates:
        return None
    if previous_box is not None:
        nearby = [(index, box) for index, box in candidates
                  if math.dist(box.center, previous_box.center) < max(.12, previous_box.width * .6)
                  and .45 <= box.area / max(previous_box.area, 1e-9) <= 2.2]
        if nearby:
            return min(nearby, key=lambda pair: math.dist(pair[1].center, previous_box.center))
    return max(candidates, key=lambda pair: pair[1].area / (1 + 2 * math.dist(pair[1].center, (.5, .45))))


def _eye_measurement(landmarks: Sequence, indices: tuple[int, ...],
                     frame_width: int, frame_height: int) -> EyeDiagnostic:
    try:
        first, second, upper, lower, iris = indices

        def pixel(index):
            x, y = _xy(landmarks[index])
            return x * frame_width, y * frame_height

        left, right = sorted((pixel(first), pixel(second)), key=lambda point: point[0])
        top, bottom, center = pixel(upper), pixel(lower), pixel(iris)
        if not all(math.isfinite(value) for point in (left, right, top, bottom, center) for value in point):
            return EyeDiagnostic(reason="non-finite eye landmarks")
        dx, dy = right[0] - left[0], right[1] - left[1]
        width = math.hypot(dx, dy)
        if width < 8:
            return EyeDiagnostic(reason="eye too small", width_pixels=width)
        ux, uy = dx / width, dy / width
        # Image y grows down. Sorting corners gives the same eye-local axes for
        # both eyes; computation stays in the original, unmirrored image.
        vx, vy = -uy, ux
        opening = abs((bottom[0] - top[0]) * vx + (bottom[1] - top[1]) * vy) / width
        horizontal = ((center[0] - left[0]) * ux + (center[1] - left[1]) * uy) / width
        midpoint = ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)
        vertical = .5 + ((center[0] - midpoint[0]) * vx + (center[1] - midpoint[1]) * vy) / width
        reason = ""
        if opening < .10:
            reason = "eye closed or aperture too narrow"
        elif opening > .75:
            reason = "implausible eyelid aperture"
        elif not (.02 <= horizontal <= .98 and .15 <= vertical <= .85):
            reason = "iris outside plausible eye geometry"
        return EyeDiagnostic(horizontal, vertical, opening, not reason, reason, width)
    except (IndexError, TypeError, ValueError, OverflowError):
        return EyeDiagnostic(reason="malformed or missing eye landmarks")


def eye_head_measurement(landmarks: Sequence, pose: HeadPose | None,
                         frame_width: int = 1280, frame_height: int = 720
                         ) -> tuple[tuple[float, ...] | None, float, GazeDiagnostics]:
    """Measure iris geometry independently from the head pose and expose validity.

    MediaPipe eye constants group 33/133/159/145 with iris center 468, and
    362/263/386/374 with 473. ``left_eye``/``right_eye`` follow its connection
    constants, independent of preview mirroring or anatomical gaze directions.

    Pixel-space axes compensate aspect ratio and in-plane head tilt. Vertical
    displacement uses the *corner axis*, not the moving eyelid midpoint: lids
    following a downward iris would otherwise cancel the signal. Eye width,
    rather than narrowing lid aperture, normalizes both iris coordinates.
    Blink/occlusion rejection remains separate from that calculation. These
    features are approximate measurements; session calibration assigns labels.
    """
    if frame_width <= 0 or frame_height <= 0:
        return None, 0.0, GazeDiagnostics(reason="invalid frame dimensions")
    if len(landmarks) < 478:
        return None, 0.0, GazeDiagnostics(reason="missing iris landmarks")
    right = _eye_measurement(landmarks, (33, 133, 159, 145, 468), frame_width, frame_height)
    left = _eye_measurement(landmarks, (362, 263, 386, 374, 473), frame_width, frame_height)
    reason = ""
    if not left.valid or not right.valid:
        reason = "; ".join(f"{side}: {eye.reason}" for side, eye in (("left", left), ("right", right)) if not eye.valid)
    # Strong disagreement can indicate occlusion or unusable iris landmarks.
    elif abs(left.horizontal - right.horizontal) > .30 or abs(left.vertical - right.vertical) > .18:
        reason = "eyes disagree; possible occlusion or unstable iris landmarks"
    elif pose is None or not all(math.isfinite(value) for value in (pose.yaw, pose.pitch, pose.roll)):
        reason = "head pose unavailable or invalid"
    diagnostics = GazeDiagnostics(left, right, not reason, reason)
    if reason:
        return None, 0.0, diagnostics
    features = ((left.horizontal + right.horizontal) / 2,
                (left.vertical + right.vertical) / 2,
                pose.yaw / 60.0, pose.pitch / 60.0)
    return features, min(1.0, left.opening / .22, right.opening / .22), diagnostics


def eye_head_features(landmarks: Sequence, pose: HeadPose | None,
                      frame_width: int = 1280, frame_height: int = 720
                      ) -> tuple[tuple[float, ...] | None, float]:
    """Compatibility interface returning the four measured features and quality."""
    features, quality, _ = eye_head_measurement(landmarks, pose, frame_width, frame_height)
    return features, quality


class FaceAnalyzer:
    """Local model, synchronous VIDEO inference; instantiate on a worker thread."""

    def __init__(self, config: VisionConfig):
        model_path = Path(config.face_model)
        if not model_path.is_file():
            raise FileNotFoundError(f"Local Face Landmarker model is missing: {model_path}")
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        self._mp = mp
        self.config = config
        self._last_timestamp_ms = -1
        self._previous_box: Box | None = None
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model_path), delegate=python.BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=2,
            min_face_detection_confidence=.5,
            min_face_presence_confidence=.5,
            min_tracking_confidence=.5,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def detect(self, frame, timestamp: float) -> FaceMeasurement:
        import cv2
        if not math.isfinite(timestamp):
            raise ValueError("Face timestamps must be finite monotonic seconds")
        milliseconds = max(self._last_timestamp_ms + 1, int(timestamp * 1000))
        self._last_timestamp_ms = milliseconds
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, milliseconds)
        chosen = choose_primary_face(result.face_landmarks, self.config.face_min_area, self._previous_box)
        frame_size = (frame.shape[1], frame.shape[0])
        if chosen is None:
            self._previous_box = None
            return FaceMeasurement(face_present=False, frame_size=frame_size)
        index, box = chosen
        self._previous_box = box
        landmarks = result.face_landmarks[index]
        transforms = result.facial_transformation_matrixes
        pose = pose_from_matrix(transforms[index]) if len(transforms) > index else None
        features, quality, diagnostics = eye_head_measurement(landmarks, pose, frame.shape[1], frame.shape[0])
        # Minimal overlay: face outline anchors, eye corners and iris centers.
        overlay_indices = (10, 152, 234, 454, 1, 33, 133, 362, 263, 468, 473)
        overlay = tuple(_xy(landmarks[i]) for i in overlay_indices if i < len(landmarks))
        return FaceMeasurement(face_present=True, box=box, landmarks=overlay,
                               features=features, head_pose=pose, quality=quality,
                               diagnostics=diagnostics, frame_size=frame_size)

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
