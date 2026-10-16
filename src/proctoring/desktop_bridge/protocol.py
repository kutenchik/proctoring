"""Small, bounded, versioned command protocol; no arbitrary function dispatch."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
from ..connected.screen_diagnostic import valid_diagnostic

MAX_REQUEST_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
COMMANDS = frozenset({
    'state.get', 'devices.refresh', 'camera.select', 'microphone.select',
    'consent.set', 'camera.start', 'camera.stop', 'audio.start', 'audio.stop',
    'audio.calibrate', 'shutdown',
    'registration.submit', 'reference.capture', 'calibration.start', 'calibration.presented',
    'calibration.cancel', 'calibration.retry', 'geometry.changed', 'exam.start', 'quiz.answer',
    'quiz.navigate', 'exam.submit', 'proctor.pause', 'proctor.resume', 'proctor.end',
    'presentation.lost', 'presentation.sync', 'emergency.end', 'report.retry', 'events.get',
    'host.external', 'host.evidence', 'setup.show', 'host.bind', 'host.progress', 'host.safety_release',
    'connected.verify', 'connected.admit', 'connected.refresh', 'sync.retry', 'sync.background',
    'screen.consent','live.poll','live.capture',
})


@dataclass(frozen=True)
class DispatchResult:
    state: dict
    data: object


class BridgeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def parse_request(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_REQUEST_BYTES:
        raise BridgeError('invalid_request', 'Request exceeds the 16 KiB limit')
    try:
        request = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise BridgeError('invalid_request', 'Request must be finite, unique-key JSON') from error
    if not isinstance(request, dict) or set(request) != {'version', 'id', 'command', 'payload'}:
        raise BridgeError('invalid_request', 'Expected version, id, command and payload')
    if type(request['version']) is not int or request['version'] != 1:
        raise BridgeError('unsupported_version', 'Only protocol version 1 is supported')
    if not isinstance(request['id'], str) or not 1 <= len(request['id']) <= 128:
        raise BridgeError('invalid_request', 'Request ID must be a 1–128 character string')
    command, payload = request['command'], request['payload']
    if not isinstance(command, str) or command not in COMMANDS:
        raise BridgeError('unknown_command', 'Command is not available in this desktop bridge')
    if not isinstance(payload, dict):
        raise BridgeError('invalid_payload', 'Payload must be an object')
    shapes = {'registration.submit': {'first_name', 'last_name', 'group_id'},
              'connected.verify': {'server_url'},
              'connected.admit': {'exam_code', 'full_name', 'group', 'student_id'},
              'calibration.presented': {'token', 'target', 'geometry'}, 'calibration.retry': {'scope'},
              'geometry.changed': {'geometry'}, 'quiz.answer': {'question_index', 'option_index', 'revision'},
              'quiz.navigate': {'question_index'}, 'presentation.sync': {'session_id', 'event_cursor'},
              'events.get': {'after', 'limit'}, 'host.evidence': {'session_id', 'kind'},
              'host.bind': {'launch_id', 'host_pid', 'windows', 'runtime'},
              'host.progress': {'lease_id', 'sequence', 'nonce', 'main_sequence', 'session_id', 'snapshot_seq'},
              'host.safety_release': {'reason'},'live.capture':{'viewer_id','state','transport','reason'}}
    fields = ({'key'} if command.endswith('.select') else {'accepted'} if command in ('consent.set','screen.consent')
              else {'pin'} if command.startswith('proctor.') else shapes.get(command, set()))
    if command == 'host.evidence' and 'event_id' in payload:
        fields = fields | {'event_id'}
    if command == 'quiz.answer' and 'option_indices' in payload:
        fields = {'question_index', 'option_indices', 'revision'}
    if command == 'live.capture' and 'diagnostic' in payload:
        fields = fields | {'diagnostic'}
        if (not valid_diagnostic(payload['diagnostic']) or payload['diagnostic']['viewer_id'] != payload.get('viewer_id') or
                payload.get('state') not in ('stopped','unavailable') or payload.get('reason') != payload['diagnostic']['code']):
            raise BridgeError('invalid_payload', 'Invalid capture diagnostic')
    if set(payload) != fields:
        raise BridgeError('invalid_payload', 'Unexpected or missing payload fields')
    if command=='live.capture' and (not isinstance(payload['viewer_id'],str) or not 1<=len(payload['viewer_id'])<=128 or
            payload['state'] not in ('starting','recovering','live','degraded','unavailable','stopped') or
            payload['transport'] not in ('direct','relay',None) or
            (payload['reason'] is not None and (not isinstance(payload['reason'],str) or len(payload['reason'])>128))):
        raise BridgeError('invalid_payload','Invalid trusted capture status')
    if command.startswith('connected.'):
        limits = {'server_url': 2048, 'exam_code': 64, 'full_name': 200, 'group': 128, 'student_id': 128}
        for name in fields:
            if (not isinstance(payload[name], str) or not payload[name].strip() or len(payload[name]) > limits[name]
                    or any(ord(c) < 32 or ord(c) == 127 for c in payload[name])):
                raise BridgeError('invalid_payload', 'Required admission details must be bounded text')
    if 'option_indices' in fields:
        values = payload['option_indices']
        if (not isinstance(values, list) or len(values) > 100 or
                any(type(value) is not int or not 0 <= value <= 1000 for value in values) or
                len(set(values)) != len(values)):
            raise BridgeError('invalid_payload', 'Expected a bounded distinct list of option indices')
    if command == 'host.bind':
        import re
        if (not isinstance(payload['launch_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', payload['launch_id'])
                or type(payload['host_pid']) is not int or not 0 < payload['host_pid'] <= 0xffffffff):
            raise BridgeError('invalid_payload', 'Invalid native launch identity')
        windows, runtime = payload['windows'], payload['runtime']
        if not isinstance(windows, list) or not 1 <= len(windows) <= 8:
            raise BridgeError('invalid_payload', 'Expected a bounded explicit window list')
        for window in windows:
            if (not isinstance(window, dict) or set(window) != {'hwnd', 'role'} or
                    not isinstance(window['role'], str) or window['role'] not in {'exam', 'dialog'} or not isinstance(window['hwnd'], str) or
                    not re.fullmatch(r'0x[0-9a-fA-F]{1,16}', window['hwnd'])):
                raise BridgeError('invalid_payload', 'Invalid native window identity')
        if (not isinstance(runtime, dict) or set(runtime) != {'electron_version', 'app_version', 'build_kind', 'build_id'} or
                not isinstance(runtime['build_kind'], str) or runtime['build_kind'] not in {'source', 'packaged'} or
                any(not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 for c in value)
                    for value in runtime.values())):
            raise BridgeError('invalid_payload', 'Invalid native runtime identity')
    if command == 'host.progress':
        import re
        for name in ('lease_id', 'nonce'):
            if not isinstance(payload[name], str) or not re.fullmatch(r'[a-f0-9]{32,64}', payload[name]):
                raise BridgeError('invalid_payload', 'Invalid control challenge')
        for name in ('sequence', 'main_sequence', 'snapshot_seq'):
            if type(payload[name]) is not int or not 0 < payload[name] <= 2**53-1:
                raise BridgeError('invalid_payload', 'Invalid control sequence')
    if command == 'host.safety_release' and (not isinstance(payload['reason'], str) or
            payload['reason'] not in {'display_geometry_changed', 'host_window_destroyed'}):
        raise BridgeError('invalid_payload', 'Unknown native release reason')
    if 'key' in fields and (not isinstance(payload['key'], str) or not 1 <= len(payload['key']) <= 1024):
        raise BridgeError('invalid_payload', 'Device key must be a non-empty bounded string')
    if 'accepted' in fields and type(payload['accepted']) is not bool:
        raise BridgeError('invalid_payload', 'Consent must be a boolean')
    for name in fields & {'first_name', 'last_name', 'group_id', 'pin', 'token', 'target', 'scope', 'kind', 'event_id'}:
        if not isinstance(payload[name], str) or len(payload[name]) > 256 or any(ord(c) < 32 for c in payload[name]):
            raise BridgeError('invalid_payload', 'Expected a bounded text value')
    for name in fields & {'question_index', 'option_index', 'revision', 'after', 'limit', 'event_cursor'}:
        if type(payload[name]) is not int or not 0 <= payload[name] <= 2**53-1:
            raise BridgeError('invalid_payload', 'Expected a non-negative integer')
    if 'session_id' in fields and payload['session_id'] is not None and (
            not isinstance(payload['session_id'], str) or len(payload['session_id']) > 128):
        raise BridgeError('invalid_payload', 'Invalid session identifier')
    if 'geometry' in fields and not isinstance(payload['geometry'], dict):
        raise BridgeError('invalid_payload', 'Expected trusted display geometry')
    if command == 'calibration.retry' and payload['scope'] not in {'target', 'baseline'}:
        raise BridgeError('invalid_payload', 'Retry scope must be target or baseline')
    if command == 'events.get' and not 1 <= payload['limit'] <= 100:
        raise BridgeError('invalid_payload', 'Event page limit must be between 1 and 100')
    if command == 'host.evidence' and payload['kind'] not in {'snapshot', 'reference', 'report'}:
        raise BridgeError('invalid_payload', 'Unknown evidence kind')
    return request


def failure(request_id, code, message):
    return {'version': 1, 'id': request_id, 'ok': False,
            'error': {'code': code, 'message': message}}


class Protocol:
    def __init__(self, dispatch):
        self.dispatch = dispatch
        self.cache = OrderedDict()

    def handle(self, raw):
        request_id = ''
        try:
            # Recover only a bounded string ID for malformed request responses.
            if len(raw) <= MAX_REQUEST_BYTES:
                try:
                    value = json.loads(raw)
                    if isinstance(value, dict) and isinstance(value.get('id'), str) and len(value['id']) <= 128:
                        request_id = value['id']
                except (ValueError, UnicodeError, RecursionError):
                    pass
            request = parse_request(raw)
            request_id = request['id']
            fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if request_id in self.cache:
                previous, response = self.cache[request_id]
                if previous != fingerprint:
                    return failure(request_id, 'duplicate_id', 'Request ID already belongs to another command')
                return json.loads(response)
            try:
                from .diagnostics import emit
                if request['command'] == 'camera.start':
                    emit('camera_received')
                result = self.dispatch(request['command'], request['payload'])
                response = {'version': 1, 'id': request_id, 'ok': True,
                            'result': result.state if isinstance(result, DispatchResult) else result}
                if isinstance(result, DispatchResult):
                    response['data'] = result.data
            except BridgeError as error:
                if request['command'] == 'camera.start':
                    emit('camera_failed', error=error)
                response = failure(request_id, error.code, str(error))
            except Exception as error:
                emit('camera_failed' if request['command'] == 'camera.start' else 'request_failed', error=error)
                # Driver/config exception text may contain paths or secrets.
                response = failure(request_id, 'backend_error', 'Desktop operation failed; synchronize the current state before retrying')
            encoded = json.dumps(response, allow_nan=False, separators=(',', ':'))
            if len(encoded.encode('utf-8')) > MAX_RESPONSE_BYTES:
                response = failure(request_id, 'response_too_large', 'Backend response exceeded its bound')
                encoded = json.dumps(response)
            self.cache[request_id] = (fingerprint, encoded)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return json.loads(encoded)
        except BridgeError as error:
            return failure(request_id, error.code, str(error))

