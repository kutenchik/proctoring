"""Bounded asynchronous student API. Credentials and answer keys stay in Python.

One admission/reconciliation request at a time. Stage 2 evidence retries are
owned by the separate durable worker. Network errors never become detector health.
"""
from collections import deque
from dataclasses import replace
from datetime import datetime
import ipaddress
import json
import math
import os
from pathlib import Path
import queue
import threading
import time
from urllib.parse import urlsplit

import requests

from ..browser_policy import NavigationPolicy
from ..exam import Quiz


class ConnectedError(ValueError):
    pass


def transport_failure(error):
    """Bounded typed cause traversal: never serialize exception text/URLs."""
    import socket
    import ssl
    import errno
    from urllib3 import exceptions as ue
    pending, seen = [error], set()
    for _ in range(12):
        if not pending: break
        current = pending.pop(0)
        if id(current) in seen: continue
        seen.add(id(current))
        for cls, code in ((socket.gaierror,'dns_failed'), (ue.NameResolutionError,'dns_failed'),
                          (ssl.SSLCertVerificationError,'tls_certificate_failed'),
                          (requests.exceptions.ConnectTimeout,'connect_timeout'),
                          (requests.exceptions.ReadTimeout,'read_timeout'),(ue.ReadTimeoutError,'read_timeout'),
                          (ConnectionRefusedError,'connection_refused'),(ConnectionResetError,'connection_reset'),
                          (requests.exceptions.ChunkedEncodingError,'response_interrupted')):
            if isinstance(current, cls): return code
        if isinstance(current, OSError) and current.errno in (errno.ENETUNREACH,errno.EHOSTUNREACH): return 'network_unreachable'
        for child in (getattr(current,'__cause__',None),getattr(current,'__context__',None),getattr(current,'reason',None),*getattr(current,'args',())[:4]):
            if isinstance(child, BaseException): pending.append(child)
    return 'tls_failed' if isinstance(error,requests.exceptions.SSLError) else 'connection_failed'


def server_origin(value, allow_loopback_http=False):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value.strip()):
        raise ConnectedError('invalid_server')
    try:
        url = urlsplit(value.strip())
        port = url.port
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or url.path not in ('', '/') or url.scheme not in ('https', 'http')):
            raise ValueError()
        if url.scheme == 'http':
            # Literal loopback only: no arbitrary DNS name can obtain this exception.
            if not allow_loopback_http or not ipaddress.ip_address(url.hostname).is_loopback:
                raise ValueError()
        host = url.hostname.encode('idna').decode('ascii').lower()
        if ':' in host:
            host = '['+host+']'
        return f'{url.scheme}://{host}' + (f':{port}' if port is not None and port != (443 if url.scheme == 'https' else 80) else '')
    except (ValueError, UnicodeError):
        raise ConnectedError('invalid_server') from None


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.timestamp()
    except (AttributeError, ValueError, OverflowError):
        raise ConnectedError('invalid_response') from None


def _policy_identity(exam):
    return {key: exam.get(key) for key in ('id', 'title', 'exam_type', 'duration_seconds', 'external_url',
        'shuffle_questions', 'shuffle_options', 'audio_monitoring', 'save_snapshots', 'protection_mode')}


