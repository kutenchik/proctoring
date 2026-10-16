"""Consent transport regression; synthetic loopback only, no devices or native input."""
import builtins
from types import SimpleNamespace
import pytest
from proctoring.connected.live import LiveWorker


def test_missing_transport_dependency_is_reported_without_silent_thread_death(monkeypatch):
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == 'websockets.sync.client': raise ModuleNotFoundError('websockets')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing)
    worker = LiveWorker(SimpleNamespace())
    worker._run()
    assert worker.connection == 'offline'
    assert worker.connection_id is None
    assert worker.error == 'live_transport_unavailable'


@pytest.mark.parametrize('version', [3, 4, 5])
def test_live_worker_sends_selected_consent_and_receives_ack_over_real_socket(version):
    import json
    import threading
    import time
    from datetime import datetime, timezone
    from websockets.sync.server import serve
    values = {} if version == 3 else {'advanced.remote_enabled': True} if version == 4 else {'audio_evidence.enabled': True}
    received = []
    errors = []
    def handler(ws):
        try:
            hello = json.loads(ws.recv(timeout=3))
            ws.send(json.dumps({'type':'hello','connection_id':'synthetic-connection','server_time':datetime.now(timezone.utc).isoformat()}))
            consent = json.loads(ws.recv(timeout=3)); received.append(consent)
            ws.send(json.dumps({'type':'consent','accepted':consent['accepted'],'version':consent['version'],
                                'session_id':hello['session_id'],'recorded_at':datetime.now(timezone.utc).isoformat()}))
            try: ws.recv(timeout=3)
            except Exception: pass
        except Exception as error: errors.append(type(error).__name__)
    with serve(handler, '127.0.0.1', 0) as server:
        owner = threading.Thread(target=server.serve_forever, daemon=True); owner.start()
        client = SimpleNamespace(server=f'http://127.0.0.1:{server.socket.getsockname()[1]}',
            settings=SimpleNamespace(allow_loopback_http=True), credential='synthetic-test-only',
            device={'device_secret':'synthetic-test-only'}, durable={'session_id':'synthetic-session'},
            admission={'attempt_id':'synthetic-attempt','exam':{'monitoring_policy':{'values':values}}})
        worker = LiveWorker(client); worker.consent(True); worker.start()
        messages = []
        try:
            deadline = time.monotonic()+5
            while time.monotonic()<deadline:
                messages += worker.drain()
                if any(item[1].get('type')=='consent' for item in messages): break
                time.sleep(.01)
            assert received == [{'type':'consent','version':version,'accepted':True}]
            assert any(message.get('accepted') is True and message.get('version')==version and
                       message.get('session_id')=='synthetic-session' for _,message,_ in messages)
            assert not errors
        finally:
            worker.close(); worker.thread.join(6); server.shutdown(); owner.join(3)
            assert not worker.thread.is_alive()
