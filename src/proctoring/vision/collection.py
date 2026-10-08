"""Collection timing and position compatibility; no gaze classification rules."""
from dataclasses import dataclass
import math

from .alignment import AlignmentConfig


@dataclass(frozen=True)
class BoundedCollection:
    starts_at: float
    nominal_seconds: float
    maximum_seconds: float
    required_samples: int

    def __post_init__(self):
        if (not all(math.isfinite(v) for v in
                    (self.starts_at, self.nominal_seconds, self.maximum_seconds))
                or self.nominal_seconds <= 0 or self.maximum_seconds < self.nominal_seconds
                or type(self.required_samples) is not int or self.required_samples < 1):
            raise ValueError("Collection needs finite times, maximum >= nominal, and positive sample count")

    @property
    def nominal_end(self):
        return self.starts_at + self.nominal_seconds

    @property
    def deadline(self):
        return self.starts_at + self.maximum_seconds

    def outcome(self, now: float, count: int) -> str:
        """Call before admitting an arrival, and again after a valid sample.

        The minimum nominal wall interval is retained even if many unique frames
        arrive in a burst. Invalid samples never move the absolute deadline.
        Source freshness, uniqueness and interval admission remain the caller's
        responsibility. A frame arriving at/after deadline must not be admitted.
        """
        if not math.isfinite(now):
            raise ValueError("Collection clock must be finite")
        if now >= self.deadline:
            return "complete" if count >= self.required_samples else "timeout"
        if now >= self.nominal_end and count >= self.required_samples:
            return "complete"
        return "collect"


class CollectionPositionGuard:
    """Keep compatible completed targets while requiring return to their position.

    Uses the existing alignment drift/scale tolerances, not eye measurements.
    It does not re-anchor after motion: that would silently mix target baselines.
    Missing/failing fresh geometry is not considered compatible. A camera-size
    change requires a new baseline, whereas returning to the same seated position
    permits a local retry after the regular alignment stability interval.
    """
    def __init__(self, config: AlignmentConfig):
        self.config = config
        self.reset()

    def reset(self):
        self._reference = None

    @staticmethod
    def _geometry(result):
        face = getattr(result, "face", None)
        box = getattr(face, "box", None)
        size = getattr(face, "frame_size", None)
        if (not getattr(result, "face_present", False) or not getattr(face, "face_present", False)
                or box is None or size is None or len(size) != 2):
            return None
        values = (*size, *box.center, box.width, box.height)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            return None
        if min(*size, box.width, box.height) <= 0:
            return None
        return tuple(size), (*box.center, box.width, box.height)

    def anchor(self, result) -> bool:
        if self._reference is None:
            self._reference = self._geometry(result)
        return self._reference is not None

    def check(self, result, alignment_status) -> str:
        geometry = self._geometry(result)
        # A rejected stale/out-of-order capture must not reset an entire baseline
        # just because it carries different old camera metadata. Alignment only
        # exposes frame_size after independently checking the source timestamp.
        fresh_size = getattr(alignment_status, "frame_size", None)
        if (geometry is not None and fresh_size is not None and tuple(fresh_size) == geometry[0]
                and self._reference is not None and geometry[0] != self._reference[0]):
            return "camera_changed"
        if geometry is None or not getattr(alignment_status, "geometry_valid", False):
            return "geometry_unavailable"
        if self._reference is None:
            return "compatible"
        current, reference = geometry[1], self._reference[1]
        differences = (
            (abs(current[0] - reference[0]), self.config.max_center_drift),
            (abs(current[1] - reference[1]), self.config.max_center_drift),
            (abs(current[2] / reference[2] - 1), self.config.max_scale_change),
            (abs(current[3] / reference[3] - 1), self.config.max_scale_change),
        )
        if any(value > limit and not math.isclose(value, limit, abs_tol=1e-12, rel_tol=0)
               for value, limit in differences):
            return "position_changed"
        return "compatible"
