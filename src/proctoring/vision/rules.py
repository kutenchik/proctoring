"""Geometry and observation mapping. Alerts belong only to the event engine."""
from __future__ import annotations

import math
from typing import Iterable

from ..domain import EventType, Observation
from .calibration import Calibration
from .settings import VisionConfig
from .types import Box, FaceMeasurement, GazeDirection, VisionResult


def _valid_box(box: Box) -> bool:
    return (all(math.isfinite(value) for value in
                (box.x1, box.y1, box.x2, box.y2, box.confidence))
            and 0 <= box.x1 < box.x2 <= 1 and 0 <= box.y1 < box.y2 <= 1
            and 0 <= box.confidence <= 1)


def filter_persons(boxes: Iterable[Box], config: VisionConfig) -> tuple[Box, ...]:
    return tuple(box for box in boxes if _valid_box(box)
                 and box.class_id in (-1, 0)
                 and box.confidence >= config.person_confidence
                 and box.area >= config.person_min_area
                 and box.height >= config.person_min_height)


def filter_phones(boxes: Iterable[Box], config: VisionConfig) -> tuple[Box, ...]:
    return tuple(box for box in boxes if _valid_box(box)
                 and box.class_id in (-1, 67)
                 and box.confidence >= config.phone_confidence
                 and box.area >= config.phone_min_area)


def phone_is_raised(phones: Iterable[Box], persons: Iterable[Box],
                    face: FaceMeasurement | None, config: VisionConfig) -> bool:
    """Phone near a face, or in an upper torso zone, is a review heuristic.

    No orientation/shutter inference is made. Duration is intentionally absent:
    the existing PHONE_RAISED event threshold supplies sustained-time handling.
    """
    phones = filter_phones(phones, config)
    persons = filter_persons(persons, config)
    face_box = face.box if face is not None and face.face_present else None
    if face_box is not None and not _valid_box(face_box):
        face_box = None
    for phone in phones:
        cx, cy = phone.center
        if face_box is not None:
            margin = config.raised_face_margin * face_box.height
            near_height = face_box.y1 - margin <= cy <= face_box.y2 + margin
            near_horizontal = abs(cx - face_box.center[0]) <= max(.18, 2.5 * face_box.width)
            if near_height and near_horizontal:
                return True
        # A visible face is not required: the phone may occlude the face.
        for person in persons:
            upper_end = person.y1 + config.raised_person_top_fraction * person.height
            if (person.x1 - .10 * person.width <= cx <= person.x2 + .10 * person.width
                    and person.y1 <= cy <= upper_end and cy <= .65):
                return True
    return False


def build_result(timestamp: float, persons: Iterable[Box], phones: Iterable[Box],
                 face: FaceMeasurement, calibration: Calibration, config: VisionConfig,
                 frame=None, yolo_latency_ms: float = 0, face_latency_ms: float = 0) -> VisionResult:
    persons = filter_persons(persons, config)
    phones = filter_phones(phones, config)
    direction, confidence = (calibration.classify(face.features) if face.face_present
                             else (GazeDirection.UNKNOWN, None))
    return VisionResult(
        timestamp=timestamp,
        phone_visible=bool(phones),
        phone_confidence=max((box.confidence for box in phones), default=None),
        person_count=len(persons),
        face_present=face.face_present,
        gaze_direction=direction,
        gaze_confidence=confidence,
        head_pose=face.head_pose,
        phone_raised=phone_is_raised(phones, persons, face, config),
        monitoring_healthy=True,
        persons=persons,
        phones=phones,
        face=face,
        frame=frame,
        yolo_latency_ms=yolo_latency_ms,
        face_latency_ms=face_latency_ms,
    )


def to_observation(result: VisionResult) -> Observation:
    """Only fresh healthy results are samples; never silently clear on failure."""
    if not result.monitoring_healthy or not math.isfinite(result.timestamp):
        raise ValueError("Unhealthy or invalid vision results must update monitoring health, not the event engine")
    conditions: dict[EventType, float | None] = {}
    if result.phone_visible:
        conditions[EventType.PHONE_VISIBLE] = result.phone_confidence
    if result.phone_raised and result.phone_visible:
        conditions[EventType.PHONE_RAISED] = result.phone_confidence
    if result.person_count >= 2:
        # Confidence of the second strongest person supports the count >= 2.
        scores = sorted((box.confidence for box in result.persons), reverse=True)
        conditions[EventType.SECOND_PERSON] = scores[1] if len(scores) >= 2 else None
    if not result.face_present:
        conditions[EventType.FACE_ABSENT] = None
    elif result.gaze_direction in (GazeDirection.LEFT, GazeDirection.RIGHT, GazeDirection.DOWN):
        gaze_event = {
            GazeDirection.LEFT: EventType.GAZE_LEFT,
            GazeDirection.RIGHT: EventType.GAZE_RIGHT,
            GazeDirection.DOWN: EventType.GAZE_DOWN,
        }[result.gaze_direction]
        conditions[gaze_event] = result.gaze_confidence
    return Observation(timestamp=result.timestamp, conditions=conditions, source="vision")
