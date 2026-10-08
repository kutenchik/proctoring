from dataclasses import replace
import json
import threading

from proctoring.config import load_config
from proctoring.package_smoke import _native_checks, _safe_config


def test_smoke_overrides_live_preferences_and_removes_credentials(tmp_path):
    original = load_config()
    original = replace(
        original, external_url="https://example.test/exam?secret=token", allowed_domains=("example.test",),
        registration=replace(original.registration, enabled=True),
        remote=replace(original.remote, enabled=True, telegram_enabled=True,
                       telegram_bot_token="secret-token", telegram_chat_id="private-id"),
        protection=replace(original.protection, enabled=True),
        audio=replace(original.audio, enabled=True),
        identity=replace(original.identity, selfie_verification_enabled=True),
        system_checks=replace(original.system_checks, block_multimonitor=True,
                              clipboard_guard_enabled=True, vm_check_enabled=True),
        reporting=replace(original.reporting, generate_pdf_report=True, send_pdf_to_telegram=True),
        vision=replace(original.vision, prefer_gpu=True, accessories=replace(
            original.vision.accessories, earphone_detection_enabled=True)),
    )
    safe = _safe_config(original, tmp_path)
    assert not safe.external_exam
    assert not safe.remote.enabled and not safe.remote.telegram_enabled
    assert not safe.remote.telegram_bot_token and not safe.remote.telegram_chat_id
    assert not safe.protection.enabled and not safe.audio.enabled
    assert not safe.registration.enabled and not safe.identity.selfie_verification_enabled
    assert not any(vars(safe.system_checks).values())
    assert not safe.reporting.generate_pdf_report and not safe.reporting.send_pdf_to_telegram
    assert not safe.vision.prefer_gpu and not safe.vision.accessories.earphone_detection_enabled
    assert safe.quiz_path == original.quiz_path
    assert safe.vision.face_model == original.vision.face_model
    assert safe.vision.yolo_model == original.vision.yolo_model
    assert original.remote.telegram_bot_token == "secret-token"


def test_native_checks_close_models_and_redact_exception_text(tmp_path, monkeypatch):
    from proctoring.vision import yolo, face
    from proctoring.storage import report_generator
    import sounddevice

    closed = []

    class FakeYolo:
        provider = "CPUExecutionProvider"

        def __init__(self, config):
            assert not config.prefer_gpu

        def detect(self, image):
            assert image.shape == (480, 640, 3)
            raise RuntimeError("Do not leak secret-token or webcam data")

        def close(self):
            closed.append("yolo")

    class FakeFace:
        def __init__(self, config):
            pass

        def detect(self, image, timestamp):
            assert timestamp > 0
            return type("Measurement", (), {"face_present": False, "frame_size": (640, 480)})()

        def close(self):
            closed.append("face")

    def fake_pdf(directory, summary):
        assert summary["session_id"] == "package-smoke"
        assert json.loads((directory / "summary.json").read_text())["events"] == []
        path = directory / "exam_integrity_report.pdf"
        path.write_bytes(b"%PDF-1.4 test")
        return path

    monkeypatch.setattr(yolo, "YoloDetector", FakeYolo)
    monkeypatch.setattr(face, "FaceAnalyzer", FakeFace)
    monkeypatch.setattr(report_generator, "generate_report", fake_pdf)
    monkeypatch.setattr(sounddevice, "InputStream", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("Smoke test must not open hardware")))
    checks = {}
    _native_checks(_safe_config(load_config(), tmp_path), tmp_path, checks, threading.Lock())
    assert closed == ["yolo", "face"]
    assert checks["yolo_cpu"] == {"ok": False, "error_type": "RuntimeError"}
    assert checks["mediapipe"]["ok"]
    assert checks["sounddevice"]["device_opened"] is False
    assert checks["pdf"]["bytes"] > 0
    assert "secret-token" not in json.dumps(checks)
