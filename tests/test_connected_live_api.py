"""Real loopback HTTP contract; isolated DB/server, synthetic desktop readiness.

No physical device, native hook, teacher UI, protected session or remote host.
The separate server environment keeps FastAPI out of the desktop dependencies.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import time

import pytest

from proctoring.connected.client import ConnectedClient
from proctoring.connected.settings import ConnectedConfig
from test_connected_client import IDENTITY, settle
from test_connected_workflow import prepare, start
from test_desktop_workflow import make_workflow

ROOT = Path(__file__).resolve().parents[1]
SERVER_PYTHON = ROOT/'.venv-server'/'Scripts'/'python.exe'


@pytest.fixture
def real_server(tmp_path):
    if not SERVER_PYTHON.is_file():
        pytest.skip('Isolated .venv-server is required for real API contract tests')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    database = tmp_path/'teacher.sqlite3'
    env = {**os.environ, 'PYTHONPATH': str(ROOT/'src'), 'PROCTOR_SERVER_DATABASE': str(database),
           'PROCTOR_SERVER_URL': origin, 'PROCTOR_TEACHER_ORIGIN': 'http://127.0.0.1:50175',
           'PROCTOR_ALLOW_LOOPBACK_HTTP': '1'}
    seed = '''
import json,time
from proctoring_server.settings import Settings
from proctoring_server.service import Service,iso
s=Service(Settings.from_env())
t=s.issue_account_token('invite','contract@example.test')
owner=s.consume_account_token('invite',{'token':t,'name':'Contract Teacher','password':'test-only-password-12345'})['teacher']['id']
library=s.save_library(owner,{'title':'Contract quiz','questions':[{'id':'question1','type':'multiple_choice','prompt':'Choose two','options':[{'id':'a','text':'A'},{'id':'b','text':'B'},{'id':'c','text':'C'}],'correct_option_ids':['a','c']}]})
now=time.time()
base={'title':'Contract exam','exam_type':'native','library_id':library['id'],'admission_start':iso(now-60),'admission_close':iso(now+3600),'duration_seconds':120,'timezone':'Asia/Qyzylorda','shuffle_questions':True,'shuffle_options':True,'audio_monitoring':False,'save_snapshots':False,'protection_mode':'unprotected'}
open_exam=s.create_exam(owner,base)
closed=s.create_exam(owner,{**base,'title':'Closed','admission_start':iso(now-3600),'admission_close':iso(now-1)})
print(json.dumps({'code':open_exam['code'],'closed_code':closed['code'],'owner':owner}))
'''
    seeded = subprocess.run([str(SERVER_PYTHON), '-c', seed], env=env, cwd=ROOT,
                            capture_output=True, text=True, timeout=15, check=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    data = json.loads(seeded.stdout)
    log = (tmp_path/'server.log').open('w', encoding='utf-8')
    process = subprocess.Popen([str(SERVER_PYTHON), '-m', 'uvicorn', 'proctoring_server.app:create_app',
        '--factory', '--host', '127.0.0.1', '--port', str(port), '--no-access-log', '--log-level', 'warning'],
        env=env, cwd=ROOT, stdout=log, stderr=log,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail('Isolated contract server exited before readiness')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1): break
            except OSError: time.sleep(.05)
        else: pytest.fail('Isolated contract server did not become ready')
        yield {**data, 'origin': origin, 'database': database, 'process': process}
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
        log.close()


def admitted_workflow(tmp_path, server):
    bridge = make_workflow(tmp_path)
    client = ConnectedClient(ConnectedConfig(enabled=True, allow_loopback_http=True, timeout_seconds=1),
                             monotonic=bridge.clock.monotonic, remember_path=tmp_path/'last-server.json')
    bridge.admission_client = client
    bridge.config = replace(bridge.config, connected=client.settings)
    bridge.dispatch('connected.verify', {'server_url': server['origin']})
    client._thread.join(3); bridge.tick()
    assert client.server == server['origin'], client.error
    bridge.dispatch('connected.admit', {**IDENTITY, 'exam_code': server['code']})
    client._thread.join(3); bridge.tick()
    assert bridge._admission_applied, client.error
    return bridge


def test_real_api_admit_refresh_start_and_finish_contract(tmp_path, real_server):
    bridge = admitted_workflow(tmp_path, real_server)
    try:
        client = bridge.admission_client
        expected_ids = [option['id'] for option in client.admission['quiz']['questions'][0]['options']]
        assert list(bridge.controller.quiz.questions[0].option_ids) == expected_ids
        original_quiz = bridge.controller.quiz
        bridge.dispatch('connected.refresh', {}); client._thread.join(3); bridge.tick()
        assert client.error is None and bridge.controller.quiz is original_quiz
        prepare(bridge); start(bridge)
        assert bridge.controller.session.running, client.error
        options = [i for i, value in enumerate(expected_ids) if value in ('a','c')]
        bridge.dispatch('quiz.answer', {'question_index':0,'option_indices':options,'revision':0})
        bridge.dispatch('exam.submit', {})
        client._thread.join(3); bridge.tick()
        assert client.finish_status == 'sent', client.error
        state = json.dumps(bridge.state())
        assert client.credential not in state and 'correct_option_ids' not in state
        with sqlite3.connect(real_server['database']) as connection:
            row = connection.execute('SELECT score,total,finished_at,end_reason FROM attempts').fetchone()
            assert row[:2] == (1,1) and row[2] is not None and row[3] == 'completed'
        assert bridge.controller.summary['score'] == 1
    finally: bridge.close()


def test_real_server_outage_after_start_does_not_pause_local_exam(tmp_path, real_server):
    bridge = admitted_workflow(tmp_path, real_server)
    try:
        prepare(bridge); start(bridge); assert bridge.controller.session.running
        process=real_server['process']; process.terminate(); process.wait(timeout=3)
        # Continue fresh simulated camera/vision samples while Internet is down.
        for _ in range(20):
            bridge.clock.advance(.5); bridge.tick()
        assert bridge.controller.session.running and not bridge.controller.session.pause_reasons
        assert bridge.controller.session.elapsed_seconds == 10
        assert not bridge.controller.review_events
        bridge.dispatch('exam.submit', {})
        bridge.admission_client._thread.join(3); bridge.tick()
        assert bridge.admission_client.finish_status == 'failed'
        assert bridge.controller.summary['end_reason'] == 'completed'
        assert (bridge.controller.store.path/'summary.json').is_file()
    finally: bridge.close()


def test_real_api_closed_admission_and_expired_preparation_rejected(tmp_path, real_server):
    bridge=admitted_workflow(tmp_path, real_server)
    try:
        client=bridge.admission_client
        other=ConnectedClient(client.settings, remember_path=tmp_path/'other.json')
        other.submit('verify', {'server_url':real_server['origin']}); settle(other)
        other.submit('admit', {**IDENTITY,'exam_code':real_server['closed_code']}); settle(other)
        assert other.error == 'admission_closed' and other.admission is None
        other.close()
        with sqlite3.connect(real_server['database']) as connection:
            connection.execute('UPDATE attempts SET preparation_deadline=?', (time.time()-1,))
        client.submit('start'); settle(client)
        assert client.error == 'preparation_expired' and not client.start_authorized
        assert not bridge.controller.session.started
    finally: bridge.close()
