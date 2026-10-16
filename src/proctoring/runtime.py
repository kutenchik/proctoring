"""Read-only bundled assets and writable files beside the portable executable."""
from pathlib import Path, PureWindowsPath
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def distribution_identity():
    if not is_frozen():
        return 'source'
    import hashlib
    inventory = Path(sys.executable).resolve().parents[2] / 'PACKAGE-INVENTORY.json'
    return hashlib.sha256(inventory.read_bytes()).hexdigest()


def resource_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parents[2]


def application_dir() -> Path:
    return Path(sys.executable).resolve().parent if is_frozen() else resource_root()


def asset_path(value: str, base: Path) -> Path:
    """@bundle/ paths select embedded defaults; ordinary paths stay editable."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Asset path must be a non-empty local path")
    if value.startswith("@bundle/"):
        relative = value[len("@bundle/"):]
        # The reserved bundle form is a relative resource name, never a drive,
        # UNC path, alternate data stream, or traversal through another folder.
        parts = relative.replace("\\", "/").split("/")
        if (not relative or PureWindowsPath(relative).anchor or ":" in relative
                or any(part in ("", ".", "..") for part in parts)):
            raise ValueError("Bundled asset path must be a relative resource name inside the bundle")
        root = resource_root()
        result = root.joinpath(*parts).resolve()
        if not result.is_relative_to(root):
            raise ValueError("Bundled asset path must stay inside the bundle")
        return result
    return (base / value).resolve()