def frozen_policy(config, admission):
    """Validate all policy fields before applying anything to the local controller."""
    try:
        exam = admission['exam']
        if not isinstance(exam, dict):
            raise ValueError()
        if any(not isinstance(exam.get(key), str) or not 1 <= len(exam[key]) <= 256 for key in ('id', 'title')):
            raise ValueError()
        duration = exam['duration_seconds']
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 1 <= duration <= 86400:
            raise ValueError()
        if exam['exam_type'] not in ('native', 'external'):
            raise ValueError()
        for field in ('audio_monitoring', 'save_snapshots', 'shuffle_questions', 'shuffle_options'):
            if type(exam[field]) is not bool:
                raise ValueError()
        mode = exam['protection_mode']
        if mode not in ('protected', 'unprotected'):
            raise ValueError()
        if (mode == 'protected') != config.protection.enabled:
            raise ConnectedError('protection_policy_mismatch')
        external = NavigationPolicy(exam['external_url'], ()) if exam['exam_type'] == 'external' else None
        quiz = None
        if external is None:
            # The server has already snapshotted and shuffled this attempt once.
            # Retries/reconnections must preserve exactly those IDs and ordering.
            quiz = Quiz.from_document(admission['quiz'])
            # Leave room for camera, events and diagnostics in the existing 256 KiB IPC.
            public = [{'id': q.id, 'prompt': q.prompt, 'options': q.options} for q in quiz.questions]
            if len(json.dumps(public, ensure_ascii=False).encode()) > 64*1024:
                raise ConnectedError('quiz_too_large')
        updated = replace(config, duration_seconds=float(duration), snapshots_enabled=exam['save_snapshots'],
                          audio=replace(config.audio, enabled=exam['audio_monitoring']),
                          registration=replace(config.registration, enabled=True, require_group=True),
                          external_url=external.external_url if external else '',
                          allowed_domains=external.allowed_domains if external else ())
        return updated, quiz
    except ConnectedError:
        raise
    except (KeyError, TypeError, ValueError):
        raise ConnectedError('invalid_policy') from None


