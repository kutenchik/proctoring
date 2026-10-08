"""Build exactly two distributable files: LocalProctoring.exe and config.toml.

Config is copied from protected-demo.toml without printing credentials. It is
never embedded into the executable. Existing distribution config is preserved
unless --replace-config is explicitly supplied.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build_environment() -> dict[str, str]:
    """Do not bundle unrelated DLLs from tools injected into the caller's PATH.

    In particular, Qt imports Windows' unversioned ICU API. A Poppler ICU DLL
    with the same basename exports a different API and must never shadow it.
    """
    import PySide6
    import shiboken6
    environment = dict(os.environ)
    windows = Path(environment.get("SystemRoot", r"C:\Windows"))
    environment["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs",
        windows / "System32", windows,
        Path(PySide6.__file__).parent, Path(shiboken6.__file__).parent,
    )))
    environment["PYINSTALLER_CONFIG_DIR"] = str(ROOT / "build/pyinstaller-cache")
    return environment


def portable_config(text: str) -> str:
    replacements = {
        ("exam", "quiz_path"): '"@bundle/assets/quiz.json"',
        ("vision", "yolo_model"): '"@bundle/models/yolo11n.onnx"',
        ("vision", "face_model"): '"@bundle/models/face_landmarker.task"',
        ("storage", "sessions_dir"): '"sessions"',
        ("protection", "validation_report"): '"artifacts/protection-validation.json"',
    }
    section = ""
    lines = []
    seen = set()
    for line in text.splitlines():
        match = re.match(r"\s*\[([^\]]+)\]\s*(?:#.*)?$", line)
        if match:
            section = match[1]
        setting = re.match(r"\s*([\w_]+)\s*=", line)
        if setting and (section, setting[1]) in replacements:
            key = section, setting[1]
            line = f"{setting[1]} = {replacements[key]}"
            seen.add(key)
        lines.append(line)
    missing = set(replacements) - seen
    if missing:
        raise ValueError(f"Protected config is missing portable path settings: {sorted(missing)}")
    return ("# Portable Local Proctoring. Edit this file, then restart the EXE.\n"
            "# @bundle/ selects built-in assets; ordinary paths are relative to this file.\n"
            "# Sessions and audit results are created beside this file at runtime.\n"
            "# This file retains your local settings and secrets. Share only with intended operators.\n"
            + "\n".join(lines) + "\n")


def build_metadata(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name in ("pyinstaller", "pyinstaller-hooks-contrib", "PySide6-Essentials",
                 "PySide6-Addons", "shiboken6", "numpy", "opencv-contrib-python",
                 "onnxruntime", "mediapipe", "sounddevice", "psutil", "requests"):
        distribution = importlib.metadata.distribution(name)
        versions[name] = distribution.version
        for file in distribution.files or []:
            if any(token in str(file).lower() for token in ("license", "copying", "notice")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    # Keep package-relative layout; same-named notices must not overwrite.
                    target = destination / "licenses" / name / str(file).replace("..", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    (destination / "versions.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace-config", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Build this Windows executable on Windows")
    output = ROOT / "dist/LocalProctoring"
    output.mkdir(parents=True, exist_ok=True)
    build_metadata(ROOT / "build/portable/metadata")
    for model in ("yolo11n.onnx", "face_landmarker.task"):
        if not (ROOT / "models" / model).is_file():
            parser.error(f"Local model missing: models/{model}")
    config = portable_config((ROOT / "config/protected-demo.toml").read_text(encoding="utf-8-sig"))
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(output), "--workpath", str(ROOT / "build/pyinstaller"),
        str(ROOT / "packaging/LocalProctoring.spec"),
    ], cwd=ROOT, env=build_environment(), check=True)
    config_path = output / "config.toml"
    if args.replace_config or not config_path.exists():
        config_path.write_text(config, encoding="utf-8")
    print(f"Built: {output / 'LocalProctoring.exe'}")
    print(f"Editable config: {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
