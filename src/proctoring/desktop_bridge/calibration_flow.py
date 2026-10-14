"""Guided collection adapter for Electron; existing gaze/position rules own fit.

Mirrors the legacy CalibrationWidget's orchestration without importing Widgets.
Each target waits for a renderer presentation acknowledgement before its monotonic
preparation interval begins. A resize/display change invalidates the baseline.
"""
from dataclasses import asdict
import math
from uuid import uuid4

from ..vision.alignment import FaceAlignment
from ..vision.calibration import DIRECTIONS
from ..vision.collection import BoundedCollection, CollectionPositionGuard
from .protocol import BridgeError


def source_size(result):
    size = getattr(getattr(result, 'face', None), 'frame_size', None)
    if size is not None:
        return tuple(size)
    frame = getattr(result, 'frame', None)
    return (int(frame.shape[1]), int(frame.shape[0])) if frame is not None else None


class CalibrationFlow:
    def __init__(self, calibration, config, clock):
        self.calibration, self.config, self.clock = calibration, config, clock
        self.alignment = FaceAlignment(config.alignment, max_age=config.result_stale_seconds)
        self.guard = CollectionPositionGuard(config.alignment)
        self.current_result = None
        self.healthy = False
        self.latest_timestamp = -math.inf
        self.cue_sequence = 0
        self.cue = None
        self.history = []
        self.geometry = None
        self.reset()

    @property
    def direction(self):
        return DIRECTIONS[self.index]

    @property
    def active(self):
        return self.phase in {'awaiting_presentation', 'preparing', 'collecting'}

    def _count(self):
        return self.calibration.counts[self.direction]

    def _remember(self, outcome):
        if any(self.calibration.counts.values()):
            self.history.append({'attempt_id': self.attempt_id, 'outcome': outcome,
                                 'diagnostics': self.calibration.diagnostics})
            self.history = self.history[-3:]

    def reset(self):
        if hasattr(self, 'attempt_id'):
            self._remember('retained before new baseline')
        self.calibration.reset()
        self.attempt_id = str(uuid4())
        self.alignment.reset()
        self.guard.reset()
        self.index, self.completed = 0, []
        self.phase = 'idle'
        self.message = 'Align your face, then start a fresh baseline at CENTER.'
        self.presentation_token = None
        self.window = None
        self.baseline_geometry_id = None
        self.last_sample_timestamp = self.latest_timestamp
        self.last_rejected = {}
        self.last_attempt = None

    def geometry_changed(self, geometry):
        previous = self.baseline_geometry_id
        self.geometry = geometry
        if previous is not None and previous != geometry.get('geometry_id'):
            self.reset()
            self.message = 'Window or display geometry changed. Align and start a new baseline.'

    def begin(self):
        if self.active:
            return  # A double click must not reset a running target.
        if self.calibration.ready or self.phase == 'fit_failed':
            raise BridgeError('wrong_state', 'Start a new baseline before collecting again')
        now = self.clock.monotonic()
        self.alignment.update(self.current_result, now, self.healthy)
        if not self.healthy or not self.alignment.status.ready:
            raise BridgeError('alignment_required', self.alignment.status.message)
        compatibility = self.guard.check(self.current_result, self.alignment.status)
        if compatibility == 'camera_changed':
            self.reset()
            raise BridgeError('camera_changed', 'Camera dimensions changed; start a new baseline')
        if compatibility == 'position_changed':
            raise BridgeError('position_changed', 'Return to the previous face position, or start a new baseline')
        self.guard.anchor(self.current_result)
        self._next_target()

    def retry_target(self):
        if self.phase not in {'target_failed', 'idle'}:
            raise BridgeError('wrong_state', 'Only an incomplete target can be retried')
        self.begin()

    def _next_target(self):
        self.calibration.discard_target(self.direction)
        self.presentation_token = str(uuid4())
        self.phase = 'awaiting_presentation'
        self.present_by = self.clock.monotonic() + 8.
        self.window = None
        self.last_sample_timestamp = self.latest_timestamp
        self.last_rejected = {}
        self.message = 'Waiting for the target to be shown.'

    def present(self, token, target, geometry):
        if token != self.presentation_token or target != self.direction.value:
            raise BridgeError('stale_target', 'The displayed target no longer matches this collection')
        if self.phase in {'preparing', 'collecting'}:
            return  # Repeated acknowledgement cannot move the capture window.
        if self.phase != 'awaiting_presentation':
            raise BridgeError('wrong_state', 'No target is waiting for presentation')
        if not isinstance(geometry, dict) or not isinstance(geometry.get('geometry_id'), str):
            raise BridgeError('geometry_required', 'The native display geometry is required')
        if self.direction.value == 'CENTER' and geometry.get('center_visible') is not True:
            raise BridgeError('center_not_visible', 'Move or enlarge the window to show the physical screen center')
        if self.baseline_geometry_id is not None and geometry['geometry_id'] != self.baseline_geometry_id:
            self.geometry_changed(geometry)
            raise BridgeError('geometry_changed', 'Display geometry changed; start a fresh baseline')
        self.geometry = geometry
        self.baseline_geometry_id = geometry['geometry_id']
        self.geometry_generation = self.alignment.status.geometry_generation
        starts_at = self.clock.monotonic() + self.config.calibration_preparation_seconds
        self.window = BoundedCollection(starts_at, self.config.calibration_collection_seconds,
                                        self.config.calibration_max_collection_seconds,
                                        self.config.calibration_samples)
        self.phase = 'preparing'
        self.message = 'Look at the target. Collection begins after the cue.'

    def cancel(self):
        if self.phase in {'fit_failed', 'complete'}:
            return
        if self.active:
            self._remember(f'{self.direction.value}: cancelled')
            self.calibration.discard_target(self.direction)
            self._cue('complete')
        self.phase = 'idle' if not self.calibration.ready else 'complete'
        self.window = None
        self.presentation_token = None
        self.message = 'Calibration cancelled. Completed compatible targets are retained.'

    def _cue(self, kind):
        self.cue_sequence += 1
        self.cue = kind

    def _reject(self, reason, stamp):
        if self.last_rejected.get(reason) == stamp:
            return
        self.last_rejected[reason] = stamp
        self.calibration.record_rejection(self.direction, reason, timestamp=stamp,
            measurement=getattr(self.current_result, 'face', None), frame_size=source_size(self.current_result))

    def _fail(self, message=None, discard=False):
        self.last_attempt = self.calibration.diagnostics['targets'][self.direction.value]
        self._remember(f'{self.direction.value}: incomplete')
        if discard:
            self.calibration.discard_target(self.direction)
        self.phase = 'target_failed'
        self.presentation_token = None
        self.window = None
        self.message = message or 'Too few valid measurements within the available time. Retry this target.'
        self._cue('complete')

    def _finish_target(self, outcome):
        if outcome != 'complete':
            self._fail()
            return
        self._cue('complete')
        self.completed.append(self.direction.value)
        if self.index < len(DIRECTIONS) - 1:
            self.index += 1
            self._next_target()
        else:
            ok, message = self.calibration.fit()
            self.phase = 'complete' if ok else 'fit_failed'
            self.message = message
            self.presentation_token = None
            self.window = None
            self._remember('production fit accepted' if ok else 'production fit rejected')

    def update(self, result, now, healthy):
        self.current_result, self.healthy = result, healthy
        self.alignment.update(result, now, healthy)
        stamp = getattr(result, 'timestamp', None)
        if isinstance(stamp, (float, int)) and math.isfinite(stamp):
            self.latest_timestamp = max(self.latest_timestamp, stamp)
        if not healthy:
            if self.active or any(self.calibration.counts.values()):
                self.reset()
                self.message = 'Monitoring interrupted. Camera recovery requires a fresh baseline.'
            return
        if self.phase == 'awaiting_presentation':
            if now >= self.present_by:
                self._fail('The target was not confirmed as visible. Retry after reconnecting the display.')
            return
        if self.phase not in {'preparing', 'collecting'}:
            return
        if now >= self.window.deadline and self._count() < self.config.calibration_samples:
            if stamp is not None and stamp > self.last_sample_timestamp:
                self._reject('arrived_after_collection', stamp)
            self._finish_target('timeout')
            return
        compatibility = self.guard.check(result, self.alignment.status)
        if compatibility == 'camera_changed':
            self.reset()
            self.message = 'Camera dimensions changed. Start a new baseline.'
            return
        if compatibility == 'position_changed':
            self._reject('incompatible_face_position', stamp)
            self._fail('Return to the previous face position and retry this target.', discard=True)
            return
        if self.alignment.status.geometry_generation != self.geometry_generation:
            self._reject('geometry_' + (self.alignment.status.geometry_reset_reason or 'continuity_lost'), stamp)
            self._fail('Face-position continuity was lost. Return to the previous position and retry.', discard=True)
            return
        outcome = self.window.outcome(now, self._count())
        if outcome != 'collect':
            self._finish_target(outcome)
            return
        if self.phase == 'preparing':
            if now < self.window.starts_at:
                return
            self.phase = 'collecting'
            self._cue('start')
        if result is not None:
            if not isinstance(stamp, (float, int)) or not math.isfinite(stamp):
                self._reject('invalid_timestamp', stamp)
            elif stamp < self.window.starts_at:
                self._reject('captured_before_collection', stamp)
            elif not 0 <= now - stamp < self.config.result_stale_seconds:
                self._reject('stale_or_future_measurement', stamp)
            elif stamp >= self.window.deadline:
                self._reject('captured_after_collection', stamp)
            elif stamp <= self.last_sample_timestamp:
                self._reject('reused_or_out_of_order_measurement', stamp)
            else:
                self.last_sample_timestamp = stamp
                face = result.face
                if not result.face_present or face is None or not face.face_present or face.features is None:
                    self._reject(getattr(getattr(face, 'diagnostics', None), 'reason', '') or 'no_valid_eye_measurement', stamp)
                elif not self.alignment.status.ready:
                    self._reject('alignment_' + self.alignment.status.reason, stamp)
                else:
                    diagnostics = getattr(face, 'diagnostics', None)
                    widths = [eye.width_pixels for eye in (diagnostics.left_eye, diagnostics.right_eye)
                              if eye.width_pixels is not None and eye.width_pixels > 0] if diagnostics else []
                    self.calibration.add_sample(self.direction, face.features, stamp, face.quality,
                        noise_floor=max((1 / width for width in widths), default=None),
                        measurement=face, frame_size=source_size(result))
        self.message = ('Keep looking at the target.' if self.alignment.status.ready else
                        'Eye measurements temporarily unavailable. Keep looking without forcing your eyes open.')
        if self.window.outcome(now, self._count()) == 'complete':
            self._finish_target('complete')

    def state(self):
        now = self.clock.monotonic()
        return {'attempt_id': self.attempt_id, 'phase': self.phase, 'target': self.direction.value,
                'presentation_token': self.presentation_token, 'cue_sequence': self.cue_sequence, 'cue': self.cue,
                'message': self.message, 'accepted_samples': self._count(),
                'required_samples': self.config.calibration_samples, 'completed_targets': list(self.completed),
                'alignment': asdict(self.alignment.status), 'ready': self.calibration.ready,
                'prepare_remaining': max(0., self.window.starts_at - now) if self.window else 0.,
                'collection_progress': min(1., max(0., (now - self.window.starts_at) / self.window.nominal_seconds)) if self.window else 0.,
                'geometry_id': self.baseline_geometry_id,
                'diagnostics': self.calibration.diagnostics, 'last_attempt': self.last_attempt,
                'retained_attempts': [{'attempt_id': row['attempt_id'], 'outcome': row['outcome']} for row in self.history]}
