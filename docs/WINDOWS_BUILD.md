# Portable Windows build

Build on this Windows machine with the project virtual environment:

```powershell
if (!(Test-Path config\protected-demo.toml)) { Copy-Item config\protected-demo.example.toml config\protected-demo.toml }
.\.venv\Scripts\python.exe scripts\build_windows.py
```

Git stores only the sanitized `.example.toml` configurations. The release assets
are `LocalProctoring.exe` and `config.toml`; the published config has remote delivery
disabled, empty credentials, and public example PIN `739261` (change before use).
A local build still preserves your private settings as described below; do not
upload that private configuration as a release asset.

The build tool is PyInstaller 6.22.3. Install from official PyPI if missing.
The output directory `dist/LocalProctoring` contains two delivery files:

- `LocalProctoring.exe`: Python, Qt/WebEngine, OpenCV, ONNX Runtime CPU,
  MediaPipe, audio support, translations, native quiz and both local models.
- `config.toml`: an editable copy of `config/protected-demo.toml` with portable
  asset/output paths. Settings and credentials are preserved, never printed or
  embedded in the EXE. Keep the two files together in a writable folder.

Double-click the EXE. No Python installation or separate validation script is
needed. When protection is enabled, the launcher runs the existing independent
recovery audit when its report is missing, expired, or from another machine or
build. Failure prevents protected startup. The audit briefly opens temporary
test windows, exercises the emergency chord, and does not suppress keyboard
input. Release Ctrl/Shift/Alt/Q and close other running proctoring instances.

The audit still binds to the exact executable and machine; rebuilding or moving
the executable requires a fresh audit. Actual protection starts only through
the existing exam workflow. `Ctrl+Shift+Alt+Q` remains the emergency release.

Edit `config.toml` and restart to change the URL, language, camera, audio,
thresholds, PIN, or optional remote delivery. The protected-demo audio setting
is preserved; set `[audio] enabled = true` to enable the microphone widget.
`@bundle/` paths refer to built-in assets. Ordinary absolute or relative paths
allow external replacements. Session records and audit results create runtime
folders beside the config; these are output data, not installation dependencies.

The source config may contain bot tokens and the proctor PIN. The generated
config is intended for the same operator; review it before sharing externally.
Offline vision uses local models. An external LMS or enabled remote delivery
still requires its normal network connection.

The first launch unpacks Qt/models to a temporary directory and can take longer
than subsequent internal helper launches. The console-enabled bootloader keeps
private helper pipes functional; only an owned console is hidden on double-click.
No administrator installation is required. The executable is not code-signed.

An explicit audit remains available:

```powershell
.\LocalProctoring.exe --validate-protection
```

For local build verification without camera/microphone, network uploads, or
keyboard blocking:

```powershell
.\LocalProctoring.exe --package-smoke-test C:\path\to\verification-output
```

This checks startup, actual CPU model inference on a generated frame, local-only
WebEngine, audio imports and PDF output. It does not validate human gaze,
microphone hardware, or a live protected exam.

Rebuilding preserves an existing distribution config. Use `--replace-config`
only when intentionally regenerating it from `config/protected-demo.toml`.
Build versions, installed dependency notices and the model-source manifest are
inside the executable; original build metadata is under `build/portable`.
