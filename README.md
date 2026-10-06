# Local Proctoring — Stage 4

Local Windows 10/11 PySide6 demonstration: built-in quiz, calibrated webcam
monitoring, review events and optional snapshots. CPU inference is the default.
No LMS or continuous video recording. Windows protection is optional and disabled
by default; the protected demo requires a successful independent recovery audit.

## Run on Windows

Use 64-bit Python 3.11. From this project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe scripts/fetch_models.py
.\.venv\Scripts\python.exe -m proctoring
```

Installation and `fetch_models.py` are one-time online preparation. Models
already supplied locally need no download. See [model manifest](models/README.md)
for sources/hashes. The app never downloads anything; absent models produce
unavailable monitoring. Prepare dependencies and both models before going offline.

The original camera-free mode remains available:

```powershell
.\.venv\Scripts\python.exe -m proctoring --synthetic
```

The demo proctor PIN is **2468**. Configuration is `config/default.toml`;
`--config C:\path\custom.toml` selects another file. Model/output paths are relative
to that file. PINs are omitted from saved session configuration.

## Protected Windows demo

The default command above is safe mode: no hooks or containment. To prepare and
run the explicit protected configuration on the demo PC:

```powershell
.\.venv\Scripts\python.exe scripts/validate_protection.py
.\.venv\Scripts\python.exe -m proctoring --config config/protected-demo.toml
```

The first command installs an **audit-only** hook in a temporary test window:
no shortcuts are suppressed and no foreign windows are refocused. It verifies
independent release, actual injected emergency input, lost heartbeat, parent
exit/crash, repeated enable/disable and PIN interaction. Protected startup requires
every check to pass, with a matching machine/Python/source fingerprint and a
report younger than 24 hours. Rerun after source changes or on another machine.
This report is a development safety prerequisite, not an anti-tamper boundary.

`config/protected-demo.toml` explicitly sets `[protection] enabled = true`.
Restrictions start only after healthy camera monitoring, successful calibration
and **Start exam**. They remain through proctor/monitoring pauses and suspicious
warnings. They end before storage/camera cleanup on completion, PIN-authorized
exit, emergency recovery, shutdown, or independent recovery.

A separate, disposable helper owns the keyboard hook and global
**Ctrl+Shift+Alt+Q** emergency hotkey. Only UI progress sends heartbeats. Missing
heartbeats release protection after five seconds by default; parent-process
death or a closed pipe also releases it. A stalled helper loop has a separate
three-second self-exit backstop. Failed native unhooking also exits the helper.
Forced cleanup retains a handle to the verified hook-owning process, including
when Python starts through a virtual-environment launcher. Exiting the helper
removes process-owned hooks.
Recovery is terminal for that exam; a later heartbeat never silently re-arms it.

The helper suppresses Alt+Tab/Alt+Shift+Tab, both Windows keys, Ctrl+C/Ctrl+V
(including Ctrl+Insert/Shift+Insert), PrintScreen, Alt+F4, Alt+Esc and
Ctrl+Esc/Ctrl+Shift+Esc. It records shortcut names, not typed text. Held keys
produce one event. The main window stays fullscreen and intercepts ordinary
minimize/close attempts; PIN dialogs share the approved process. Foreign-window
activation is logged and focus restoration is best-effort. Security events enter
the same review table, JSONL and summary immediately, without CV thresholds or
pausing the exam timer. The panel shows ACTIVE / INACTIVE / RECOVERY.

No other application is terminated. No registry, startup, desktop-security or
system policy changes are made. Ctrl+Alt+Del and Windows secure desktops remain
outside these restrictions. Windows can deny focus restoration or remove a slow
hook; elevated applications, remote input and other capture methods are outside
this controlled demonstration's assurances. It is not an unbreakable kiosk.

After the audit passes, optional bounded native shortcut checks are:

```powershell
.\.venv\Scripts\python.exe scripts/test_windows_protection.py --run
.\.venv\Scripts\python.exe scripts/test_protected_session.py --run
```

These use owned temporary windows and a five-second maximum restriction lease
per check. The session harness uses simulated camera observations and exam time.
See [Windows test matrix](docs/STAGE4_TEST_MATRIX.md) for results and
remaining physical checks; do not treat automated injection as operator testing.

## Demonstration

1. Click **Open camera** and wait for healthy monitoring and a clear preview.
2. Follow **CENTER → LEFT → RIGHT → DOWN**. Press **Prepare** for each target,
   then look there during the two-second countdown. Collection starts with a
   beep and lasts three seconds; keep looking until the completion beep. LEFT
   and RIGHT are just beyond the physical screen edges; DOWN is below the
   physical bottom edge, not an application button. Keep your head comfortable.
   At least twenty fresh, valid samples per target are required.
3. Start after calibration succeeds. Samples exist only in memory for this
   session. Poor-quality or indistinguishable eye measurements require retry; there is
   no silent fallback to uncalibrated gaze rules.
4. Answer the six questions. The adjacent panel displays the feed, person/phone
   boxes, minimal face outline, gaze/head pose, health, FPS and inference latency.
5. Sustained suspicious observations create review events while the exam continues.
6. Camera errors, stale frames/results and worker failures pause the quiz/timer.
   Recovery in **less than 15 seconds** automatically resumes unless a proctor
   pause remains. **15 seconds or longer** requires healthy monitoring and
   **Resume with PIN**. Recoverable camera errors retry automatically; **Retry
   camera** restarts workers once previous workers have released their resources.
7. **Proctor pause…** and **End session…** require the PIN. End and timer expiry
   release protection first, stop monitoring and show/save the summary.

Internal emergency shortcut: **Ctrl+Shift+Alt+Q**, including within the PIN dialog.
Safe mode uses an application-local shortcut. Protected mode also has the separate
helper's global recovery route. Native capture/release calls stay off the UI
thread. Bounded camera shutdown does not open a second capture worker while a
blocked previous worker is alive.

For local numerical calibration diagnostics, with protection disabled:

Calibration now requires a face inside the preview guide, sufficiently large
source-image face/eye measurements, a natural frontal pose and 0.75 seconds of
stable positioning. Prepare stays disabled until ready; poor positioning samples
are rejected without bypassing gaze-fit checks. See [face alignment checks and
configuration](docs/FACE_ALIGNMENT.md).

```powershell
.\.venv\Scripts\python.exe -m proctoring --calibration-debug
```

Expand **Developer calibration diagnostics** for per-eye measurements, openness,
source dimensions, rejection reasons, per-axis medians/spreads, and every constant,
pixel and spread threshold contribution. Failed attempts can be exported as local
numerical JSON only after explicit opt-in. A separate fresh CENTER/LEFT/RIGHT/DOWN/
READING pass reports DEBUG / UNVALIDATED predictions and cannot enable an exam.
No images/video are exported. Debug mode refuses enabled Windows protection.
Human eyes-only accuracy remains unvalidated: follow the
[operator diagnostic workflow](docs/GAZE_DIAGNOSTIC_RUN.md).
The [actual operator analysis](docs/GAZE_OPERATOR_ANALYSIS.md) documents the pixel
gate, DOWN correction and unresolved reading/LEFT confusion. A new human run is
required to assess the corrected classifier.

## Performance and configuration

The default camera request is index 0, 1280×720 at 30 FPS. The driver may negotiate
a different rate/resolution. Automatic Windows backend selection tries MSMF,
DirectShow and the default backend; both backend and camera index are configurable.

YOLO is scheduled at up to 5 Hz, Face Landmarker at up to 12 Hz. A latest-frame
capture slot and one inference worker bound memory and avoid old-frame backlogs.
Actual rates depend on model latency and CPU. Combined event observations require
fresh YOLO and face results from the same frame; face-only processing never
refreshes old phone evidence. Preview boxes can trail the live feed by an inference
interval. Capture timestamps, worker heartbeats and result age determine health.

`yolo_input_size=416` applies to dynamic ONNX models. Fixed-shape models use their
exported dimensions, shown in metrics. Use a smaller/dynamic raw-output YOLO11n
export to reduce the input size. Configurable controls include inference rates,
CPU threads, detection confidence, minimum box sizes and freshness limits. Keep
freshness limits above measured inference intervals while short enough to detect
failures. Stale/no-face are deliberately different states.

CPU ONNX Runtime is installed by default. `prefer_gpu=true` opts in to CUDA only
when a compatible GPU provider has been separately provisioned. Initialization
or execution failure falls back to CPU. Neither CUDA nor an NVIDIA GPU is
required. MediaPipe uses CPU.

```powershell
.\.venv\Scripts\python.exe scripts/benchmark.py --camera-only --seconds 10 --output artifacts/camera-test.json
.\.venv\Scripts\python.exe scripts/benchmark.py --seconds 20 --output artifacts/benchmark-cpu.json
```

The benchmark forces CPU and reports capture FPS, mean/p95 YOLO and MediaPipe
latency, combined monitoring FPS, CPU use and memory. `--models-only` runs a
labelled blank-frame diagnostic, not a live-camera benchmark. Diagnostics save
metrics only, never camera frames or video.

## Architecture

| Module | Responsibility |
|---|---|
| `vision/camera.py` | Background capture, latest frame and reconnect |
| `vision/yolo.py` | ONNX providers, letterbox, COCO person/phone classes and NMS |
| `vision/face.py` | MediaPipe landmarks, primary face, iris features/head pose |
| `vision/calibration.py` | Session samples, quality checks and gaze classification |
| `vision/rules.py`, `types.py` | Normalized results, raised geometry and observation mapping |
| `vision/monitor.py`, `health.py` | Worker scheduling, heartbeat/error/freshness health |
| `events/`, `session.py` | Existing threshold/hysteresis engine and monotonic exam lifecycle |
| `controller.py` | Connects health, observations, events, quiz and persistence |
| `ui/` | Camera/calibration setup, quiz, preview, event table, PIN and summary |
| `storage/` | JSONL log, atomic summary and bounded background JPEG writes |
| `security/` | PIN, safe adapter, independent Windows helper, recovery and validation gate |

MediaPipe supplies landmarks and a face transform, **not gaze labels**. Iris
positions are measured relative to the eye-corner axis and normalized by eye
width. Eye-only direction references are learned per session; head pose is shown
separately and can only reject an unsupported pose. Calibration requires eye
separation above measured spread and pixel uncertainty. Labels require proximity
to the calibrated off-screen reference, rather than any departure from exact
CENTER. Blinks, invalid geometry, ambiguous or distant features return UNKNOWN.
Confidence is reference similarity, not a probability of misconduct. Fresh frames without a face produce FACE_ABSENT;
camera/pipeline unavailability produces monitoring failure.

Threshold defaults in seconds: phone 1.0, second person 1.0, raised phone 1.25,
gaze down/left/right 3.0, face absent 3.0, clearing 0.75. All are configurable.
Events transition candidate → active → clearing → closed with one stable ID per
sustained event. Only fresh observations advance evidence. Monotonic time drives
durations; UTC wall timestamps are for audit display. Outages interrupt active
events and reset candidates. Existing timer/event logic is retained.

Raised-phone geometry considers phone position near the face or upper person
region. The event engine handles sustained duration. Its warning is exactly:

> Phone raised — possible screen capture attempt.

This cannot verify camera orientation, shutter activity or an actual photograph.
YOLO may miss small/occluded phones or detect objects in posters/screens. Two
large/confident person boxes trigger second-person evidence; there is no identity
verification. Lighting, glasses, distance and movement degrade gaze estimates.
Freshness measures frame arrival; a driver repeating a frozen image as new data
may evade that check. All detections require human review.

## Evidence and tests

Started exams create `sessions/<id>/` containing `session.json`, PIN-free
`config.json`, `events.jsonl` and `summary.json`. When enabled, a single activation
snapshot per event is saved to `snapshots/<event-id>.jpg`. A bounded writer queue
keeps disk/JPEG work off the UI; write/drop errors appear in the summary. JSONL
can refer to queued snapshots; the final summary includes only successful paths.
No continuous frames/video or calibration samples are persisted by normal sessions.
Calibration-debug offers a separate, explicitly enabled numerical JSON export;
it includes no camera images/video and works after failed calibration.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests cover thresholds, hysteresis, exact recovery boundaries, overlapping pauses,
timers, camera/worker failures, stale results, ONNX mapping, raised geometry,
person filters, calibration, Qt widgets and persistence. Hardware diagnostics
remain separate from deterministic unit tests.

## Final demonstration validation

Keep development on the default safe configuration. Rehearse a calibrated
protected exam on the university-managed machine, including physical camera
disconnect, short/long recovery, PIN pause/resume, emergency exit and normal
completion. Verify normal Windows interaction after each scenario. The existing
CV, event thresholds, timer and monitoring-recovery architecture remain intact.
