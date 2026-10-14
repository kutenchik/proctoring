"""Deterministic durable protocol checks without devices or protected mode."""
import base64
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import secrets
from uuid import uuid4

import pytest

from proctoring_server.service import Problem, iso
from proctoring_server.sync import SyncService, checksum
from review_fixtures import build_review_bundle


@pytest.fixture
def bound(service, admission_data):
    data = {**admission_data, 'admission_id': uuid4().hex, 'device_id': uuid4().hex,
            'device_secret': secrets.token_urlsafe(32), 'credential': secrets.token_urlsafe(32)}
    admission = service.admit(data)
    sync = SyncService(service)
    start = {'start_key': uuid4().hex, 'session_id': 'session-'+uuid4().hex}
    return sync, data, admission, start


def problem(code, call):
    with pytest.raises(Problem) as caught:
        call()
    assert caught.value.code == code


def started(bound, clock):
    sync, data, admission, start = bound
    sync.authorize_start(data['credential'], data['device_secret'], start)
    sync.confirm_start(data['credential'], data['device_secret'], {**start, 'started_at': iso(clock())})
    return sync, data, admission, start


def test_admission_retry_survives_lost_ack_and_closed_window(bound, service, clock):
    _, data, admission, _ = bound
    clock.advance(4000)
    retry = service.admit(data)
    assert retry['attempt_id'] == admission['attempt_id']
    assert retry['quiz'] == admission['quiz']
    problem('admission_conflict', lambda: service.admit({**data, 'group': 'Changed'}))


def test_admission_parallel_retries_create_one_attempt(service, admission_data):
    data = {**admission_data, 'admission_id': uuid4().hex, 'device_id': uuid4().hex,
            'device_secret': secrets.token_urlsafe(32), 'credential': secrets.token_urlsafe(32)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: service.admit(data), range(4)))
    assert len({r['attempt_id'] for r in responses}) == 1


def test_two_phase_start_reconciles_and_does_not_restart_timer(bound, clock):
    sync, data, admission, start = bound
    first = sync.authorize_start(data['credential'], data['device_secret'], start)
    assert first['started_at'] is None and first['lifecycle'] == 'start_authorized'
    timestamp = iso(clock())
    clock.advance(400)
    assert sync.authorize_start(data['credential'], data['device_secret'], start)['start_key'] == start['start_key']
    confirm = {**start, 'started_at': timestamp}
    assert sync.confirm_start(data['credential'], data['device_secret'], confirm)['started_at'] == timestamp
    clock.advance(100)
    assert sync.confirm_start(data['credential'], data['device_secret'], confirm)['started_at'] == timestamp
    problem('start_conflict', lambda: sync.confirm_start(data['credential'], data['device_secret'], {**confirm, 'started_at': iso(clock())}))


def test_start_requires_original_device_and_unexpired_first_authorization(bound, clock):
    sync, data, _, start = bound
    problem('wrong_device', lambda: sync.authorize_start(data['credential'], secrets.token_urlsafe(32), start))
    clock.advance(300)
    problem('preparation_expired', lambda: sync.authorize_start(data['credential'], data['device_secret'], start))


def test_teacher_specific_same_attempt_recovery(bound, owner, other, clock):
    sync, data, admission, start = started(bound, clock)
    interruption = {'interruption_id': uuid4().hex, 'session_id': start['session_id'], 'reason': 'unexpected restart',
                    'checkpoint': {'elapsed_seconds': 25, 'remaining_seconds': 575, 'answers': {'single': ['two']}, 'pause_reasons': ['monitoring']}}
    sync.interrupted(data['credential'], data['device_secret'], interruption)
    request = {'interruption_id': interruption['interruption_id'], 'reason': 'Supervised recovery'}
    problem('not_found', lambda: sync.authorize_recovery(other, admission['attempt_id'], request))
    grant = sync.authorize_recovery(owner, admission['attempt_id'], request)
    consume = {'grant_id': grant['grant_id'], 'session_id': start['session_id']}
    problem('recovery_unavailable', lambda: sync.recovery(data['credential'], data['device_secret'], consume, confirm=True))
    result = sync.recovery(data['credential'], data['device_secret'], consume)
    assert result['recovery']['checkpoint'] == interruption['checkpoint']
    result = sync.recovery(data['credential'], data['device_secret'], consume, confirm=True)
    assert result['lifecycle'] == 'started' and result['session_id'] == start['session_id']
    assert sync.recovery(data['credential'], data['device_secret'], consume, confirm=True)['recovery']['state'] == 'confirmed'


