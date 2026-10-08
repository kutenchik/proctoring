import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests

from proctoring.storage.remote_dispatcher import RemoteDispatcher, format_telegram_message


def remote_config(**overrides):
    values = dict(enabled=True, webhook_url="", webhook_token="",
                  telegram_enabled=True, telegram_bot_token="test-secret-token",
                  telegram_chat_id="-123", max_queue_size=50,
                  upload_timeout_seconds=5.0)
    values.update(overrides)
    return SimpleNamespace(**values)


def payload(**overrides):
    values = dict(session_id="session-test", candidate={"first_name": "Amina",
                  "last_name": "Abai", "group_id": "CS-101"},
                  timestamp="2026-10-07T12:30:00Z", event_type="phone_raised",
                  duration_seconds=1.25, total_events=2)
    values.update(overrides)
    return values


@pytest.fixture(autouse=True)
def mocked_http():
    # Every test is isolated from actual Telegram/webhook services.
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {"ok": True}
    response.raise_for_status.return_value = None
    with patch("proctoring.storage.remote_dispatcher.requests.post", return_value=response) as post:
        yield post


@pytest.mark.parametrize(("kind", "expected"), [
    ("session_start", "🎓 [Exam Started]\nCandidate: Amina Abai\nGroup: CS-101\nSession: session-test"),
    ("violation_alert", "⚠️ [Proctoring Alert] PHONE_RAISED\nCandidate: Amina Abai (CS-101)\nDuration: 1.25s\nTimestamp: 2026-10-07T12:30:00Z"),
    ("session_end", "✅ [Exam Finished]\nCandidate: Amina Abai (CS-101)\nTotal Violations: 2\nSession: session-test"),
])
def test_telegram_plain_text_templates(kind, expected):
    assert format_telegram_message(kind, payload()) == expected


def test_disabled_has_no_worker_no_http_and_no_queueing(mocked_http):
    with patch("proctoring.storage.remote_dispatcher.threading.Thread") as thread:
        dispatcher = RemoteDispatcher(remote_config(enabled=False))
        assert not dispatcher.enqueue("session_start", payload())
        dispatcher.close()
        dispatcher.close()
        thread.assert_not_called()
    mocked_http.assert_not_called()
    assert dispatcher.drain_warnings() == []


