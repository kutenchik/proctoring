"""Convert fresh complete observations into deduplicated review events.

Evidence duration uses observation monotonic timestamps, never UI ticks or wall
time. The engine deliberately does not infer continued evidence between outages.
The session health controller must call ``interrupt`` as soon as monitoring fails.
"""

from dataclasses import dataclass
import math

from proctoring.clock import Clock
from proctoring.domain import EVENT_LABELS, EventType, Observation


@dataclass
class _Evidence:
    start: float
    start_timestamp: str
    last_positive: float
    confidence: float | None
    source: str
    clearing_since: float | None = None
    event: dict | None = None


class EventEngine:
    """One event per sustained condition, with configurable clearing hysteresis.

    ``conditions`` is a complete sample: an absent key means false; a present key
    with ``None`` means true without an available confidence score. Confidence in
    the record is the highest available source confidence during that event.

    Change records include an ``action`` (activated/updated/clearing/closed).
    Candidates are not persisted as events. Public records are defensive copies.
    """

    def __init__(
        self,
        thresholds: dict[EventType, float],
        clearing_seconds: float,
        clock: Clock,
        max_observation_gap: float = 2.0,
    ):
        if not thresholds:
            raise ValueError("At least one event threshold is required")
        self.thresholds = {EventType(key): float(value) for key, value in thresholds.items()}
        for value in self.thresholds.values():
            self._positive_finite(value, "Event thresholds")
        self.clearing_seconds = float(clearing_seconds)
        self._positive_finite(self.clearing_seconds, "Clearing duration")
        self.max_observation_gap = float(max_observation_gap)
        self._positive_finite(self.max_observation_gap, "Maximum observation gap")
        self.clock = clock
        self._evidence: dict[EventType, _Evidence] = {}
        self._events: list[dict] = []
        self._last_observation: float | None = None
        self._minimum_timestamp = float("-inf")

    @staticmethod
    def _positive_finite(value: float, name: str) -> None:
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and greater than zero")

    @property
    def events(self) -> list[dict]:
        return [dict(event) for event in self._events]

    @property
    def states(self) -> dict[EventType, str]:
        return {
            kind: (
                "closed" if kind not in self._evidence
                else "candidate" if self._evidence[kind].event is None
                else self._evidence[kind].event["state"]
            )
            for kind in self.thresholds
        }

    def observe(self, observation: Observation) -> list[dict]:
        """Process one new sample, ignoring reordered/duplicate/stale evidence.

        A gap greater than ``max_observation_gap`` closes active events and resets
        candidates before considering the new sample. A future timestamp is an
        invalid clock-domain mismatch and is rejected.
        """
        timestamp = float(observation.timestamp)
        now = self.clock.monotonic()
        if not math.isfinite(timestamp) or timestamp > now + 1e-6:
            raise ValueError("Observation timestamp must be finite and not in the future")
        if timestamp < self._minimum_timestamp:
            return []
        if self._last_observation is not None and timestamp <= self._last_observation:
            return []
        if now - timestamp > self.max_observation_gap:
            return self.interrupt("stale_observation")

        conditions = {EventType(kind): confidence for kind, confidence in observation.conditions.items()}
        for confidence in conditions.values():
            if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
                raise ValueError("Detection confidence must be between zero and one, or None")

        changes: list[dict] = []
        if self._last_observation is not None and timestamp - self._last_observation > self.max_observation_gap:
            changes.extend(self._reset("observation_gap"))
        self._last_observation = timestamp
        wall_timestamp = self.clock.wall_time()

        for kind, threshold in self.thresholds.items():
            evidence = self._evidence.get(kind)
            # An expired clearing period closes even if this sample is positive.
            # A fresh candidate then starts; unseen time cannot bridge the gap.
            if evidence is not None and evidence.clearing_since is not None:
                if timestamp - evidence.clearing_since >= self.clearing_seconds:
                    changes.append(self._close(kind, evidence, "condition_cleared", wall_timestamp))
                    evidence = None

            if kind in conditions:
                confidence = conditions[kind]
                if evidence is None:
                    self._evidence[kind] = _Evidence(timestamp, wall_timestamp, timestamp, confidence, observation.source)
                    continue
                evidence.last_positive = timestamp
                evidence.source = observation.source
                if confidence is not None:
                    evidence.confidence = confidence if evidence.confidence is None else max(evidence.confidence, confidence)
                evidence.clearing_since = None
                if evidence.event is None:
                    if timestamp - evidence.start >= threshold:
                        evidence.event = {
                            "event_id": f"event-{len(self._events) + 1:06d}",
                            "event_type": kind.value,
                            "label": EVENT_LABELS[kind],
                            "state": "active",
                            "start_timestamp": evidence.start_timestamp,
                            "activated_timestamp": wall_timestamp,
                            "closed_timestamp": None,
                            "duration_seconds": timestamp - evidence.start,
                            "confidence": evidence.confidence,
                            "source": evidence.source,
                            "close_reason": None,
                        }
                        self._events.append(evidence.event)
                        changes.append(self._change(evidence.event, "activated"))
                else:
                    evidence.event.update(
                        state="active",
                        duration_seconds=timestamp - evidence.start,
                        confidence=evidence.confidence,
                        source=evidence.source,
                    )
                    changes.append(self._change(evidence.event, "updated"))
            elif evidence is not None:
                if evidence.event is None:
                    del self._evidence[kind]
                elif evidence.clearing_since is None:
                    evidence.clearing_since = timestamp
                    evidence.event["state"] = "clearing"
                    changes.append(self._change(evidence.event, "clearing"))
        return changes

    @staticmethod
    def _change(event: dict, action: str) -> dict:
        return {**event, "action": action}

    def _close(self, kind: EventType, evidence: _Evidence, reason: str, wall_timestamp: str) -> dict:
        assert evidence.event is not None
        evidence.event.update(
            state="closed",
            closed_timestamp=wall_timestamp,
            duration_seconds=evidence.last_positive - evidence.start,
            close_reason=reason,
        )
        del self._evidence[kind]
        return self._change(evidence.event, "closed")

    def _reset(self, reason: str) -> list[dict]:
        changes = []
        wall_timestamp = self.clock.wall_time()
        for kind, evidence in list(self._evidence.items()):
            if evidence.event is not None:
                changes.append(self._close(kind, evidence, reason, wall_timestamp))
            else:
                del self._evidence[kind]
        return changes

    def interrupt(self, reason: str = "monitoring_unavailable") -> list[dict]:
        """Close active events and discard candidates without counting outage time."""
        changes = self._reset(reason)
        # Drop observations captured before the interruption, even if they arrive
        # later through a worker queue. Keep last timestamp for duplicate checks.
        self._minimum_timestamp = self.clock.monotonic()
        return changes

    def close_all(self, reason: str = "session_ended") -> list[dict]:
        return self.interrupt(reason)
