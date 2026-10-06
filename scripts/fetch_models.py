"""One-time model preparation. The application itself never downloads models."""
import argparse
from hashlib import sha256
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "yolo11n.onnx": (
        "https://huggingface.co/webnn/yolo11n/resolve/9c5acfdd74aaff2d0f47c51b878506361039a51f/onnx/yolo11n.onnx",
        "7d8fd1717d9d5bbab6986cd134afb620649c7a394303d55b1e09fc00804cc5c1",
    ),
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    ),
}


def fetch(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in MODELS.items():
        target = directory / name
        if target.exists() and expected and sha256(target.read_bytes()).hexdigest() == expected:
            print(f"Verified existing {name}", flush=True)
            continue
        partial = target.with_suffix(target.suffix + ".partial")
        digest = sha256()
        with urllib.request.urlopen(url, timeout=45) as response, partial.open("wb") as output:
            while data := response.read(64 * 1024):
                output.write(data)
                digest.update(data)
        actual = digest.hexdigest()
        if expected and actual != expected:
            raise RuntimeError(f"Checksum mismatch for {name}: {actual}")
        partial.replace(target)
        print(f"{name}: {target.stat().st_size} bytes SHA256={actual}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "models")
    fetch(parser.parse_args().directory)
