"""Focused real TLS/WSS + production sender/viewer/sync, synthetic inputs only."""
import asyncio
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import threading
import time

import pytest
import requests.adapters
import uvicorn
from fastapi.responses import HTMLResponse
from proctoring.connected.durable import DurableJournal
from proctoring.connected.sync import file_hash
from proctoring_server.app import create_app
from proctoring_server.settings import Settings

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('synthetic',ROOT/'scripts/stage4b_synthetic/run.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


@pytest.fixture
def tls(tmp_path,monkeypatch):
    openssl=Path('C:/Program Files/Git/usr/bin/openssl.exe')
    assert openssl.is_file(), 'Local OpenSSL is required; no TLS bypass'
    cert=tmp_path/'cert.pem';key=tmp_path/'key.pem'
    subprocess.run([str(openssl),'req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(cert),
        '-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1','-addext','basicConstraints=critical,CA:TRUE'],check=True,capture_output=True)
    pub=subprocess.run([str(openssl),'x509','-in',str(cert),'-pubkey','-noout'],check=True,capture_output=True).stdout
    der=subprocess.run([str(openssl),'pkey','-pubin','-outform','DER'],input=pub,check=True,capture_output=True).stdout
    pin=base64.b64encode(hashlib.sha256(der).digest()).decode()
    monkeypatch.setattr(requests.adapters,'DEFAULT_CA_BUNDLE_PATH',str(cert))
    monkeypatch.setenv('NODE_EXTRA_CA_CERTS',str(cert))
    # Websockets uses a verified private test CA; no global certificate-store mutation.
    monkeypatch.setenv('SSL_CERT_FILE',str(cert))
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    origin=f'https://127.0.0.1:{port}'
    app=create_app(Settings(database=tmp_path/'teacher.sqlite3',public_url=origin,teacher_origin=origin))
    bundle=subprocess.run(['node','-e',"const e=require('./teacher-web/node_modules/esbuild');process.stdout.write(e.buildSync({stdin:{contents:\"import {LiveViewer} from './teacher-web/src/live-viewer';window.LiveViewer=LiveViewer;\",resolveDir:process.cwd()},bundle:true,write:false,format:'iife'}).outputFiles[0].text)"],cwd=ROOT,check=True,capture_output=True).stdout.decode()
    @app.get('/fixture',response_class=HTMLResponse)
    def page():return '<canvas></canvas><script>'+bundle+'</script>'
    @app.middleware('http')
    async def fixture_headers(request,call_next):
        response=await call_next(request)
        if request.url.path=='/fixture': response.headers['Content-Security-Policy']="default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'; img-src blob:"
        return response
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,ssl_certfile=str(cert),ssl_keyfile=str(key),ws='websockets-sansio',ws_per_message_deflate=False,timeout_graceful_shutdown=2))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    limit=time.time()+5
    while not server.started and time.time()<limit:time.sleep(.01)
    assert server.started
    service=app.state.service
    token=service.issue_account_token('invite','stage4b-synthetic@example.invalid')
    password='synthetic-test-password-12345'
    owner=service.consume_account_token('invite',{'token':token,'name':'Synthetic','password':password})['teacher']['id']
    library=service.save_library(owner,{'title':'Synthetic','questions':[{'id':'q1','type':'single_choice','prompt':'Synthetic','options':[{'id':'a','text':'A'},{'id':'b','text':'B'}],'correct_option_ids':['a']}]})
    DurableJournal(tmp_path/'fixture-private.sqlite3').put('fixture',{'owner':owner,'library_id':library['id'],'password':password})
    try:yield tmp_path,origin,pin,password,app
    finally:
        server.should_exit=True;thread.join(5);listener.close();assert not thread.is_alive()


def test_real_tls_wss_production_sender_browser_decode_ack_stop(tls):
    run,origin,pin,password,app=tls
    client,journal,row=fixture.admit(run,origin,'relay')
    async def exercise():
        task=asyncio.create_task(fixture.relay(run,client,journal,row,time.time()+30))
        deadline=time.time()+5
        while time.time()<deadline:
            peer=app.state.live.students.get(row['attempt_id'])
            if peer and peer.status and peer.status.get('state')=='running':break
            await asyncio.sleep(.1)
        browser=await asyncio.create_subprocess_exec('node','scripts/stage4b_synthetic/local-viewer.mjs',cwd=ROOT,
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        raw,err=await asyncio.wait_for(browser.communicate(json.dumps({'origin':origin,'spki':pin,'password':password,
            'email':'stage4b-synthetic@example.invalid','attempt':row['attempt_id']}).encode()+b'\n'),25)
        assert browser.returncode==0,err.decode()
        await asyncio.wait_for(task,8)
        return json.loads(raw)
    result=asyncio.run(exercise())
    assert result['before']['delivery']['frames']>=8
    assert result['before']['transport']=='relay'
    assert result['before']['trace']['counts']['presented']>=8
    assert result['after']['reason']=='teacher_stopped'
    evidence=json.loads((run/'relay-results.json').read_text())
    assert evidence['first_failure'] is None,evidence
    assert any(r.get('trace',{}).get('counts',{}).get('ack_accepted',0)>0 for r in evidence['records'])
    assert evidence['generated']>=8


def test_real_tls_multichunk_duplicate_lost_response_receipt_cleanup(tls):
    run,origin,*_=tls
    client,journal,row=fixture.admit(run,origin,'sync');fixture.start(client,row)
    fixture.synchronize(run,client,journal,row,time.time()+60)
    result=json.loads((run/'sync-results.json').read_text())
    assert result['first_failure'] is None
    assert result['independent_receipt_before_cleanup'] and result['cleanup'] and result['injected_response_loss']
    assert result['receipt']['file_count']==6 and result['receipt']['record_count']==1400
    assert any(r.get('offset',0) and r['offset']>=524288 for r in result['requests'])
    assert result['retained_file_count']==0


def test_public_gate_refuses_missing_approval_and_no_output(tmp_path):
    with pytest.raises(ValueError):fixture.gate(tmp_path,False)
    assert not list(tmp_path.iterdir())


def test_generated_frames_are_distinct_and_bounded():
    assert fixture.frame(1)!=fixture.frame(2)
    assert len(base64.b64decode(fixture.frame(9999)))<262144