def test_new_interruption_cannot_reuse_old_grant(bound, owner, clock):
    sync, data, admission, start = started(bound, clock)
    record = {'interruption_id': uuid4().hex, 'session_id': start['session_id'], 'reason': 'crash',
              'checkpoint': {'elapsed_seconds': 1, 'remaining_seconds': 599, 'answers': {}, 'pause_reasons': []}}
    sync.interrupted(data['credential'], data['device_secret'], record)
    grant = sync.authorize_recovery(owner, admission['attempt_id'], {'interruption_id': record['interruption_id'], 'reason': 'check'})
    payload = {'grant_id': grant['grant_id'], 'session_id': start['session_id']}
    sync.recovery(data['credential'], data['device_secret'], payload)
    sync.recovery(data['credential'], data['device_secret'], payload, confirm=True)
    sync.interrupted(data['credential'], data['device_secret'], {**record, 'interruption_id': uuid4().hex})
    problem('recovery_unavailable', lambda: sync.recovery(data['credential'], data['device_secret'], payload))


def test_interruption_after_consumed_recovery_with_lost_confirmation_needs_new_grant(bound, owner, clock):
    sync, data, admission, start = started(bound, clock)
    first = {'interruption_id': uuid4().hex, 'session_id': start['session_id'], 'reason': 'first crash',
             'checkpoint': {'elapsed_seconds': 10, 'remaining_seconds': 590, 'answers': {'single': ['two']}, 'pause_reasons': ['proctor']}}
    sync.interrupted(data['credential'], data['device_secret'], first)
    grant = sync.authorize_recovery(owner, admission['attempt_id'], {'interruption_id': first['interruption_id'], 'reason': 'First supervised recovery'})
    consumed = {'grant_id': grant['grant_id'], 'session_id': start['session_id']}
    assert sync.recovery(data['credential'], data['device_secret'], consumed)['lifecycle'] == 'recovery_authorized'
    # Local exam resumed, then crashed before recovery confirmation reached the
    # server. Its newer durable checkpoint must require a fresh teacher grant.
    second = {**first, 'interruption_id': uuid4().hex, 'reason': 'crash after local resume',
              'checkpoint': {**first['checkpoint'], 'elapsed_seconds': 12, 'remaining_seconds': 588}}
    result = sync.interrupted(data['credential'], data['device_secret'], second)
    assert result['lifecycle'] == 'interrupted'
    assert result['recovery']['checkpoint'] == second['checkpoint']
    assert result['recovery']['grant_id'] is None
    for confirm in (False, True):
        problem('recovery_unavailable', lambda: sync.recovery(data['credential'], data['device_secret'], consumed, confirm=confirm))
    next_grant = sync.authorize_recovery(owner, admission['attempt_id'], {'interruption_id': second['interruption_id'], 'reason': 'Second supervised recovery'})
    assert next_grant['grant_id'] != grant['grant_id']
    payload = {'grant_id': next_grant['grant_id'], 'session_id': start['session_id']}
    sync.recovery(data['credential'], data['device_secret'], payload)
    resumed = sync.recovery(data['credential'], data['device_secret'], payload, confirm=True)
    assert resumed['lifecycle'] == 'started'
    assert resumed['recovery']['checkpoint']['elapsed_seconds'] == 12
    assert resumed['recovery']['checkpoint']['pause_reasons'] == ['proctor']


def test_record_retries_immutable_and_out_of_order(bound, clock):
    sync, data, _, start = started(bound, clock)
    records = [{'sequence': i, 'record': {'session_id': start['session_id'], 'event_id': 'same', 'duration_seconds': i}} for i in [2, 0, 1]]
    payload = {'session_id': start['session_id'], 'records': records}
    sync.records_upload(data['credential'], data['device_secret'], payload)
    sync.records_upload(data['credential'], data['device_secret'], payload)
    assert sync.status(data['credential'], data['device_secret'])['record_sequences'] == [0, 1, 2]
    altered = deepcopy(payload); altered['records'][0]['record']['duration_seconds'] = 42
    problem('record_conflict', lambda: sync.records_upload(data['credential'], data['device_secret'], altered))