def test_queue_full_drops_without_waiting_for_network(mocked_http):
    entered, release = threading.Event(), threading.Event()
    response = mocked_http.return_value

    def hold_http(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return response

    mocked_http.side_effect = hold_http
    dispatcher = RemoteDispatcher(remote_config(max_queue_size=1))
    try:
        assert dispatcher.enqueue("session_start", payload())
        assert entered.wait(1)
        assert dispatcher.enqueue("violation_alert", payload())
        before = time.monotonic()
        assert not dispatcher.enqueue("session_end", payload())
        assert time.monotonic() - before < .5
        assert dispatcher.drain_warnings() == [{
            "type": "remote_dispatch_warning", "code": "queue_full",
            "dispatch_type": "session_end", "session_id": "session-test",
        }]
    finally:
        release.set()
        dispatcher.close()
    assert mocked_http.call_count == 2


def test_payload_is_copied_and_all_requests_run_off_caller_thread(mocked_http):
    entered, release = threading.Event(), threading.Event()
    threads = []
    response = mocked_http.return_value

    def hold_first(*args, **kwargs):
        threads.append(threading.current_thread())
        entered.set()
        assert release.wait(3)
        return response

    mocked_http.side_effect = hold_first
    dispatcher = RemoteDispatcher(remote_config())
    mutable = payload()
    try:
        dispatcher.enqueue("session_start", payload())
        assert entered.wait(1)
        dispatcher.enqueue("violation_alert", mutable)
        mutable["candidate"]["first_name"] = "CHANGED"
        mutable["event_type"] = "CHANGED"
    finally:
        release.set()
        dispatcher.close()
    assert all(thread is not threading.current_thread() and thread.daemon for thread in threads)
    assert "Amina Abai" in mocked_http.call_args.kwargs["json"]["text"]
    assert "PHONE_RAISED" in mocked_http.call_args.kwargs["json"]["text"]


@pytest.mark.parametrize(("error", "code"), [
    (requests.exceptions.Timeout("https://secret:token@example.org/"), "network_timeout"),
    (requests.exceptions.ConnectionError("test-secret-token"), "network_error"),
    (ValueError("unexpected error with test-secret-token"), "delivery_error"),
])
def test_errors_do_not_escape_and_next_delivery_continues(mocked_http, error, code, caplog):
    mocked_http.side_effect = [error, mocked_http.return_value]
    dispatcher = RemoteDispatcher(remote_config())
    dispatcher.enqueue("session_start", payload())
    dispatcher.enqueue("session_end", payload())
    dispatcher.close()
    assert mocked_http.call_count == 2
    warnings = dispatcher.drain_warnings()
    assert warnings[0]["code"] == code
    assert "test-secret-token" not in json.dumps(warnings) + caplog.text
    assert "secret:token" not in json.dumps(warnings) + caplog.text
    assert dispatcher.drain_warnings() == []


def test_telegram_failure_does_not_block_webhook_and_all_calls_have_timeout(mocked_http):
    response = mocked_http.return_value
    failure = requests.exceptions.HTTPError("token-in-url", response=response)
    response.status_code = 503
    success = Mock(spec=requests.Response, status_code=200)
    success.raise_for_status.return_value = None
    mocked_http.side_effect = [failure, success]
    dispatcher = RemoteDispatcher(remote_config(webhook_url="https://university.example/ingest",
                                               webhook_token="webhook-secret", upload_timeout_seconds=.6))
    dispatcher.enqueue("violation_alert", payload())
    dispatcher.close()
    assert mocked_http.call_count == 2
    webhook_call = mocked_http.call_args
    assert webhook_call.args == ("https://university.example/ingest",)
    assert webhook_call.kwargs["json"] == {**payload(), "type": "violation_alert"}
    assert webhook_call.kwargs["headers"] == {"Authorization": "Bearer webhook-secret"}
    assert all(call.kwargs["timeout"] == .6 and call.kwargs["allow_redirects"] is False
               for call in mocked_http.call_args_list)
    assert dispatcher.drain_warnings()[0]["http_status"] == 503


def test_jpeg_upload_for_telegram_and_webhook_is_closed_after_delivery(tmp_path, mocked_http):
    photo = tmp_path / "event.jpg"
    photo.write_bytes(b"test JPEG")
    opened = []
    response = mocked_http.return_value

    def inspect_request(*args, **kwargs):
        filename, handle, mime = kwargs["files"]["photo"]
        assert filename == "event.jpg"
        assert mime == "image/jpeg"
        assert handle.read() == b"test JPEG"
        opened.append(handle)
        return response

    mocked_http.side_effect = inspect_request
    dispatcher = RemoteDispatcher(remote_config(webhook_url="https://university.example/ingest"))
    dispatcher.enqueue("violation_alert", payload(), photo)
    dispatcher.close()
    telegram_call, webhook_call = mocked_http.call_args_list
    assert telegram_call.args[0].endswith("/sendPhoto")
    assert telegram_call.kwargs["data"]["caption"] == format_telegram_message("violation_alert", payload())
    assert json.loads(webhook_call.kwargs["data"]["payload"]) == {**payload(), "type": "violation_alert"}
    assert all(handle.closed for handle in opened)
    assert dispatcher.drain_warnings() == []


@pytest.mark.parametrize("path", [None, "missing.jpg", "wrong-format.png"])
def test_no_snapshot_falls_back_to_text_and_json(tmp_path, mocked_http, path):
    snapshot = tmp_path / path if path else None
    dispatcher = RemoteDispatcher(remote_config(webhook_url="https://university.example/ingest"))
    dispatcher.enqueue("violation_alert", payload(), snapshot)
    dispatcher.close()
    telegram_call, webhook_call = mocked_http.call_args_list
    assert telegram_call.args[0].endswith("/sendMessage")
    assert "PHONE_RAISED" in telegram_call.kwargs["json"]["text"]
    assert webhook_call.kwargs["json"]["type"] == "violation_alert"
    assert all("files" not in call.kwargs for call in mocked_http.call_args_list)
    assert len(dispatcher.drain_warnings()) == (2 if path else 0)


def test_snapshot_file_error_falls_back_without_exposing_path(mocked_http):
    with patch.object(Path, "open", side_effect=PermissionError("secret-full-path")):
        dispatcher = RemoteDispatcher(remote_config())
        dispatcher.enqueue("violation_alert", payload(), Path("evidence.jpg"))
        dispatcher.close()
    assert mocked_http.call_args.args[0].endswith("/sendMessage")
    warnings = dispatcher.drain_warnings()
    assert warnings[0]["code"] == "snapshot_unavailable"
    assert "secret-full-path" not in json.dumps(warnings)


def test_shutdown_is_bounded_and_drops_queued_work(mocked_http):
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    response = mocked_http.return_value

    def hold_http(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        completed.set()
        return response

    mocked_http.side_effect = hold_http
    dispatcher = RemoteDispatcher(remote_config(webhook_url="https://university.example/ingest"))
    try:
        dispatcher.enqueue("session_start", payload())
        assert entered.wait(1)
        dispatcher.enqueue("session_end", payload())
        before = time.monotonic()
        dispatcher.close(timeout=.02)
        dispatcher.close(timeout=2)
        assert time.monotonic() - before < .5
        warnings = dispatcher.drain_warnings()
        assert warnings == [{"type": "remote_dispatch_warning", "code": "shutdown_timeout", "dropped_count": 1}]
        assert not dispatcher.enqueue("session_start", payload())
    finally:
        release.set()
        assert completed.wait(1)
        dispatcher._thread.join(1)
    assert mocked_http.call_count == 1


def test_close_caps_requested_timeout_to_two_seconds():
    dispatcher = RemoteDispatcher(remote_config(enabled=False))
    fake_thread = Mock()
    fake_thread.is_alive.return_value = False
    dispatcher._thread = fake_thread
    dispatcher.close(timeout=999)
    fake_thread.join.assert_called_once_with(2.0)


def test_telegram_api_rejection_is_reported_without_response_secrets(mocked_http):
    mocked_http.return_value.json.return_value = {"ok": False, "description": "test-secret-token"}
    dispatcher = RemoteDispatcher(remote_config())
    dispatcher.enqueue("session_start", payload())
    dispatcher.close()
    warnings = dispatcher.drain_warnings()
    assert warnings[0]["code"] == "telegram_rejected"
    assert "test-secret-token" not in json.dumps(warnings)


def test_remote_redirect_is_not_followed(mocked_http):
    mocked_http.return_value.status_code = 302
    dispatcher = RemoteDispatcher(remote_config())
    dispatcher.enqueue("session_start", payload())
    dispatcher.close()
    assert mocked_http.call_args.kwargs["allow_redirects"] is False
    assert dispatcher.drain_warnings()[0]["http_status"] == 302


def test_webhook_only_never_calls_telegram(mocked_http):
    dispatcher = RemoteDispatcher(remote_config(telegram_enabled=False, webhook_url="https://university.example/ingest"))
    dispatcher.enqueue("session_start", payload(type="must-not-override-kind"))
    dispatcher.close()
    mocked_http.assert_called_once()
    assert mocked_http.call_args.args == ("https://university.example/ingest",)
    assert mocked_http.call_args.kwargs["json"]["type"] == "session_start"


def test_invalid_payload_and_unknown_kind_are_dropped(mocked_http):
    dispatcher = RemoteDispatcher(remote_config())
    assert not dispatcher.enqueue("unrecognized", payload())
    assert not dispatcher.enqueue("session_start", None)
    dispatcher.close()
    assert [warning["code"] for warning in dispatcher.drain_warnings()] == ["invalid_payload", "invalid_payload"]
    mocked_http.assert_not_called()
