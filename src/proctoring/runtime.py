"""Read-only bundled assets and writable files beside the portable executable."""
from pathlib import Path
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parents[2]


def application_dir() -> Path:
    return Path(sys.executable).resolve().parent if is_frozen() else resource_root()


def asset_path(value: str, base: Path) -> Path:
    """@bundle/ paths select embedded defaults; ordinary paths stay editable."""
    if value.startswith("@bundle/"):
        root = resource_root()
        result = (root / value[len("@bundle/"):]).resolve()
        if not result.is_relative_to(root):
            raise ValueError("Bundled asset path must stay inside the bundle")
        return result
    return (base / value).resolve()