class ConnectedClient:
    def __init__(self, settings, *, monotonic=time.monotonic, transport=None, remember_path=None, journal=None):
        self.settings, self.clock = settings, monotonic
        self.request_diagnostics = deque(maxlen=32)
        self.transport = transport or self._request
        self.remember_path = remember_path or Path(os.environ.get('LOCALAPPDATA', Path.home()))/'LocalProctoring'/'last-server.json'
        self.server = ''
        initial_error = None
        try:
            self.suggested_server = server_origin(settings.server_url, settings.allow_loopback_http) if settings.server_url else ''
        except ConnectedError:
            # A mistaken configured URL must not expose embedded credentials to UI.
            self.suggested_server, initial_error = '', 'invalid_server'
        if not self.suggested_server:
            try:
                value = json.loads(self.remember_path.read_text(encoding='utf-8'))['server_url']
                self.suggested_server = server_origin(value, settings.allow_loopback_http)
            except (OSError, ValueError, KeyError):
                pass
        self.credential = None
        self.admission = None
        self.identity = None
        self.busy = None
        self.error = initial_error
        self.deadline = 0.
        self.start_authorized = False
        self.start_attempted = False
        self.finish_sent = False
        self.finish_status = 'not_sent'
        self.closed = False
        self._results = queue.Queue(maxsize=1)
        self._thread = None
        self.journal = journal
        self.device = journal.get('device') if journal is not None else None
        self.durable = None
        self.restored = False
        if journal is not None:
            unfinished = [r for r in journal.attempts() if not r.get('cleanup')]
            if unfinished:
                self.durable = unfinished[-1]
                self.server = self.suggested_server = server_origin(self.durable['server'], settings.allow_loopback_http)
                self.credential = self.durable['credential']
                self.identity = self.durable['identity']
                self.admission = self.durable['admission']
                self.restored = True

    def persist(self, **values):
        if self.journal is not None and self.durable:
            self.durable = self.journal.update('attempt:'+self.durable['attempt_id'], **values)
        return self.durable

    def _request(self, method, origin, endpoint, payload, credential):
        started = time.monotonic()
        diagnostic = {'operation':'admission' if endpoint == '/student/admit' else 'snapshot_chunk' if endpoint.startswith('/student/sync/snapshots/') else 'sync_chunk' if endpoint.startswith('/student/sync/files/') else 'sync' if endpoint.startswith('/student/sync/') else 'control',
                      'phase':'request', 'http_status':None, 'response_bytes':0, 'elapsed_ms':0, 'code':'ok',
                      'request_json_bytes':len(json.dumps(payload).encode()) if payload is not None else 0,
                      'offset':payload.get('offset') if (endpoint.startswith('/student/sync/files/') or endpoint.startswith('/student/sync/snapshots/')) and isinstance(payload,dict) and type(payload.get('offset')) is int else None}
        headers = {'Accept': 'application/json'}
        if credential:
            headers['Authorization'] = 'Bearer '+credential
        if self.device:
            headers['X-Device-Secret'] = self.device['device_secret']
        try:
            # Never use arbitrary redirects, proxy credentials, response exception text,
            # cookies, OS TLS bypasses or renderer networking for admission credentials.
            with requests.Session() as session:
                session.trust_env = False
                deadline = time.monotonic()+self.settings.timeout_seconds
                with session.request(method, origin+'/api/v1'+endpoint, json=payload,
                                     headers=headers, timeout=self.settings.timeout_seconds,
                                     allow_redirects=False, verify=True, stream=True) as response:
                    diagnostic['http_status'] = response.status_code
                    diagnostic['phase'] = 'response_body'
                    if response.status_code >= 500 or response.status_code in (408, 429):
                        raise ConnectedError('server_unavailable')
                    body = bytearray()
                    for chunk in response.iter_content(16384):
                        if time.monotonic() > deadline:
                            diagnostic['transport_failure'] = 'response_deadline'
                            raise ConnectedError('connection_failed')
                        body.extend(chunk)
                        diagnostic['response_bytes'] = len(body)
                        if len(body) > 1024*1024:
                            raise ConnectedError('invalid_response')
                    diagnostic['phase'] = 'response_parse'
                    try:
                        data = json.loads(body)
                    except ValueError:
                        raise ConnectedError('invalid_response' if 200 <= response.status_code < 300 else 'request_rejected') from None
                    if response.status_code < 200 or response.status_code >= 300:
                        detail = data.get('detail') if isinstance(data, dict) else None
                        code = detail.get('code') if isinstance(detail, dict) else None
                        safe_codes = {'invalid_code', 'exam_not_found', 'admission_closed', 'admission_not_open', 'attempt_exists',
                                      'preparation_expired', 'invalid_credential', 'invalid_identity', 'attempt_finished',
                                      'attempt_superseded', 'attempt_not_started', 'repeat_authorized', 'invalid_result',
                                      'recovery_required', 'recovery_not_authorized', 'invalid_device', 'manifest_incomplete',
                                      'checksum_mismatch', 'invalid_chunk', 'upload_conflict', 'receipt_incomplete',
                                      'invalid_manifest','invalid_file_type','file_conflict','record_conflict','bundle_frozen',
                                      'invalid_checkpoint','recovery_unavailable','start_conflict','completion_conflict'}
                        raise ConnectedError(code if code in safe_codes else 'request_rejected')
                    if not isinstance(data, dict):
                        raise ConnectedError('invalid_response')
                    return data
        except ConnectedError as error:
            diagnostic['code'] = str(error)
            error.diagnostic = diagnostic
            raise
        except requests.RequestException as error:
            diagnostic['transport_failure'] = transport_failure(error)
            diagnostic['code'] = ('tls_failed' if isinstance(error, requests.exceptions.SSLError) else
                                  'connect_timeout' if isinstance(error, requests.exceptions.ConnectTimeout) else
                                  'read_timeout' if isinstance(error, requests.exceptions.ReadTimeout) else 'connection_failed')
            failure = ConnectedError('connection_failed')
            failure.diagnostic = diagnostic
            raise failure from None
        finally:
            diagnostic['elapsed_ms'] = round((time.monotonic()-started)*1000)
            self.request_diagnostics.append(dict(diagnostic))

    def submit(self, operation, payload=None):
        if self.closed or self.busy:
            raise ConnectedError('busy')
        payload = payload or {}
        if operation in ('verify', 'admit') and self.admission is not None:
            raise ConnectedError('already_admitted')
        if operation == 'verify':
            origin = server_origin(payload['server_url'], self.settings.allow_loopback_http)
            method, endpoint, body = 'GET', '/health', None
        else:
            origin = self.server
            if not origin:
                raise ConnectedError('verify_first')
            if operation == 'admit':
                method, endpoint, body = 'POST', '/student/admit', payload
                if self.journal is not None:
                    pending = self.journal.prepare_admission(origin, payload)
                    body = {**payload, **{k: pending[k] for k in ('admission_id','device_id','device_secret','credential')}}
            else:
                if not self.credential:
                    raise ConnectedError('admission_required')
                method = 'GET' if operation == 'refresh' else 'POST'
                endpoint = {'refresh': '/student/attempt', 'start': '/student/start', 'finish': '/student/finish',
                            'confirm': '/student/start/confirm', 'interrupted': '/student/interrupted',
                            'recover': '/student/recovery/consume', 'recovered': '/student/recovery/confirm'}[operation]
                body = payload if operation in ('finish','confirm','interrupted','recover','recovered') else None
                if operation == 'start' and self.durable:
                    body = {k: self.durable[k] for k in ('start_key','session_id')}
                    self.persist(phase='start_authorization_pending')
        self.error, self.busy = None, operation
        if operation == 'start':
            self.start_attempted = True
        if operation == 'finish':
            self.finish_status = 'pending'
        started = self.clock()
        credential = self.credential
        def work():
            try:
                data = self.transport(method, origin, endpoint, body, credential)
                result = (operation, started, origin, payload, data, None)
            except Exception as error:
                result = (operation, started, origin, payload, None,
                          str(error) if isinstance(error, ConnectedError) else 'connection_failed')
            if not self.closed:
                self._results.put_nowait(result)
        self._thread = threading.Thread(target=work, name='student-admission-http', daemon=True)
        self._thread.start()

    def poll(self):
        try:
            operation, started, origin, payload, data, error = self._results.get_nowait()
        except queue.Empty:
            return None
        self.busy = None
        if error:
            self.error = error
            if operation == 'finish':
                self.finish_status = 'failed'
            return None
        try:
            if operation == 'verify':
                if data.get('service') != 'local-proctoring-teacher' or data.get('api_version') != 1:
                    raise ConnectedError('invalid_server')
                _time(data.get('server_time'))
                self.server = self.suggested_server = origin
                try:
                    self.remember_path.parent.mkdir(parents=True, exist_ok=True)
                    self.remember_path.write_text(json.dumps({'server_url': origin}), encoding='utf-8')
                except OSError:
                    pass  # The successfully verified connection still works this launch.
            elif operation in ('admit', 'refresh', 'start', 'confirm', 'interrupted', 'recover', 'recovered'):
                if not isinstance(data.get('attempt_id'), str) or not isinstance(data.get('exam'), dict):
                    raise ConnectedError('invalid_response')
                if operation == 'admit':
                    credential = data.get('credential')
                    if not isinstance(credential, str) or not 20 <= len(credential) <= 1024:
                        raise ConnectedError('invalid_response')
                    self.credential = credential
                    self.identity = {key: payload[key] for key in ('full_name', 'group', 'student_id')}
                elif not self.admission or data['attempt_id'] != self.admission['attempt_id'] or _policy_identity(data['exam']) != _policy_identity(self.admission['exam']) or data.get('quiz') != self.admission.get('quiz'):
                    raise ConnectedError('policy_changed')
                self.deadline = started + _time(data['preparation_deadline']) - _time(data['server_time'])
                self.admission = {key: value for key, value in data.items() if key != 'credential'}
                if operation == 'admit' and self.journal is not None:
                    self.durable = self.journal.admit(self.server, self.admission, self.identity, self.credential)
                elif self.durable:
                    self.persist(admission=self.admission)
                if operation == 'start':
                    if data.get('status') != 'started' and data.get('lifecycle') != 'start_authorized':
                        raise ConnectedError('invalid_response')
                    self.start_authorized = True
                    if self.durable:
                        self.persist(phase='start_authorized')
            elif operation == 'finish':
                if data.get('status') != 'finished':
                    raise ConnectedError('invalid_response')
                self.finish_status = 'sent'
            return operation
        except (KeyError, TypeError, ValueError) as error:
            self.error = str(error) if isinstance(error, ConnectedError) else 'invalid_response'
            if operation == 'finish':
                self.finish_status = 'failed'
            return None

    def public(self):
        return {'enabled': True, 'server_url': self.suggested_server, 'verified_server': self.server,
                'busy': self.busy, 'error': self.error, 'admitted': self.admission is not None,
                'attempt_id': self.admission['attempt_id'] if self.admission else None,
                'exam_title': str(self.admission['exam'].get('title', '')) if self.admission else '',
                'preparation_remaining_seconds': max(0., self.deadline-self.clock()),
                'preparation_deadline': self.admission.get('preparation_deadline') if self.admission else None,
                'identity': self.identity, 'start_authorized': self.start_authorized,
                'finish_status': self.finish_status}

    def close(self):
        self.closed = True
        self.credential = None
        # No GUI-thread wait for a network call; requests are daemonized and bounded.
