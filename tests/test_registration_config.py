"""Registration and delivery configuration do not depend on Qt or HTTP."""
from dataclasses import FrozenInstanceError
import json
import re

import pytest

from proctoring.clock import FakeClock
from proctoring.config import DEFAULT_CONFIG, load_config
from proctoring.registration import CandidateInfo
from proctoring.session import SessionController
from proctoring.settings import RegistrationConfig, RemoteConfig


def configured(tmp_path, registration="enabled = true\nrequire_group = true", remote="enabled = false"):
    source = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    for section in ("exam.registration", "remote"):
        source = re.sub(rf"(?m)^\[{re.escape(section)}\]\s*\n[^\[]*", "", source)
    source += f"\n[exam.registration]\n{registration}\n\n[remote]\n{remote}\n"
    path = tmp_path / "registration.toml"
    path.write_text(source, encoding="utf-8")
    return load_config(path)


def test_registration_defaults_and_grouped_exam_api(tmp_path):
    config = configured(tmp_path)
    assert config.registration == RegistrationConfig(True, True)
    assert config.exam.registration is config.registration
    assert config.exam.duration_seconds == config.duration_seconds
    assert config.exam.quiz_path == config.quiz_path
    assert config.exam.external_url == config.external_url
    assert config.exam.allowed_domains == config.allowed_domains
    assert not config.remote.enabled
    assert config.remote.max_queue_size == 50
    assert config.remote.upload_timeout_seconds == 5.0


def test_registration_can_be_skipped_or_group_optional(tmp_path):
    config = configured(tmp_path, "enabled = false\nrequire_group = false")
    assert not config.registration.enabled
    assert not config.registration.require_group


def test_active_backends_are_parsed(tmp_path):
    config = configured(tmp_path, remote='''enabled = true
webhook_url = "https://example.edu/alerts?access=private-query"
webhook_token = "private-header"
telegram_enabled = true
telegram_bot_token = "private-bot-token"
telegram_chat_id = "-100123456789"
max_queue_size = 7
upload_timeout_seconds = 1.5''')
    assert config.remote.webhook_token == "private-header"
    assert config.remote.telegram_bot_token == "private-bot-token"
    assert config.remote.telegram_chat_id == "-100123456789"
    assert config.remote.max_queue_size == 7
    assert config.remote.upload_timeout_seconds == 1.5
    public = json.dumps(config.public_dict())
    diagnostic_repr = repr(config)
    for secret in ("private-query", "private-header", "private-bot-token"):
        assert secret not in public
        assert secret not in diagnostic_repr
    assert config.public_dict()["remote"]["webhook_host"] == "example.edu"


@pytest.mark.parametrize("field,value", [
    ("enabled", '"true"'), ("require_group", "1"), ("unknown", "true"),
])
def test_invalid_registration_config_is_rejected(tmp_path, field, value):
    with pytest.raises(ValueError, match="registration"):
        configured(tmp_path, f"{field} = {value}")


@pytest.mark.parametrize("source", [
    'enabled = "false"', 'telegram_enabled = 1', 'webhook_url = true',
    'webhook_token = 42', 'telegram_bot_token = false', 'telegram_chat_id = 123',
    'max_queue_size = 0', 'max_queue_size = -1', 'max_queue_size = true',
    'max_queue_size = 2.5', 'upload_timeout_seconds = 0',
    'upload_timeout_seconds = nan', 'upload_timeout_seconds = inf',
    'upload_timeout_seconds = true', 'upload_timeout_seconds = "5"',
    'webhook_url = "file:///tmp/alerts"', 'webhook_url = "https://"',
    'webhook_url = "https://user:secret@example.edu/alerts"',
    'webhook_url = "https://example.edu:99999/alerts"',
    'webhook_url = "https://exa mple.edu/alerts"',
    'webhook_token = "line\\nheader"', 'unknown = true',
    'enabled = true', 'enabled = true\ntelegram_enabled = true',
    'enabled = true\ntelegram_enabled = true\ntelegram_bot_token = "token"',
])
def test_invalid_remote_configuration_fails_without_echoing_credentials(tmp_path, source):
    with pytest.raises(ValueError, match="remote") as raised:
        configured(tmp_path, remote=source)
    assert "secret@example" not in str(raised.value)


