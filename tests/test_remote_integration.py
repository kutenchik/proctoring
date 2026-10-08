"""Local evidence stays authoritative when optional remote delivery fails."""
from dataclasses import replace
import json
import threading
import time
from unittest.mock import Mock, patch

import numpy as np
import pytest
import requests

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType
from proctoring.settings import RegistrationConfig, RemoteConfig
from test_controller_camera import QueuedMonitor


CANDIDATE = {"first_name": "Әмина", "last_name": "Иванова", "group_id": "CS-101"}


@pytest.fixture(autouse=True)
def remote_http():
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {"ok": True}
    response.raise_for_status.return_value = None
    with patch("proctoring.storage.remote_dispatcher.requests.post", return_value=response) as post:
        yield post


@pytest.fixture
def make_controller(tmp_path):
    controllers = []

    def make(*, camera=False, enabled=True, telegram=False, snapshots=True):
        config = replace(load_config(), sessions_dir=tmp_path / "sessions",
                         registration=RegistrationConfig(enabled=True),
                         snapshots_enabled=snapshots,
                         remote=RemoteConfig(enabled=enabled,
                                             webhook_url="https://university.example/events" if not telegram else "",
                                             telegram_enabled=telegram,
                                             telegram_bot_token="test-bot-secret" if telegram else "",
                                             telegram_chat_id="-123" if telegram else ""))
        clock = FakeClock()
        monitor = QueuedMonitor() if camera else None
        app = AppController(config, clock, mode="camera" if camera else "synthetic", monitor=monitor)
        app.register_candidate(dict(CANDIDATE))
        controllers.append(app)
        if camera:
            app.prepare_monitoring()
            monitor.publish(clock.monotonic())
        return clock, app

    yield make
    for app in controllers:
        if app.session.started and not app.session.ended:
            app.end("test_cleanup")
        app.close_remote()


def activate_phone(clock, app, *, frame=None):
    if app.mode == "synthetic":
        app.monitor.set_condition(EventType.PHONE_VISIBLE, True)
    duration = app.config.thresholds[EventType.PHONE_VISIBLE]
    for _ in range(int(duration / .1) + 3):
        clock.advance(.1)
        if app.mode == "camera":
            app.monitor.publish(clock.monotonic(), phone_visible=True, phone_confidence=.9, frame=frame)
        app.step()
    assert len(app.events.events) == 1
    assert app.events.events[0]["state"] == "active"


def records(app, filename="events.jsonl"):
    return [json.loads(line) for line in (app.store.path / filename).read_text(encoding="utf-8").splitlines()]


def test_registered_identity_persists_in_session_journal_and_summary(make_controller):
    clock, app = make_controller(enabled=False)
    app.start()
    activate_phone(clock, app)
    app.pause("2468")
    app.resume("2468")
    app.end()
    metadata = json.loads((app.store.path / "session.json").read_text(encoding="utf-8"))
    journal = records(app)
    summary = json.loads((app.store.path / "summary.json").read_text(encoding="utf-8"))
    assert metadata["candidate"] == CANDIDATE
    assert journal[0]["record_kind"] == "session_header"
    assert all(record["candidate"] == CANDIDATE for record in journal)
    assert {record["session_id"] for record in journal} == {metadata["session_id"]}
    assert summary["candidate"] == CANDIDATE
    assert summary["session_id"] == metadata["session_id"]
    assert summary["events"][0]["event_type"] == "phone_visible"
    with pytest.raises(RuntimeError, match="cannot change"):
        app.register_candidate({**CANDIDATE, "first_name": "Changed"})


def test_controller_remote_disabled_creates_no_network_thread(make_controller, remote_http):
    with patch("proctoring.storage.remote_dispatcher.threading.Thread") as thread:
        clock, app = make_controller(enabled=False)
        app.start()
        activate_phone(clock, app)
        app.end()
        app.close_remote()
        thread.assert_not_called()
    assert app.remote is None
    remote_http.assert_not_called()


def test_remote_sequence_sends_one_alert_for_sustained_event(make_controller, remote_http):
    clock, app = make_controller()
    app.start()
    activate_phone(clock, app)
    for _ in range(8):
        clock.advance(.25)
        app.step()
    assert app.session.running and not app.session.pause_reasons
    app.end()
    app.end()  # Final summary and remote end are idempotent.
    app.close_remote()
    messages = [call.kwargs["json"] for call in remote_http.call_args_list]
    assert [message["type"] for message in messages] == ["session_start", "violation_alert", "session_end"]
    assert all(message["candidate"] == CANDIDATE for message in messages)
    assert all(message["session_id"] == app.store.path.name for message in messages)
    assert messages[1]["event_type"] == "phone_visible"
    assert messages[1]["duration_seconds"] >= app.config.thresholds[EventType.PHONE_VISIBLE]
    assert messages[-1]["total_events"] == 1
    assert sum(record.get("action") == "activated" for record in records(app)) == 1