@pytest.fixture
def bundle(service, owner, exam_data):
    return build_review_bundle(service, owner, exam_data, complete=False)


def finish(bundle):
    return bundle['sync'].complete(bundle['credential'], bundle['device_secret'], {'manifest_sha256': checksum(bundle['manifest'])})['receipt']


def test_receipt_verified_server_score_and_owner_isolation(bundle, owner, other):
    receipt = finish(bundle)
    assert finish(bundle) == receipt
    detail = bundle['sync'].teacher_detail(owner, bundle['attempt_id'])
    assert detail['receipt_complete'] is True
    assert detail['server_result']['score'] == 2 and detail['server_result']['consistent'] is False
    assert detail['client_result']['score'] == 1
    problem('not_found', lambda: bundle['sync'].teacher_detail(other, bundle['attempt_id']))
    problem('not_found', lambda: bundle['sync'].file_path(other, bundle['attempt_id'], 'reference'))


def test_missing_pdf_and_later_corruption_cannot_produce_receipt(bundle):
    sync = bundle['sync']
    pdf = sync._path(bundle['attempt_id'], 'original_pdf')
    original = pdf.read_bytes(); pdf.unlink()
    problem('bundle_incomplete', lambda: finish(bundle))
    pdf.write_bytes(original)
    receipt = finish(bundle)
    pdf.write_bytes(b'corrupt')
    problem('bundle_incomplete', lambda: finish(bundle))
    status = sync.status(bundle['credential'], bundle['device_secret'])
    assert status['receipt'] is None and status['status'] != 'fully_synchronized'
    assert receipt['complete'] is True


@pytest.mark.parametrize('mutation,code', [
    (lambda m: m['items'][0].update(relative_path='../session.json'), 'invalid_path'),
    (lambda m: m['items'][0].update(relative_path='config.json'), 'invalid_file_type'),
    (lambda m: m.update(proctor_pin='123'), 'private_material'),
    (lambda m: m['items'].__setitem__(slice(None), [i for i in m['items'] if i['kind'] != 'original_pdf']), 'missing_required_kind'),
])
def test_manifest_boundaries(bundle, mutation, code):
    manifest = deepcopy(bundle['manifest']); mutation(manifest)
    problem(code, lambda: bundle['sync'].manifest_upload(bundle['credential'], bundle['device_secret'], {'manifest': manifest}))


def test_missing_required_error_is_not_complete_receipt(bound, clock):
    sync, data, admission, start = started(bound, clock)
    kinds = {'session': 'session.json', 'events': 'events.jsonl', 'summary': 'summary.json', 'answers': 'answers.json', 'original_pdf': 'report.pdf'}
    manifest = {'version': 1, 'attempt_id': admission['attempt_id'], 'session_id': start['session_id'], 'ended_at': iso(clock()), 'end_reason': 'emergency_shortcut', 'record_count': 0, 'identity_required': False,
                'items': [{'id': k, 'kind': k, 'relative_path': p, 'required': True, 'status': 'missing_error', 'error': 'disk failure', 'size': None, 'sha256': None} for k, p in kinds.items()] + [{'id': 'disabled', 'kind': 'snapshot', 'relative_path': 'snapshots/disabled.jpg', 'required': False, 'status': 'disabled', 'error': None, 'size': None, 'sha256': None}]}
    response = sync.manifest_upload(data['credential'], data['device_secret'], {'manifest': manifest})
    problem('bundle_incomplete', lambda: sync.complete(data['credential'], data['device_secret'], response))
    problem('attempt_finished', lambda: sync.interrupted(data['credential'], data['device_secret'], {'session_id': start['session_id'], 'interruption_id': uuid4().hex, 'reason': 'restart', 'checkpoint': {'elapsed_seconds': 1, 'remaining_seconds': 599, 'answers': {}, 'pause_reasons': []}}))


