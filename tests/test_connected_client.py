"""Connected admission tests use injected HTTP and clocks, never media or hooks."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.connected.client import ConnectedClient, ConnectedError, frozen_policy, server_origin
from proctoring.connected.settings import ConnectedConfig
from proctoring.desktop_bridge.protocol import BridgeError, parse_request
from proctoring.registration import CandidateInfo


QUIZ = {'title': 'Example', 'questions': [{'id': 'q1', 'type': 'multiple_choice', 'prompt': 'Two',
        'options': [{'id': 'a', 'text': 'A'}, {'id': 'b', 'text': 'B'}, {'id': 'c', 'text': 'C'}],
        'correct_option_ids': ['a', 'c']}]}
ADMISSION = {'attempt_id': 'attempt-1', 'credential': 'secret-attempt-credential-keep-in-python',
             'status': 'preparing', 'server_time': '2026-10-13T10:00:00+00:00',
             'preparation_deadline': '2026-10-13T10:05:00+00:00',
             'exam': {'id': 'exam-1', 'title': 'Example', 'duration_seconds': 120, 'exam_type': 'native',
                      'shuffle_questions': False, 'shuffle_options': False, 'audio_monitoring': False,
                      'save_snapshots': False, 'protection_mode': 'unprotected'}, 'quiz': QUIZ}
IDENTITY = {'exam_code': 'ABCD123', 'full_name': 'Single Name', 'group': 'Demo', 'student_id': 'student-1'}


def settle(client):
    client._thread.join(2)
    assert not client._thread.is_alive()
    return client.poll()


def ready_client(tmp_path, clock=None):
    clock = clock or FakeClock(100)
    def transport(method, origin, endpoint, body, credential):
        if endpoint == '/health':
            return {'service': 'local-proctoring-teacher', 'api_version': 1, 'server_time': ADMISSION['server_time']}
        result = deepcopy(ADMISSION)
        if endpoint != '/student/admit':
            assert credential == ADMISSION['credential']
            result.pop('credential')
        if endpoint == '/student/start': result['status'] = 'started'
        return result
    client = ConnectedClient(ConnectedConfig(enabled=True, allow_loopback_http=True), monotonic=clock.monotonic,
                             transport=transport, remember_path=tmp_path/'remember.json')
    client.submit('verify', {'server_url': 'http://127.0.0.1:8000'})
    assert settle(client) == 'verify'
    return client, clock


@pytest.mark.parametrize('value,dev', [('http://example.com', True), ('http://127.0.0.1', False),
    ('https://user:password@example.com', False), ('file:///etc/passwd', True),
    ('https://example.com/path', False), ('https://example.com?token=secret', False),
    ('http://localhost', True), ('https://example.com/#hash', False)])
def test_server_origin_rejects_unsafe_urls(value, dev):
    with pytest.raises(ConnectedError): server_origin(value, dev)


def test_literal_local_exception_and_https():
    assert server_origin('http://127.0.0.1:8000/', True) == 'http://127.0.0.1:8000'
    assert server_origin('https://School.example/') == 'https://school.example'
    assert server_origin('https://School.example:443/') == 'https://school.example'


def test_tunnel_origin_change_does_not_migrate_admitted_attempt(tmp_path):
    client,_=ready_client(tmp_path)
    client.submit('admit',IDENTITY)
    assert settle(client)=='admit'
    before=(client.server,client.credential,client.admission['attempt_id'],client.deadline)
    with pytest.raises(ConnectedError,match='already_admitted'):
        client.submit('verify',{'server_url':'https://new-demo.trycloudflare.com'})
    with pytest.raises(ConnectedError,match='already_admitted'):
        client.submit('admit',IDENTITY)
    assert (client.server,client.credential,client.admission['attempt_id'],client.deadline)==before
    assert server_origin('http://[::1]:8000/', True) == 'http://[::1]:8000'


def test_admission_is_async_and_no_secret_enters_public_or_remembered_state(tmp_path):
    client, clock = ready_client(tmp_path)
    client.submit('admit', IDENTITY)
    assert settle(client) == 'admit'
    assert client.deadline == 400
    public = json.dumps(client.public())
    assert 'credential' not in public and 'correct_option_ids' not in public
    assert ADMISSION['credential'] not in (tmp_path/'remember.json').read_text()
    assert set(json.loads((tmp_path/'remember.json').read_text())) == {'server_url'}
    client.submit('start')
    assert settle(client) == 'start' and client.start_authorized
    client.close()
    assert client.credential is None


def test_failed_verification_does_not_remember_server(tmp_path):
    client = ConnectedClient(ConnectedConfig(), remember_path=tmp_path/'last.json',
                             transport=lambda *args: {'service': 'something-else'})
    client.submit('verify', {'server_url': 'https://example.test'})
    assert settle(client) is None
    assert not client.server and not client.remember_path.exists()


def test_invalid_configured_origin_never_exposes_embedded_password(tmp_path):
    client = ConnectedClient(ConnectedConfig(server_url='https://user:secret@example.test'), remember_path=tmp_path/'x')
    assert client.public()['server_url'] == '' and client.public()['error'] == 'invalid_server'
    assert 'secret' not in json.dumps(client.public())


def test_single_background_request_never_blocks_caller_or_opens_more_threads(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def transport(*args): entered.set(); release.wait(2); raise OSError('private credential in exception')
    client = ConnectedClient(ConnectedConfig(), transport=transport, remember_path=tmp_path/'x')
    client.submit('verify', {'server_url': 'https://example.test'})
    assert entered.wait(1)
    with pytest.raises(ConnectedError, match='busy'):
        client.submit('verify', {'server_url': 'https://example.test'})
    assert client.public()['busy'] == 'verify'
    release.set()
    settle(client)
    assert client.error == 'connection_failed'
    assert 'private' not in json.dumps(client.public())


def test_extension_uses_authenticated_server_deadline_and_frozen_references(tmp_path):
    client, clock = ready_client(tmp_path)
    client.submit('admit', IDENTITY); settle(client)
    original = client.transport
    def extended(*args):
        result = original(*args)
        result['server_time'] = '2026-10-13T10:05:01+00:00'
        result['preparation_deadline'] = '2026-10-13T10:10:00+00:00'
        return result
    clock.advance(301)
    assert client.public()['preparation_remaining_seconds'] == 0
    client.transport = extended
    client.submit('refresh'); assert settle(client) == 'refresh'
    assert client.public()['preparation_remaining_seconds'] == 299
    def changed(*args):
        result = extended(*args); result['exam']['duration_seconds'] = 1000; return result
    client.transport = changed
    client.submit('start'); assert settle(client) is None
    assert client.error == 'policy_changed' and not client.start_authorized


def test_policy_is_applied_as_validated_new_config_and_never_enables_protection():
    config = load_config(Path('config/connected.example.toml'))
    updated, quiz = frozen_policy(config, ADMISSION)
    assert updated.duration_seconds == 120 and not updated.audio.enabled and not updated.snapshots_enabled
    assert quiz.questions[0].type == 'multiple_choice'
    assert config.duration_seconds == 600 and not config.protection.enabled
    protected = deepcopy(ADMISSION); protected['exam']['protection_mode'] = 'protected'
    with pytest.raises(ConnectedError, match='protection_policy_mismatch'):
        frozen_policy(config, protected)


def test_external_policy_reuses_existing_exact_hostname_navigation_policy():
    admission = deepcopy(ADMISSION)
    admission['exam'].update(exam_type='external', external_url='https://lms.example/quiz?access=secret')
    config, quiz = frozen_policy(load_config(Path('config/connected.example.toml')), admission)
    assert config.allowed_domains == ('lms.example',) and config.external_exam and quiz is None


def test_server_shuffled_order_is_not_shuffled_again_by_client():
    admission = deepcopy(ADMISSION)
    admission['exam'].update(shuffle_questions=True, shuffle_options=True)
    admission['quiz']['questions'][0]['options'].reverse()
    _, quiz = frozen_policy(load_config(Path('config/connected.example.toml')), admission)
    assert quiz.questions[0].option_ids == ('c', 'b', 'a')


def test_http_transport_uses_tls_no_redirects_and_redacts_server_error_text(tmp_path, monkeypatch):
    from proctoring.connected import client as module
    captured = {}
    class Response:
        status_code = 302
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size):
            yield json.dumps({'detail': {'code': 'private-token', 'message': 'private details'}}).encode()
    class Session:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, *args, **kwargs):
            captured.update(kwargs); captured['trust_env'] = self.trust_env
            return Response()
    monkeypatch.setattr(module.requests, 'Session', Session)
    client = ConnectedClient(ConnectedConfig(), remember_path=tmp_path/'x')
    with pytest.raises(ConnectedError, match='request_rejected'):
        client._request('GET', 'https://example.test', '/student/attempt', None, 'test-secret')
    assert captured['verify'] is True and captured['allow_redirects'] is False
    assert captured['trust_env'] is False and captured['timeout'] == 5.
    assert captured['headers']['Authorization'] == 'Bearer test-secret'


def test_new_protocol_shapes_reject_credentials_and_validate_multiselect():
    def parse(command, payload):
        return parse_request(json.dumps({'version': 1, 'id': 'test', 'command': command, 'payload': payload}).encode())
    assert parse('connected.admit', IDENTITY)['payload'] == IDENTITY
    with pytest.raises(BridgeError): parse('connected.admit', {**IDENTITY, 'credential': 'injected'})
    assert parse('quiz.answer', {'question_index': 0, 'option_indices': [0, 2], 'revision': 0})
    for values in ([0, 0], [True], [1.5], '0', [-1]):
        with pytest.raises(BridgeError): parse('quiz.answer', {'question_index': 0, 'option_indices': values, 'revision': 0})


def test_candidate_full_name_does_not_invent_a_surname_and_legacy_shape_stays():
    assert CandidateInfo('', '', 'A', 'Name', 'ID').as_dict()['full_name'] == 'Name'
    assert CandidateInfo('First', 'Last', 'A').as_dict() == {'first_name': 'First', 'last_name': 'Last', 'group_id': 'A'}
    with pytest.raises(ValueError): CandidateInfo('', '', 'A', '   ', 'ID')


def test_finish_status_distinguishes_pending_acknowledged_and_failed(tmp_path):
    client, _ = ready_client(tmp_path)
    client.submit('admit', IDENTITY); settle(client)
    client.transport = lambda *args: {'status': 'finished'}
    client.submit('finish', {'score': 1, 'total': 1, 'end_reason': 'completed'})
    assert client.public()['finish_status'] == 'pending'
    assert settle(client) == 'finish'
    assert client.public()['finish_status'] == 'sent'
    client.transport = lambda *args: (_ for _ in ()).throw(ConnectedError('connection_failed'))
    client.submit('finish', {'score': 1, 'total': 1, 'end_reason': 'completed'}); settle(client)
    assert client.public()['finish_status'] == 'failed'
