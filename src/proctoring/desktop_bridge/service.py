"""Qt-compatible setup device owner, with no route to exam side effects."""
from dataclasses import replace
import math
import threading
import time

from .. import devices
from ..audio.monitor import AudioMonitor
from ..clock import SystemClock
from ..vision.qt_camera import NamedCamera
from .protocol import BridgeError


CHECK_FIELDS = ('state', 'reason', 'progress', 'gain', 'applied_gain', 'threshold',
                'committed_threshold', 'threshold_source', 'rejection_code', 'gain_limited',
                'processed_noise', 'processed_speech', 'units', 'resolved_device',
                'device_key', 'stream_format')


def _finite(value, default=0.):
    return float(value) if isinstance(value, (float, int)) and math.isfinite(value) else default


def _device(device):
    result = {key: getattr(device, key) for key in ('key', 'label', 'name', 'backend', 'advanced',
              'supported', 'ambiguous', 'details', 'default_target_key')}
    return {key: value[:1024] if isinstance(value, str) else value for key, value in result.items()}


class SetupBridge:
    def __init__(self, config, *, clock=None, camera_factory=NamedCamera,
                 audio_factory=AudioMonitor, scanner=None, auto_scan=True):
        self.config, self.clock = config, clock or SystemClock()
        self.camera_factory, self.audio_factory = camera_factory, audio_factory
        self.scanner = scanner
        self.camera = None
        self.camera_key = None
        # A setup-only copy does not enable optional exam monitoring.
        self.audio = audio_factory(replace(config.audio, enabled=True), self.clock)
        self.audio_key = None
        self.consent = False
        self.closed = False
        self.preview = None
        self._camera_state = 'not_started'
        self._catalog = {'cameras': [], 'microphones': []}
        self._scan_lock = threading.Lock()
        self._scan_result = None
        self._scanning = False
        self._scan_started = None
        self._scan_thread = None
        self._scan_errors = {}
        if auto_scan:
            self.refresh_devices()

    @staticmethod
    def _scan(*, refresh_audio=False):
        result = {}
        audio_scan = devices.refresh_microphones if refresh_audio else devices.microphones
        for key, function in (('cameras', devices.cameras), ('microphones', audio_scan)):
            try:
                result[key] = function()[:64]
            except Exception:
                result[key] = []
                result[key+'_error'] = 'Device enumeration unavailable; check device permissions and retry'
        if not refresh_audio:
            result['microphones_notice'] = ('Microphone catalog is cached while the input is running or releasing. '
                                            'Stop the microphone, then refresh devices to discover newly connected inputs.')
        return result

    def refresh_devices(self):
        if self._scanning:
            raise BridgeError('busy', 'Device refresh is already running')
        self._scanning = True
        self._scan_started = self.clock.monotonic()
        # PortAudio refresh rebuilds its cached catalog and must never overlap
        # an owned stream, even a stopped stream whose native read is releasing.
        # _selected rejects start/select commands until this scan completes.
        refresh_audio = not self._audio_alive()
        def scan():
            try:
                result = self.scanner() if self.scanner is not None else self._scan(refresh_audio=refresh_audio)
            except Exception:
                result = {'cameras': [], 'microphones': [], 'scan_error': 'Device enumeration unavailable'}
            with self._scan_lock:
                if not self.closed:
                    self._scan_result = result
        self._scan_thread = threading.Thread(target=scan, name='desktop-device-catalog', daemon=True)
        self._scan_thread.start()

    def _take_scan(self):
        with self._scan_lock:
            result, self._scan_result = self._scan_result, None
        if result is None:
            return
        self._scanning = False
        self._catalog = {name: result.get(name, [])[:64] for name in ('cameras', 'microphones')}
        self._scan_errors = {name: str(value)[:512] for name, value in result.items()
                             if name.endswith(('_error', '_notice'))}
        # Missing selections remain explicit; a rescan never starts any stream.

    def _selected(self, kind, key):
        self._take_scan()
        if self._scanning:
            raise BridgeError('busy', 'Wait for the device catalog to finish refreshing')
        selected = next((item for item in self._catalog[kind] if item.key == key), None)
        if selected is None or not selected.supported:
            raise BridgeError('device_unavailable', 'Selected device is unavailable; refresh and select an input')
        return selected

    def _require_consent(self):
        if not self.consent:
            raise BridgeError('consent_required', 'Accept local device access before starting a device test')

    def _stop_camera(self):
        if self.camera is not None:
            self.camera.stop(timeout=.2)
        self._camera_state = 'stopped'
        if self.preview is not None:
            self.preview.clear()

    def _stop_audio(self):
        self.audio.stop(timeout=.2)

    def _audio_alive(self):
        thread = getattr(self.audio, '_thread', None)
        return bool(thread and thread.is_alive())

    def latest_frame(self):
        if (self.closed or not self.consent or self._camera_state == 'stopped' or
                self.camera is None or not self.camera.alive):
            return None
        frame = self.camera.latest
        if frame is None or self.clock.monotonic()-frame.timestamp > self.config.vision.frame_stale_seconds:
            return None
        return frame

    def dispatch(self, command, payload):
        if self.closed and command != 'shutdown':
            raise BridgeError('disconnected', 'The setup bridge is shutting down')
        if command == 'state.get':
            pass
        elif command == 'devices.refresh':
            self.refresh_devices()
        elif command == 'consent.set':
            self.consent = payload['accepted']
            if not self.consent:
                self._stop_camera()
                self._stop_audio()
        elif command == 'camera.select':
            selected = self._selected('cameras', payload['key'])
            if selected.key != self.camera_key:
                self._stop_camera()
                if self.camera is not None and self.camera.alive:
                    raise BridgeError('device_releasing', 'Previous camera is still releasing; retry shortly')
                self.camera, self.camera_key = None, selected.key
                self._camera_state = 'not_started'
        elif command == 'microphone.select':
            selected = self._selected('microphones', payload['key'])
            previous = self.audio.selection
            same = (previous is not None and previous.key == selected.key and
                    previous.signature == selected.signature and
                    (selected.key != 'system-default' or not self.audio.device_key or
                     selected.default_target_key == self.audio.device_key))
            if not same:
                self._stop_audio()
                if self._audio_alive():
                    raise BridgeError('device_releasing', 'Previous microphone is still releasing; retry shortly')
                self.audio = self.audio_factory(replace(self.config.audio, enabled=True), self.clock)
            self.audio.selection, self.audio_key = selected, selected.key
        elif command == 'camera.start':
            self._require_consent()
            self._selected('cameras', self.camera_key)
            if self.camera is not None and self.camera.alive:
                if self.camera.stopped:
                    raise BridgeError('device_releasing', 'Previous camera is still releasing; retry shortly')
            else:
                self.camera = self.camera_factory(self.config.vision, self.clock, self.camera_key)
                self._camera_state = 'opening'
                self.camera.start()
        elif command == 'camera.stop':
            self._stop_camera()
        elif command in {'audio.start', 'audio.calibrate'}:
            self._require_consent()
            self._selected('microphones', self.audio_key)
            if self._audio_alive() and self.audio.status['state'] == 'stopped':
                raise BridgeError('device_releasing', 'Previous microphone is still releasing; retry shortly')
            if command == 'audio.calibrate':
                if self.audio.check_status['state'] in {'ambient', 'speak'}:
                    raise BridgeError('busy', 'A microphone calibration is already running')
                if not self.audio.begin_calibration():
                    raise BridgeError('calibration_unavailable', 'Microphone calibration is disabled or unavailable')
            else:
                self.audio.start()
        elif command == 'audio.stop':
            self._stop_audio()
        elif command == 'shutdown':
            self.close()
        else:
            raise BridgeError('unknown_command', 'Command is not available in this setup bridge')
        return self.state()

    def state(self):
        self._take_scan()
        now, camera = self.clock.monotonic(), self.camera
        frame = camera.latest if camera is not None and self._camera_state != 'stopped' else None
        age = max(0., now-frame.timestamp) if frame is not None else None
        camera_state, error = self._camera_state, None
        if self.camera_key and not self._scanning and not any(d.key == self.camera_key for d in self._catalog['cameras']):
            camera_state, error = 'unavailable', 'Selected camera is missing; refresh or choose another camera'
        elif camera is not None and self._camera_state != 'stopped':
            if not camera.alive:
                camera_state, error = 'unavailable', 'Selected camera could not provide frames; check permissions and retry'
            elif frame is not None:
                camera_state = 'live' if age <= self.config.vision.frame_stale_seconds else 'stale'
                error = None if camera_state == 'live' else 'Camera frame is stale; stop and retry the camera'
        if self.preview is not None and self.preview.error:
            error = self.preview.error
        check = self.audio.check_status
        timestamp = check.get('timestamp')
        audio_age = max(0., now-timestamp) if timestamp is not None else None
        running = self._audio_alive() and self.audio.status['state'] != 'stopped'
        rms = _finite(check.get('rms')) if running and audio_age is not None and audio_age <= .5 else 0.
        audio_state = self.audio.status['state']
        audio_error = check.get('reason') if check.get('state') in {'unavailable', 'no_signal', 'clipping', 'noisy'} else None
        if self.audio_key and not self._scanning and not any(d.key == self.audio_key for d in self._catalog['microphones']):
            audio_state, audio_error = 'unavailable', 'Selected microphone is missing; refresh or choose another input'
        errors = dict(self._scan_errors)
        if self._scanning and now-self._scan_started > 5:
            errors['scan_error'] = 'Device scan is taking longer than expected; no second scan has been started'
        destinations = []
        if self.config.remote.enabled:
            if self.config.remote.telegram_enabled:
                destinations.append('telegram')
            if self.config.remote.webhook_url:
                destinations.append('webhook')
        return {'version': 1, 'mode': 'setup_only', 'connected': not self.closed,
                'consent_accepted': self.consent, 'language': self.config.ui.language,
                'protection': {'enabled': False, 'reason': 'electron_recovery_audit_pending'},
                'config': {'audio_exam_enabled': self.config.audio.enabled,
                           'remote_enabled': self.config.remote.enabled, 'remote_destinations': destinations,
                           'external_exam_configured': bool(self.config.external_url),
                           'registration_enabled': self.config.registration.enabled},
                'devices': {'scanning': self._scanning, 'cameras': [_device(d) for d in self._catalog['cameras']],
                            'microphones': [_device(d) for d in self._catalog['microphones']], 'errors': errors},
                'camera': {'selected_key': self.camera_key, 'state': camera_state, 'error': error,
                           'fps': _finite(camera.fps) if camera is not None and camera_state == 'live' else 0.,
                           'frame_age_seconds': age, 'source_width': int(frame.image.shape[1]) if frame is not None else None,
                           'source_height': int(frame.image.shape[0]) if frame is not None else None,
                           'preview_sequence': self.preview.metadata['sequence'] if self.preview is not None and self.preview.metadata else None},
                'audio': {'selected_key': self.audio_key, 'state': audio_state, 'error': audio_error,
                          'running': running, 'processed_level': max(0., min(1., rms)), 'frame_age_seconds': audio_age,
                          'check': {key: check.get(key) for key in CHECK_FIELDS}},
                'unavailable_actions': ['registration.submit', 'reference.capture', 'gaze.start', 'exam.start']}

    def close(self):
        if self.closed:
            return
        self.closed, self.consent = True, False
        deadline = time.monotonic()+2.
        if self.camera is not None:
            self.camera.stop(timeout=0.)
        self._camera_state = 'stopped'
        self.audio.stop(timeout=0.)
        if self.preview is not None:
            self.preview.close()
        # Signal every worker first, then share a two-second cleanup budget.
        # In particular, do not destroy a running Qt camera thread at GUI exit.
        if self.camera is not None and self.camera.alive:
            self.camera.stop(timeout=max(0., deadline-time.monotonic()))
        if self._audio_alive():
            self.audio.stop(timeout=max(0., deadline-time.monotonic()))
        if self._scan_thread is not None:
            self._scan_thread.join(max(0., deadline-time.monotonic()))

    @property
    def native_cleanup_pending(self):
        return bool((self.camera is not None and self.camera.alive) or self._audio_alive() or
                    (self._scan_thread is not None and self._scan_thread.is_alive()))
