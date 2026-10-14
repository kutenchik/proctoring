# Separate one-directory backend. The legacy one-file release/spec is unchanged.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
import PySide6

root = Path(SPECPATH).parent
datas = [
    (str(root / "assets/quiz.json"), "assets"),
    (str(root / "models/yolo11n.onnx"), "models"),
    (str(root / "models/face_landmarker.task"), "models"),
    (str(root / "models/README.md"), "models"),
    (str(root / "src/proctoring/locales"), "proctoring/locales"),
]
qt_package = Path(PySide6.__file__).parent
binaries = [(str(path), ".") for path in qt_package.glob("*140*.dll")]
for package in ("mediapipe", "onnxruntime"):
    datas += collect_data_files(package)
    binaries += collect_dynamic_libs(package)

a = Analysis(
    [str(root / "packaging/electron_backend_entry.py")], pathex=[str(root / "src")],
    binaries=binaries, datas=datas,
    hiddenimports=["PySide6.QtMultimedia", "PySide6.QtTest", "sounddevice",
                   "_sounddevice_data", "onnxruntime", "mediapipe.tasks.python.vision"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    # The external exam belongs to Electron. Do not ship a second Chromium runtime.
    excludes=["PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
              "pytest", "IPython", "notebook", "torch", "tensorflow", "tkinter"],
    noarchive=False,
)
# The CPU Windows demo uses normal MME/WASAPI/DirectSound, not optional ASIO or
# unrelated architectures. The upstream sounddevice hook collects all variants.
a.binaries = [entry for entry in a.binaries if not (
    Path(entry[0]).name.lower().startswith("libportaudio")
    and Path(entry[0]).name.lower() != "libportaudio64bit.dll"
)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ProctoringBackend",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, contents_directory="_internal")
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ProctoringBackend")
