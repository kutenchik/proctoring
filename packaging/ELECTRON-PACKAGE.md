# Local Proctoring — Electron inspection package

**UNVALIDATED.** A successful build is not a passing protection audit or a human
camera/gaze test. Protected use requires this package's machine-specific,
unexpired recovery audit. No audit result is included in this folder.

This is a Windows x64 runnable folder. Keep all files together. It includes the
Electron runtime, built local renderer, a one-directory Python backend, Qt native
components, PortAudio, CPU ONNX Runtime, MediaPipe, models, quiz, and local fonts.
Python, Node, npm, a repository checkout and a development web server are not
required on the target PC. No model or font is downloaded at runtime.

## Launch and settings

Run `LocalProctoring-Electron.exe` for the safe default. On first launch, the
reviewed public template is copied to
`%LOCALAPPDATA%\LocalProctoring\Electron\config.toml`. Edit that file and restart.
The public demo PIN is `739261`; choose a private PIN before actual use.
Remote delivery and Windows protection are disabled by default.

An explicitly supplied `--config "C:\Exam settings\config.toml"` is used in place
of the default. A relative explicit path resolves from the launch working
directory; ordinary paths inside TOML resolve relative to that TOML. `@bundle/`
paths select immutable resources in `resources/backend/_internal/` and remain
valid when the configuration is stored elsewhere. Do not copy old relative
`../models` or `../assets` settings without adjusting their locations.

Default sessions and audit paths are relative to the writable per-user config
directory. The installed folder is not the evidence/settings directory. The
`resources/protected.example.toml` file is an explicit public opt-in template,
not permission to skip the runtime audit. Do not overwrite the safe default with
this profile until the packaged recovery test and operator checks are complete.

The backend is an internal child executable. It routes helper and guardian modes
before Qt initialization; starting it directly without its private mode arguments
fails. No copied developer virtual environment is shipped.

## Build identity and local verification

`resources/package-build.json` enumerates the immutable package files used by the
recovery identity. The recovery implementation hashes their actual bytes. Source
audits and audits from another build/machine cannot authorize this package.
Before native preparation, the backend retains Windows read handles for the
fingerprinted files and hashes their full contents. These sharing locks deny
ordinary writes/deletion until the app closes. Exam start checks the same file
identities, exact resource enumeration and current audit expiry without hashing
the entire package under the five-second control lease. A changed/missing file,
new source/artifact file, conflicting writer or expired audit blocks protection.
Close the app completely before updating/rebuilding its resources. Settings,
audit reports and session evidence are outside these locks. This is local build
consistency, not protection against an administrator or kernel-level tampering;
the control lease and emergency recovery deadlines are unchanged.

`PACKAGE-INVENTORY.json` records file hashes, dependency versions and the explicit
UNVALIDATED status. It is an inventory, not a safety certificate or signature.

No production signing credentials were provided. This application is **unsigned
by this project**; individual third-party DLLs may carry vendor signatures.
Do not disable Windows Defender/SmartScreen. Later signing requires the
organization's own signing identity and a freshly validated signed artifact.

The old PySide6 release is separate and is not replaced by this package. Do not
run both frontends against the same camera/microphone simultaneously.

## Notices and model provenance

See `THIRD-PARTY-NOTICES/dependencies.json`, retained package license files,
Electron's `LICENSE` and `LICENSES.chromium.html`, and additional notices.
The exact model hashes and source locations are also retained in
`resources/backend/_internal/models/README.md`.

- YOLO11n is the pinned community ONNX export from `webnn/yolo11n`, revision
  `9c5acfdd74aaff2d0f47c51b878506361039a51f`, licensed AGPL-3.0 in its model card.
  The model is not represented as permissively licensed. This local inspection
  package is not approval for a proprietary/public redistribution; corresponding
  source and licensing obligations must be fulfilled before such distribution.
- Google Face Landmarker float16 version 1 comprises BlazeFace, Face Mesh V2 and
  Blendshape V2. The official model cards identify Apache License 2.0. Model cards:
  [BlazeFace](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20%28Short%20Range%29.pdf),
  [Face Mesh V2](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf),
  [Blendshape V2](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf).
- Qt/PySide6 use the documented open-source terms; no commercial Qt entitlement
  is claimed. Shared Qt DLLs remain separate in the one-directory runtime.
  LGPL/GPL notices and exact version/source references accompany the package;
  [Qt for Python sources](https://code.qt.io/cgit/pyside/pyside-setup.git/),
  [Qt 6.11.2 source archive](https://download.qt.io/archive/qt/6.11/6.11.2/single/).
- Nunito and Inter include the SIL Open Font License. PortAudio's normal Windows
  host APIs are bundled; this package does not promise ASIO support.

Implementation references:
[Electron packaging](https://www.electronjs.org/docs/latest/tutorial/application-distribution),
[ASAR limitations](https://www.electronjs.org/docs/latest/tutorial/asar-archives),
[PyInstaller runtime paths](https://pyinstaller.org/en/stable/runtime-information.html),
[Electron code signing](https://www.electronjs.org/docs/latest/tutorial/code-signing),
[Windows file-sharing semantics](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
