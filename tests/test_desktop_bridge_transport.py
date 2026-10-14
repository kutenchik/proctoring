"""Bounded control queues and real minimal-Qt process shutdown."""
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import pytest

from proctoring.desktop_bridge.__main__ import ControlTransport
from proctoring.desktop_bridge.__main__ import ShutdownDrain
from proctoring.desktop_bridge.protocol import MAX_REQUEST_BYTES


def command(name, identifier='1'):
    return json.dumps({'version': 1, 'id': identifier, 'command': name, 'payload': {}}).encode()+b'\n'


def test_request_queue_is_bounded_and_flood_disconnects():
    transport = ControlTransport(io.BytesIO(command('state.get')*100), io.BytesIO())
    transport._read()
    assert transport.incoming.qsize() == 64 and transport.disconnected.is_set()


def test_oversize_frame_disconnects_without_unbounded_read():
    transport = ControlTransport(io.BytesIO(b'x'*(MAX_REQUEST_BYTES+1000)), io.BytesIO())
    transport._read()
    assert transport.incoming.empty() and transport.disconnected.is_set()


def test_blocked_control_output_cannot_grow_queue_unbounded():
    transport = ControlTransport(io.BytesIO(), io.BytesIO())
    for _ in range(200):
        transport.send({'ok': True})
    assert transport.outgoing.qsize() == 128 and transport.disconnected.is_set()


def test_shutdown_keeps_qt_alive_for_report_and_has_bounded_deadline():
    from types import SimpleNamespace
    from unittest.mock import Mock
    now = [0.]
    bridge = SimpleNamespace(close=Mock(), report_cleanup_pending=True)
    drain = ShutdownDrain(bridge, monotonic=lambda: now[0])
    assert not drain.finished()
    drain.begin()
    drain.begin()
    bridge.close.assert_called_once()
    now[0] = .5
    assert not drain.finished()
    bridge.report_cleanup_pending = False
    assert drain.finished()
    bridge.report_cleanup_pending = True
    now[0] = 1.
    assert drain.finished()  # Caller must use hard exit if Qt objects remain owned.


def test_shutdown_allows_final_response_flush_without_any_worker():
    from types import SimpleNamespace
    now = [0.]
    drain = ShutdownDrain(SimpleNamespace(close=lambda: None, report_cleanup_pending=False), monotonic=lambda: now[0])
    drain.begin()
    assert not drain.finished()
    now[0] = .05
    assert drain.finished()


def test_actual_cli_refuses_protected_configuration_without_electron_host(isolated_default_config, tmp_path):
    import re
    source = isolated_default_config.read_text(encoding='utf-8')
    source = re.sub(r'(\[protection\]\s*\n)enabled = false', r'\1enabled = true', source)
    config = tmp_path/'protected.toml'
    config.write_text(source, encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'proctoring.desktop_bridge', '--config', str(config)],
                            input=b'', capture_output=True, timeout=10.,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert result.returncode == 2 and result.stdout == b''
    assert b'ELECTRON_HOST_UNAVAILABLE' in result.stderr


@pytest.mark.parametrize('shutdown_command', [True, False])
def test_actual_cli_state_and_shutdown_or_parent_eof(isolated_default_config, shutdown_command):
    environment = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}
    process = subprocess.Popen([sys.executable, '-m', 'proctoring.desktop_bridge', '--config', str(isolated_default_config)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                               cwd=str(Path(__file__).resolve().parents[1]))
    output = queue.Queue()
    def read():
        while line := process.stdout.readline():
            output.put(line)
    threading.Thread(target=read, daemon=True).start()
    try:
        process.stdin.write(command('state.get'))
        process.stdin.flush()
        response = json.loads(output.get(timeout=10.))
        assert response['ok'] and response['result']['mode'] == 'exam_workflow'
        assert not response['result']['consent_accepted']
        assert not response['result']['audio']['running']
        assert response['result']['camera']['state'] == 'not_started'
        malformed = json.loads(command('state.get', 'invalid-version'))
        malformed['version'] = 2
        process.stdin.write(json.dumps(malformed).encode()+b'\n')
        process.stdin.flush()
        rejected = json.loads(output.get(timeout=10.))
        assert rejected['id'] == 'invalid-version' and rejected['error']['code'] == 'unsupported_version'
        if shutdown_command:
            process.stdin.write(command('shutdown', '2'))
            process.stdin.flush()
            response = json.loads(output.get(timeout=10.))
            assert response['ok'] and not response['result']['connected']
        else:
            process.stdin.close()
        code = process.wait(timeout=10.)
        assert code == 0, process.stderr.read().decode('utf-8', errors='replace')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.)