def test_chunk_retries_compare_bytes_and_checksum(bundle):
    sync = bundle['sync']; payload = {'manifest_sha256': checksum(bundle['manifest']), 'offset': 0, 'data_base64': base64.b64encode(bundle['raw']['reference']).decode()}
    assert sync.chunk(bundle['credential'], bundle['device_secret'], 'reference', payload)['complete']
    payload['data_base64'] = base64.b64encode(b'x' * len(bundle['raw']['reference'])).decode()
    problem('chunk_conflict', lambda: sync.chunk(bundle['credential'], bundle['device_secret'], 'reference', payload))


def test_retention_leaves_incomplete_and_before_due(bundle, clock, owner):
    sync = bundle['sync']
    clock.advance(31*86400)
    assert sync.retain()['deleted'] == []
    # Receipt was never issued; an incomplete attempt cannot be purged early.
    problem('review_not_ready', lambda: sync.delete_materials(owner, bundle['attempt_id'], {'confirm': True, 'reason': 'request'}))


def test_retention_uses_actual_end_and_deletes_owned_completed_bundle(bundle, clock, owner):
    finish(bundle); sync = bundle['sync']
    clock.advance(30*86400)
    assert sync.retain()['deleted'] == []  # Actual end is 20 seconds after admission.
    clock.advance(21)
    assert sync.retain()['deleted'][0]['attempt_id'] == bundle['attempt_id']
    assert not sync.directory(bundle['attempt_id']).exists()
    detail = sync.teacher_detail(owner, bundle['attempt_id'])
    assert detail['status'] == 'deleted' and not detail['receipt_complete']


def test_delete_failure_blocks_reads_then_retry_completes(bundle, owner, monkeypatch):
    finish(bundle); sync = bundle['sync']
    import proctoring_server.sync as module
    original = module.shutil.rmtree
    def failure(path):
        raise OSError('simulated busy disk')
    monkeypatch.setattr(module.shutil, 'rmtree', failure)
    with pytest.raises(OSError):
        sync.delete_materials(owner, bundle['attempt_id'], {'confirm': True, 'reason': 'Teacher request'})
    problem('materials_deleted', lambda: sync.file_path(owner, bundle['attempt_id'], 'original_pdf'))
    assert not sync.teacher_detail(owner, bundle['attempt_id'])['receipt_complete']
    monkeypatch.setattr(module.shutil, 'rmtree', original)
    assert sync.delete_materials(owner, bundle['attempt_id'], {'confirm': True, 'reason': 'Retry original request'})['deleted']


def test_http_bound_start_and_finish_requires_device(client, service, admission_data):
    data = {**admission_data, 'admission_id': uuid4().hex, 'device_id': uuid4().hex, 'device_secret': secrets.token_urlsafe(32), 'credential': secrets.token_urlsafe(32)}
    assert client.post('/api/v1/student/admit', json=data).status_code == 201
    headers = {'Authorization': 'Bearer '+data['credential']}
    assert client.get('/api/v1/student/attempt', headers=headers).status_code == 401
    headers['X-Device-Secret'] = data['device_secret']
    payload = {'start_key': uuid4().hex, 'session_id': 'session-'+uuid4().hex}
    response = client.post('/api/v1/student/start', headers=headers, json=payload)
    assert response.status_code == 200 and response.json()['started_at'] is None
    response = client.post('/api/v1/student/finish', headers=headers, json={'end_reason': 'completed'})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'sync_required'


def test_authorized_start_blocks_repeat_and_extension_after_deadline(bound, owner, clock, service):
    sync, data, admission, start = bound
    sync.authorize_start(data['credential'], data['device_secret'], start)
    clock.advance(301)
    problem('attempt_live', lambda: service.allow_repeat(owner, admission['attempt_id'], {'reason': 'expired'}))
    problem('attempt_started', lambda: service.extend(owner, admission['attempt_id'], {'reason': 'expired'}))
    clock.advance(4000)
    assert service.exam(owner, admission['exam']['id'])['phase'] == 'active'


