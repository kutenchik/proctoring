from ..domain import EventType, Observation


class SyntheticMonitor:
    """Explicit test input, never represented as camera or model output.

    Stage 3 will derive gaze features from MediaPipe landmarks and per-session
    calibration; MediaPipe does not directly return these event classifications.
    """
    def __init__(self):
        self.conditions: dict[EventType, float | None] = {}
        self.available = True
        self.stalled = False
        self.stopped = False

    def set_condition(self, event_type: EventType, enabled: bool) -> None:
        if enabled:
            # Explicitly synthetic score, not a measured model confidence.
            self.conditions[event_type] = 0.9
        else:
            self.conditions.pop(event_type, None)

    def sample(self, timestamp: float) -> Observation | None:
        if not self.available or self.stalled or self.stopped:
            return None
        return Observation(timestamp=timestamp, conditions=dict(self.conditions), source="synthetic")

    def stop(self) -> None:
        self.stopped = True

