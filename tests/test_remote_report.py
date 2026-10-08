from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests

from proctoring.storage.remote_dispatcher import RemoteDispatcher, format_telegram_message


def settings(**values):
    return SimpleNamespace(**{**dict(enabled=True, telegram_enabled=True, telegram_bot_token="test-secret",
                                    telegram_chat_id="1234", max_queue_size=5, upload_timeout_seconds=.7,
                                    webhook_url="", webhook_token=""), **values})


def metadata():
    return dict(session_id="report-test", candidate=dict(first_name="Amina", last_name="Abai", group_id="CS-101"),
                trust_score=60, total_events=2)


@pytest.fixture(autouse=True)
def http():
    response = Mock(spec=requests.Response, status_code=200)
    response.json.return_value = {"ok": True}
    with patch("proctoring.storage.remote_dispatcher.requests.post", return_value=response) as post:
        yield post


def test_telegram_document_upload_payload_and_timeout(tmp_path, http):
    path = tmp_path / "exam_integrity_report.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic fixture")
    opened = []
    response = http.return_value
    def inspect(url, **kwargs):
        assert url.endswith("/sendDocument")
        name, stream, mime = kwargs["files"]["document"]
        assert name == path.name
        assert stream.read().startswith(b"%PDF-")
        assert mime == "application/pdf"
        opened.append(stream)
        assert kwargs["timeout"] == .7
        assert kwargs["allow_redirects"] is False
        assert kwargs["data"]["chat_id"] == "1234"
        caption = kwargs["data"]["caption"]
        assert "📋 [Final Exam Report]" in caption
        assert "Amina Abai (CS-101)" in caption
        assert "Trust Score: 60%" in caption and "Total Events: 2" in caption
        assert "not a misconduct probability" in caption
        return response
    http.side_effect = inspect
    dispatcher = RemoteDispatcher(settings())
    dispatcher.enqueue("session_report", metadata(), document_path=path)
    dispatcher.close()
    http.assert_called_once()
    assert opened[0].closed
    assert dispatcher.drain_warnings() == []


@pytest.mark.parametrize("contents", [None, b"not a PDF"])
def test_unavailable_or_invalid_report_not_uploaded(tmp_path, http, contents):
    path = tmp_path / "report.pdf"
    if contents is not None:
        path.write_bytes(contents)
    dispatcher = RemoteDispatcher(settings())
    dispatcher.enqueue("session_report", metadata(), document_path=path)
    dispatcher.close()
    http.assert_not_called()
    assert dispatcher.drain_warnings()[0]["code"] == ("document_unavailable" if contents is None else "document_invalid")


def test_pdf_not_uploaded_to_webhook(tmp_path, http):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4\nfixture")
    dispatcher = RemoteDispatcher(settings(telegram_enabled=False, webhook_url="https://example.org/ingest"))
    dispatcher.enqueue("session_report", metadata(), document_path=path)
    dispatcher.close()
    http.assert_called_once()
    assert "files" not in http.call_args.kwargs
    assert http.call_args.kwargs["json"] == {**metadata(), "type": "session_report"}


def test_document_timeout_is_contained_and_token_not_logged(tmp_path, http):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4\nfixture")
    http.side_effect = requests.Timeout("test-secret")
    dispatcher = RemoteDispatcher(settings())
    dispatcher.enqueue("session_report", metadata(), document_path=path)
    dispatcher.close()
    warnings = dispatcher.drain_warnings()
    assert warnings[0]["code"] == "network_timeout"
    assert "test-secret" not in str(warnings)
