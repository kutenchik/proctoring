import json
import math

import pytest

from proctoring.clock import FakeClock
from proctoring.storage import SessionStore


def test_unique_sessions_and_human_readable_metadata(tmp_path):
    clock = FakeClock()
    with SessionStore(tmp_path, clock) as first, SessionStore(tmp_path, clock) as second:
        assert first.path != second.path
        metadata = json.loads((first.path / "session.json").read_text(encoding="utf-8"))
        assert metadata["created_at"] == clock.wall_time()
        assert metadata["session_id"] == first.path.name


def test_append_flushes_valid_unicode_records_before_close(tmp_path):
    with SessionStore(tmp_path, FakeClock()) as store:
        records = [
            {"event_type": "phone_raised", "message": "Phone raised — possible screen capture attempt."},
            {"event_type": "phone_raised", "duration": 1.25, "confidence": 0.9},
        ]
        for record in records:
            store.append(record)
        raw = (store.path / "events.jsonl").read_text(encoding="utf-8")
        assert "—" in raw
        assert [json.loads(line) for line in raw.splitlines()] == records


def test_invalid_record_does_not_corrupt_previous_journal(tmp_path):
    with SessionStore(tmp_path, FakeClock()) as store:
        store.append({"sequence": 1})
        with pytest.raises(ValueError):
            store.append({"confidence": math.nan})
        store.append({"sequence": 2})
        lines = (store.path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["sequence"] for line in lines] == [1, 2]


def test_configuration_secrets_redacted_without_mutating_input(tmp_path):
    config = {"security": {"proctor_pin": "0246", "blocking_enabled": False},
              "nested": [{"PIN": "1234"}], "thresholds": {"phone_visible": 1.0}}
    with SessionStore(tmp_path, FakeClock()) as store:
        store.save_config(config)
        saved = json.loads((store.path / "config.json").read_text(encoding="utf-8"))
    assert saved["security"]["proctor_pin"] == "[REDACTED]"
    assert saved["nested"][0]["PIN"] == "[REDACTED]"
    assert saved["thresholds"]["phone_visible"] == 1.0
    assert saved["security"]["blocking_enabled"] is False
    assert config["security"]["proctor_pin"] == "0246"


def test_final_summary_is_replaced_atomically_and_failed_replace_preserves_previous(tmp_path, monkeypatch):
    with SessionStore(tmp_path, FakeClock()) as store:
        store.finalize({"event_count": 1})
        import proctoring.storage.session_store as module

        def fail_replace(source, destination):
            # Old summary remains readable up until the atomic replacement.
            assert json.loads(destination.read_text(encoding="utf-8"))["event_count"] == 1
            raise OSError("simulated write failure")

        monkeypatch.setattr(module.os, "replace", fail_replace)
        with pytest.raises(OSError, match="simulated write failure"):
            store.finalize({"event_count": 2})
        assert json.loads((store.path / "summary.json").read_text(encoding="utf-8")) == {"event_count": 1}
        assert not list(store.path.glob("*.tmp"))
        assert not list(store.path.glob(".*.tmp"))


def test_close_idempotent_and_rejects_writes(tmp_path):
    store = SessionStore(tmp_path, FakeClock())
    store.close()
    store.close()
    with pytest.raises(RuntimeError, match="closed"):
        store.append({"type": "late"})
    with pytest.raises(RuntimeError, match="closed"):
        store.finalize({})
    with pytest.raises(RuntimeError, match="closed"):
        store.save_config({})


def test_underlying_close_error_is_reported_once_and_store_stays_closed(tmp_path):
    store = SessionStore(tmp_path, FakeClock())
    journal = store._journal

    class FailingClose:
        calls = 0

        def close(self):
            self.calls += 1
            journal.close()
            raise OSError("simulated final flush failure")

    broken = FailingClose()
    store._journal = broken
    with pytest.raises(OSError, match="final flush failure"):
        store.close()
    assert journal.closed
    store.close()
    assert broken.calls == 1
    with pytest.raises(RuntimeError, match="closed"):
        store.append({"event_type": "late"})
    with pytest.raises(RuntimeError, match="closed"):
        store.finalize({})
    with pytest.raises(RuntimeError, match="closed"):
        store.save_config({})
