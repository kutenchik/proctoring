from dataclasses import replace
import json
from pathlib import Path
import threading
from unittest.mock import Mock, patch

import pytest
import requests
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # Optional dev inspection; the app uses only QtGui for PDFs.
    QPdfDocument = None
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType
from proctoring.settings import RegistrationConfig, RemoteConfig, ReportingConfig


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_controller(tmp_path, qt_app):
    controllers = []
    def make(reporting=None, remote=None):
        base = load_config()
        config = replace(base, sessions_dir=tmp_path / "sessions", external_url="", allowed_domains=(),
                         registration=RegistrationConfig(enabled=False), remote=remote or RemoteConfig(),
                         reporting=reporting or ReportingConfig(generate_pdf_report=True),
                         audio=replace(base.audio, enabled=False),
                         identity=replace(base.identity, selfie_verification_enabled=False))
        controller = AppController(config, FakeClock())
        controllers.append(controller)
        return controller
    yield make
    for controller in controllers:
        if controller.session.started and not controller.session.ended:
            controller.end("test_cleanup")
        controller.close_remote()


def test_disabled_reporting_no_pdf_worker_or_file(make_controller):
    app = make_controller(reporting=ReportingConfig(generate_pdf_report=False))
    with patch("proctoring.storage.report_generator.ReportJob") as job:
        app.start()
        app.end()
        assert app.report_status == "disabled"
        job.assert_not_called()
    assert (app.store.path / "summary.json").is_file()
    assert not list(app.store.path.glob("*.pdf"))


def test_pdf_begins_after_summary_on_background_thread(make_controller):
    from proctoring.storage.report_generator import generate_report
    app = make_controller()
    observations = []
    def check_order(directory, summary, filename):
        stored = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        observations.append((stored["session_id"], threading.current_thread()))
        assert stored["end_reason"] == "completed"
        return generate_report(directory, summary, filename)
    with patch("proctoring.storage.report_generator.generate_report", side_effect=check_order):
        app.start()
        app.end()
        assert app._report_job.close(2)
    assert app.report_status == "complete"
    assert observations[0][0] == app.store.path.name
    assert observations[0][1] is not threading.current_thread()
    assert app._report_job.result.path.read_bytes().startswith(b"%PDF-")


@pytest.mark.skipif(QPdfDocument is None, reason="Optional QtPdf add-on unavailable for text inspection")
def test_saved_controller_report_title_score_and_system_text(make_controller):
    app = make_controller()
    app.start()
    app.end()
    assert app._report_job.close(2)
    assert app.report_status == "complete"
    pdf = QPdfDocument()
    assert pdf.load(str(app._report_job.result.path)) == QPdfDocument.Error.None_
    text = pdf.getAllText(0).text()
    assert "Exam Proctoring Integrity Report" in text
    assert "Trust Score: 100%" in text
    assert "Windows" in text or '"platform"' in text
    pdf.close()


@pytest.mark.parametrize(("enabled", "telegram", "send", "expected"), [
    (False, False, True, False), (True, False, True, False),
    (True, True, False, False), (True, True, True, True)])
def test_report_callback_respects_all_remote_flags(make_controller, enabled, telegram, send, expected):
    remote = RemoteConfig(enabled=enabled, telegram_enabled=telegram,
                          telegram_bot_token="test-secret", telegram_chat_id="123",
                          webhook_url="https://example.org/ingest" if enabled and not telegram else "")
    fake = Mock()
    fake.drain_warnings.return_value = []
    with patch("proctoring.storage.remote_dispatcher.RemoteDispatcher", return_value=fake):
        app = make_controller(remote=remote, reporting=ReportingConfig(generate_pdf_report=True,
                                                                     send_pdf_to_telegram=send))
        app.start()
        app.end()
        assert app._report_job.close(2)
        reports = [call for call in fake.enqueue.call_args_list if call.args[0] == "session_report"]
        assert len(reports) == int(expected)
        if expected:
            assert reports[0].kwargs["document_path"] == app._report_job.result.path
            assert reports[0].args[1]["trust_score"] == 100
            assert reports[0].args[1]["total_events"] == 0


def test_generated_inline_snapshot_pdf_is_sent_by_background_dispatcher(make_controller):
    remote = RemoteConfig(enabled=True, telegram_enabled=True, telegram_bot_token="test-secret",
                          telegram_chat_id="123", upload_timeout_seconds=.7)
    response = Mock(spec=requests.Response, status_code=200)
    response.json.return_value = {"ok": True}
    uploads = []

    def post(url, **kwargs):
        if url.endswith("/sendDocument"):
            name, stream, mime = kwargs["files"]["document"]
            uploads.append((name, stream.read(), mime, threading.current_thread()))
            assert kwargs["timeout"] == .7
            assert kwargs["allow_redirects"] is False
        return response

    with patch("proctoring.storage.remote_dispatcher.requests.post", side_effect=post):
        app = make_controller(remote=remote, reporting=ReportingConfig(generate_pdf_report=True,
                                                                       send_pdf_to_telegram=True))
        app.start()
        app.monitor.set_condition(EventType.PHONE_VISIBLE, True)
        app.clock.advance(.1)
        app.step()
        app.clock.advance(1.1)
        app.step()
        event_id = app.events.events[0]["event_id"]
        # Supply a saved synthetic evidence image as if the existing writer completed.
        directory = app.store.path / "snapshots"
        directory.mkdir(exist_ok=True)
        image = QImage(640, 480, QImage.Format_RGB32)
        image.fill(Qt.lightGray)
        assert image.save(str(directory / "inline.jpg"))
        app._snapshots[event_id] = "snapshots/inline.jpg"
        app.end()
        assert app._report_job.close(2)
        app.close_remote()

    assert app.report_status == "complete"
    assert len(uploads) == 1
    name, contents, mime, worker = uploads[0]
    assert name == "exam_integrity_report.pdf"
    assert contents == app._report_job.result.path.read_bytes()
    assert contents.startswith(b"%PDF-") and len(contents) > 1000
    assert b"/Subtype /Image" in contents
    assert mime == "application/pdf"
    assert worker is not threading.current_thread()


def test_failed_report_keeps_saved_local_summary_and_releases_exam(make_controller):
    app = make_controller()
    with patch("proctoring.storage.report_generator.generate_report", side_effect=OSError("disk error")):
        app.start()
        app.end()
        assert app._report_job.close(2)
    assert app.report_status == "failed"
    assert app.session.ended
    assert not app.protection.armed
    assert app.store is not None and app.store._closed
    assert json.loads((app.store.path / "summary.json").read_text(encoding="utf-8"))["end_reason"] == "completed"
    assert not list(app.store.path.glob("*.pdf"))
