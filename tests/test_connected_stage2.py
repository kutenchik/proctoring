"""Stage 2 only: isolated journals, synthetic devices, no native restrictions."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import os
import pytest

from proctoring.connected.client import ConnectedClient, ConnectedError
from proctoring.connected.durable import DurableJournal
from proctoring.connected.sync import SyncWorker, build_manifest, cleanup_received, digest, evidence_path, verify_receipt
from proctoring.connected.vault import WindowsVault, VaultError
from proctoring.connected.workflow import ConnectedWorkflow
from proctoring.connected.settings import ConnectedConfig
from proctoring.desktop_bridge.protocol import BridgeError
from proctoring.session import SessionController
from proctoring.clock import FakeClock
from test_connected_client import ADMISSION, IDENTITY, settle
from test_connected_workflow import prepare, start
from test_desktop_workflow import make_workflow


class TestVault:
    __test__ = False
    def __init__(self, binding=b'test-device'):
        self.binding = binding
    def encrypt(self, value):
        return self.binding+b'\0'+bytes(v^173 for v in value)
    def decrypt(self, value):
        prefix = self.binding+b'\0'
        if not value.startswith(prefix):
            raise VaultError('wrong_device')
        return bytes(v^173 for v in value[len(prefix):])


class Stage2Transport:
    def __init__(self):
        self.reply = deepcopy(ADMISSION)
        self.reply['status'] = 'admitted'
        self.reply['lifecycle'] = 'admitted'
        self.reply['recovery'] = None
        self.calls = []
    def __call__(self, method, origin, endpoint, body, credential):
        self.calls.append((endpoint, deepcopy(body)))
        if endpoint == '/health':
            return {'service':'local-proctoring-teacher','api_version':1,'server_time':ADMISSION['server_time']}
        if endpoint == '/student/admit':
            self.reply['credential'] = body['credential']
            return deepcopy(self.reply)
        if endpoint == '/student/start':
            self.reply.update(lifecycle='start_authorized', start_key=body['start_key'], session_id=body['session_id'])
        elif endpoint == '/student/interrupted':
            self.reply.update(lifecycle='interrupted', recovery={'state':'pending','interruption_id':body['interruption_id'],'grant_id':None})
        elif endpoint == '/student/recovery/consume':
            if (self.reply.get('recovery') or {}).get('state') != 'granted':
                raise ConnectedError('recovery_not_authorized')
            self.reply['recovery']['state'] = 'consumed'
        return {k:deepcopy(v) for k,v in self.reply.items() if k != 'credential'}


def workflow(tmp_path, transport=None, journal=None, restore=False, timestamp=None):
    bridge = make_workflow(tmp_path)
    if timestamp:bridge.clock.timestamp=timestamp
    transport = transport or Stage2Transport()
    journal = journal or DurableJournal(tmp_path/'outbox.sqlite3', vault=TestVault())
    client = ConnectedClient(ConnectedConfig(enabled=True,allow_loopback_http=True),
        journal=journal, transport=transport, monotonic=bridge.clock.monotonic, remember_path=tmp_path/'remember.json')
    bridge.admission_client=client
    bridge.config=replace(bridge.config,connected=client.settings)
    bridge.connected_sync=ConnectedWorkflow(bridge)
    if client.restored:
        bridge._apply_admission()
    else:
        client.submit('verify',{'server_url':'http://127.0.0.1:8000'}); assert settle(client)=='verify'
        bridge.dispatch('connected.admit',IDENTITY)
        client._thread.join(2);bridge.tick()
    return bridge, transport, journal


def ended(tmp_path):
    b,t,j=workflow(tmp_path)
    prepare(b);start(b)
    b.dispatch('quiz.answer',{'question_index':0,'option_indices':[0,2],'revision':0})
    b.dispatch('proctor.end',{'pin':'2468'})
    row=b.connected_sync.row()
    root=b.controller.store.path
    (root/b.config.reporting.report_filename).write_bytes(b'%PDF-1.4\nfixture\n%%EOF')
    return b,t,j,row,root


def receipt(row):
    m=row['manifest']
    return {'version':1,'receipt_id':'receipt-test','attempt_id':row['attempt_id'],'session_id':row['session_id'],
            'manifest_sha256':digest(m),'record_count':m['record_count'],'file_count':sum(i['status']=='present' for i in m['items']),
            'complete':True,'verified_at':'2026-10-14T10:00:00+00:00'}


def test_dpapi_no_plaintext_fallback_and_device_bound_test_storage(tmp_path):
    j=DurableJournal(tmp_path/'db',vault=TestVault())
    j.put('secret',{'credential':'never-in-renderer'})
    assert b'never-in-renderer' not in (tmp_path/'db').read_bytes()
    assert DurableJournal(tmp_path/'db',vault=TestVault()).get('secret')['credential']=='never-in-renderer'
    with pytest.raises(VaultError):DurableJournal(tmp_path/'db',vault=TestVault(b'other-machine'))


@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI only')
def test_windows_current_user_dpapi_roundtrip():
    vault=WindowsVault();sealed=vault.encrypt(b'isolated-test-not-a-real-credential')
    assert b'isolated-test-not-a-real-credential' not in sealed
    assert vault.decrypt(sealed)==b'isolated-test-not-a-real-credential'


def test_admission_retry_reuses_persisted_keys_then_new_admission_gets_new_key(tmp_path):
    j=DurableJournal(tmp_path/'db',vault=TestVault())
    a=j.prepare_admission('https://school.example',IDENTITY)
    b=DurableJournal(tmp_path/'db',vault=TestVault()).prepare_admission('https://school.example',IDENTITY)
    assert a==b
    j.admit(a['server'],{k:v for k,v in ADMISSION.items() if k!='credential'},IDENTITY,a['credential'])
    assert j.prepare_admission(a['server'],IDENTITY)['admission_id']!=a['admission_id']


def test_actual_controller_bundle_has_ids_exact_answers_and_no_configs(tmp_path):
    b,t,j,row,root=ended(tmp_path)
    try:
        manifest=build_manifest(b.config.sessions_dir,row)
        assert all(json.loads(line)['session_id']==row['session_id'] for line in (root/'events.jsonl').read_bytes().splitlines())
        assert json.loads((root/'answers.json').read_bytes())['answers']=={'q1':['a','c']}
        assert {'session','events','summary','answers','original_pdf'} <= {i['kind'] for i in manifest['items']}
        assert not any('config' in i['relative_path'] or 'calibration' in i['relative_path'] for i in manifest['items'])
        assert row['credential'] not in json.dumps(b.state())
        assert row['device_secret'] not in json.dumps(b.state())
        assert not b.state()['synchronization']['fully_synchronized']
    finally:b.close()


@pytest.mark.parametrize('field,value',[('complete',False),('complete',1),('version',True),('attempt_id','other'),('session_id','other'),('manifest_sha256','0'*64),('file_count',999),('record_count',999)])
def test_mismatching_receipt_never_deletes(tmp_path,field,value):
    b,t,j,row,root=ended(tmp_path)
    try:
        row=j.update('attempt:'+row['attempt_id'],manifest=build_manifest(b.config.sessions_dir,row))
        r=receipt(row);r[field]=value;row=j.update('attempt:'+row['attempt_id'],receipt=r)
        with pytest.raises(ValueError):cleanup_received(j,b.config.sessions_dir,row)
        assert (root/'summary.json').is_file()
    finally:b.close()


def test_missing_required_pdf_blocks_receipt_and_cleanup(tmp_path):
    b,t,j,row,root=ended(tmp_path)
    try:
        (root/b.config.reporting.report_filename).unlink()
        row=j.update('attempt:'+row['attempt_id'],manifest=build_manifest(b.config.sessions_dir,row))
        assert next(i for i in row['manifest']['items'] if i['kind']=='original_pdf')['status']=='missing_error'
        with pytest.raises(ValueError,match='required_material_missing'):verify_receipt(row,receipt(row))
    finally:b.close()


def test_receipt_cleanup_is_exact_idempotent_and_preserves_unrelated_data(tmp_path):
    b,t,j,row,root=ended(tmp_path)
    try:
        other=tmp_path/'sessions'/'standalone';other.mkdir();(other/'summary.json').write_text('keep')
        (root/'developer-calibration.json').write_text('keep')
        row=j.update('attempt:'+row['attempt_id'],manifest=build_manifest(b.config.sessions_dir,row))
        row=j.update('attempt:'+row['attempt_id'],receipt=receipt(row))
        cleanup_received(j,b.config.sessions_dir,row)
        cleanup_received(j,b.config.sessions_dir,j.get('attempt:'+row['attempt_id']))
        assert not (root/'summary.json').exists()
        assert (root/'config.json').is_file() and (root/'developer-calibration.json').is_file()
        assert (other/'summary.json').read_text()=='keep'
        assert j.get('attempt:'+row['attempt_id'])['cleanup']
    finally:b.close()


def test_modified_local_material_blocks_cleanup(tmp_path):
    b,t,j,row,root=ended(tmp_path)
    try:
        row=j.update('attempt:'+row['attempt_id'],manifest=build_manifest(b.config.sessions_dir,row))
        row=j.update('attempt:'+row['attempt_id'],receipt=receipt(row))
        (root/'summary.json').write_text('changed')
        with pytest.raises(ValueError,match='local_evidence_changed'):cleanup_received(j,b.config.sessions_dir,row)
        assert (root/'session.json').is_file()
    finally:b.close()


@pytest.mark.parametrize('path',['../config.toml','config.json','debug.json','snapshots/../../config.json','audio.wav','screen.mp4','C:/secret.pdf'])
def test_evidence_whitelist_rejects_non_evidence(tmp_path,path):
    with pytest.raises(ValueError):evidence_path(tmp_path,path)


def test_unexpected_restart_preserves_answers_time_and_independent_pauses(tmp_path):
    b,t,j=workflow(tmp_path)
    prepare(b);start(b)
    b.dispatch('quiz.answer',{'question_index':0,'option_indices':[0,2],'revision':0})
    b.clock.advance(1);b.monitor.publish();b.tick()
    b.dispatch('proctor.pause',{'pin':'2468'})
    b.controller.session._pause_reasons.add('recovery_pin')
    b.close()
    saved=j.attempts()[0];elapsed=saved['checkpoint']['elapsed_seconds'];sid=saved['session_id']
    assert saved['phase']=='unexpected_interruption'
    b2,_,_=workflow(tmp_path,t,j,timestamp='2026-10-20T12:00:00+00:00')
    try:
        b2.admission_client._thread.join(2);b2.tick()
        b2.admission_client._thread.join(2);b2.tick()
        assert not b2.readiness()['ready'] and not b2.controller.session.started
        assert b2.controller.quiz.answers=={0:[0,2]}
        t.reply['recovery'].update(state='granted',grant_id='grant-test')
        b2.dispatch('connected.refresh',{});b2.admission_client._thread.join(2);b2.tick()
        prepare(b2);start(b2)
        assert b2.controller.session.started and not b2.controller.session.running
        assert b2.controller.store.path.name==sid
        assert b2.controller.session.elapsed_seconds==elapsed
        assert b2.controller.session.pause_reasons=={'proctor','recovery_pin'}
        b2.dispatch('proctor.resume',{'pin':'2468'})
        assert b2.controller.session.running
    finally:b2.close()


def test_terminal_emergency_exit_never_becomes_recovery(tmp_path):
    b,t,j=workflow(tmp_path);prepare(b);start(b)
    b.dispatch('emergency.end',{});b.close()
    row=j.attempts()[0]
    assert row['phase']=='ended_locally' and row['terminal_reason']=='emergency_shortcut'
    b2,_,_=workflow(tmp_path,t,j)
    try:
        assert b2.controller.session.ended
        assert not b2.connected_sync.public()['recovery_required']
        with pytest.raises(BridgeError):b2.dispatch('exam.start',{})
    finally:b2.close()


def test_background_requires_ended_and_all_media_release(tmp_path):
    b,t,j=workflow(tmp_path)
    try:
        with pytest.raises(BridgeError):b.dispatch('sync.background',{})
        prepare(b);start(b)
        with pytest.raises(BridgeError):b.dispatch('sync.background',{})
        b.dispatch('proctor.end',{'pin':'2468'})
        assert b.connected_sync.public()['can_background']
        b.dispatch('sync.background',{})
        assert b.connected_sync.background and not b.monitor._camera.alive
    finally:b.close()


def test_pause_checkpoint_is_durable_without_waiting_for_periodic_tick(tmp_path):
    b,t,j=workflow(tmp_path);prepare(b);start(b)
    try:
        b.dispatch('proctor.pause',{'pin':'2468'})
        assert b.connected_sync.row()['checkpoint']['pause_reasons']==['proctor']
        b.dispatch('proctor.resume',{'pin':'2468'})
        assert b.connected_sync.row()['checkpoint']['pause_reasons']==[]
    finally:b.close()


def test_oversized_canonical_journal_record_is_explicit_material_error(tmp_path):
    b,t,j,row,root=ended(tmp_path)
    try:
        with (root/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'detail':'x'*65536})+'\n')
        with pytest.raises(ValueError,match='journal_record_too_large'):
            SyncWorker(j,b.config.sessions_dir,t)._records(row,root)
        assert j.attempts()[0]['event_cursor']==0 and (root/'summary.json').is_file()
    finally:b.close()


def test_cleanup_crash_resumes_without_deleted_metadata_and_purges_payload(tmp_path,monkeypatch):
    b,t,j,row,root=ended(tmp_path)
    row=j.update('attempt:'+row['attempt_id'],manifest=build_manifest(b.config.sessions_dir,row),final_summary=b.controller.summary)
    row=j.update('attempt:'+row['attempt_id'],receipt=receipt(row))
    update=j.update
    def crash(key,**values):
        if 'removed' in values:raise OSError('interrupted after first unlink')
        return update(key,**values)
    monkeypatch.setattr(j,'update',crash)
    with pytest.raises(OSError):cleanup_received(j,b.config.sessions_dir,row)
    assert not (root/'session.json').exists()
    monkeypatch.setattr(j,'update',update)
    b.close()
    b2,_,_=workflow(tmp_path,t,j)
    try:
        assert b2.controller.session.ended and b2.controller.store is None
        cleanup_received(j,b2.config.sessions_dir,j.get('attempt:'+row['attempt_id']))
        final=j.get('attempt:'+row['attempt_id'])
        assert final['cleanup'] and final['checkpoint'] is None and final['credential'] is None
        assert final['identity'] is None and final['final_summary'] is None
        assert b2.state()['synchronization']['fully_synchronized']
    finally:b2.close()


def test_terminal_marker_without_summary_never_allows_teacher_recovery(tmp_path):
    b,t,j=workflow(tmp_path);prepare(b);start(b)
    b.controller.protection.release('emergency_shortcut')
    b.controller.session.end('emergency_shortcut')
    b.connected_sync.terminal()
    # Simulate death before normal finalize: do not call bridge.close.
    root=b.controller.store.path
    b.controller.store.close();b.monitor.stop();b.audio.stop()
    assert not (root/'summary.json').exists()
    b2,_,_=workflow(tmp_path,t,j,timestamp='2026-10-20T12:00:00+00:00')
    try:
        assert b2.controller.session.ended and b2.controller.summary['end_reason']=='emergency_shortcut'
        assert b2.controller.summary['ended_at']==b.controller.session.records[-1]['timestamp']
        assert not b2.connected_sync.public()['recovery_required']
        assert not any(endpoint=='/student/interrupted' for endpoint,_ in t.calls)
        assert (root/'summary.json').is_file()
    finally:b2.close()


def test_restart_after_final_summary_before_ended_checkpoint_preserves_answers(tmp_path):
    b,t,j=workflow(tmp_path);prepare(b);start(b)
    b.dispatch('quiz.answer',{'question_index':0,'option_indices':[0,2],'revision':0})
    b.controller.end('proctor_ended')  # no bridge.tick after summary is written
    assert j.attempts()[0]['phase']=='terminal_pending'
    assert not (b.controller.store.path/'answers.json').exists()
    b2,_,_=workflow(tmp_path,t,j)
    try:
        b2.tick()
        assert b2.controller.quiz.answers=={0:[0,2]}
        answer=json.loads((b2.controller.store.path/'answers.json').read_bytes())
        assert answer['answers']=={'q1':['a','c']} and answer['score']==1
        assert j.attempts()[0]['phase']=='ended_locally'
    finally:b2.close()


def test_terminal_dpapi_commit_failure_uses_durable_marker_without_duplicate_end(tmp_path,monkeypatch):
    b,t,j=workflow(tmp_path);prepare(b);start(b)
    original=b.admission_client.persist
    def unavailable(**values):
        if values.get('phase')=='terminal_pending':raise OSError('secure commit unavailable')
        return original(**values)
    monkeypatch.setattr(b.admission_client,'persist',unavailable)
    b.controller.protection.release('emergency_shortcut')
    b.controller.session.end('emergency_shortcut')
    b.controller._write_session_records()
    b.connected_sync.terminal()
    assert b.connected_sync.error=='terminal_checkpoint_requires_attention'
    assert j.attempts()[0]['phase']=='locally_started'
    b.controller.store.close();b.monitor.stop();b.audio.stop()
    b2,_,_=workflow(tmp_path,t,j,timestamp='2026-10-20T12:00:00+00:00')
    try:
        assert b2.controller.session.ended and not b2.connected_sync.public()['recovery_required']
        ends=[r for r in b2.controller.summary['lifecycle'] if r['event_type']=='session_ended']
        assert len(ends)==1 and ends[0]['timestamp']==b.controller.session.records[-1]['timestamp']
        raw=[json.loads(line) for line in (b2.controller.store.path/'events.jsonl').read_bytes().splitlines()]
        assert len([r for r in raw if r.get('event_type')=='session_ended'])==1
    finally:b2.close()


def test_journal_tail_event_after_checkpoint_is_preserved_and_id_advances(tmp_path):
    from proctoring.domain import EventType, Observation
    b,t,j=workflow(tmp_path);prepare(b);start(b)
    checkpoint=b.connected_sync.row()['checkpoint']
    event={'event_id':'event-000001','event_type':'phone_visible','state':'active','action':'activated',
           'start_timestamp':b.clock.wall_time(),'duration_seconds':1.,'confidence':.9}
    b.controller._append({'record_kind':'review_event',**event});b.controller.store.flush_durable()
    assert checkpoint['events']==[]
    b.connected_sync.restore_events(checkpoint)
    assert b.controller.events.events[0]['event_id']=='event-000001'
    assert b.controller.events.events[0]['state']=='closed'
    b.clock.advance(.01)
    b.controller.events.observe(Observation(b.clock.monotonic(),{EventType.PHONE_VISIBLE:.8}))
    b.clock.advance(1.1)
    changes=b.controller.events.observe(Observation(b.clock.monotonic(),{EventType.PHONE_VISIBLE:.8}))
    assert any(c['event_id']=='event-000002' for c in changes)
    b.close()


def test_uncommitted_start_request_can_reconcile_to_preparation_without_timer(tmp_path):
    b,t,j=workflow(tmp_path);prepare(b)
    def offline(*_):raise ConnectedError('connection_failed')
    b.admission_client.transport=offline;start(b)
    assert not b.controller.session.started
    b.close()
    b2,_,_=workflow(tmp_path,t,j)
    try:
        b2.admission_client._thread.join(2);b2.tick()
        assert j.attempts()[0]['phase']=='preparation'
        assert not b2.controller.session.started
        assert not b2.connected_sync.public()['recovery_required']
    finally:b2.close()



@pytest.mark.parametrize('lost_completion',[False,True])
def test_final_chunk_requests_verified_receipt_without_an_extra_tick(tmp_path,lost_completion):
    b,t,j,row,root=ended(tmp_path)
    try:
        manifest=build_manifest(b.config.sessions_dir,row)
        row=j.update('attempt:'+row['attempt_id'],media_released=True,event_cursor=manifest['record_count'])
        present=[i for i in manifest['items'] if i['status']=='present'];last=present[-1]
        calls=[]
        def transport(method,origin,endpoint,payload,credential):
            calls.append(endpoint)
            if endpoint.endswith('/manifest'):return {'manifest_sha256':digest(manifest)}
            if endpoint.endswith('/status'):return {'files':[{'id':i['id'],'complete':i!=last,'received_bytes':0 if i==last else i['size']} for i in present]}
            if endpoint.endswith('/chunks'):return {'item_id':last['id'],'received_bytes':last['size'],'complete':True}
            if endpoint.endswith('/complete'):
                assert j.attempts()[0]['sync_status']=='verifying'
                if lost_completion:raise ConnectedError('connection_failed')
                return {'receipt':receipt(j.attempts()[0])}
            raise AssertionError(endpoint)
        worker=SyncWorker(j,b.config.sessions_dir,transport)
        if lost_completion:
            with pytest.raises(ConnectedError):worker.once(row)
            assert (root/'summary.json').exists() and not j.attempts()[0]['cleanup']
        else:
            worker.once(row)
            assert j.attempts()[0]['cleanup'] and j.attempts()[0]['receipt']['complete'] is True
        assert calls[-1]=='/student/sync/complete'
        assert sum(c.endswith('/chunks') for c in calls)==1
    finally:b.close()
