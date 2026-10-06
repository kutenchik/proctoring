from pathlib import Path
import pytest
from proctoring.config import load_config, DEFAULT_CONFIG
from proctoring.domain import EventType


def test_default_thresholds_and_paths():
    config = load_config()
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


@pytest.mark.parametrize("old,new", [
    ("phone_visible = 1.0", "phone_visible = -1"),
    ("phone_visible = 1.0", "phone_visible = nan"),
    ("phone_visible = 1.0", "phone_visible = true"),
    ("blocking_enabled = false", "blocking_enabled = true"),
    ('proctor_pin = "2468"', 'proctor_pin = "abc"'),
    ('proctor_pin = "2468"', 'proctor_pin = "' + '1' * 65 + '"'),
    ("snapshots_enabled = true", 'snapshots_enabled = "true"'),
    ("synthetic_interval_ms = 100", "synthetic_interval_ms = 3000"),
])
def test_invalid_config_fails_early(tmp_path: Path, old, new):
    path = tmp_path / "bad.toml"
    path.write_text(DEFAULT_CONFIG.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)