def test_photo_alert_waits_until_jpeg_is_atomically_saved(make_controller, remote_http, monkeypatch):
    import cv2

    clock, app = make_controller(camera=True, telegram=True)
    entered, release = threading.Event(), threading.Event()
    original_encode = cv2.imencode

    def hold_encode(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original_encode(*args, **kwargs)

    monkeypatch.setattr(cv2, "imencode", hold_encode)
    photo_seen = threading.Event()
    original_response = remote_http.return_value

    def inspect_upload(url, **kwargs):
        if url.endswith("/sendPhoto"):
            filename, handle, mime = kwargs["files"]["photo"]
            assert filename.endswith(".jpg") and mime == "image/jpeg"
            data = handle.read()
            decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            assert decoded.shape == (24, 32, 3)
            assert not list(app.store.path.rglob("*.partial"))
            photo_seen.set()
        return original_response

    remote_http.side_effect = inspect_upload
    app.start()
    try:
        activate_phone(clock, app, frame=np.full((24, 32, 3), 120, dtype=np.uint8))
        assert entered.wait(1)
        assert len(app._pending_remote_alerts) == 1
        assert not photo_seen.is_set()
        assert app.session.running
        assert not list(app.store.path.rglob("*.jpg"))
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while not photo_seen.is_set() and time.monotonic() < deadline:
        app.step()
        photo_seen.wait(.01)
    assert photo_seen.is_set()
    assert app.session.running and app.summary is None
    app.end()
    app.close_remote()
    assert photo_seen.is_set()
    assert len([call for call in remote_http.call_args_list if call.args[0].endswith("/sendPhoto")]) == 1
    assert app._pending_remote_alerts == {}
    assert app.summary["events"][0]["snapshot_path"].endswith(".jpg")


@pytest.mark.parametrize("failure", ["encoding", "enqueue", "missing_frame", "disabled"])
def test_snapshot_failure_falls_back_to_alert_text(make_controller, remote_http, monkeypatch, failure):
    import cv2

    clock, app = make_controller(camera=True, telegram=True, snapshots=failure != "disabled")
    app.start()
    frame = np.zeros((24, 32, 3), dtype=np.uint8)
    if failure == "encoding":
        monkeypatch.setattr(cv2, "imencode", lambda *args, **kwargs: (False, None))
    elif failure == "enqueue":
        monkeypatch.setattr(app.store, "enqueue_snapshot", Mock(side_effect=RuntimeError("snapshot queue full")))
    elif failure == "missing_frame":
        frame = None
    activate_phone(clock, app, frame=frame)
    assert app.session.running and app.session.monitoring_healthy
    app.end()
    app.close_remote()
    assert remote_http.call_count == 3
    assert all(call.args[0].endswith("/sendMessage") for call in remote_http.call_args_list)
    text = remote_http.call_args_list[1].kwargs["json"]["text"]
    assert "PHONE_VISIBLE" in text and CANDIDATE["first_name"] in text
    assert app.summary["events"][0]["snapshot_path"] is None
    assert sum(record.get("action") == "activated" for record in records(app)) == 1


@pytest.mark.parametrize("failure", ["network", "enqueue"])
def test_remote_failure_never_pauses_or_prevents_local_evidence(make_controller, remote_http, monkeypatch, failure):
    clock, app = make_controller()
    if failure == "network":
        remote_http.side_effect = requests.exceptions.Timeout("URL with test-bot-secret")
    else:
        monkeypatch.setattr(app.remote, "enqueue", Mock(side_effect=RuntimeError("test-bot-secret")))
    app.start()
    activate_phone(clock, app)
    clock.advance(.5)
    app.step()
    assert app.session.running and app.session.monitoring_healthy
    assert not app.session.pause_reasons
    assert app.session.elapsed_seconds > .5
    app.end()
    app.close_remote()
    assert app.summary["event_count"] == 1
    assert (app.store.path / "summary.json").exists()
    assert sum(record.get("action") == "activated" for record in records(app)) == 1
    warnings = records(app, "remote_warnings.jsonl")
    assert warnings
    assert "test-bot-secret" not in json.dumps(warnings)
    assert not any(record.get("event_type") == "monitoring_failed" for record in records(app))


def test_shutdown_warning_is_saved_after_final_summary_and_journal_close(make_controller, remote_http):
    entered, release = threading.Event(), threading.Event()
    original_response = remote_http.return_value

    def hold_http(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original_response

    remote_http.side_effect = hold_http
    clock, app = make_controller()
    try:
        app.start()
        assert entered.wait(1)
        activate_phone(clock, app)
        app.end()
        assert app.store._closed
        before = time.monotonic()
        app.close_remote(timeout=.02)
        assert time.monotonic() - before < .5
        assert (app.store.path / "summary.json").exists()
        warnings = records(app, "remote_warnings.jsonl")
        assert warnings[-1]["code"] == "shutdown_timeout"
        assert warnings[-1]["dropped_count"] == 2
        assert "timestamp" in warnings[-1]
    finally:
        release.set()
        app.remote._thread.join(1)
