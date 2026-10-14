"""New Stage 2 client + actual loopback server, no hardware or protection."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import sqlite3
import time

import pytest

from proctoring.connected.client import ConnectedClient, ConnectedError
from proctoring.connected.durable import DurableJournal
from proctoring.connected.settings import ConnectedConfig
from proctoring.connected.workflow import ConnectedWorkflow
from proctoring.connected.sync import SyncWorker
from proctoring.storage.report_generator import generate_report
from test_connected_live_api import real_server
from test_connected_client import IDENTITY, settle
from test_connected_workflow import prepare, start
from test_connected_stage2 import TestVault
from test_desktop_workflow import make_workflow


def real_workflow(tmp_path, server, journal=None):
    b=make_workflow(tmp_path)
    b.clock.timestamp=datetime.now(timezone.utc).isoformat()
    j=journal or DurableJournal(tmp_path/'outbox.sqlite3',vault=TestVault())
    client=ConnectedClient(ConnectedConfig(enabled=True,allow_loopback_http=True,timeout_seconds=2),journal=j,
        monotonic=b.clock.monotonic,remember_path=tmp_path/'remember.json')
    b.admission_client=client;b.config=replace(b.config,connected=client.settings)
    b.connected_sync=ConnectedWorkflow(b)
    if client.restored:
        b._apply_admission()
    else:
        client.submit('verify',{'server_url':server['origin']});assert settle(client)=='verify'
        b.dispatch('connected.admit',{**IDENTITY,'exam_code':server['code']})
        client._thread.join(3);b.tick()
        assert b._admission_applied,client.error
    return b,j


@pytest.mark.parametrize('expired_offline_restart',[False,True])
def test_actual_controller_to_real_server_repeated_upload_receipt_and_cleanup(tmp_path,real_server,expired_offline_restart):
    from PySide6.QtWidgets import QApplication
    qt=QApplication.instance() or QApplication([])
    b,j=real_workflow(tmp_path,real_server)
    try:
        prepare(b);start(b)
        assert b.controller.session.started,b.admission_client.error
        q=b.controller.quiz.questions[0]
        selected=[q.option_ids.index(v) for v in q.correct_option_ids]
        b.dispatch('quiz.answer',{'question_index':0,'option_indices':selected,'revision':0})
        b.dispatch('proctor.end',{'pin':b.config.proctor_pin})
        root=b.controller.store.path
        result=generate_report(root,b.controller.summary,b.config.reporting.report_filename)
        assert result.is_file() and result.stat().st_size>500
        original=result.read_bytes()
        real=b.admission_client.transport
        if expired_offline_restart:
            offline=SyncWorker(j,b.config.sessions_dir,lambda *_: (_ for _ in ()).throw(ConnectedError('connection_failed')))
            with pytest.raises(ConnectedError):offline.once(j.attempts()[0])
            assert (root/'summary.json').is_file() and not j.attempts()[0].get('cleanup')
            # Explicit next launch uses the persisted outbox, with no new start.
            j=DurableJournal(tmp_path/'outbox.sqlite3',vault=TestVault())
            with sqlite3.connect(real_server['database']) as db:
                db.execute('UPDATE attempts SET credential_expires_at=?',(time.time()-60,))
        dropped=set()
        def interrupted_response(method,origin,endpoint,payload,credential):
            result=real(method,origin,endpoint,payload,credential)
            # Server commits first: the client must repeat these exact requests.
            if endpoint.endswith('/records') or '/chunks' in endpoint:
                if endpoint not in dropped:
                    dropped.add(endpoint);raise ConnectedError('connection_failed')
            return result
        worker=SyncWorker(j,b.config.sessions_dir,interrupted_response)
        for _ in range(55):
            row=j.attempts()[0]
            if row.get('cleanup'):break
            try:worker.once(row)
            except ConnectedError:pass
        row=j.attempts()[0]
        assert row.get('cleanup'),row.get('error')
        assert row['sync_status']=='fully_synchronized'
        assert not (root/'summary.json').exists() and (root/'config.json').is_file()
        with sqlite3.connect(real_server['database']) as db:
            assert db.execute('SELECT count(*) FROM sync_receipts').fetchone()[0]==1
            assert db.execute('SELECT count(*) FROM sync_records').fetchone()[0]==row['manifest']['record_count']
            assert db.execute('SELECT count(*) FROM sync_records GROUP BY attempt_id,sequence HAVING count(*)>1').fetchone() is None
        assert original.startswith(b'%PDF-') and dropped
    finally:b.close()


@pytest.mark.parametrize('crash_after_durable_start',[False,True])
def test_lost_start_authorization_reconciles_same_attempt_then_teacher_recovery(tmp_path,real_server,crash_after_durable_start):
    b,j=real_workflow(tmp_path,real_server)
    real=b.admission_client.transport
    def lost(method,origin,endpoint,payload,credential):
        value=real(method,origin,endpoint,payload,credential)
        if endpoint=='/student/start':raise ConnectedError('connection_failed')
        return value
    prepare(b)
    original_start=None
    if crash_after_durable_start:
        b.admission_client.submit('start');assert settle(b.admission_client)=='start'
        b.connected_sync.before_start();b.controller.start();b.controller.store.flush_durable()
        original_start=next(r['timestamp'] for r in b.controller.session.records if r['event_type']=='session_started')
        # Process death before after_start: close only simulated devices/store,
        # deliberately do not execute graceful bridge-close/checkpoint code.
        b.controller.store.close();b.monitor.stop();b.audio.stop()
    else:
        b.admission_client.transport=lost
        start(b)
        assert not b.controller.session.started
    original=j.attempts()[0]
    assert original['phase']==('start_authorized' if crash_after_durable_start else 'start_authorization_pending')
    if not crash_after_durable_start:b.close()
    b2,_=real_workflow(tmp_path,real_server,j)
    try:
        b2.admission_client._thread.join(3);b2.tick()
        b2.admission_client._thread.join(3);b2.tick()
        assert b2.admission_client.error is None,b2.admission_client.error
        assert b2.connected_sync.public()['recovery_required']
        assert not b2.connected_sync.can_start()
        with sqlite3.connect(real_server['database']) as db:
            assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==1
            assert db.execute('SELECT started_at FROM attempts').fetchone()[0] is None
        import requests
        origin='http://127.0.0.1:50175'
        with requests.Session() as teacher:
            login=teacher.post(real_server['origin']+'/api/v1/auth/login',json={'email':'contract@example.test','password':'test-only-password-12345'},headers={'Origin':origin},timeout=2)
            assert login.status_code==200,login.text
            csrf=login.json()['csrf_token']
            row=j.attempts()[0]
            grant=teacher.post(real_server['origin']+'/api/v1/attempts/'+row['attempt_id']+'/recovery/authorize',
                json={'interruption_id':row['interruption_id'],'reason':'Approved isolated recovery test'},
                headers={'Origin':origin,'X-CSRF-Token':csrf},timeout=2)
            assert grant.status_code==200,grant.text
        b2.dispatch('connected.refresh',{});b2.admission_client._thread.join(3);b2.tick()
        prepare(b2);start(b2)
        assert b2.controller.session.started,b2.admission_client.error
        assert b2.controller.session.elapsed_seconds==0
        assert b2.controller.store.path.name==original['session_id']
        assert b2.admission_client.admission['attempt_id']==original['attempt_id']
        if crash_after_durable_start:
            starts=[r for r in b2.controller.session.records if r['event_type']=='session_started']
            assert len(starts)==1 and starts[0]['timestamp']==original_start
        b2.dispatch('emergency.end',{})
        assert j.attempts()[0]['terminal_reason']=='emergency_shortcut'
        if crash_after_durable_start:
            from PySide6.QtWidgets import QApplication
            qt=QApplication.instance() or QApplication([])
            generate_report(b2.controller.store.path,b2.controller.summary,b2.config.reporting.report_filename)
            worker=SyncWorker(j,b2.config.sessions_dir,b2.admission_client.transport)
            for _ in range(40):
                if j.attempts()[0].get('cleanup'):break
                worker.once(j.attempts()[0])
            assert j.attempts()[0].get('cleanup')
    finally:b2.close()
