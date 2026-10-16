"""Real workflow/controller with injected devices; no capture or native hooks."""
import json
from proctoring.desktop_bridge.protocol import Protocol
from test_desktop_workflow import make_workflow


def test_partial_camera_initialization_releases_device_and_blocks_exam(tmp_path):
    bridge = make_workflow(tmp_path)
    try:
        bridge.dispatch('consent.set', {'accepted': True})
        bridge.dispatch('camera.select', {'key': 'camera-a'})
        camera = bridge.monitor._camera
        def fail():
            camera.alive = True
            raise OSError('private driver information')
        camera.start = fail
        protocol = Protocol(bridge.dispatch)
        result = protocol.handle(json.dumps({'version': 1, 'id': 'camera-test', 'command': 'camera.start', 'payload': {}}).encode())
        assert not result['ok']
        assert result['error']['code'] == 'camera_initialization_failed'
        assert 'private driver' not in str(result)
        assert not camera.alive
        assert not bridge.controller._camera_preview_allowed
        result = protocol.handle(json.dumps({'version': 1, 'id': 'start', 'command': 'exam.start', 'payload': {}}).encode())
        assert not result['ok']
        assert not bridge.controller.session.started
    finally:
        bridge.close()


def test_successful_mock_camera_request_does_not_start_exam(tmp_path):
    bridge = make_workflow(tmp_path)
    try:
        bridge.dispatch('consent.set', {'accepted': True})
        bridge.dispatch('camera.select', {'key': 'camera-a'})
        result = Protocol(bridge.dispatch).handle(json.dumps({'version': 1, 'id': 'camera-test', 'command': 'camera.start', 'payload': {}}).encode())
        assert result['ok']
        assert bridge.monitor._camera.alive
        assert not bridge.controller.session.started
    finally:
        bridge.close()


def test_metadata_emitter_never_serializes_exception_text(capsys):
    from proctoring.desktop_bridge.diagnostics import emit
    emit('camera_failed', error=OSError('SECRET path token answer'))
    emit('SECRET', error=RuntimeError('SECRET'))
    output = capsys.readouterr()
    assert output.out == ''
    assert json.loads(output.err.removeprefix('PROCTORING_LIFECYCLE:')) == {'event': 'camera_failed', 'classification': 'os'}


def test_qt_partial_initialization_attempts_all_finalizers(monkeypatch, capsys):
    from types import SimpleNamespace
    import proctoring.vision.qt_camera as module
    import PySide6.QtMultimedia as multimedia
    from proctoring.clock import FakeClock
    from proctoring.vision.settings import VisionConfig
    calls = []
    signal = SimpleNamespace(connect=lambda *args: None)
    class Camera:
        errorOccurred = signal
        def __init__(self, *_): pass
        def start(self): raise OSError('SECRET initialization')
        def stop(self):
            calls.append('stop')
            raise RuntimeError('SECRET cleanup')
    class Session:
        def setVideoSink(self, value):
            if value is None: calls.append('sink')
        def setCamera(self, value):
            if value is None: calls.append('camera')
    monkeypatch.setattr(multimedia, 'QCamera', Camera)
    monkeypatch.setattr(multimedia, 'QMediaCaptureSession', Session)
    monkeypatch.setattr(multimedia, 'QVideoSink', lambda: SimpleNamespace(videoFrameChanged=signal))
    monkeypatch.setattr(multimedia, 'QMediaDevices', SimpleNamespace(videoInputs=lambda: [SimpleNamespace(id=lambda: b'a', videoFormats=lambda: [])]))
    monkeypatch.setattr(module, 'QEventLoop', lambda: SimpleNamespace(quit=lambda: None))
    monkeypatch.setattr(module, 'QTimer', lambda: SimpleNamespace(timeout=signal, start=lambda _: None, stop=lambda: None))
    camera = module.NamedCamera(VisionConfig(), FakeClock(100.), b'a'.hex())
    camera._run_qt()
    assert calls == ['stop', 'sink', 'camera']
    assert camera.error.startswith('Camera initialization failed')
    output = capsys.readouterr().err
    assert 'SECRET' not in output
    assert output.index('camera_failed') < output.index('camera_cleanup_failed')
