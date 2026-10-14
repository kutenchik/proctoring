"""Build a separate UNVALIDATED Windows x64 inspection folder/ZIP.

Run with build/electron-package-venv/Scripts/python.exe after installing
packaging/requirements-electron-build.lock. No app is launched, hardware opened,
audit installed, protection enabled or legacy output replaced by this command.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ELECTRON_FILES = (
    "electron.exe", "chrome_100_percent.pak", "chrome_200_percent.pak",
    "d3dcompiler_47.dll", "dxcompiler.dll", "dxil.dll", "ffmpeg.dll", "icudtl.dat",
    "LICENSE", "LICENSES.chromium.html", "resources.pak", "snapshot_blob.bin",
    "v8_context_snapshot.bin", "version", "vk_swiftshader_icd.json",
    "vk_swiftshader.dll", "vulkan-1.dll",
)
ELECTRON_APP_FILES = (
    "main.cjs", "preload.cjs", "recovery-renderer.js", "recovery-renderer.html",
)
MODEL_HASHES = {
    "yolo11n.onnx": "7d8fd1717d9d5bbab6986cd134afb620649c7a394303d55b1e09fc00804cc5c1",
    "face_landmarker.task": "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
}
DENIED_PARTS = {".git", ".venv", "node_modules", "sessions", "artifacts", "cookies", "__pycache__", "brag-output"}
FRONTEND_SUFFIXES = {".html", ".js", ".css", ".woff2", ".woff", ".svg", ".txt"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_path(package: Path) -> Path:
    # Version dots belong to the directory name, not a replaceable suffix.
    return package.with_name(package.name + ".zip")


def read_pins(path: Path) -> dict[str, str]:
    pins = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            pins.update(read_pins((path.parent / line[3:].strip()).resolve()))
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)", line)
        if not match:
            raise ValueError(f"Unpinned build requirement: {line}")
        pins[match[1]] = match[2]
    return pins


def require_environment() -> dict[str, str]:
    pins = read_pins(ROOT / "packaging/requirements-electron-build.lock")
    mismatches = []
    for name, expected in pins.items():
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            actual = "missing"
        if actual != expected:
            mismatches.append(f"{name}: expected {expected}, installed {actual}")
    if mismatches:
        raise ValueError("Use the isolated locked build environment:\n" + "\n".join(mismatches))
    return pins


def public_config(text: str, *, protected: bool = False) -> str:
    """Transform only reviewed public templates, never local/private TOML."""
    data = tomllib.loads(text)
    remote = data["remote"]
    if remote["enabled"] or remote["telegram_enabled"] or any(remote[key] for key in
        ("webhook_url", "webhook_token", "telegram_bot_token", "telegram_chat_id")):
        raise ValueError("Public template must have remote delivery disabled and blank credentials")
    if data["exam"].get("external_url") or data["security"]["proctor_pin"] != "739261":
        raise ValueError("Public template must use the empty external URL and documented demo PIN")
    if data["security"]["blocking_enabled"] or data["reporting"]["send_pdf_to_telegram"]:
        raise ValueError("Public template must not enable legacy blocking or remote reports")
    replacements = {
        ("exam", "quiz_path"): '"@bundle/assets/quiz.json"',
        ("vision", "yolo_model"): '"@bundle/models/yolo11n.onnx"',
        ("vision", "face_model"): '"@bundle/models/face_landmarker.task"',
        ("storage", "sessions_dir"): '"sessions"',
        ("protection", "validation_report"): '"audits/electron-recovery.json"',
        ("protection", "enabled"): "true" if protected else "false",
    }
    section = ""; seen = set(); lines = []
    for line in text.splitlines():
        header = re.match(r"\s*\[([^\]]+)\]", line)
        if header:
            section = header[1]
        field = re.match(r"\s*(\w+)\s*=", line)
        key = (section, field[1]) if field else None
        if key in replacements:
            line = f"{key[1]} = {replacements[key]}"; seen.add(key)
        lines.append(line)
    if seen != set(replacements):
        raise ValueError("Public template missing required resource/storage paths")
    return ("# Electron package PUBLIC template. Protection requires a current packaged-runtime audit.\n"
            "# Default launch copies the safe template to the per-user configuration directory.\n"
            "# @bundle assets are immutable backend resources; ordinary paths resolve beside this TOML.\n"
            + "\n".join(lines) + "\n")


def copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Expected regular allowlisted file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path, *, suffixes: set[str] | None = None) -> None:
    for entry in sorted(source.rglob("*")):
        relative = entry.relative_to(source)
        if entry.is_symlink() or not entry.resolve().is_relative_to(source.resolve()):
            raise ValueError(f"Symlink not permitted in package input: {relative}")
        if not entry.is_file():
            continue
        if any(part.casefold() in DENIED_PARTS for part in relative.parts):
            raise ValueError(f"Private/development input rejected: {relative}")
        if suffixes is not None and entry.suffix.lower() not in suffixes:
            raise ValueError(f"Unexpected generated asset: {relative}")
        copy_file(entry, destination / relative)


def copy_electron_entrypoints(source: Path, destination: Path) -> None:
    # Recovery's separately loaded trusted renderer must be present in the
    # packaged audit too. Never copy the build directory indiscriminately.
    for filename in ELECTRON_APP_FILES:
        copy_file(source / filename, destination / filename)


def build_environment() -> dict[str, str]:
    # Reuse the proven native DLL-path isolation, not the private legacy builder.
    import PySide6
    import shiboken6
    env = dict(os.environ)
    windows = Path(env.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs",
        windows / "System32", windows, Path(PySide6.__file__).parent, Path(shiboken6.__file__).parent,
    )))
    env["PYINSTALLER_CONFIG_DIR"] = str(ROOT / "build/electron-pyinstaller-cache")
    return env


def collect_notices(destination: Path, pins: dict[str, str]) -> None:
    required = {"AGPL-3.0.txt", "GPL-3.0.txt", "LGPL-3.0.txt", "Apache-2.0.txt", "PortAudio-LICENSE.txt", "YOLO11n-model-card.md"}
    sources = json.loads((ROOT / "packaging/electron-notices/sources.json").read_text(encoding="utf-8"))
    if not required <= {record["file"] for record in sources}:
        raise ValueError("Required model/native license notices are missing")
    for record in sources:
        source = ROOT / "packaging/electron-notices" / record["file"]
        if not source.resolve().is_relative_to((ROOT / "packaging/electron-notices").resolve()) or sha256(source) != record["sha256"]:
            raise ValueError("License notice source/hash mismatch")
    records = []
    for name, version in pins.items():
        distribution = metadata.distribution(name)
        notices = []
        for file in distribution.files or []:
            if not any(token in Path(str(file)).name.lower() for token in ("license", "copying", "notice")):
                continue
            source = Path(distribution.locate_file(file))
            if source.is_file() and source.suffix.lower() not in {".xml", ".py", ".pyc"}:
                relative = Path(str(file).replace("..", "_"))
                copy_file(source, destination / "python" / name / relative)
                notices.append(relative.as_posix())
        records.append({"name": name, "version": version, "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License"), "notices": notices})
    copy_file(Path(sys.base_prefix) / "LICENSE.txt", destination / "python/Python-LICENSE.txt")
    # JS is bundled by esbuild/Vite; preserve notices for the whole locked graph.
    lock = json.loads((ROOT / "desktop/package-lock.json").read_text(encoding="utf-8"))
    for module_path, info in lock["packages"].items():
        if not module_path:
            continue
        package = ROOT / "desktop" / module_path
        name = module_path.removeprefix("node_modules/")
        if not package.is_dir():
            continue  # Optional packages for other platforms are not shipped.
        for source in package.iterdir():
            if source.is_file() and any(token in source.name.lower() for token in ("license", "copying", "notice")):
                copy_file(source, destination / "javascript" / name.replace("node_modules/", "dependencies/") / source.name)
        records.append({"name": name, "version": info.get("version"), "license": info.get("license"), "source": info.get("resolved"), "integrity": info.get("integrity")})
    copy_tree(ROOT / "packaging/electron-notices", destination / "additional")
    (destination / "dependencies.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def inspect_files(package: Path) -> list[dict]:
    """Final archive inventory; no recursively copied repository directory."""
    records = []
    for file in sorted(package.rglob("*")):
        if file.is_symlink():
            raise ValueError("Package contains a symlink")
        if not file.is_file():
            continue
        relative = file.relative_to(package)
        if any(part.casefold() in DENIED_PARTS for part in relative.parts):
            raise ValueError(f"Private package path: {relative}")
        if file.suffix.casefold() == ".toml" and relative.as_posix() not in {"resources/default.example.toml", "resources/protected.example.toml"}:
            raise ValueError(f"Unexpected configuration: {relative}")
        if any(token in file.name.casefold() for token in ("glasses", "failed-attempt", "recovery-bundle")):
            raise ValueError(f"Diagnostic evidence in package: {relative}")
        records.append({"path": relative.as_posix(), "bytes": file.stat().st_size, "sha256": sha256(file)})
    return records


def write_manifests(package: Path, versions: dict[str, str]) -> None:
    inventory = inspect_files(package)
    # Safety identity is built from immutable shipped bytes, excluding user data.
    files = [row["path"] for row in inventory if not row["path"].endswith(".toml")]
    manifest = {"schema": 1, "build_kind": "packaged", "files": files}
    (package / "resources/package-build.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (package / "PACKAGE-INVENTORY.json").write_text(json.dumps({
        "schema": 1, "status": "UNVALIDATED", "signing": "not signed by this project",
        "python": sys.version.split()[0], "python_dependencies": versions,
        "electron": (ROOT / "desktop/node_modules/electron/dist/version").read_text().strip(),
        "files": inspect_files(package),
    }, indent=2) + "\n", encoding="utf-8")


def build(output: Path, *, build_ui: bool = True) -> Path:
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise ValueError("Build on 64-bit Windows using 64-bit Python")
    versions = require_environment()
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    for model, expected in MODEL_HASHES.items():
        if sha256(ROOT / "models" / model) != expected:
            raise ValueError(f"Model checksum mismatch: {model}")
    output = output.resolve()
    if not output.is_relative_to((ROOT / "dist").resolve()) or output == (ROOT / "dist/LocalProctoring").resolve():
        raise ValueError("New package must be a separate folder under dist; legacy output is protected")
    if output.exists() or archive_path(output).exists():
        raise ValueError("Choose a fresh versioned output path; existing packages are never overwritten")
    if build_ui:
        node = Path(shutil.which("node") or "")
        npm = node.parent / "node_modules/npm/bin/npm-cli.js"
        if not node.is_file() or not npm.is_file():
            raise ValueError("Build prerequisite: Node with npm; run npm run build before --use-built-ui")
        subprocess.run([str(node), str(npm), "run", "build"], cwd=ROOT / "desktop", check=True)
    work = ROOT / "build/electron-frozen"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(work / "dist"), "--workpath", str(work / "work"),
                    str(ROOT / "packaging/ProctoringBackend.spec")],
                   cwd=ROOT, env=build_environment(), check=True)
    output.mkdir(parents=True)
    electron = ROOT / "desktop/node_modules/electron/dist"
    for filename in ELECTRON_FILES:
        copy_file(electron / filename, output / ("LocalProctoring-Electron.exe" if filename == "electron.exe" else filename))
    copy_tree(electron / "locales", output / "locales", suffixes={".pak"})
    application = output / "resources/app"
    copy_electron_entrypoints(ROOT / "desktop/build-electron", application / "build-electron")
    copy_tree(ROOT / "desktop/dist", application / "dist", suffixes=FRONTEND_SUFFIXES)
    (application / "package.json").write_text(json.dumps({"name": "local-proctoring-electron", "productName": "Local Proctoring", "version": "0.4.0", "main": "build-electron/main.cjs", "private": True}, indent=2) + "\n", encoding="utf-8")
    copy_tree(work / "dist/ProctoringBackend", output / "resources/backend")
    source = (ROOT / "config/default.example.toml").read_text(encoding="utf-8-sig")
    for protected, name in ((False, "default.example.toml"), (True, "protected.example.toml")):
        (output / "resources" / name).write_text(public_config(source, protected=protected), encoding="utf-8")
    collect_notices(output / "THIRD-PARTY-NOTICES", versions)
    copy_file(ROOT / "packaging/ELECTRON-PACKAGE.md", output / "README.md")
    write_manifests(output, versions)
    archive = archive_path(output)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
        for row in inspect_files(output):
            target.write(output / row["path"], f"{output.name}/{row['path']}")
    archive.with_suffix(".zip.sha256").write_text(f"{sha256(archive)}  {archive.name}\n", encoding="ascii")
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/LocalProctoring-Electron-0.4.0-stage3-UNVALIDATED")
    parser.add_argument("--use-built-ui", action="store_true", help="Use explicitly prebuilt renderer/main; final artifact still requires its own audit")
    args = parser.parse_args()
    print(build(args.output, build_ui=not args.use_built_ui))
