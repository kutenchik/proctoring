"""Electron presentation adapter around the existing exam services."""
from dataclasses import asdict, dataclass, replace
import json
import os
import re
from pathlib import Path
import time

from ..controller import AppController
from ..domain import EventType
from ..vision.camera import CapturedFrame
from .calibration_flow import CalibrationFlow
from .protocol import BridgeError, DispatchResult
from .service import SetupBridge
from ..connected.client import ConnectedClient, ConnectedError, frozen_policy


@dataclass(frozen=True)
class AnnotatedFrame(CapturedFrame):
    overlays: tuple = ()


class WorkflowBridge(SetupBridge):
    """One controller, one selected camera and one microphone throughout setup/exam."""
    def __init__(self, config, *, controller=None, protection=None,
                 expected_launch_id=None, package_root=None, connected_client=None, live_factory=None, **kwargs):
        self.admission_client = connected_client
        self._admission_applied = False
        self.policy_revision = 0
        self.effective_policy = None
        self._connected_start_pending = False
        self.connected_sync = None
        self.live_teacher = None
        self._secure_storage_error = None
        self._protected_requested = config.protection.enabled
        if self._protected_requested and protection is None and controller is None:
            expected_launch_id = expected_launch_id or os.environ.get('PROCTORING_HOST_LAUNCH_ID')
            if not isinstance(expected_launch_id, str) or not re.fullmatch(r'[a-f0-9]{32}', expected_launch_id):
                raise BridgeError('host_binding_required', 'Protected mode requires a verified Electron host launch')
            from ..security.electron import ElectronProtection
            protection = ElectronProtection(config.protection,
                                            expected_launch_id=expected_launch_id,
                                            package_root=package_root)
        # OS clipboard clearing is scoped to an actually armed protected exam.
        # A safe Electron session and all pre-exam device checks leave it alone.
        self._clipboard_requested = config.system_checks.clipboard_guard_enabled
        if not self._protected_requested:
            config = replace(config, system_checks=replace(config.system_checks, clipboard_guard_enabled=False))
        self.controller = controller or AppController(config, clock=kwargs.get('clock'), mode='camera', protection=protection)
        self.electron_protection = self.controller.protection if self._protected_requested else None
        if self.electron_protection is not None and self.controller.system_checker is not None:
            self.controller.system_checker.clipboard_scope_guard = lambda: (
                self.electron_protection.armed and self.controller.session.started
                and not self.controller.session.ended)
        kwargs.setdefault('clock', self.controller.clock)
        self.monitor = self.controller.monitor
        self.flow = CalibrationFlow(self.monitor.calibration, config.vision, self.controller.clock)
        self._step = 'setup'
        self._revision = 0
        self._quiz_revision = 0
        self._question_index = 0
        self._presentation_cursor = 0
        self._geometry = None
        self._ticking = False
        self._closing_workflow = False
        self._last_preview_timestamp = None
        self._preview_counter = 0
        self._last_camera_retry = float('-inf')
        audio = self.controller.audio
        future_audio_factory = kwargs.get('audio_factory')
        if audio is not None:
            kwargs['audio_factory'] = lambda *_: audio
        super().__init__(config, **kwargs)
        if config.connected.enabled and self.admission_client is None:
            from ..connected.durable import DurableJournal
            try:
                journal = DurableJournal(Path(os.environ.get('LOCALAPPDATA', Path.home()))/'LocalProctoring'/'connected-stage2.sqlite3')
                self.admission_client = ConnectedClient(config.connected, monotonic=self.clock.monotonic, journal=journal)
            except Exception as error:
                self._secure_storage_error = ('unfinished_attempt_from_different_build'
                    if isinstance(error,ConnectedError) and str(error)=='unfinished_attempt_from_different_build'
                    else 'secure_storage_unavailable')
                self.admission_client = ConnectedClient(config.connected, monotonic=self.clock.monotonic)
                self.admission_client.error = self._secure_storage_error
        if self.admission_client is not None and self.admission_client.journal is not None:
            from ..connected.workflow import ConnectedWorkflow
            self.connected_sync = ConnectedWorkflow(self)
            if self.admission_client.restored:
                try:
                    self._apply_admission()
                except Exception:
                    self._secure_storage_error = 'saved_attempt_requires_attention'
                    self.admission_client.error = self._secure_storage_error
            self.connected_sync.worker.start()
            from ..connected.live_workflow import LiveWorkflow
            self.live_teacher = (live_factory or LiveWorkflow)(self)
        # Subsequent device changes create a fresh AudioMonitor as Stage 1 did;
        # only initialization shares the controller's already-created monitor.
        if audio is not None:
            from ..audio.monitor import AudioMonitor
            self.audio_factory = future_audio_factory or AudioMonitor

    def _setup_only(self):
        if self.controller.session.started:
            raise BridgeError('wrong_state', 'Device setup and calibration cannot change after exam start')

    def _session_id(self):
        return self.controller.store.path.name if self.controller.store is not None else getattr(self.controller, 'connected_session_id', None)

    def _event_cursor(self):
        if self.controller.store is None:
            return 0
        try:
            return (self.controller.store.path/'events.jsonl').stat().st_size
        except OSError:
            return 0

    def _stop_camera(self):
        self.monitor.stop(timeout=.2)
        self.camera = self.monitor._camera
        self._camera_state = 'stopped'
        if self.preview is not None:
            self.preview.clear()

    def tick(self):
        if self.closed or self._ticking:
            return
        self._ticking = True
        try:
            self._poll_admission()
            self._take_scan()
            self.controller.device_selection_ready = not self._scanning and not getattr(self.monitor, '_switching', False)
            self.camera = self.monitor._camera if self._camera_state != 'not_started' else self.camera
            self.controller.step()
            self._retry_selected_exam_camera()
            if self.live_teacher:
                self.live_teacher.tick()
            recalibrating=bool(self.live_teacher and self.live_teacher.recalibrating)
            if not self.controller.session.started or recalibrating:
                health = self.monitor.health(self.clock.monotonic())
                self.flow.update(self.monitor.latest_calibration_result, self.clock.monotonic(), health.healthy)
                if recalibrating:
                    self._step='paused' if self.monitor.calibration.ready else 'calibration'
                elif self.monitor.calibration.ready and self._step == 'calibration':
                    self._step = 'ready'
            elif self.controller.session.ended:
                self._step = 'summary'
            else:
                self._step = 'exam' if self.controller.session.running else 'paused'
            self._finish_connected()
        finally:
            self._ticking = False

    def _apply_admission(self):
        client = self.admission_client
        config, quiz = frozen_policy(self.config, client.admission)
        from ..registration import CandidateInfo
        identity = client.identity
        candidate = CandidateInfo('', '', identity['group'], identity['full_name'], identity['student_id'])
        if self.consent or self.controller.store is not None or self.controller.session.started:
            raise ConnectedError('policy_too_late')
        if 'monitoring_policy' in client.admission['exam'] and client.journal:
            saved=client.journal.get('attempt:'+client.admission['attempt_id']) or {}
            if saved.get('effective_monitoring_policy'):
                from ..exam_policy import apply_policy
                config=apply_policy(config,saved['effective_monitoring_policy'])
                self.policy_revision=saved.get('policy_revision',0)
        self.config = self.controller.config = config
        if self._protected_requested and not config.protection.enabled:
            # Admission can select unprotected use within a protection-capable
            # host, never the reverse. No session or device capture exists yet.
            self.controller.protection.close()
            from ..security.protection import NoOpProtection
            self.controller.protection = NoOpProtection()
            self.electron_protection = None
            self._protected_requested = False
            if self.controller.system_checker is not None:
                self.controller.system_checker.clipboard_scope_guard = lambda: False
        self.controller.session.duration_seconds = config.duration_seconds
        if quiz is not None:
            self.controller.quiz = quiz
        self.controller.audio = self.audio if config.audio.enabled else None
        if config.audio.enabled and self.controller.audio_events is None:
            from ..events import EventEngine
            self.controller.audio_events = EventEngine({EventType.VOICE_DETECTED: config.audio.voice_duration_threshold},
                config.clearing_seconds, self.clock, max_observation_gap=.5, accumulate_sample_durations=True)
        elif not config.audio.enabled:
            self.controller.audio_events = None
        if 'monitoring_policy' in client.admission['exam']:
            from ..exam_policy import configure_admission, values_from_config
            configure_admission(self, config)
            self.effective_policy = {'schema_version': 3, 'values': values_from_config(config)}
        self.controller.register_candidate(candidate.as_dict())
        self.controller.connected_attempt = {'attempt_id': client.admission['attempt_id'],
                                            'exam_id': client.admission['exam']['id'],
                                            'server_url': client.server,
                                            'exam_title': client.admission['exam']['title']}
        self._admission_applied = True
        if self.connected_sync:
            self.connected_sync.admitted()
        self.controller.configure_advanced(str(self._session_id())+':'+client.admission['attempt_id'])

    def _poll_admission(self):
        client = self.admission_client
        if client is None:
            return
        operation = client.poll()
        try:
            if operation == 'proctor_pin':
                action = client.pin_action
                client.pin_action = None
                session = self.controller.session
                if session.started and not session.ended:
                    if action == 'proctor.pause':
                        session.pause_by_proctor()
                    elif action == 'proctor.resume':
                        if not session.resume_by_proctor(True):
                            client.error = 'resume_blocked'
                    elif action == 'proctor.end':
                        self.controller.end('proctor_ended')
                    self.controller._write_session_records()
            if operation == 'admit':
                self._apply_admission()
            if self.connected_sync and operation:
                self.connected_sync.operation(operation)
            if operation in ('start', 'recover') and self._connected_start_pending:
                self._connected_start_pending = False
                # Server authorization does not bypass a changed camera/calibration/
                # presentation/recovery check while the HTTP request was in flight.
                self._require_protected_geometry()
                if not self.readiness()['ready']:
                    raise ConnectedError('readiness_changed')
                self._start_local()
        except (ConnectedError, BridgeError, ValueError, RuntimeError):
            client.error = 'readiness_changed' if operation == 'start' else 'invalid_policy'
            if operation == 'admit':
                try:
                    frozen_policy(self.config, client.admission)
                except ConnectedError as error:
                    client.error = str(error)

    def _finish_connected(self):
        if self.connected_sync:
            try:
                self.connected_sync.tick()
            except Exception:
                self.connected_sync.error = 'local_checkpoint_requires_attention'
            return
        client = self.admission_client
        if client and self.controller.session.ended and client.start_authorized and not client.finish_sent and not client.busy:
            client.finish_sent = True
            client.submit('finish', {'score': self.controller.quiz.score if not self.config.external_url else None,
                                    'total': self.controller.quiz.total if not self.config.external_url else None,
                                    'end_reason': self.controller.session.end_reason})

    def _start_local(self):
        if self.config.audio.enabled:
            self.controller.audio = self.audio
        else:
            self.audio.stop(timeout=.2)
        if self.connected_sync:
            self.connected_sync.before_start()
        if self.live_teacher:
            self.live_teacher.prepare_start()
        self.controller.start()
        if self.connected_sync:
            try:
                self.connected_sync.after_start()
            except Exception:
                # A local start without its durable checkpoint cannot be treated
                # as recoverable success. Release through the existing end path.
                self.controller.end('checkpoint_failure')
                raise
        self._step = 'exam'

    def _retry_selected_exam_camera(self):
        """Reopen a released Qt capture after an active-exam disconnect only.

        Keep the source object/ID, calibration, reference and inference worker.
        In particular, do not clear its error onset: a fresh captured frame and
        then a fresh inference result must satisfy the existing recovery policy.
        """
        from ..vision.qt_camera import NamedCamera
        session, camera = self.controller.session, self.monitor._camera
        now = self.clock.monotonic()
        if (self.closed or not self.consent or not session.started or session.ended or
                session.monitoring_healthy or getattr(self.monitor, 'stopped', False) or
                getattr(self.monitor, '_switching', False) or
                getattr(self.monitor, '_selection_error', None) or
                not isinstance(camera, NamedCamera) or camera.stopped or camera.alive or
                camera.device_id != self.camera_key or
                self.monitor.selected_camera_id != self.camera_key or
                now-self._last_camera_retry < .5):
            return
        self._last_camera_retry = now
        try:
            # NamedCamera.start is non-blocking and replaces only a finished
            # QThread. Explicit stop sets camera.stopped and forbids reopening.
            camera.start()
            self._camera_state = 'opening'
        except Exception:
            # Preserve the concrete capture failure and its original timestamp.
            self._camera_state = 'unavailable'

    def dispatch(self, command, payload):
        if self.closed and command != 'shutdown':
            raise BridgeError('disconnected', 'The exam bridge is shutting down')
        self.tick()
        data = None
        session = self.controller.session
        try:
            if self.admission_client and not self._admission_applied and command not in {
                    'state.get', 'connected.verify', 'connected.admit', 'connected.refresh', 'sync.retry', 'sync.background',
                    'geometry.changed', 'host.bind', 'host.progress', 'host.safety_release',
                    'shutdown', 'presentation.lost', 'events.get','live.poll','live.capture'}:
                raise BridgeError('admission_required', 'Complete teacher-server admission before device setup')
            if self.effective_policy is not None and not self.config.audio.enabled and command in ('audio.start','audio.calibrate'):
                raise BridgeError('audio_disabled','Microphone monitoring is disabled by exam policy')
            setup_commands = {'devices.refresh', 'camera.select', 'microphone.select', 'consent.set',
                              'camera.start', 'camera.stop', 'audio.start', 'audio.stop', 'audio.calibrate',
                              'registration.submit', 'reference.capture', 'calibration.start',
                              'calibration.presented', 'calibration.cancel', 'calibration.retry', 'setup.show'}
            if command in setup_commands:
                if not (self.live_teacher and self.live_teacher.recalibrating and command.startswith('calibration.')):
                    self._setup_only()
                if self.live_teacher and command in {'camera.start','audio.start','audio.calibrate','reference.capture','calibration.start','calibration.retry','calibration.presented'}:
                    self.live_teacher.require_display()
            if (self.electron_protection is not None and command in {
                    'camera.select', 'microphone.select', 'camera.start', 'audio.start',
                    'audio.calibrate', 'reference.capture', 'calibration.start', 'calibration.retry'}
                    and not self.electron_protection.binding_status().get('media_allowed')):
                raise BridgeError('host_not_ready', 'The protected desktop owner must be verified before starting devices')
            if command=='screen.consent':
                self._setup_only()
                if not self.live_teacher:raise BridgeError('not_enabled','Connected screen consent is not enabled')
                self.live_teacher.consent(payload['accepted'])
            elif command=='live.poll':
                data=self.live_teacher.poll_host() if self.live_teacher else {'messages':[],'connection':'offline'}
            elif command=='live.capture':
                if self.live_teacher:self.live_teacher.capture(payload)
            elif command.startswith('connected.'):
                if self.admission_client is None:
                    raise BridgeError('not_enabled', 'Connected mode is not enabled')
                self._setup_only()
                if self._secure_storage_error:
                    raise BridgeError(self._secure_storage_error, 'Secure local recovery storage is unavailable')
                try:
                    self.admission_client.submit(command.split('.')[1], payload)
                except ConnectedError as error:
                    raise BridgeError(str(error), 'Teacher-server request cannot start') from None
            elif command == 'sync.retry':
                if not self.connected_sync:
                    raise BridgeError('not_enabled', 'Connected synchronization is not enabled')
                self.connected_sync.worker.next_retry.clear()
            elif command == 'sync.background':
                if not self.connected_sync or not self.connected_sync.public()['can_background']:
                    raise BridgeError('background_not_ready', 'End the attempt and release all media/protection first')
                self.connected_sync.background = True
                self.controller.close_remote(timeout=0.)
                self.controller.protection.close()
            elif command == 'host.bind':
                if self.electron_protection is None:
                    raise BridgeError('not_enabled', 'This session has not requested native protection')
                self._setup_only()
                data = self.electron_protection.configure_host(payload)
            elif command == 'host.progress':
                if self.electron_protection is None:
                    raise BridgeError('not_enabled', 'This session has not requested native protection')
                if payload['session_id'] != self._session_id() or not 0 < payload['snapshot_seq'] <= self._revision:
                    raise BridgeError('stale_presentation', 'Control progress belongs to a different or unseen presentation')
                # dispatch has just completed controller.step on this Qt loop.
                # A status reader, camera worker or pending pipe message cannot
                # renew this chain independently of session-control progress.
                accepted = self.electron_protection.accept_progress({key: payload[key] for key in (
                    'lease_id', 'sequence', 'nonce', 'main_sequence')})
                data = {'accepted': bool(accepted)}
            elif command == 'host.safety_release':
                if self.electron_protection is not None:
                    self.controller.protection.release(payload['reason'])
                    if session.started and not session.ended:
                        self.controller.emergency_end(payload['reason'])
            elif command == 'setup.show':
                self.flow.cancel()
                self._step = 'setup'
            elif command == 'camera.select':
                selected = self._selected('cameras', payload['key'])
                if getattr(self.monitor, '_switching', False):
                    raise BridgeError('busy', 'Previous camera is still releasing')
                # The requested dropdown key is updated before the monitor's
                # asynchronous switch completes. A failed release/open must be
                # retryable without choosing an unrelated device first.
                if (selected.key != self.camera_key or
                        selected.key != self.monitor.selected_camera_id or
                        getattr(self.monitor, '_selection_error', None)):
                    if not self.monitor.select_camera(selected.key, activate=False):
                        raise BridgeError('device_unavailable', 'Camera selection could not be applied')
                    self.controller._invalidate_camera_reference()
                    self.camera_key = selected.key
                    self._camera_state = 'not_started'
                    self.flow.reset()
                    self._step = 'setup'
                    if self.preview is not None:
                        self.preview.clear()
            elif command == 'camera.start':
                self._require_consent()
                self._selected('cameras', self.camera_key)
                try:
                    self.controller.prepare_camera_preview()
                except Exception as error:
                    from .diagnostics import emit
                    emit('camera_failed', error=error)
                    raise BridgeError('camera_initialization_failed',
                                      'Camera initialization failed; check permissions and connection, then retry camera') from error
                self.camera = self.monitor._camera
                self._camera_state = 'opening'
            elif command == 'camera.stop':
                self.flow.cancel()
                self._stop_camera()
            elif command == 'registration.submit':
                if self.admission_client:
                    raise BridgeError('identity_fixed', 'Candidate identity belongs to the admitted attempt')
                self.controller.register_candidate(payload)
            elif command == 'reference.capture':
                self._require_consent()
                if self.config.registration.enabled and self.controller.candidate_info is None:
                    raise BridgeError('registration_required', 'Submit candidate details before taking the reference photo')
                if not (self.config.identity.selfie_verification_enabled or self.config.advanced.identity_enabled):
                    raise BridgeError('not_enabled', 'Reference-photo comparison is not enabled')
                self.controller.capture_identity_baseline()
            elif command == 'calibration.start':
                self._require_consent()
                self.controller._require_registration()
                self._require_protected_geometry()
                if self.monitor.calibration.ready:
                    self._step = 'ready'
                else:
                    self._step = 'calibration'
                    self.flow.begin()
            elif command == 'calibration.presented':
                if self._geometry is None or payload['geometry'] != self._geometry:
                    raise BridgeError('stale_geometry', 'Display geometry changed; show the current target again')
                self.flow.present(payload['token'], payload['target'], payload['geometry'])
            elif command == 'calibration.cancel':
                self.flow.cancel()
            elif command == 'calibration.retry':
                self.controller._require_registration()
                self._require_protected_geometry()
                self._step = 'calibration'
                if payload['scope'] == 'baseline':
                    self.flow.reset()
                else:
                    self.flow.retry_target()
            elif command == 'geometry.changed':
                changed = self._geometry is not None and self._geometry.get('geometry_id') != payload['geometry'].get('geometry_id')
                self._geometry = payload['geometry']
                if changed and self._protected_requested and session.started and not session.ended:
                    self.controller.emergency_end('display_geometry_changed')
                if not session.started or (self.live_teacher and self.live_teacher.recalibrating):
                    self.flow.geometry_changed(self._geometry)
                    if self._step == 'ready' and not self.monitor.calibration.ready:
                        self._step = 'calibration'
            elif command == 'exam.start':
                if session.ended:
                    raise BridgeError('wrong_state', 'This exam has already ended')
                if not session.started:
                    self._require_protected_geometry()
                    if not self.readiness()['ready']:
                        raise BridgeError('not_ready', 'Complete the blocked readiness checks before starting')
                    if self.admission_client:
                        try:
                            if self.connected_sync:
                                self.connected_sync.request_start()
                            else:
                                self.admission_client.submit('start')
                        except ConnectedError as error:
                            raise BridgeError(str(error), 'Start authorization could not be requested') from None
                        self._connected_start_pending = True
                    else:
                        self._start_local()
            elif command == 'quiz.answer':
                self._require_active(native=True)
                revision = payload['revision']
                index, option = payload['question_index'], payload.get('option_indices', payload.get('option_index'))
                if revision != self._quiz_revision:
                    if revision < self._quiz_revision and self.controller.quiz.answers.get(index) == option:
                        return self.state()
                    raise BridgeError('stale_answer', 'Answers changed; resynchronize before applying this selection')
                if not self.controller.answer(index, option):
                    raise BridgeError('wrong_state', 'Answers can only change while the exam is running')
                self._quiz_revision += 1
                if self.connected_sync:
                    self.connected_sync.checkpoint(force=True)
            elif command == 'quiz.navigate':
                self._require_active(native=True)
                index = payload['question_index']
                if not 0 <= index < self.controller.quiz.total:
                    raise BridgeError('invalid_payload', 'Question index is outside the configured quiz')
                self._question_index = index
            elif command == 'exam.submit':
                if not session.ended:
                    self._require_active(native=True)
                    self.controller.end('completed')
            elif command in {'proctor.pause', 'proctor.resume', 'proctor.end'}:
                if not session.started:
                    raise BridgeError('wrong_state', 'No exam has started')
                if self.admission_client is not None:
                    if session.ended:
                        raise BridgeError('wrong_state', 'Exam has ended')
                    self.admission_client.submit('proctor_pin', {'pin': payload['pin'], 'action': command})
                    return self.state()
                if not self.controller.pin.verify(payload['pin']):
                    raise BridgeError('invalid_pin', 'Incorrect proctor PIN')
                if not session.ended:
                    if command == 'proctor.pause':
                        if 'proctor' not in session.pause_reasons:
                            self.controller.pause(payload['pin'])
                    elif command == 'proctor.resume':
                        if session.pause_reasons and not self.controller.resume(payload['pin']):
                            raise BridgeError('resume_blocked', 'Restore monitoring and presentation before resuming')
                    else:
                        self.controller.end_with_pin(payload['pin'])
            elif command == 'presentation.lost':
                if session.presentation_lost():
                    self._presentation_cursor = self._event_cursor()
                    self.controller._write_session_records()
                elif not session.started:
                    # A lost setup presentation must not leave invisible media
                    # running. Reconnection needs explicit consent/test actions.
                    self.consent = False
                    self.flow.cancel()
                    self._stop_camera()
                    self._stop_audio()
            elif command == 'presentation.sync':
                if payload['session_id'] != self._session_id():
                    raise BridgeError('stale_session', 'Snapshot belongs to a different session')
                if not self._presentation_cursor <= payload['event_cursor'] <= self._event_cursor():
                    raise BridgeError('stale_cursor', 'Synchronize the current event cursor before resuming presentation')
                session.presentation_recovered()
                self.controller._write_session_records()
            elif command == 'emergency.end':
                if session.started and not session.ended:
                    self.controller.emergency_end('emergency_shortcut')
            elif command == 'report.retry':
                if not self.controller.retry_report():
                    raise BridgeError('wrong_state', 'Only a failed report can be retried')
            elif command == 'events.get':
                data = self.event_page(payload['after'], payload['limit'])
            elif command == 'host.external':
                data = {'url': self.config.external_url, 'allowed_domains': list(self.config.allowed_domains)}
            elif command == 'host.evidence':
                data = self.evidence(payload)
            elif command == 'shutdown':
                self.close()
            elif command == 'state.get':
                pass
            else:
                result = super().dispatch(command, payload)
                if command == 'microphone.select' and self.config.audio.enabled:
                    self.controller.audio = self.audio
                if command == 'consent.set' and not self.consent:
                    self.flow.cancel()
                return result
        except BridgeError:
            raise
        except (RuntimeError, ValueError, IndexError) as error:
            raise BridgeError('operation_rejected', str(error)) from error
        self._revision += command != 'state.get'
        if self.connected_sync and command in {'proctor.pause', 'proctor.resume', 'presentation.lost', 'presentation.sync'}:
            # Pause transitions cannot wait for the periodic elapsed checkpoint:
            # an immediate process loss must retain independent proctor reasons.
            self.connected_sync.checkpoint(force=True)
        self.tick()
        state = self.state()
        return DispatchResult(state, data) if data is not None else state

    def _require_active(self, *, native=False):
        if not self.controller.session.running:
            raise BridgeError('wrong_state', 'The exam must be running for this action')
        if native and self.config.external_url:
            raise BridgeError('external_exam', 'The external platform owns its answers and submission; use proctor End session to stop local monitoring')

    def _require_protected_geometry(self):
        if self._protected_requested and (not self._geometry or
                self._geometry.get('fullscreen') is not True or self._geometry.get('settled') is not True):
            raise BridgeError('geometry_pending', 'Settle the final fullscreen layout before calibration and protected Start')

    def readiness(self):
        live = self.live_teacher
        self.controller.audio_evidence_consent = bool(self.consent and live and
            live.consent_accepted and live.consent_acknowledged and live.consent_version == 5)
        self.controller.authorize_advanced(bool(self.consent and live and
            live.consent_accepted and live.consent_acknowledged))
        health = self.monitor.health(self.clock.monotonic())
        checks = []
        def check(name, ready, message, enabled=True):
            checks.append({'id': name, 'status': 'not_enabled' if not enabled else 'ready' if ready else 'blocked',
                           'message': message})
        check('consent', self.consent, 'Device-access consent is required' if not self.consent else 'Consent accepted')
        if self.live_teacher:
            live=self.live_teacher
            check('screen_consent',live.consent_accepted and live.consent_acknowledged,
                  'Screen-viewing consent must be accepted and recorded by the teacher server')
            check('single_display',live.display['ready'],'Exactly one active Windows display is required')
        if self.admission_client:
            client = self.admission_client
            available = (self._admission_applied and not self._secure_storage_error and
                         (self.connected_sync.can_start() if self.connected_sync else client.deadline > self.clock.monotonic()))
            check('admission', available, 'Teacher admission and preparation deadline are required')
        check('registration', self.controller.candidate_info is not None, 'Submit candidate details', self.config.registration.enabled)
        check('reference', self.controller.identity_ready, self.controller.identity_status, self.config.identity.selfie_verification_enabled or self.config.advanced.identity_enabled)
        check('advanced',self.controller.advanced_ready,self.controller.advanced_status,self.config.advanced.enabled)
        check('camera', health.healthy, health.reason or 'Camera and vision pipeline are healthy')
        check('gaze', self.monitor.calibration.ready and not self.flow.active,
              'Session gaze calibration accepted' if self.monitor.calibration.ready else 'Complete session gaze calibration')
        check('devices', not self._scanning and not getattr(self.monitor, '_switching', False), 'Device selection must finish')
        preflight = self.controller.preflight_status()
        check('system', preflight['ready'], preflight.get('reason') or 'Configured system checks completed')
        if self.config.protection.enabled and self.admission_client and self.admission_client.admission:
            check('teacher_pin', self.admission_client.admission.get('protection_pin_configured') is True,
                  'Teacher must configure a protection PIN, then refresh admission')
        if self.electron_protection is not None:
            binding = self.electron_protection.binding_status()
            check('protection', bool(binding.get('ready')), binding.get('error') or 'Independent recovery and window ownership verified')
        # Optional microphone availability never masquerades as a camera/PIN blocker.
        audio_check = self.audio.check_status
        audio_stamp = audio_check.get('timestamp')
        audio_ready = (self._audio_alive() and audio_stamp is not None and
                       0 <= self.clock.monotonic()-audio_stamp <= .5 and
                       audio_check.get('state') not in {'unavailable', 'no_signal', 'clipping', 'noisy'})
        checks.append({'id': 'audio', 'status': ('ready' if audio_ready else 'blocked') if self.config.audio.enabled else 'not_enabled',
                       'required': False,
                       'message': self.controller.audio_status if self.config.audio.enabled else 'Not enabled'})
        return {'ready': all(item['status'] != 'blocked' or not item.get('required', True) for item in checks), 'checks': checks}

    def latest_frame(self):
        frame = super().latest_frame()
        if frame is None:
            return None
        result = self.monitor.latest_result
        now = self.clock.monotonic()
        overlays = []
        if result is not None and result.frame is not None and 0 <= now-result.timestamp < self.config.vision.result_stale_seconds:
            image, timestamp = result.frame, result.timestamp
            for label, boxes in (('person', result.persons), ('phone', result.phones),
                                 ('face', (result.face.box,) if result.face is not None and result.face.box else ())):
                overlays.extend({'kind': 'box', 'label': label, 'x1': box.x1, 'y1': box.y1,
                                 'x2': box.x2, 'y2': box.y2, 'confidence': box.confidence} for box in boxes[:32])
        else:
            image, timestamp = frame.image, frame.timestamp
        if not self.controller.session.started:
            x1, y1, x2, y2 = self.config.vision.alignment.guide
            overlays.append({'kind': 'ellipse', 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                             'ready': self.flow.alignment.status.ready})
        if timestamp != self._last_preview_timestamp:
            self._preview_counter += 1
            self._last_preview_timestamp = timestamp
        return AnnotatedFrame(self._preview_counter, timestamp, image, tuple(overlays))

    def event_page(self, after, limit):
        if self.connected_sync and (self.connected_sync.public()['fully_synchronized'] or
                self.connected_sync.row().get('cleanup_started')):
            return {'cursor': 0, 'records': [], 'has_more': False}
        fence = self._event_cursor()
        if after > fence:
            raise BridgeError('stale_cursor', 'Event cursor is beyond this session journal')
        if self.controller.store is None:
            return {'cursor': 0, 'records': [], 'has_more': False}
        records, size = [], 0
        with (self.controller.store.path/'events.jsonl').open('rb') as handle:
            if after:
                handle.seek(after-1)
                if handle.read(1) != b'\n':
                    raise BridgeError('invalid_cursor', 'Event cursor must be a journal record boundary')
            handle.seek(after)
            while handle.tell() < fence and len(records) < limit and size < 96*1024:
                line = handle.readline(128*1024)
                if not line.endswith(b'\n'):
                    raise BridgeError('journal_unavailable', 'A complete journal record is unavailable')
                record = json.loads(line)
                size += len(line)
                records.append({'sequence': handle.tell(), 'record': record})
            cursor = handle.tell()
        return {'cursor': cursor, 'records': records, 'has_more': cursor < fence}

    def evidence(self, payload):
        store = self.controller.store
        if store is None or payload['session_id'] != store.path.name:
            raise BridgeError('unknown_session', 'Evidence belongs to a different session')
        root = store.path.resolve()
        kind = payload['kind']
        if kind == 'report':
            if self.controller.report_status != 'complete':
                raise BridgeError('not_available', 'The report has not completed successfully')
            relative = self.config.reporting.report_filename
            mime = 'application/pdf'
        elif kind == 'reference':
            if not self.controller.identity_ready and self.controller._baseline_saved is None:
                raise BridgeError('not_available', 'No reference photo has been saved')
            relative, mime = 'reference_face.jpg', 'image/jpeg'
        else:
            event_id = payload.get('event_id')
            event = next((event for event in self.controller.review_events if event['event_id'] == event_id), None)
            relative = self.controller._snapshots.get(event_id) if event is not None else None
            if not relative:
                raise BridgeError('not_available', 'This review event has no saved snapshot')
            mime = 'image/jpeg'
        path = (root/relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 64*1024*1024:
            raise BridgeError('not_available', 'Evidence file is unavailable')
        with path.open('rb') as stream:
            prefix = stream.read(5)
        if not (prefix.startswith(b'%PDF-') if mime == 'application/pdf' else prefix.startswith(b'\xff\xd8')):
            raise BridgeError('invalid_evidence', 'Evidence format is invalid')
        return {'path': str(path), 'file_name': path.name, 'mime': mime, 'session_id': store.path.name,
                'kind': kind, 'event_id': payload.get('event_id')}

    def state(self):
        self._revision += 1  # Monotonic snapshot ordering also covers read-only polls.
        base = super().state()
        selection_error = getattr(self.monitor, '_selection_error', None)
        if selection_error:
            base['camera'].update(state='unavailable', error=str(selection_error)[:512])
        controller, session = self.controller, self.controller.session
        health = self.monitor.health(self.clock.monotonic())
        result = self.monitor.latest_result if health.healthy else None
        events = [{**event, 'snapshot_path': controller._snapshots.get(event['event_id'])} for event in controller.review_events]
        started_at = next((r['timestamp'] for r in session.records if r['event_type'] == 'session_started'), None)
        summary = None
        if controller.summary is not None:
            summary = {**controller.summary, 'started_at': started_at}
            for name in ('events', 'lifecycle', 'security_events'):
                rows = summary.get(name, [])
                summary[name+'_total'] = len(rows)
                summary[name+'_truncated'] = len(rows) > 30
                summary[name] = rows[-30:]
            summary['history_source'] = 'events.get'
        job = controller._report_job
        base['mode'] = 'exam_workflow'
        if self.admission_client:
            base['admission'] = {**self.admission_client.public(), 'policy_applied': self._admission_applied}
        if self.connected_sync:
            base['synchronization'] = self.connected_sync.public()
        if self.live_teacher:
            base['live_teacher']=self.live_teacher.public()
        base['config']['clipboard_guard_deferred'] = self._clipboard_requested and not self._protected_requested
        base['protection'] = (self.electron_protection.public_state() if self.electron_protection is not None
                              else {'requested': False, 'enabled': False, 'state': 'disabled', 'reason': 'development_mode'})
        base['workflow'] = {
            'version': 2, 'step': self._step, 'revision': self._revision, 'snapshot_seq': self._revision, 'session_id': self._session_id(),
            'config_path': str(self.config.source_path or ''),
            'registration': {'enabled': self.config.registration.enabled, 'require_group': self.config.registration.require_group,
                             'candidate': controller.candidate_info, 'complete': not self.config.registration.enabled or controller.candidate_info is not None},
            'reference': {'enabled': self.config.identity.selfie_verification_enabled or self.config.advanced.identity_enabled, 'advanced': self.config.advanced.identity_enabled, 'ready': controller.identity_ready,
                          'can_capture': controller.identity_can_capture, 'status': controller.identity_status},
            'calibration': self.flow.state(), 'readiness': self.readiness(),
            'session': {'started': session.started, 'ended': session.ended, 'running': session.running,
                        'started_at': started_at, 'elapsed_seconds': session.elapsed_seconds,
                        'remaining_seconds': session.remaining_seconds, 'duration_seconds': session.duration_seconds,
                        'pause_reasons': sorted(session.pause_reasons), 'monitoring_healthy': session.monitoring_healthy,
                        'recovery_pin_required': session.recovery_pin_required, 'end_reason': session.end_reason},
            'quiz': {'mode': 'external' if self.config.external_url else 'native', 'current_index': self._question_index,
                     'total': controller.quiz.total if not self.config.external_url else None,
                     'answered': controller.quiz.answered_count if not self.config.external_url else None,
                     'revision': self._quiz_revision,
                     'questions': [{'id': q.id, 'type': q.type, 'prompt': q.prompt, 'options': list(q.options),
                                    'option_ids': list(q.option_ids)} for q in controller.quiz.questions]
                                  if not self.config.external_url else [],
                     'answers': controller.quiz.answers if not self.config.external_url else {}},
            'monitoring': {'healthy': health.healthy, 'reason': health.reason,
                           'gaze_direction': result.gaze_direction.value if result else 'UNKNOWN',
                           'gaze_confidence': result.gaze_confidence if result else None,
                           'face_present': result.face_present if result else None,
                           'head_down': result.head_down if result else None,
                           'head_pose': asdict(result.head_pose) if result and result.head_pose else None,
                           'person_count': result.person_count if result else None,
                           'phone_visible': result.phone_visible if result else None,
                           'latency_ms': {'face': result.face_latency_ms if result else None, 'yolo': result.yolo_latency_ms if result else None},
                           'fps': self.monitor.metrics['monitoring_fps']},
            'events': {'cursor': self._event_cursor(), 'records': events[-30:]},
            'summary': summary, 'report': {'status': controller.report_status,
                                         'error': job.result.error if job is not None else None,
                                         'file_name': self.config.reporting.report_filename,
                                         'available': controller.report_status == 'complete' and not
                                         (self.connected_sync and self.connected_sync.public()['fully_synchronized'])}}
        base['unavailable_actions'] = []
        return base

    def close(self, reason='backend_disconnected'):
        if self.closed or self._closing_workflow:
            return
        self._closing_workflow = True
        try:
            # Also release prepared (unarmed) desktop ownership on setup exit.
            # Neither media cleanup nor PDF completion owns protection lifetime.
            self.controller.protection.release(reason)
            if self.live_teacher:
                self.live_teacher.close()
            if self.controller.session.started and not self.controller.session.ended:
                if self.connected_sync and reason in ('backend_disconnected', 'shutdown'):
                    self.connected_sync.interrupt(reason)
                else:
                    self.controller.end(reason)
            self._finish_connected()
            if self.connected_sync:
                self.connected_sync.close()
            if self.admission_client:
                self.admission_client.close()
            self.controller.protection.close()
            self.monitor.stop(timeout=0.)
            super().close()
            self.monitor.stop(timeout=2.)
            self.controller.close_remote(timeout=2.)
        finally:
            self._closing_workflow = False

    @property
    def report_cleanup_pending(self):
        job = self.controller._report_job
        thread = getattr(job, '_thread', None)
        # Status changes just before the optional delivery callback returns, so
        # test actual ownership rather than only a reported "complete" status.
        return bool(thread is not None and thread.is_alive())

    @property
    def native_cleanup_pending(self):
        return bool(super().native_cleanup_pending or
                    (getattr(self.monitor, '_thread', None) and self.monitor._thread.is_alive()))
