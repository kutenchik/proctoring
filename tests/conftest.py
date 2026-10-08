"""Keep automated tests independent of the operator's live demo preferences."""
import json
import re

import pytest

from proctoring.config import DEFAULT_CONFIG, load_config
from proctoring import i18n


def _replace_line(source: str, key: str, value: str) -> str:
    changed, count = re.subn(rf"^{re.escape(key)}\s*=.*$", lambda _match: f"{key} = {value}",
                             source, flags=re.MULTILINE)
    if count != 1:
        raise AssertionError(f"Expected exactly one {key!r} configuration line, found {count}")
    return changed


@pytest.fixture(scope="session", autouse=True)
def isolated_default_config(tmp_path_factory):
    """Only no-argument load_config() calls use a temporary native/en config.

    Browser tests continue to pass explicit URLs/config paths. Resolving paths
    before relocating the copied TOML preserves the real asset/model locations.
    This never edits the operator's external URL, locale, or other preferences.
    """
    import tomllib

    source = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    values = tomllib.loads(source)
    source = _replace_line(source, "external_url", '""')
    source = _replace_line(source, "language", '"en"')
    # Lifecycle/UI fixtures use this test-only PIN, independently of examples.
    source = _replace_line(source, "proctor_pin", '"2468"')
    # Lifecycle tests exercise the native exam directly. Feature tests opt in
    # explicitly; operator settings must not open hardware, arm restrictions,
    # or start uploads while an unrelated test is running.
    disabled_options = {
        "[exam.registration]": {"enabled"},
        "[remote]": {"enabled", "telegram_enabled"},
        "[protection]": {"enabled"},
        "[security.system_checks]": {"block_multimonitor", "clipboard_guard_enabled", "vm_check_enabled"},
        "[exam.identity]": {"selfie_verification_enabled"},
        "[audio]": {"enabled"},
        "[vision.accessories]": {"earphone_detection_enabled"},
        "[reporting]": {"generate_pdf_report", "send_pdf_to_telegram"},
    }
    lines = source.splitlines()
    section = ""
    for index, line in enumerate(lines):
        if line.strip().startswith("["):
            section = line.strip()
        else:
            setting = re.match(r"(\w+)\s*=", line.strip())
            if setting and setting[1] in disabled_options.get(section, set()):
                lines[index] = f"{setting[1]} = false"
    source = "\n".join(lines) + "\n"
    for section, key in (
        ("exam", "quiz_path"), ("storage", "sessions_dir"),
        ("vision", "yolo_model"), ("vision", "face_model"),
        ("protection", "validation_report"),
    ):
        value = str((DEFAULT_CONFIG.parent / values[section][key]).resolve())
        source = _replace_line(source, key, json.dumps(value))
    isolated_path = tmp_path_factory.mktemp("native-test-config") / "default.toml"
    isolated_path.write_text(source, encoding="utf-8")
    previous_defaults = load_config.__defaults__
    load_config.__defaults__ = (isolated_path,)
    try:
        yield isolated_path
    finally:
        load_config.__defaults__ = previous_defaults


@pytest.fixture(autouse=True)
def isolated_ui_language():
    """A locale-switch test must not change expectations in unrelated tests."""
    i18n.set_language("en")
    yield
    i18n.set_language("en")
