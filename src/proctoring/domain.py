from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    PHONE_VISIBLE = "phone_visible"
    SECOND_PERSON = "second_person"
    PHONE_RAISED = "phone_raised"
    GAZE_DOWN = "gaze_down"
    GAZE_LEFT = "gaze_left"
    GAZE_RIGHT = "gaze_right"
    FACE_ABSENT = "face_absent"


EVENT_LABELS = {
    EventType.PHONE_VISIBLE: "Phone visible",
    EventType.SECOND_PERSON: "Second person visible",
    EventType.PHONE_RAISED: "Phone raised — possible screen capture attempt.",
    EventType.GAZE_DOWN: "Prolonged downward gaze",
    EventType.GAZE_LEFT: "Prolonged gaze to the left",
    EventType.GAZE_RIGHT: "Prolonged gaze to the right",
    EventType.FACE_ABSENT: "Student’s face absent",
}


@dataclass(frozen=True)
class Observation:
    """One fresh complete sample; omitted conditions are false.

    Values are source detection confidence, not misconduct probability.
    Gaze signals will be derived from landmarks and session calibration in Stage 3.
    """
    timestamp: float
    conditions: dict[EventType, float | None] = field(default_factory=dict)
    source: str = "synthetic"

