import json
import re
import tomllib

import pytest

from proctoring.config import DEFAULT_CONFIG, load_config


def write_config(tmp_path, url="", domains=()):
    source = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    source = re.sub(r"^external_url\s*=.*$", lambda _match: f"external_url = {json.dumps(url)}",
                    source, flags=re.MULTILINE)
    source = re.sub(r"^allowed_domains\s*=.*$", lambda _match: f"allowed_domains = {json.dumps(list(domains))}",
                    source, flags=re.MULTILINE)
    path = tmp_path / "browser.toml"
    path.write_text(source, encoding="utf-8")
    return path


@pytest.mark.parametrize("url", ["", "   "])
def test_empty_url_preserves_native_quiz_mode(tmp_path, url):
    config = load_config(write_config(tmp_path, url))
    assert config.external_url == ""
    assert config.allowed_domains == ()
    assert config.external_exam is False
    assert config.public_dict()["exam_mode"] == "native"


def test_missing_url_fields_preserve_existing_configuration(tmp_path):
    path = write_config(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace('external_url = ""', "")
                    .replace("allowed_domains = []", ""), encoding="utf-8")
    config = load_config(path)
    assert config.external_url == ""
    assert config.allowed_domains == ()
    assert not config.external_exam


def test_none_url_from_configuration_provider_means_native(monkeypatch):
    data = tomllib.loads(DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8"))
    data["exam"]["external_url"] = None
    monkeypatch.setattr("proctoring.config.tomllib.load", lambda _handle: data)
    assert not load_config().external_exam


def test_valid_url_enables_external_mode_and_defaults_to_origin_host(tmp_path):
    config = load_config(write_config(tmp_path, "https://LMS.example.edu/exam?access_token=secret#q2"))
    assert config.external_exam
    assert config.external_url == "https://lms.example.edu/exam?access_token=secret#q2"
    assert config.allowed_domains == ("lms.example.edu",)
    public = config.public_dict()
    assert public["exam_mode"] == "external"
    assert public["allowed_domains"] == ["lms.example.edu"]
    assert "secret" not in str(public)
    assert "access_token" not in str(public)


def test_explicit_domains_are_normalized_and_deduplicated(tmp_path):
    config = load_config(write_config(tmp_path, "https://lms.example.edu/", [
        "LMS.EXAMPLE.EDU", "login.example.edu", "lms.example.edu.",
    ]))
    assert config.allowed_domains == ("lms.example.edu", "login.example.edu")


def test_native_config_can_retain_domains_for_later_url_configuration(tmp_path):
    config = load_config(write_config(tmp_path, "", ["LOCALHOST", "lms.example.edu"]))
    assert not config.external_exam
    assert config.allowed_domains == ("localhost", "lms.example.edu")


@pytest.mark.parametrize("field,value", [
    ("external_url", False), ("external_url", 0), ("external_url", []),
    ("external_url", "file:///exam.html"),
    ("external_url", "https://student:secret@lms.example.edu/"),
    ("allowed_domains", "lms.example.edu"), ("allowed_domains", [42]),
    ("allowed_domains", ["*.example.edu"]),
])
def test_bad_external_exam_fields_fail_early(monkeypatch, field, value):
    data = tomllib.loads(DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8"))
    data["exam"][field] = value
    monkeypatch.setattr("proctoring.config.tomllib.load", lambda _handle: data)
    with pytest.raises(ValueError):
        load_config()


def test_explicit_allowlist_must_include_initial_exam_host(tmp_path):
    with pytest.raises(ValueError, match="must include"):
        load_config(write_config(tmp_path, "https://lms.example.edu/", ["other.example.edu"]))