def test_pending_ended_evidence_still_syncs_after_explicit_repeat(bundle, service, owner):
    service.allow_repeat(owner, bundle['attempt_id'], {'reason': 'New supervised attempt'})
    exam = service.exam(owner, bundle['exam_id'])
    next_attempt = service.admit({'exam_code': exam['code'], 'full_name': 'Same student', 'group': 'G', 'student_id': '00123'})
    assert next_attempt['attempt_id'] != bundle['attempt_id']
    assert finish(bundle)['complete']
    problem('start_blocked', lambda: bundle['sync'].authorize_start(bundle['credential'], bundle['device_secret'], {'start_key': uuid4().hex, 'session_id': bundle['session_id']}))


def reset_file(bundle, item_id):
    sync = bundle['sync']
    sync._path(bundle['attempt_id'], item_id).unlink()
    with sync.database.connect(write=True) as connection:
        connection.execute('UPDATE sync_files SET complete=0,received_bytes=0 WHERE attempt_id=? AND item_id=?', (bundle['attempt_id'], item_id))
    return sync


def test_partial_chunks_resume_across_service_restart_and_compare_retries(bundle, service):
    sync = reset_file(bundle, 'original_pdf')
    raw = bundle['raw']['original_pdf']; split = len(raw)//2
    def chunk(offset, value):
        return {'manifest_sha256': checksum(bundle['manifest']), 'offset': offset, 'data_base64': base64.b64encode(value).decode()}
    auth = bundle['credential'], bundle['device_secret'], 'original_pdf'
    assert sync.chunk(*auth, chunk(0, raw[:split]))['received_bytes'] == split
    restarted = SyncService(service)
    assert restarted.chunk(*auth, chunk(0, raw[:split]))['received_bytes'] == split
    problem('chunk_gap', lambda: restarted.chunk(*auth, chunk(split+1, raw[split+1:])))
    assert restarted.chunk(*auth, chunk(split, raw[split:]))['complete']
    assert finish(bundle)['complete']


def test_checksum_failure_no_ack_then_valid_retry(bundle):
    sync = reset_file(bundle, 'original_pdf')
    raw = bundle['raw']['original_pdf']
    args = bundle['credential'], bundle['device_secret'], 'original_pdf'
    payload = {'manifest_sha256': checksum(bundle['manifest']), 'offset': 0, 'data_base64': base64.b64encode(b'x'*len(raw)).decode()}
    problem('checksum_mismatch', lambda: sync.chunk(*args, payload))
    status = sync.status(bundle['credential'], bundle['device_secret'])
    assert next(f for f in status['files'] if f['id'] == 'original_pdf')['received_bytes'] == 0
    payload['data_base64'] = base64.b64encode(raw).decode()
    assert sync.chunk(*args, payload)['complete']


def test_crash_after_rename_before_db_commit_recovers_existing_verified_bytes(bundle, monkeypatch):
    sync = reset_file(bundle, 'original_pdf')
    import proctoring_server.sync as module
    original = module.os.replace
    def moved_then_failed(source, target):
        original(source, target)
        raise OSError('simulated process interruption after rename')
    payload = {'manifest_sha256': checksum(bundle['manifest']), 'offset': 0, 'data_base64': base64.b64encode(bundle['raw']['original_pdf']).decode()}
    monkeypatch.setattr(module.os, 'replace', moved_then_failed)
    with pytest.raises(OSError):
        sync.chunk(bundle['credential'], bundle['device_secret'], 'original_pdf', payload)
    monkeypatch.setattr(module.os, 'replace', original)
    assert sync.chunk(bundle['credential'], bundle['device_secret'], 'original_pdf', payload)['complete']
    assert finish(bundle)['complete']


@pytest.mark.parametrize('kind,raw', [('original_pdf', b'%PDF-1.7\nnot a PDF'), ('reference', b'\xff\xd8\xffnot a JPEG')])
def test_file_type_requires_real_structure_not_only_signature(tmp_path, kind, raw):
    path = tmp_path/'file'; path.write_bytes(raw)
    problem('invalid_file_type', lambda: SyncService._file_type(path, kind))


