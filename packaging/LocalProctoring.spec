# Build from the project virtual environment: python scripts/build_windows.py
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
    (str(root / "build/portable/metadata"), "build-metadata"),
]
# Pin Microsoft's runtime to the versions shipped by the installed Qt wheel.
# The build shell may have unrelated runtimes on PATH. If collected at
# bundle root, Windows loads those first and Qt can fail with missing exports.
qt_package = Path(PySide6.__file__).parent
binaries = [(str(path), ".") for path in qt_package.glob("*140*.dll")]
for package in ("mediapipe", "onnxruntime"):
    datas += collect_data_files(package)
    binaries += collect_dynamic_libs(package)

a = Analysis(
    [str(root / "scripts/frozen_entry.py")],
    pathex=[str(root / "src")], binaries=binaries, datas=datas,
    hiddenimports=["PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore",
                   "PySide6.QtTest", "sounddevice", "_sounddevice_data",
                   "onnxruntime", "mediapipe.tasks.python.vision"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["pytest", "IPython", "notebook", "torch", "tensorflow", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="LocalProctoring", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, hide_console="hide-early",
)
