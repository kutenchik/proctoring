"""Safe command gates only: never invokes Tunnel/Start with approval."""
import json
import subprocess
from pathlib import Path
from uuid import uuid4
import pytest

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'scripts/stage4b-demo.ps1'

def call(action,run,*extra):
    # Detached Windows children can inherit PIPE handles despite redirecting
    # their own streams. Files avoid waiting on an unrelated child's pipe EOF.
    import tempfile
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        result=subprocess.run(['powershell.exe','-NoProfile','-File',str(SCRIPT),'-Action',action,'-RunDirectory',str(run),*extra],stdout=out,stderr=err,timeout=20)
        out.seek(0);err.seek(0)
        result.stdout=out.read().decode(errors='replace');result.stderr=err.read().decode(errors='replace')
        return result

@pytest.fixture
def run_dir():return ROOT/'build/stage4b'/('script-test-'+uuid4().hex)

def test_prepare_and_no_implicit_public_launch(run_dir):
    assert call('Prepare',run_dir).returncode==0
    assert call('Prepare',run_dir).returncode!=0
    config=json.loads((run_dir/'config.json').read_text())
    assert config['origin'] is None and config['port']==8034
    for action in ('Tunnel','Start','Restart'):
        assert call(action,run_dir).returncode!=0
    assert not (run_dir/'tunnel-owner.json').exists()
    assert not (run_dir/'server-owner.json').exists()
    assert not (run_dir/'teacher.sqlite3').exists()
    assert call('Stop',run_dir).returncode==0

def test_outside_run_root_and_wildcard_pin_rejected(tmp_path,run_dir):
    assert call('Prepare',tmp_path/'bad').returncode!=0
    assert call('Prepare',run_dir).returncode==0
    assert call('Pin',run_dir,'-PublicOrigin','https://*.trycloudflare.com').returncode!=0
    assert json.loads((run_dir/'config.json').read_text())['origin'] is None

def test_reused_pid_identity_cannot_be_stopped(run_dir):
    assert call('Prepare',run_dir).returncode==0
    # This test process is intentionally the protected target; a mismatched
    # creation time MUST reject before any Stop-Process invocation.
    import os
    (run_dir/'tunnel-owner.json').write_text(json.dumps({'pid':os.getpid(),'created':'wrong','exe':'wrong','command':'wrong','owner':'wrong'}))
    result=call('Stop',run_dir)
    assert result.returncode!=0
    assert 'identity changed' in result.stderr

def test_stop_only_recorded_owned_fixture_process(run_dir):
    import sys
    assert call('Prepare',run_dir).returncode==0
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(25)'],creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        code=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={child.pid}'; $o=Invoke-CimMethod -InputObject $p -MethodName GetOwner; @{{pid=$p.ProcessId;created=$p.CreationDate.ToUniversalTime().ToString('o');exe=$p.ExecutablePath;command=$p.CommandLine;owner=($o.Domain+'\\'+$o.User)}}|ConvertTo-Json"
        record=subprocess.run(['powershell.exe','-NoProfile','-Command',code],capture_output=True,text=True,check=True).stdout
        (run_dir/'tunnel-owner.json').write_text(record)
        assert call('Stop',run_dir).returncode==0
        child.wait(timeout=5)
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=5)

def test_full_local_launcher_restart_preserves_database(run_dir):
    """The recorded 'tunnel' is a sleeping fixture, with NO network connector.
    This tests the real server launcher solely on loopback; no public exposure.
    """
    import socket
    import httpx
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    assert call('Prepare',run_dir,'-Port',str(port)).returncode==0
    fixture=subprocess.Popen(['powershell.exe','-NoProfile','-Command','Start-Sleep -Seconds 60'],creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        code=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={fixture.pid}'; $o=Invoke-CimMethod -InputObject $p -MethodName GetOwner; @{{pid=$p.ProcessId;created=$p.CreationDate.ToUniversalTime().ToString('o');exe=$p.ExecutablePath;command=$p.CommandLine;owner=($o.Domain+'\\'+$o.User)}}|ConvertTo-Json"
        record=subprocess.run(['powershell.exe','-NoProfile','-Command',code],capture_output=True,text=True,check=True).stdout
        (run_dir/'tunnel-owner.json').write_text(record)
        origin='https://launcher-fixture.trycloudflare.com'
        (run_dir/'tunnel.stdout.log').write_text(origin);(run_dir/'tunnel.stderr.log').write_text('')
        result=call('Pin',run_dir,'-PublicOrigin',origin);assert result.returncode==0,result.stderr
        for action in ('Start','Restart'):
            result=call(action,run_dir,'-OperatorApprovedPublicExposure');assert result.returncode==0,result.stderr
            with httpx.Client(trust_env=False) as client:
                response=client.get(f'http://127.0.0.1:{port}/api/v1/health',headers={'Host':'launcher-fixture.trycloudflare.com','X-Forwarded-Proto':'https'})
            assert response.status_code==200
            assert (run_dir/'teacher.sqlite3').exists()
            import sqlite3
            with sqlite3.connect(run_dir/'teacher.sqlite3') as db:
                if action=='Start':
                    db.execute('CREATE TABLE fixture_persistence(value INTEGER)')
                    db.execute('INSERT INTO fixture_persistence VALUES(42)')
                else:
                    assert db.execute('SELECT value FROM fixture_persistence').fetchone()==(42,)
        assert list(run_dir.glob('server-owner-*.json'))
        result=call('Stop',run_dir);assert result.returncode==0,result.stderr
        fixture.wait(timeout=5)
        assert (run_dir/'teacher.sqlite3').exists()
    finally:
        call('Stop',run_dir)
        if fixture.poll() is None:fixture.terminate();fixture.wait(timeout=5)
