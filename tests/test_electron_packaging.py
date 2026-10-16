import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


builder = module("scripts/build_electron_windows.py", "electron_builder")
entry = module("packaging/electron_backend_entry.py", "electron_backend_entry")


def test_public_templates_safe_and_resource_paths_are_explicit():
    text = (ROOT / "config/default.example.toml").read_text(encoding="utf-8")
    for protected in (False, True):
        data = tomllib.loads(builder.public_config(text, protected=protected))
        assert data["protection"]["enabled"] is protected
        assert data["exam"]["quiz_path"] == "@bundle/assets/quiz.json"
        assert data["vision"]["yolo_model"] == "@bundle/models/yolo11n.onnx"
        assert data["storage"]["sessions_dir"] == "sessions"
        assert data["protection"]["validation_report"] == "audits/startup-current.json"
        assert not data["remote"]["enabled"]
        assert not data["remote"]["telegram_bot_token"]


def test_public_builder_refuses_private_credentials():
    text = (ROOT / "config/default.example.toml").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="credentials"):
        builder.public_config(text.replace('telegram_bot_token = ""', 'telegram_bot_token = "not-a-real-token"'))


def test_lock_is_fully_pinned_and_retains_repository_numpy():
    pins = builder.read_pins(ROOT / "packaging/requirements-electron-build.lock")
    assert pins["numpy"] == "1.26.4"
    assert pins["PyInstaller"] == "6.22.3"
    assert pins["requests"] == "2.34.2"
    assert pins["websockets"] == "15.0.1"


def test_versioned_archive_keeps_complete_inspection_name(tmp_path):
    package = tmp_path / "LocalProctoring-Electron-0.4.0-stage3-UNVALIDATED"
    assert builder.archive_path(package).name == package.name + ".zip"


@pytest.mark.parametrize("mode,target", [("--desktop-bridge", "proctoring.desktop_bridge.__main__"),
                                       ("--desktop-supervisor", "proctoring.desktop_bridge.supervisor"),
                                       ("--electron-recovery-audit", "proctoring.security.electron_audit"),
                                       ("--electron-protected-test", "proctoring.security.electron_protected_test"),
                                       ("--protection-helper", "proctoring.security.helper"),
                                       ("--protection-guardian", "proctoring.security.guardian")])
def test_frozen_dispatch_routes_exact_arguments_before_other_entrypoints(monkeypatch, mode, target):
    child = Mock(return_value=13)
    monkeypatch.setitem(sys.modules, target, SimpleNamespace(main=child))
    assert entry.main([mode, "--config", "C:/Тест с пробелами/config.toml"]) == 13
    child.assert_called_once_with(["--config", "C:/Тест с пробелами/config.toml"])


def test_private_backend_does_not_fall_through_to_exam():
    assert entry.main([]) == 2
    assert entry.main(["--unknown"]) == 2


@pytest.mark.parametrize("relative", ["sessions/student/summary.json", "resources/default.toml", ".git/config", "glasses-fresh-with-validation.json"])
def test_final_inventory_rejects_private_payloads(tmp_path, relative):
    file = tmp_path / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("private", encoding="utf-8")
    with pytest.raises(ValueError):
        builder.inspect_files(tmp_path)


def test_inventory_and_runtime_manifest_use_relocation_safe_paths(tmp_path, monkeypatch):
    package = tmp_path / "Тест с пробелами"
    (package / "resources").mkdir(parents=True)
    (package / "LocalProctoring-Electron.exe").write_bytes(b"test-electron")
    (package / "resources/default.example.toml").write_text("# safe", encoding="utf-8")
    builder.write_manifests(package, {"numpy": "1.26.4"})
    manifest = json.loads((package / "resources/package-build.json").read_text())
    assert manifest == {"schema": 1, "build_kind": "packaged", "files": ["LocalProctoring-Electron.exe", "resources/default.example.toml"]}
    inventory = json.loads((package / "PACKAGE-INVENTORY.json").read_text())
    assert inventory["status"] == "UNVALIDATED"
    assert all(not Path(row["path"]).is_absolute() for row in inventory["files"])


def test_frontend_allowlist_rejects_unexpected_data(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "operator.json").write_text("{}")
    with pytest.raises(ValueError, match="Unexpected"):
        builder.copy_tree(source, tmp_path / "output", suffixes=builder.FRONTEND_SUFFIXES)


def test_electron_entrypoints_include_separately_loaded_audit_and_exclude_other_build_files(tmp_path):
    source, output = tmp_path / "build-electron", tmp_path / "output"
    source.mkdir()
    for filename in builder.ELECTRON_APP_FILES:
        (source / filename).write_text("// trusted generated code", encoding="utf-8")
    (source / "recovery-renderer.html").write_text('<script src="recovery-renderer.js"></script>', encoding="utf-8")
    (source / "private-audit-results.json").write_text("{}", encoding="utf-8")
    builder.copy_electron_entrypoints(source, output)
    assert (output / "recovery-renderer.html").is_file()
    assert (output / "recovery-renderer.js").is_file()
    assert not (output / "private-audit-results.json").exists()
    manifest = builder.inspect_files(output)
    assert len(manifest) == len(builder.ELECTRON_APP_FILES)


def test_missing_audit_renderer_aborts_packaging(tmp_path):
    source = tmp_path / "build-electron"
    source.mkdir()
    (source / "main.cjs").write_text("// main", encoding="utf-8")
    (source / "preload.cjs").write_text("// preload", encoding="utf-8")
    with pytest.raises(ValueError, match="recovery-renderer"):
        builder.copy_electron_entrypoints(source, tmp_path / "output")


@pytest.mark.parametrize("frozen", [False, True])
def test_public_bundle_config_resolves_assets_without_relocating_writable_paths(tmp_path, monkeypatch, frozen):
    from proctoring.config import load_config
    from proctoring import runtime
    bundle = tmp_path / "Приложение с пробелами" / "resources/backend/_internal"
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    else:
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        bundle = ROOT
    settings = tmp_path / "Настройки пользователя" / "config.toml"
    settings.parent.mkdir()
    settings.write_text(builder.public_config((ROOT / "config/default.example.toml").read_text(encoding="utf-8")), encoding="utf-8")
    config = load_config(settings)
    assert runtime.resource_root() == bundle.resolve()
    assert config.quiz_path == bundle / "assets/quiz.json"
    assert config.vision.yolo_model == bundle / "models/yolo11n.onnx"
    assert config.vision.face_model == bundle / "models/face_landmarker.task"
    assert config.sessions_dir == settings.parent / "sessions"
    assert config.protection.validation_report == settings.parent / "audits/startup-current.json"


@pytest.mark.parametrize("resource", ["", "../outside", "models/../../outside", "models/../quiz.json",
                                    r"..\outside", "/absolute", "C:/outside", r"C:\outside",
                                    r"\\server\share\model", "models/model:stream"])
def test_bundle_resource_rejects_traversal_or_anchored_path(tmp_path, resource):
    from proctoring.runtime import asset_path
    with pytest.raises(ValueError, match="Bundled asset path"):
        asset_path("@bundle/" + resource, tmp_path)


def test_existing_ordinary_relative_asset_semantics_are_unchanged(tmp_path):
    from proctoring.runtime import asset_path
    config_dir = tmp_path / "Настройки" / "config"
    assert asset_path("../models/face.task", config_dir) == (config_dir.parent / "models/face.task").resolve()
