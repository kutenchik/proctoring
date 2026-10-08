import json
from pathlib import Path
import re
import pytest
from proctoring.config import load_config, DEFAULT_CONFIG
from proctoring.domain import EventType


def _replace_setting(text: str, key: str, value: str) -> str:
    changed, count = re.subn(rf"^{re.escape(key)}\s*=.*$", lambda _: f"{key} = {value}",
                             text, flags=re.MULTILINE)
    assert count == 1, f"Expected one {key} setting in the test configuration"
    return changed


@pytest.fixture
def isolated_config_text():
    # The operator edits default.toml for the demo. Exercise the original
    # timing contract explicitly without rewriting that live configuration.
    text = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    for key, value in {"phone_visible": "1.0", "second_person": "1.0",
                       "phone_raised": "1.25", "gaze_deviation": "3.0",
                       "face_absent": "3.0", "clearing_seconds": "0.75",
                       "recovery_seconds": "15.0"}.items():
        text = _replace_setting(text, key, value)
    return _replace_setting(text, "quiz_path", json.dumps(str(load_config().quiz_path)))


def test_explicit_thresholds_and_paths(tmp_path, isolated_config_text):
    path = tmp_path / "configured.toml"
    path.write_text(isolated_config_text, encoding="utf-8")
    config = load_config(path)
    assert config.thresholds[EventType.PHONE_VISIBLE] == 1
    assert config.thresholds[EventType.SECOND_PERSON] == 1
    assert config.thresholds[EventType.PHONE_RAISED] == 1.25
    assert config.thresholds[EventType.GAZE_DOWN] == 3
    assert config.thresholds[EventType.FACE_ABSENT] == 3
    assert config.clearing_seconds == .75
    assert config.recovery_seconds == 15
    assert config.quiz_path.is_file()
    assert config.blocking_enabled is False
    assert "proctor_pin" not in str(config.public_dict())


@pytest.mark.parametrize("key,value", [
    ("phone_visible", "-1"),
    ("phone_visible", "nan"),
    ("phone_visible", "true"),
    ("blocking_enabled", "true"),
    ("proctor_pin", '"abc"'),
    ("proctor_pin", '"' + '1' * 65 + '"'),
    ("snapshots_enabled", '"true"'),
    ("synthetic_interval_ms", "3000"),
])
def test_invalid_config_fails_early(tmp_path: Path, isolated_config_text, key, value):
    path = tmp_path / "bad.toml"
    path.write_text(_replace_setting(isolated_config_text, key, value), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)