def test_webhook_only_and_telegram_only_supported():
    webhook = RemoteConfig(enabled=True, webhook_url="http://localhost:8181/ingest")
    telegram = RemoteConfig(enabled=True, telegram_enabled=True,
                            telegram_bot_token="bot-token", telegram_chat_id="@exam")
    assert webhook.enabled and not webhook.telegram_enabled
    assert telegram.enabled and not telegram.webhook_url


def test_disabled_remote_allows_unconfigured_dormant_telegram():
    assert not RemoteConfig(telegram_enabled=True).enabled


def test_candidate_names_are_trimmed_unicode_and_immutable():
    source = {"first_name": "  Әлия  ", "last_name": "  Иванова  ", "group_id": "  К-42 "}
    candidate = CandidateInfo.from_dict(source)
    source["first_name"] = "Other"
    output = candidate.as_dict()
    assert output == {"first_name": "Әлия", "last_name": "Иванова", "group_id": "К-42"}
    output["last_name"] = "Other"
    assert candidate.last_name == "Иванова"
    with pytest.raises(FrozenInstanceError):
        candidate.first_name = "Other"


@pytest.mark.parametrize("field,value", [
    ("first_name", ""), ("last_name", "  "), ("group_id", "  "),
    ("first_name", 3), ("last_name", None), ("group_id", False),
    ("first_name", "A\nB"), ("last_name", "A\rB"), ("group_id", "A\x00B"),
    ("first_name", "a" * 101), ("last_name", "a" * 101), ("group_id", "a" * 129),
])
def test_invalid_candidate_is_rejected(field, value):
    candidate = {"first_name": "A", "last_name": "B", "group_id": "C"}
    candidate[field] = value
    with pytest.raises(ValueError, match="candidate"):
        CandidateInfo.from_dict(candidate)


def test_optional_group_requires_names():
    assert CandidateInfo.from_dict({"first_name": "A", "last_name": "B"},
                                   require_group=False).group_id == ""
    with pytest.raises(ValueError):
        CandidateInfo.from_dict({}, require_group=False)


@pytest.mark.parametrize("value", [None, [], "candidate"])
def test_candidate_requires_mapping(value):
    with pytest.raises(ValueError, match="mapping"):
        CandidateInfo.from_dict(value)


def test_session_keeps_candidate_fixed_without_changing_timer_logic():
    clock = FakeClock()
    session = SessionController(clock, duration_seconds=600)
    assert session.candidate is None
    session.set_candidate({"first_name": "A", "last_name": "B", "group_id": "C"})
    assert session.records == []
    assert session.elapsed_seconds == 0
    session.start()
    clock.advance(2)
    with pytest.raises(RuntimeError, match="cannot change"):
        session.set_candidate(CandidateInfo("D", "E", "F"))
    assert session.candidate.first_name == "A"
    assert session.elapsed_seconds == 2
    session.pause_by_proctor()
    clock.advance(3)
    assert session.elapsed_seconds == 2
    assert session.resume_by_proctor(True)
    session.end()
    with pytest.raises(RuntimeError):
        session.set_candidate(CandidateInfo("D", "E", "F"))


def test_session_optional_group_admission_is_explicit():
    session = SessionController(FakeClock(), duration_seconds=600)
    candidate = CandidateInfo("A", "B")
    with pytest.raises(ValueError, match="group_id"):
        session.set_candidate(candidate)
    assert session.candidate is None
    session.set_candidate(candidate, require_group=False)
    assert session.candidate == candidate