def test_recovery_after_lost_start_confirmation_sets_original_timestamp(bound, owner, clock):
    sync, data, admission, start = bound
    sync.authorize_start(data['credential'], data['device_secret'], start)
    interruption = {'interruption_id': uuid4().hex, 'session_id': start['session_id'], 'reason': 'crash before acknowledgement', 'checkpoint': {'elapsed_seconds': 5, 'remaining_seconds': 595, 'answers': {}, 'pause_reasons': []}}
    sync.interrupted(data['credential'], data['device_secret'], interruption)
    grant = sync.authorize_recovery(owner, admission['attempt_id'], {'interruption_id': interruption['interruption_id'], 'reason': 'Supervised'})
    payload = {'grant_id': grant['grant_id'], 'session_id': start['session_id'], 'started_at': iso(clock())}
    sync.recovery(data['credential'], data['device_secret'], payload)
    response = sync.recovery(data['credential'], data['device_secret'], payload, confirm=True)
    assert response['started_at'] == payload['started_at']


def test_early_delete_requires_owning_teacher_and_explicit_confirmation(bundle, owner, other):
    finish(bundle); sync = bundle['sync']
    problem('confirmation_required', lambda: sync.delete_materials(owner, bundle['attempt_id'], {'reason': 'test'}))
    problem('not_found', lambda: sync.delete_materials(other, bundle['attempt_id'], {'confirm': True, 'reason': 'test'}))
    assert sync.file_path(owner, bundle['attempt_id'], 'original_pdf').is_file()


def test_all_student_sync_mutations_require_device_secret(client, bound):
    _, data, _, _ = bound
    headers = {'Authorization': 'Bearer '+data['credential'], 'X-Device-Secret': secrets.token_urlsafe(32)}
    response = client.get('/api/v1/student/sync/status', headers=headers)
    assert response.status_code == 403 and response.json()['detail']['code'] == 'wrong_device'


def test_review_delete_csrf_and_origin_are_preserved(client, bundle):
    response = client.post('/api/v1/auth/login', headers={'Origin': 'http://127.0.0.1:5174'}, json={'email': 'teacher@example.com', 'password': 'test password 12345'})
    assert response.status_code == 200
    url = '/api/v1/attempts/'+bundle['attempt_id']+'/materials/delete'
    assert client.post(url, json={'confirm': True, 'reason': 'test'}).status_code == 403
    assert client.post(url, headers={'Origin': 'http://127.0.0.1:5174'}, json={'confirm': True, 'reason': 'test'}).status_code == 403


def test_expired_bearer_can_only_finish_already_authorized_evidence(bundle, clock):
    clock.advance(31*86400)
    sync = bundle['sync']
    problem('invalid_credential', lambda: sync.attempt(bundle['credential'], bundle['device_secret']))
    problem('invalid_credential', lambda: sync.authorize_start(bundle['credential'], bundle['device_secret'], {'start_key': uuid4().hex, 'session_id': bundle['session_id']}))
    problem('invalid_credential', lambda: sync.recovery(bundle['credential'], bundle['device_secret'], {'grant_id': uuid4().hex, 'session_id': bundle['session_id']}))
    problem('wrong_device', lambda: sync.status(bundle['credential'], secrets.token_urlsafe(32)))
    assert finish(bundle)['complete']
    assert sync.status(bundle['credential'], bundle['device_secret'])['status'] == 'fully_synchronized'


def test_expired_unstarted_admission_cannot_upload(bound, clock):
    sync, data, _, start = bound
    clock.advance(31*86400)
    problem('session_required', lambda: sync.records_upload(data['credential'], data['device_secret'], {'session_id': start['session_id'], 'records': [{'sequence': 0, 'record': {'session_id': start['session_id']}}]}))
    problem('invalid_credential', lambda: sync.authorize_start(data['credential'], data['device_secret'], start))


def test_receipt_reconciles_missing_start_ack_without_resetting_time(bundle, clock):
    sync = bundle['sync']
    with sync.database.connect(write=True) as connection:
        original = connection.execute('SELECT started_at FROM attempts WHERE id=?', (bundle['attempt_id'],)).fetchone()[0]
        connection.execute('UPDATE attempts SET started_at=NULL WHERE id=?', (bundle['attempt_id'],))
        connection.execute('UPDATE sync_attempts SET local_started_at=NULL WHERE attempt_id=?', (bundle['attempt_id'],))
    clock.advance(31*86400)
    assert finish(bundle)['complete']
    with sync.database.connect() as connection:
        assert connection.execute('SELECT started_at FROM attempts WHERE id=?', (bundle['attempt_id'],)).fetchone()[0] == original
