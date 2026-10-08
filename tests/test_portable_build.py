from dataclasses import replace
import importlib.util
from pathlib import Path
import os
from types import SimpleNamespace
from unittest.mock import Mock
import tomllib

import pytest

from proctoring import desktop, runtime
from proctoring.config import load_config


def test_bundle_assets_and_external_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "resource_root", lambda: tmp_path / "embedded")
    assert runtime.asset_path("@bundle/models/face.task", tmp_path) == tmp_path / "embedded/models/face.task"
    assert runtime.asset_path("custom/face.task", tmp_path) == tmp_path / "custom/face.task"
    with pytest.raises(ValueError, match="inside the bundle"):
        runtime.asset_path("@bundle/../outside", tmp_path)


def test_frozen_locations_do_not_depend_on_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime.sys, "_MEIPASS", str(tmp_path / "extracted"), raising=False)
    monkeypatch.setattr(runtime.sys, "executable", str(tmp_path / "portable/LocalProctoring.exe"))
    assert runtime.application_dir() == tmp_path / "portable"
    assert runtime.resource_root() == tmp_path / "extracted"


def test_portable_config_preserves_preferences_and_only_relocates_assets(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("build_windows", root / "scripts/build_windows.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Autouse fixture disables all hardware/network; do not copy operator secrets.
    source_path = load_config.__defaults__[0]
    source = source_path.read_text(encoding="utf-8")
    portable = module.portable_config(source)
    before, after = tomllib.loads(source), tomllib.loads(portable)
    for section in ("remote", "audio", "events", "monitoring", "ui", "security", "reporting"):
        assert before[section] == after[section]
    config_path = tmp_path / "config.toml"
    config_path.write_text(portable, encoding="utf-8")
    config = load_config(config_path)
    assert config.quiz_path.is_file()
    assert config.vision.face_model == runtime.resource_root() / "models/face_landmarker.task"
    assert config.sessions_dir == tmp_path / "sessions"
    assert config.protection.validation_report == tmp_path / "artifacts/protection-validation.json"


def _protected(tmp_path):
    config = load_config()
    return replace(config, protection=replace(config.protection, enabled=True,
                   validation_report=tmp_path / "artifacts/audit.json"))


def test_audit_not_run_when_protection_disabled(monkeypatch):
    run = Mock()
    monkeypatch.setattr(desktop.subprocess, "run", run)
    desktop.ensure_recovery_audit(load_config())
    run.assert_not_called()


def test_current_audit_is_reused(tmp_path, monkeypatch):
    from proctoring.security import validation
    require = Mock(return_value={"passed": True})
    run = Mock()
    monkeypatch.setattr(validation, "require_recovery_validation", require)
    monkeypatch.setattr(desktop.subprocess, "run", run)
    desktop.ensure_recovery_audit(_protected(tmp_path))
    require.assert_called_once()
    run.assert_not_called()


def test_missing_audit_runs_independent_process_and_rechecks(tmp_path, monkeypatch):
    from proctoring.security import validation
    require = Mock(side_effect=[ValueError("missing"), {"passed": True}])
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="PASS native audit"))
    monkeypatch.setattr(validation, "require_recovery_validation", require)
    monkeypatch.setattr(desktop.subprocess, "run", run)
    desktop.ensure_recovery_audit(_protected(tmp_path))
    assert require.call_count == 2
    assert run.call_args.kwargs["timeout"] == 90
    assert (tmp_path / "artifacts/audit.log").read_text() == "PASS native audit"


def test_failed_audit_blocks_startup(tmp_path, monkeypatch):
    from proctoring.security import validation
    monkeypatch.setattr(validation, "require_recovery_validation", Mock(side_effect=ValueError("missing")))
    monkeypatch.setattr(desktop.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=1, stdout="FAIL")))
    with pytest.raises(RuntimeError, match="Recovery validation failed"):
        desktop.ensure_recovery_audit(_protected(tmp_path))


def test_config_cli_forms():
    assert desktop._config_argument(["--config", "custom.toml"]) == Path("custom.toml")
    assert desktop._config_argument(["--config=custom.toml"]) == Path("custom.toml")


def test_builder_does_not_inherit_unrelated_native_tools_on_path(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("build_windows", root / "scripts/build_windows.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("PATH", "C:/unrelated-poppler/Library/bin")
    environment = module.build_environment()
    assert "unrelated-poppler" not in environment["PATH"]
    assert str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32") in environment["PATH"]
    assert environment["PYINSTALLER_CONFIG_DIR"] == str(root / "build/pyinstaller-cache")
