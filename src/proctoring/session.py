"""Exam lifecycle and timer, independent of Qt and computer vision.

Durations only use Clock.monotonic(). The timer accrues time in running
segments, never by counting UI timer callbacks.
"""
from __future__ import annotations

import math

from proctoring.clock import Clock
from proctoring.registration import CandidateInfo


class SessionController:
    def __init__(self, clock: Clock, duration_seconds: float,
                 recovery_seconds: float = 15.0):
        for name, value in (("duration_seconds", duration_seconds),
                            ("recovery_seconds", recovery_seconds)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        self.clock = clock
        self.duration_seconds = float(duration_seconds)
        self.time_adjustment_ids = []
        self.recovery_seconds = float(recovery_seconds)
        self.started = False
        self.ended = False
        self.end_reason: str | None = None
        self.records: list[dict] = []
        self._elapsed = 0.0
        self._running_since: float | None = None
        self._timing_boundary = self.clock.monotonic()
        self._pause_reasons: set[str] = set()
        self._monitoring_healthy = True
        self._failure_since: float | None = None
        self._candidate: CandidateInfo | None = None

    @property
    def candidate(self) -> CandidateInfo | None:
        return self._candidate

    def set_candidate(self, candidate: CandidateInfo | dict, *, require_group: bool = True) -> None:
        if self.started or self.ended:
            raise RuntimeError("Candidate identity cannot change after the session starts")
        values = candidate.as_dict() if isinstance(candidate, CandidateInfo) else candidate
        self._candidate = CandidateInfo.from_dict(values, require_group=require_group)

    @property
    def pause_reasons(self) -> set[str]:
        return set(self._pause_reasons)

    @property
    def monitoring_healthy(self) -> bool:
        return self._monitoring_healthy

    @property
    def recovery_pin_required(self) -> bool:
        return "recovery_pin" in self._pause_reasons

    @property
    def running(self) -> bool:
        return self.started and not self.ended and not self._pause_reasons

    def _elapsed_at(self, now: float) -> float:
        segment = (max(0.0, now - self._running_since)
                   if self._running_since is not None else 0.0)
        return min(self.duration_seconds, self._elapsed + segment)

    @property
    def elapsed_seconds(self) -> float:
        return self._elapsed_at(self.clock.monotonic())

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.duration_seconds - self.elapsed_seconds)

    def _record(self, event_type: str, **details) -> None:
        self.records.append({
            "timestamp": self.clock.wall_time(),
            "event_type": event_type,
            "elapsed_seconds": self.elapsed_seconds,
            **details,
        })

    def _freeze(self, now: float) -> None:
        self._elapsed = self._elapsed_at(now)
        self._running_since = None
        self._timing_boundary = now

    def _latch_recovery_requirement(self, now: float) -> None:
        if (self.started and not self.ended
                and self._failure_since is not None
                and now - self._failure_since >= self.recovery_seconds
                and not self.recovery_pin_required):
            self._pause_reasons.add("recovery_pin")
            self._record("recovery_pin_required")

    def _synchronize(self) -> float:
        now = self.clock.monotonic()
        if self.running and self._elapsed_at(now) >= self.duration_seconds:
            self._finish("time_expired", now)
        self._latch_recovery_requirement(now)
        return now

    def start(self) -> None:
        if self.started or self.ended:
            raise RuntimeError("A session can only be started once")
        if not self.monitoring_healthy:
            raise RuntimeError("Monitoring must be healthy before starting")
        self.started = True
        now = self.clock.monotonic()
        self._running_since = now if not self._pause_reasons else None
        self._timing_boundary = now
        self._record("session_recovered" if getattr(self, '_restored', False) else "session_started")

    def restore_connected_checkpoint(self, checkpoint):
        """After teacher authorization, before ordinary start/readiness/arming.

        Closed time is never accrued. Monitoring/presentation are re-established
        by fresh checks; independent human pause/PIN requirements are retained.
        """
        if self.started or self.ended or checkpoint.get('ended'):
            raise ValueError('Terminal or running sessions cannot recover')
        duration = checkpoint.get('duration_seconds', self.duration_seconds)
        adjustment_ids = checkpoint.get('time_adjustment_ids', [])
        if (type(duration) not in (int,float) or not math.isfinite(duration) or not self.duration_seconds <= duration <= 172800 or
                not isinstance(adjustment_ids, list) or len(adjustment_ids)>2048 or
                any(not isinstance(value,str) or not 1 <= len(value) <= 128 for value in adjustment_ids) or
                len(set(adjustment_ids)) != len(adjustment_ids) or (duration != self.duration_seconds and not adjustment_ids)):
            raise ValueError('Invalid saved time allowance')
        self.duration_seconds = float(duration)
        self.time_adjustment_ids = list(adjustment_ids)
        elapsed = checkpoint['elapsed_seconds']
        if type(elapsed) not in (float, int) or not math.isfinite(elapsed) or not 0 <= elapsed < self.duration_seconds:
            raise ValueError('Invalid recovery timing')
        reasons = set(checkpoint.get('pause_reasons', []))
        if not reasons <= {'proctor', 'recovery_pin', 'monitoring', 'presentation', 'teacher', 'display'}:
            raise ValueError('Unknown saved pause reason')
        self._elapsed = float(elapsed)
        self._running_since = None
        self._pause_reasons = reasons & {'proctor', 'recovery_pin', 'teacher', 'display'}
        self.records = list(checkpoint.get('lifecycle', []))
        self._restored = any(r.get('event_type') == 'session_started' for r in self.records)

    def tick(self) -> None:
        """Check expiry and recovery deadline; callback frequency is irrelevant."""
        self._synchronize()

    def monitoring_failed(self, reason: str = "Monitoring unavailable",
                          detected_at: float | None = None) -> bool:
        """Pause at a known monotonic failure onset, even if polled later.

        A missed observation deadline may precede this callback. Account only
        for healthy time before that deadline, before checking current expiry.
        The onset is bounded by the current timing segment: delayed evidence
        cannot rewrite previously completed running or paused segments.
        """
        now = self.clock.monotonic()
        onset = now if detected_at is None else float(detected_at)
        if not math.isfinite(onset) or onset > now:
            raise ValueError("Failure onset must be finite and no later than now")
        if self.ended:
            return False
        if not self.monitoring_healthy:
            self._latch_recovery_requirement(now)
            return False
        onset = max(self._timing_boundary, onset)
        if self.running and self._elapsed_at(onset) >= self.duration_seconds:
            self._finish("time_expired", onset)
            return False
        self._freeze(onset)
        self._monitoring_healthy = False
        self._failure_since = onset
        self._pause_reasons.add("monitoring")
        self._record("monitoring_failed", reason=reason,
                     detection_delay_seconds=now - onset)
        self._latch_recovery_requirement(now)
        return True

    def monitoring_recovered(self) -> bool:
        now = self._synchronize()
        if self.ended or self.monitoring_healthy:
            return False
        duration = max(0.0, now - self._failure_since)
        self._monitoring_healthy = True
        self._failure_since = None
        self._pause_reasons.discard("monitoring")
        if self.running:
            self._running_since = now
            self._timing_boundary = now
        self._record(
            "monitoring_recovered", duration=duration,
            recovery="pin_required" if self.recovery_pin_required else "automatic",
            resumed=self.running,
        )
        return True

    def pause_by_proctor(self) -> bool:
        now = self._synchronize()
        if not self.started or self.ended or "proctor" in self._pause_reasons:
            return False
        self._freeze(now)
        self._pause_reasons.add("proctor")
        self._record("proctor_paused")
        return True

    def presentation_lost(self) -> bool:
        """Electron presentation loss is independent of camera/PIN recovery."""
        now = self._synchronize()
        if not self.started or self.ended or 'presentation' in self._pause_reasons:
            return False
        self._freeze(now)
        self._pause_reasons.add('presentation')
        self._record('presentation_lost')
        return True

    def presentation_recovered(self) -> bool:
        """Call only after the trusted host acknowledged a fresh state snapshot."""
        now = self._synchronize()
        if not self.started or self.ended or 'presentation' not in self._pause_reasons:
            return False
        self._pause_reasons.discard('presentation')
        if self.running:
            self._running_since = now
            self._timing_boundary = now
        self._record('presentation_recovered', resumed=self.running)
        return True

    def resume_by_proctor(self, pin_valid: bool) -> bool:
        now = self._synchronize()
        if (not self.started or self.ended or not pin_valid
                or not self.monitoring_healthy or not self._pause_reasons):
            return False
        self._pause_reasons.discard("proctor")
        self._pause_reasons.discard("recovery_pin")
        if self.running:
            self._running_since = now
            self._timing_boundary = now
        self._record("proctor_resumed", recovery="proctor_pin", resumed=self.running)
        return self.running

    def _finish(self, reason: str, now: float) -> None:
        self._freeze(now)
        if self._failure_since is not None:
            self._record("monitoring_interruption_ended",
                         duration=max(0.0, now - self._failure_since),
                         recovery="session_ended", resumed=False)
            self._failure_since = None
        self.ended = True
        self.end_reason = reason
        self._pause_reasons.clear()
        self._record("session_ended", reason=reason)

    def teacher_pause(self, **audit) -> bool:
        now = self._synchronize()
        if not self.started or self.ended:
            return False
        self._freeze(now)
        changed = 'teacher' not in self._pause_reasons
        self._pause_reasons.add('teacher')
        self._record('teacher_paused', changed=changed, **audit)
        return True

    def teacher_resume(self, **audit) -> bool:
        now = self._synchronize()
        if not self.started or self.ended or 'teacher' not in self._pause_reasons:
            return False
        self._pause_reasons.discard('teacher')
        if self.running:
            self._running_since = self._timing_boundary = now
        self._record('teacher_resumed', resumed=self.running, **audit)
        return True

    def teacher_monitoring_recovery(self, **audit) -> bool:
        now = self._synchronize()
        if not self.started or self.ended or not self.monitoring_healthy or not self.recovery_pin_required:
            return False
        self._pause_reasons.discard('recovery_pin')
        if self.running:
            self._running_since = self._timing_boundary = now
        self._record('teacher_monitoring_recovered', resumed=self.running, **audit)
        return True

    def display_pause(self, **audit) -> bool:
        now = self._synchronize()
        if not self.started or self.ended or 'display' in self._pause_reasons:
            return False
        self._freeze(now)
        self._pause_reasons.add('display')
        self._record('display_interrupted', **audit)
        return True

    def teacher_display_recovery(self, **audit) -> bool:
        now = self._synchronize()
        if not self.started or self.ended or 'display' not in self._pause_reasons:
            return False
        self._pause_reasons.discard('display')
        if self.running:
            self._running_since = self._timing_boundary = now
        self._record('teacher_display_recovered', resumed=self.running, **audit)
        return True

    def teacher_add_time(self, seconds, command_id, **audit) -> bool:
        self._synchronize()
        if (not self.started or self.ended or type(seconds) is not int or not 1 <= seconds <= 3600 or
                self.duration_seconds+seconds > 172800 or command_id in self.time_adjustment_ids):
            return False
        old = self.duration_seconds
        self.duration_seconds += seconds
        self.time_adjustment_ids.append(command_id)
        self._record('teacher_time_added', old_duration_seconds=old, duration_seconds=self.duration_seconds,
                     delta_seconds=seconds, command_id=command_id, **audit)
        return True

    def end(self, reason: str = "completed") -> bool:
        now = self._synchronize()
        if not self.started or self.ended:
            return False
        self._finish(reason, now)
        return True
