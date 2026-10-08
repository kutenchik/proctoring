# Local Proctoring

[English](README.md) | [Русский](README.ru.md)

A Windows desktop prototype for a controlled university proctoring demonstration.
It combines an exam interface, local webcam inference, calibrated gaze estimates,
review-event logging, optional evidence snapshots, and optional Windows session
restrictions. CPU operation is supported; an NVIDIA GPU is not required.

This README describes the current implementation, including the portable
`LocalProctoring.exe` build and the editable configuration beside it. Feature
availability and enabled options depend on the configuration you launch.
The existing operator configurations may contain custom settings and credentials;
do not assume their values match the baseline settings documented below.

Git includes `config/default.example.toml` and
`config/protected-demo.example.toml`. The working `default.toml` and
`protected-demo.toml` files are local and ignored. Collected calibration data,
generated PDFs, session evidence, and brag output are also excluded from Git.

## Contents

1. [Features and scope](#1-features-and-scope)
2. [Run the portable EXE](#2-run-the-portable-exe)
3. [Run from source](#3-run-from-source)
4. [Candidate and proctor workflow](#4-candidate-and-proctor-workflow)
5. [Camera alignment and gaze calibration](#5-camera-alignment-and-gaze-calibration)
6. [Microphone check](#6-microphone-check)
7. [Native quiz and external web exams](#7-native-quiz-and-external-web-exams)
8. [Events, timing, and monitoring recovery](#8-events-timing-and-monitoring-recovery)
9. [Windows protection and emergency recovery](#9-windows-protection-and-emergency-recovery)
10. [Configuration reference](#10-configuration-reference)
11. [Optional identity and system checks](#11-optional-identity-and-system-checks)
12. [Evidence, privacy, and PDF reports](#12-evidence-privacy-and-pdf-reports)
13. [Telegram and webhook delivery](#13-telegram-and-webhook-delivery)
14. [Languages](#14-languages)
15. [Models and CPU performance](#15-models-and-cpu-performance)
16. [Architecture and project structure](#16-architecture-and-project-structure)
17. [Tests and validation](#17-tests-and-validation)
18. [Build the Windows executable](#18-build-the-windows-executable)
19. [Troubleshooting](#19-troubleshooting)
20. [Limitations and further documentation](#20-limitations-and-further-documentation)

## 1. Features and scope

| Area | Implemented behavior |
| --- | --- |
| Exam | Built-in multiple-choice quiz or an embedded external web exam; local countdown, pause/resume, PIN-controlled ending, saved summary. |
| Registration | First name, last name, and optional/required group or student ID linked to the session. |
| Webcam | One configurable camera, latest-frame capture, preview, freshness and worker-health checks. |
| Object detection | YOLO11n ONNX person and cell-phone detection, CPU by default. |
| Face and gaze | MediaPipe face landmarks, per-session CENTER/LEFT/RIGHT/DOWN calibration, guarded iris/aperture estimates, and a separately reported head-down posture cue. |
| Review events | Sustained phone, raised-phone, second-person, gaze/head-down, and face-absence observations with thresholds and clearing hysteresis. |
| Microphone | Optional live RMS meter, ambient calibration, sound-level test, manual sensitivity, and sustained audio-activity review events. |
| Protection | Optional Windows keyboard/focus restrictions after an independent recovery audit; PIN exit and emergency recovery. |
| Optional checks | Reference selfie/face-shape comparison, screen count, clipboard guard, VM heuristic, experimental ear-adjacent appearance heuristic. |
| Evidence | Local JSON/JSONL, optional event JPEGs, and optional PDF timeline with inline thumbnails. |
| Delivery | Optional bounded background Telegram and/or webhook dispatch. |
| Languages | English, Russian, and Kazakh interface. |

The intended platform is **64-bit Windows 10/11**, a modern Intel/AMD CPU,
**at least 8 GB RAM**, and one built-in or USB webcam. A microphone is optional.
The default camera request is 1280×720; a driver may negotiate a lower resolution.
Keep enough writable disk space for the executable, temporary extraction, and
session evidence. Actual inference speed must be measured on the demonstration PC.

CV inference is local, with local model files and no runtime model downloads.
An external LMS and explicitly enabled remote delivery need network access.
There is no continuous video/audio recording, LMS grade/submission API integration,
validated biometric authentication, or production-grade anti-tamper guarantee.
Review findings are indicators for a human reviewer, not automatic proof of cheating.

## 2. Run the portable EXE

The delivery folder contains two required files:

Download **both assets** from the repository's
[GitHub release](https://github.com/kutenchik/proctoring/releases).
The release configuration has remote delivery disabled, blank remote credentials,
and the public example PIN `739261`. Change the PIN before running an exam.
EXE files are release assets, not files tracked in Git.

```text
dist/LocalProctoring/
├── LocalProctoring.exe
└── config.toml
```

1. Copy both files together into a writable folder on the Windows PC.
2. Review `config.toml`, particularly protection, PIN, external exam URL, audio,
   remote delivery, and evidence settings. Keep private credentials private.
3. Double-click `LocalProctoring.exe`.
4. If protection is enabled and its audit is missing, expired, or belongs to
   another machine/build/location, allow the automatic recovery audit to finish.
   Keep Windows unlocked, the desktop active, and Ctrl/Shift/Alt/Q released.
5. Follow registration, camera setup, calibration, and exam start in the UI.

Python, Qt/WebEngine, the CPU vision runtime, audio support, translations, the
native quiz, and both required models are bundled. The first launch extracts
resources into a temporary directory and may take longer. No Python installation
or separate audit script is needed for normal portable use.

To launch explicitly from PowerShell:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\dist\LocalProctoring'
.\LocalProctoring.exe
```

A different complete configuration can be selected explicitly:

```powershell
.\LocalProctoring.exe --config C:\path\to\custom.toml
```

Edit the adjacent `config.toml`, save it, and restart the application to apply
configuration changes. The October 7, 2026 protected build preserved audio as
disabled: set `enabled = true` under its existing `[audio]` section to show the
microphone check. This is a setting of that build's copied config, not a limitation
of the EXE.

`@bundle/` paths select bundled assets. Ordinary relative paths resolve from the
configuration directory, so custom quiz/model files can live beside the config.
The application creates runtime `sessions/` and `artifacts/` folders as needed;
the two-file requirement applies to distribution, not to generated evidence.

The EXE is not code-signed. It does not require an administrator installation.
Use the school's normal review process for running a local unsigned application.
Full portable details: [WINDOWS_BUILD.md](docs/WINDOWS_BUILD.md).

## 3. Run from source

Use **64-bit Python 3.11**. Open PowerShell in the repository root:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe scripts\fetch_models.py
if (!(Test-Path config\default.toml)) { Copy-Item config\default.example.toml config\default.toml }
if (!(Test-Path config\protected-demo.toml)) { Copy-Item config\protected-demo.example.toml config\protected-demo.toml }
.\.venv\Scripts\python.exe -m proctoring
```

Dependency installation and model preparation require network access once, unless
the files/packages have already been prepared locally. `fetch_models.py` uses
pinned model sources and verifies hashes. Do not replace dependencies with
arbitrary unofficial binary wheels when a setup error occurs.

The source entry point reads `config/default.toml`; a different complete config
can be selected explicitly:

```powershell
.\.venv\Scripts\python.exe -m proctoring --config config\protected-demo.toml
.\.venv\Scripts\python.exe -m proctoring --config C:\path\to\custom.toml
```

Edit the copied files, not the examples. The default example disables Windows
restrictions; the protected example enables them and requires the recovery audit.
Both use the native quiz and have remote delivery disabled. Tests read the
versioned examples and do not require your private configuration files.

For external browser exams, install the official WebEngine add-on in the same venv:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.lock
```

The main lock includes audio support and references the remote-client lock.
For an older environment missing the remote dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-remote.lock
```

Camera-free synthetic mode is useful for event/session demonstrations:

```powershell
.\.venv\Scripts\python.exe -m proctoring --synthetic
```

Synthetic mode does not by itself disable optional audio, remote delivery, or
protection. Use a private test config with those options disabled when a test
must not access a microphone, network destination, or Windows hooks. Also disable
reference-selfie requirements and leave `external_url = ""` for a hardware-free,
local-only synthetic demonstration.

The checked-in lock and an already-installed development environment may differ.
For example, the source lock pins NumPy 1.26.4, while the verified portable build
records NumPy 2.4.6 in its build metadata. Do not infer that a fresh installation
was tested merely from a successful build of the existing environment.

## 4. Candidate and proctor workflow

1. **Register**, if enabled: enter first name, last name, and group/student ID.
   Required fields must contain non-whitespace text. Registration alone starts
   neither the exam timer nor Windows restrictions.
2. **Capture a reference selfie**, if configured: use the registration preview
   and Take Baseline Photo with one visible frontal face.
3. **Open camera** and wait for healthy monitoring and a clear live preview.
4. **Align** within the fixed oval. Follow measured feedback such as Move closer,
   Center your face, Keep both eyes visible, and Hold still.
5. **Start calibration** once and follow CENTER → LEFT → RIGHT → DOWN. Follow
   the preparation/countdown and collection cues. Retry only a failed target when
   the UI permits; use a new baseline after changing position or conditions.
6. **Check the microphone**, when enabled: stay quiet for the ambient measurement,
   speak when prompted, and inspect the meter and threshold.
7. **Start exam** after the required camera, calibration, identity, and system
   checks pass. Protected mode activates restrictions at this point.
8. **Take the quiz or web exam** while the preview and event panel remain visible.
   Suspicious observations record review events; they do not stop the timer.
9. A proctor can **pause**, **resume**, or **end the session** through the PIN flow.
   Monitoring outages use the recovery rules described below.
10. At completion or timer expiry, restrictions are released first, monitoring
    stops, local records are finalized, and the summary is shown. If configured,
    PDF generation and remote dispatch run in their background workers.

The proctor should verify the PIN before a live demonstration. It is configured
under `[security]`; this README intentionally does not publish a working PIN.
For an external exam, submit answers in the website before ending the local
session. Local completion does not certify that the website accepted submission.

Emergency recovery: **Ctrl+Shift+Alt+Q**. This is an internal recovery route, not
the normal candidate exit mechanism. Rehearse recovery on the demonstration PC.

## 5. Camera alignment and gaze calibration

The oval is fixed in preview-image coordinates and follows image resizing and
letterboxing. It does not resize to follow the detected face. Amber/green states
communicate positioning readiness before/during calibration; the actual exam
removes the positioning oval from the preview.

Admission checks include face presence/containment, sufficient source-image face
and eye size, both eyes measurable, approximately frontal head pose, measurement
quality, and a short stable-position interval. The default stability interval is
0.75 seconds with at least three unique samples. Enlargement of eye close-ups
does not add source pixels. Passing positioning is not passing gaze calibration.

The automatic target sequence uses two seconds of preparation, at least three
seconds of collection, and at least 20 fresh valid samples for each target.
Collection can extend to six seconds if needed. The fixed maximum is not extended
by blinks or repeated UI polling. A failed target can be retried without pooling
its old failed samples; compatible completed targets are retained. Moving to a
new position or losing the baseline requires recollection.

Look at the **physical screen center** for CENTER, beyond the corresponding
screen edge for LEFT/RIGHT, and below the physical bottom edge for DOWN. Keep a
comfortable approximately frontal head. Do not use exaggerated rotation or
remove necessary corrective glasses as a required solution.

MediaPipe supplies landmarks and a face transform, **not gaze-left/right labels**.
Floating-point iris features are normalized by eye width, with per-eye references
learned in the current session. Fit checks consider sample count, target spread,
constant uncertainty, and a configurable pixel uncertainty assumption. CENTER–DOWN
uses vertical separation; the other pair checks retain their defined radial metric.
Fit failure is not bypassed and cannot enable the exam.

The current guarded DOWN supplement uses both a learned downward iris shift and
reduced opening relative to each eye's CENTER reference. Narrowing alone is not
DOWN. Invalid measurements and closure guards produce UNKNOWN; neither is face
absence or camera failure. Similarity/confidence is not a probability of misconduct.
See [GUARDED_DOWN.md](docs/GUARDED_DOWN.md) for the exact guards and fit formula.

A separate head-down posture cue can support the existing `gaze_down` review
condition after successful calibration: `14 < pitch < 90`, `abs(yaw) <= 15`,
`abs(roll) <= 12` degrees by baseline settings. It can be present while the iris
estimate is UNKNOWN. The UI retains the separate posture and eye signals; this
is not a claim that head pose measured the eyes. See
[HEAD_DOWN_POSTURE.md](docs/HEAD_DOWN_POSTURE.md).

For numerical diagnostics, use a config with `protection.enabled = false`:

```powershell
.\.venv\Scripts\python.exe -m proctoring --config C:\path\to\safe.toml --calibration-debug
```

The existing developer panel exposes source dimensions, eye widths, openness,
per-axis medians/spreads, accepted/rejected sample counts, rejection reasons,
threshold contributions, attempt identity, and validation's source attempt.
Optional live eye close-ups use the matching frame/landmarks and are never saved.
There is no automatic validated glare detector.

Numerical export requires explicit local opt-in and works for rejected attempts.
Run the separate labeled validation pass with new measurements, including normal
quiz reading, blinks, closure, and squinting. UNKNOWN must be reported separately
from correct predictions. Debug/experimental predictions do not create misconduct
events or authorize an exam. Human gaze performance remains camera/condition
dependent and must be checked independently of passing regression tests.

## 6. Microphone check

Enable `[audio] enabled = true`. After registration, the setup page shows a live
normalized RMS meter at up to 20 Hz, a threshold marker, the threshold source,
ambient measurement, and a sensitivity slider. Audio processing stays off the UI.

1. Click **Calibrate Mic** and remain quiet for **2.5 seconds**.
2. The median background RMS is used to recommend
   `max(ambient * 2.5, ambient + 0.08)`.
3. Speak a few words at ordinary volume. The level must exceed the proposed
   threshold for at least **0.15 seconds within eight seconds**.
4. A successful rise shows **Microphone ready** and commits the session threshold.

Baseline threshold limits are 0.05–0.40 normalized RMS. A recommended threshold
above the maximum is reported as too noisy rather than silently accepted below
the measured floor. High sensitivity lowers the trigger; Low raises it. The
slider changes detection sensitivity, not Windows microphone gain. A manual
change removes the ready indication until the setting is checked again.

The check is optional and does not block exam start. Without a committed adaptive
or manual threshold, the legacy fallback learns ambient noise for three seconds
and uses `max(ambient + energy_threshold, 3 * ambient)`; its configured increment
is 0.15. A failed retry retains an earlier committed threshold, identified
separately from the failed attempt's measurements.

No microphone/denied permissions/stale input is shown as unavailable and can be
retried. Audio unavailability does not pause the camera or exam timer. On exam
start, preflight samples are discarded; only fresh exam audio can accumulate the
two-second audio event. RMS detects sustained **sound energy**, not speech content:
music, a fan, and voices can cross the same threshold. No audio recording,
transcription, storage, or upload is performed.

Detailed operation and hardware check: [AUDIO_CHECK.md](docs/AUDIO_CHECK.md).

## 7. Native quiz and external web exams

With `[exam] external_url = ""`, the app loads the native quiz from `quiz_path`.
The supplied demo has six multiple-choice questions. A custom UTF-8 JSON quiz
uses this structure:

```json
{
  "questions": [
    {
      "id": "q1",
      "prompt": "What is 2 + 2?",
      "options": ["3", "4", "5"],
      "correct_index": 1
    }
  ]
}
```

The quiz must contain at least one question, unique nonempty string IDs,
nonempty prompts, at least two nonempty options per question, and a zero-based
integer `correct_index` within those options. The answers are local demonstration
data; storing correct answers in the client is not a secure question bank.
For a portable custom quiz, set `quiz_path = "quiz.json"` and place that file next
to `config.toml`.

To use a university site, edit the existing `[exam]` table:

```toml
external_url = "https://moodle.university.edu/mod/quiz/view.php?id=123"
allowed_domains = ["moodle.university.edu", "login.university.edu"]
```

An empty allowlist defaults to the external URL's exact hostname. Entries must
be hostnames without schemes, paths, or wildcards. Subdomains are not implicitly
trusted. Navigation to other hosts is blocked in the main page and child frames.
CDN resources can still load: the guard limits document navigation, not all network
traffic. Context menus, downloads, extra windows/tabs, F12, and Ctrl+Shift+I are
blocked. Browser camera/microphone/screen requests are denied. The profile is
in memory for that run; proctoring frames are not supplied to the website.

The configured page loads when the exam starts. A loading indicator and Reload
control handle page/network problems. Authentication requiring popups or refusing
embedded browsers may fail, so rehearse the LMS login and submission flow.
Local pauses disable browser interaction but cannot pause an LMS server's timer.
Network failure is not treated as camera failure. The local summary does not
claim an external score or confirmed submission.

## 8. Events, timing, and monitoring recovery

The baseline configurable thresholds are:

| Observation | Technical event | Sustained duration |
| --- | --- | --- |
| Phone visible | `phone_visible` | 1.0 s |
| At least two sufficiently large/confident people | `second_person` | 1.0 s |
| Phone raised near face/upper-body screen level | `phone_raised` | 1.25 s |
| Calibrated left/right/down or supported head-down cue | `gaze_left`, `gaze_right`, `gaze_down` | 3.0 s |
| Fresh camera image, no valid primary face | `face_absent` | 3.0 s |
| Optional sustained microphone energy | `VOICE_DETECTED` | 2.0 s |
| Clearing after a condition disappears | Existing active event | 0.75 s |

The raised-phone warning is exactly:

> Phone raised — possible screen capture attempt.

This geometry heuristic cannot confirm phone camera orientation, shutter activity,
or that a photograph was taken.

Events transition **candidate → active → clearing → closed**. A sustained event
keeps one ID and updates its duration rather than repeatedly alerting or capturing
snapshots. Brief detection gaps within clearing hysteresis retain that event.
Only fresh observations advance evidence. Durations and timer decisions use a
monotonic clock; wall-clock timestamps are for human-readable records.

| Situation | Exam/timer behavior |
| --- | --- |
| Suspicious review event | Continue. |
| Proctor pause | Pause until PIN-authorized resume. |
| Camera disconnect, stale frames/results, worker failure | Pause as soon as the health failure is detected. |
| Monitoring healthy again after less than 15.0 s | Resume automatically unless another pause reason remains. |
| Monitoring healthy again after 15.0 s or longer | Require proctor PIN to resume. |
| Poor eye visibility/UNKNOWN with otherwise healthy vision | Reduce gaze availability; other detectors and timer continue. |
| Unavailable optional microphone or failed remote upload | Continue camera monitoring and timer. |

At exactly 15.0 seconds the PIN requirement applies. Overlapping pause reasons
are retained independently: recovering the camera cannot cancel a proctor pause.
The pause is immediate upon detected failure, not necessarily at the physical
instant a cable is removed: freshness checks use configured deadlines (two seconds
for frames/results by baseline settings), and a camera read can fail sooner.
Monitoring interruptions close/reset affected evidence state rather than counting
unobserved time. Local timer expiry ends the session safely.

## 9. Windows protection and emergency recovery

Protection is an explicit setting: `[protection] enabled = true`.
For a safe diagnostic run, explicitly set it to `false` in the chosen config.
The legacy `[security] blocking_enabled` must remain `false`; it does not enable
the current protection backend.

For source execution, first run the independent audit and then the protected app:

```powershell
.\.venv\Scripts\python.exe scripts\validate_protection.py
.\.venv\Scripts\python.exe -m proctoring --config config\protected-demo.toml
```

The portable launcher automatically runs the same recovery validation when needed.
An explicit portable audit is also available:

```powershell
.\LocalProctoring.exe --validate-protection
```

The audit uses owned temporary windows and an **audit-only** hook: it does not
suppress shortcuts or refocus foreign windows. It checks independent release,
injected emergency input, heartbeat loss, parent exit/crash, repeated enable/disable,
and PIN interaction. All checks must pass with a matching machine/build fingerprint
and a report younger than 24 hours by default. Rebuilding, changing relevant source,
or moving to another machine/location can require a new audit. An audit report is
a development recovery prerequisite, not an anti-tamper boundary.

Restrictions begin only after the normal prerequisites and Start exam, and remain
through proctor/monitoring pauses. The transient Windows helper suppresses
Alt+Tab/Alt+Shift+Tab, both Windows keys, Ctrl+C/Ctrl+V and their Insert variants,
PrintScreen, Alt+F4, Alt+Esc, Ctrl+Esc, and Ctrl+Shift+Esc. Held keys create one
shortcut event. Only shortcut names are recorded, not typed text.

The exam window stays fullscreen and intercepts ordinary close/minimize attempts.
PIN dialogs remain within the allowed application process. Foreign-window
activation is logged, with best-effort focus restoration. Other applications are
not terminated. Security events appear immediately in the review log rather than
using CV duration thresholds or pausing the timer.

**Ctrl+Shift+Alt+Q** is the emergency chord. Safe mode provides an application-local
shortcut; protected mode additionally uses the independent helper's global route.
The helper owns the hook and receives UI-progress heartbeats. By baseline settings,
lost heartbeats release restrictions after five seconds; parent death/closed pipe
also releases them. A separate three-second stalled-loop backstop exits the helper.
Recovery is terminal for the exam and never silently re-arms restrictions.

Normal end, PIN-authorized exit, emergency exit, or application cleanup releases
protection before camera/storage cleanup. No registry/startup/security-policy
changes are made. Ctrl+Alt+Del and Windows secure desktops remain outside this
application's restrictions. Elevated apps, focus-policy decisions, remote input,
and alternative screen-capture methods limit what this demonstration can prevent.

Optional native bounded tests, after successful validation:

```powershell
.\.venv\Scripts\python.exe scripts\test_windows_protection.py --run
.\.venv\Scripts\python.exe scripts\test_protected_session.py --run
```

These use owned test windows and at most five-second restriction leases per
check. Their simulated inputs do not replace physical operator recovery testing.

## 10. Configuration reference

Modify the selected TOML file and restart. Do not paste a second table with the
same name. Use `true`/`false`, quoted strings, and quoted Windows paths with
appropriate TOML escaping; forward slashes or literal single-quoted paths are
convenient. Relative asset/output paths resolve from the config directory.

The values below describe **baseline code settings or demonstration defaults**,
not a dump of the current operator configuration. Inspect your actual config.
Required core sections should be retained when creating a custom config; the
short snippets in this README are edits to an existing complete file.

### Exam, UI, storage, timing, and security

| Section / key | Baseline / expected value | Meaning |
| --- | --- | --- |
| `exam.duration_seconds` | 600.0 | Positive local exam duration. |
| `exam.quiz_path` | `../assets/quiz.json` in source configs | Local native quiz; portable default uses `@bundle/assets/quiz.json`. |
| `exam.external_url` | `""` | Empty uses native quiz; HTTP(S) URL uses WebEngine. |
| `exam.allowed_domains` | `[]` | Exact navigation hosts; empty derives the URL host. |
| `exam.registration.enabled` / `require_group` | true / true | Candidate form and required group ID. |
| `ui.language` | `en` | `en`, `ru`, or `kk`. |
| `storage.sessions_dir` | Config-relative directory | Session output root; portable config uses `sessions`. |
| `storage.snapshots_enabled` | Boolean in selected config | Save activation JPEGs when available. |
| `events.phone_visible` / `second_person` | 1.0 / 1.0 | Duration in seconds. |
| `events.phone_raised` | 1.25 | Raised-phone duration. |
| `events.gaze_deviation` / `face_absent` | 3.0 / 3.0 | Gaze/head-down and absent-face duration. |
| `events.clearing_seconds` | 0.75 | Clearing hysteresis. |
| `monitoring.recovery_seconds` | 15.0 | Auto-resume/PIN interruption boundary. |
| `monitoring.stale_seconds` | Positive; greater than synthetic interval | Observation freshness, particularly synthetic mode. |
| `monitoring.synthetic_interval_ms` | Integer at least 10 | Synthetic observation cadence. |
| `security.proctor_pin` | Private quoted 4–64 ASCII digits | Local PIN controls; omitted from saved public config. |
| `security.blocking_enabled` | false | Legacy compatibility field; must stay false. |
| `protection.enabled` | false in code | Explicit real Windows protection switch. |
| `protection.heartbeat_timeout_seconds` | 5.0 | Helper's UI-heartbeat release deadline. |
| `protection.startup_timeout_seconds` | 5.0 | Bounded helper startup wait. |
| `protection.foreground_poll_ms` | 100 | Foreground-window check cadence. |
| `protection.validation_report` | `artifacts/protection-validation.json` | Local audit report path. |
| `protection.validation_max_age_hours` | 24.0 | Maximum accepted audit age. |

### Camera and detection: `[vision]`

| Key | Baseline | Meaning |
| --- | --- | --- |
| `camera_index` | 0 | OpenCV device index. |
| `capture_width`, `capture_height`, `capture_fps` | 1280, 720, 30 | Requested capture mode; actual mode may differ. |
| `camera_backend` | `auto` | `auto`, `msmf`, `dshow`, or `any`; auto tries Windows backends. |
| `yolo_model`, `face_model` | Local model paths | Portable files use `@bundle/models/...`. |
| `yolo_input_size` | 416 | Dynamic model size, at least 128 and divisible by 32; fixed models retain their exported shape. |
| `yolo_fps`, `face_fps` | 5.0, 12.0 | Maximum scheduling rates, not guaranteed throughput. |
| `prefer_gpu` | false | Optional available CUDA provider; CPU fallback remains. |
| `cpu_threads` | 2 | ONNX CPU threading control. |
| `phone_confidence`, `person_confidence` | 0.35, 0.50 | Minimum detection scores. |
| `person_min_area`, `person_min_height` | 0.015, 0.12 | Minimum normalized person-box area/height. |
| `phone_min_area` | 0.0005 | Minimum normalized phone-box area. |
| `nms_iou` | 0.45 | Detection nonmaximum-suppression overlap threshold. |
| `face_min_area` | 0.01 | Minimum normalized face area. |
| `head_down_pitch_degrees` | 14.0 | Lower bound for separate downward posture cue. |
| `head_down_max_yaw_degrees`, `head_down_max_roll_degrees` | 15.0, 12.0 | Posture cue's lateral/roll limits. |
| `frame_stale_seconds`, `result_stale_seconds` | 2.0, 2.0 | Capture/result freshness limits. |
| `heartbeat_stale_seconds` | 5.0 | Vision-worker heartbeat limit. |
| `raised_face_margin` | 0.6 | Face-relative raised-phone geometry margin. |
| `raised_person_top_fraction` | 0.45 | Upper person-box region for raised-phone geometry. |

### Gaze collection and fit: `[vision]`

| Key | Baseline | Meaning |
| --- | --- | --- |
| `calibration_samples` | 20 | Minimum valid samples per target. |
| `calibration_max_samples` | 240 | Bounded retained target samples. |
| `calibration_preparation_seconds` | 2.0 | Target preparation interval. |
| `calibration_collection_seconds` | 3.0 | Minimum nominal collection duration. |
| `calibration_max_collection_seconds` | 6.0 | Fixed maximum target collection duration. |
| `calibration_debug` | false | Developer diagnostics; incompatible with enabled protection. |
| `calibration_max_spread` | 0.12 | Maximum accepted target spread. |
| `calibration_eye_noise_floor` | 0.01 | Constant assumed uncertainty in eye-width units. |
| `calibration_min_signal_noise` | 3.0 | Multiplier for the constant uncertainty floor. |
| `calibration_pixel_uncertainty_multiplier` | 0.8 | Pixel-resolution uncertainty assumption; not measured tracker noise. |
| `calibration_offscreen_radius_fraction` | 0.30 | Off-screen reference core size. |
| `calibration_center_radius_fraction` | 0.45 | CENTER reference region control. |
| `calibration_min_separation` | 0.08, legacy | Accepted for old files; superseded by measured eye-space separation checks. |

### Positioning: `[vision.alignment]`

| Key | Baseline | Meaning |
| --- | --- | --- |
| `guide` | `[0.18, 0.08, 0.82, 0.92]` | Fixed normalized guide bounds in the source frame. |
| `min_face_width_pixels`, `min_face_height_pixels` | 140, 160 | Required source-image face dimensions. |
| `min_eye_width_pixels` | 32 | Required width of each eye in source pixels. |
| `min_quality` | 0.45 | Minimum alignment measurement quality. |
| `max_yaw_degrees`, `max_pitch_degrees`, `max_roll_degrees` | 15, 15, 12 | Frontal positioning limits during calibration. |
| `stable_seconds`, `min_stable_samples` | 0.75, 3 | Minimum stable interval and unique samples. |
| `max_center_drift`, `max_scale_change` | 0.02, 0.10 | Allowed positioning drift/relative scale change. |
| `max_sample_gap_seconds` | 0.5 | Maximum continuity gap for stability. |

### Optional features

| Section / key | Code baseline | Meaning |
| --- | --- | --- |
| `audio.enabled` | false | Start optional local microphone monitoring. |
| `audio.sample_rate` | 16000 | Mono capture sample rate. |
| `audio.voice_duration_threshold` | 2.0 | Sustained energy duration before a review event. |
| `audio.energy_threshold` | 0.15 | Legacy fallback increment, not adaptive absolute threshold. |
| `audio.adaptive_calibration` | true | Show ambient/speak calibration when audio is enabled. |
| `audio.min_energy_threshold`, `max_energy_threshold` | 0.05, 0.40 | Adaptive/manual absolute RMS limits. |
| `exam.identity.selfie_verification_enabled` | false | Require reference selfie and periodic shape comparison. |
| `exam.identity.impersonation_threshold` | 0.40 | Unitless face-shape residual threshold. |
| `exam.identity.periodic_check_interval_seconds` | 30.0 | Comparison interval. |
| `security.system_checks.block_multimonitor` | false | Block start for more than one Qt-visible screen. |
| `security.system_checks.clipboard_guard_enabled` | false | Clear changed clipboard during exam; log without content. |
| `security.system_checks.vm_check_enabled` | false | BIOS/vendor heuristic; informational review result. |
| `vision.accessories.earphone_detection_enabled` | false | Experimental ear-adjacent appearance cue. |
| `vision.accessories.min_ear_yaw_trigger` | 12.0 | Minimum yaw for that heuristic. |
| `reporting.generate_pdf_report` | false | Write local report after session completion. |
| `reporting.send_pdf_to_telegram` | false | Upload report only with remote and Telegram enabled. |
| `reporting.report_filename` | `exam_integrity_report.pdf` | Plain safe PDF filename. |
| `remote.enabled`, `telegram_enabled` | false, false | Dispatcher and Telegram switches. |
| `remote.webhook_url`, `webhook_token` | Empty | Optional HTTP(S) destination and bearer token. |
| `remote.telegram_bot_token`, `telegram_chat_id` | Empty | Private bot credential and intended recipient. |
| `remote.max_queue_size` | 50 | Maximum pending remote copies. |
| `remote.upload_timeout_seconds` | 5.0 | Timeout passed to each HTTP request. |

Do not lower gaze, alignment, or freshness safeguards only to make a particular
trial pass. Use the numerical diagnostics and a separate new validation pass.
Configuration validation rejects invalid ranges, types, and unknown optional
settings; an error at startup is preferable to silently using a misspelled option.

## 11. Optional identity and system checks

Reference selfie capture uses a fresh matching frame/face result and saves a
256-pixel-square JPEG linked to the candidate. Periodic comparison aligns
normalized face landmarks and measures a Procrustes shape residual. These are
**not trained identity embeddings**. Expression, lighting, pose, and tracking
errors can cause mismatch. More than three consecutive valid mismatches produce
`IMPERSONATION_SUSPECTED` through the review pipeline; invalid comparisons reset
the streak and are not evidence of a different identity.

Screen counting uses Qt-visible displays; with its toggle enabled, more than one
blocks exam start. It is not complete virtual-display detection. Clipboard guard
clears changed/nonempty clipboard contents during the exam and records
`CLIPBOARD_ACCESSED`, without storing copied text. VM checking uses Windows
BIOS/vendor hints and can record `VIRTUAL_MACHINE_DETECTED`; a match does not
automatically block the exam. Unavailable enumeration is not a positive finding.

The earphone option inspects patches near the cheek/ear region and requires a
short sequence of appearance anomalies. MediaPipe does not supply verified ear
anatomy for this task. Hair, glasses, skin, and shadows can produce similar cues.
`EARPHONE_SUSPECTED` therefore remains an unvalidated review heuristic.

These options do not turn on Windows protection. See
[PROCTORING_EXPANSION.md](docs/PROCTORING_EXPANSION.md) for the implementation and
separate operator checks.

## 12. Evidence, privacy, and PDF reports

Started sessions normally create the following under the configured output root:

```text
sessions/<session_id>/
├── session.json              # Session identity, candidate and setup metadata
├── config.json               # Public configuration with secrets omitted
├── events.jsonl              # Session header and event/lifecycle records
├── summary.json              # Final result, timings and completed event details
├── snapshots/<event-id>.jpg  # Optional successfully written event snapshots
├── reference_face.jpg        # Optional explicitly captured reference selfie
├── remote_warnings.jsonl     # Optional local delivery failures
└── exam_integrity_report.pdf # Optional final report
```

An explicitly requested reference selfie can create its session directory before
the exam starts. Some optional files exist only when the relevant feature runs.
Normal sessions do not persist continuous frames/video, audio samples, or gaze
calibration samples. Explicit developer numerical export is a separate local
action; live eye close-ups are not saved.

A bounded background writer saves one activation snapshot per event when enabled
and a suitable frame is available. Sustained updates do not repeatedly capture it.
The journal may initially refer to queued evidence; the final summary contains
successful snapshot paths and writer/drop errors. Simultaneous events may have
separate event files even when their captured image content is identical.

PDF generation runs in a background Qt document worker after local finalization.
The report includes candidate/session details, any reference selfie, and one
timeline row per review event. Snapshot thumbnails appear directly in the table,
preserving aspect ratio; missing images show No capture. Times use `HH:MM:SS` in
the recorded timestamp's offset, with full timestamps retained in JSON/JSONL.
Identical image content/overlays reuse a resource. There is no repeated large-image
gallery. A typical short session fits one or two pages; long event lists naturally
need more. Report overlays do not modify original JPEG evidence.

The report's rule-based score is:

```text
max(0, 100 - 30*phone_events - 15*audio_events - 10*gaze_events - 50*identity_events)
```

Each distinct event ID counts once. Phone-visible and phone-raised are separate
events and may each contribute. This score summarizes a configured review rule;
100 does not establish absence of misconduct or uninterrupted monitoring.

The PIN, bot credentials, webhook token/full token-bearing URL, and complete
external exam URL are omitted from saved public configuration. The editable
operator TOML still contains any configured secrets. Local files are not encrypted
at rest and no automatic evidence-retention policy is implemented. Keep session
folders and private configs under the institution's intended access/retention rules.
Enabled remote delivery discloses the specified metadata/evidence as described below.

## 13. Telegram and webhook delivery

The remote dispatcher is optional. It never replaces local recording. Edit the
existing `[remote]` table; this example intentionally contains no credentials:

```toml
[remote]
enabled = false
webhook_url = ""
webhook_token = ""
telegram_enabled = false
telegram_bot_token = ""
telegram_chat_id = ""
max_queue_size = 50
upload_timeout_seconds = 5.0
```

For Telegram, supply the bot token and intended chat/channel ID, grant the bot
permission to send there, then enable both remote and Telegram. For a webhook,
provide its HTTP(S) URL and enable remote; a nonempty token becomes a bearer
Authorization header. HTTPS is preferable for a remote recipient. Both destinations
can run together. A disabled dispatcher creates no network worker thread.

| Remote type | Information sent |
| --- | --- |
| `session_start` | Candidate name/group, session ID, start timestamp. |
| `violation_alert` | Review-event code/description, candidate, duration, confidence when available, timestamps, and an existing snapshot when available. |
| `session_end` | Candidate, session ID, completed summary counts/timing/end reason. |
| PDF delivery | Final report via Telegram `sendDocument`, only when all required flags are enabled. |

`violation_alert` is a wire-format name; it does not mean confirmed cheating.
Telegram uses `sendPhoto` for a usable JPEG and `sendMessage` otherwise. Webhooks
receive JSON, or multipart fields `payload` (JSON string) and `photo` for an existing
JPEG. No image is captured solely for remote delivery. To send the PDF, enable
`reporting.generate_pdf_report`, `reporting.send_pdf_to_telegram`,
`remote.enabled`, and `remote.telegram_enabled`.

One daemon handles requests and file reads. Producers use a nonblocking bounded
queue. A full queue drops the new remote copy; timeout/network/HTTP errors are
logged locally without pausing the exam or blocking local writes. Telegram failure
does not prevent the webhook attempt. Redirects are rejected. There are no
automatic retries or durable outbox: reconnecting does not replay missed alerts.
Shutdown waits at most two seconds for the worker; queued work may be dropped.
This is best-effort delivery, including final summaries and PDF uploads.

Enabling delivery sends candidate identifiers, review data, and selected existing
photos/report to the configured recipient, and through Telegram when selected.
Use an intended university/proctor destination and inform participants. Tests mock
HTTP; actual receipt requires a deliberate operator test with a controlled identity.
See [REGISTRATION_REMOTE.md](docs/REGISTRATION_REMOTE.md) for payload details.

## 14. Languages

Choose **EN**, **RU**, or **ҚАЗ** in the top-right header. Open widgets retranslate
without restarting or clearing answers, calibration, timers, or registration.
The selection persists for the current application session and does not rewrite
TOML. To set the next startup language:

```toml
[ui]
language = "ru"
```

Supported codes are `en`, `ru`, and `kk`; the code fallback is English. Canonical
event/gaze identifiers such as `phone_visible`, `gaze_down`, and `UNKNOWN` remain
ASCII in background logic and persistence. Raw developer diagnostics remain
technical. Custom quiz text and external websites retain their own content/language;
only the bundled demo quiz has supplied question translations.

## 15. Models and CPU performance

The required local files are `yolo11n.onnx` and `face_landmarker.task`. Their sources,
pinned hashes, and license notes are in [models/README.md](models/README.md).
The application does not download them at runtime. Missing/unreadable models
produce unavailable monitoring and cannot silently start an unmonitored exam.

YOLO supports a COCO raw-output, float32 NCHW detection model with one output
`[1,84,N]` or `[1,N,84]`, batch one, and no integrated NMS. COCO class 0 is person
and 67 is cell phone. Custom class orders, segmentation/pose outputs, quantized
exports, and end-to-end NMS models are not supported substitutions.

Camera capture keeps the latest frame; inference runs on background workers
without an accumulating frame backlog. YOLO is scheduled up to 5 Hz and face
processing up to 12 Hz by baseline settings. Combined observations require fresh
YOLO/face results; a face-only update cannot renew old phone evidence. Preview
boxes may trail the displayed frame by an inference interval.

CPU ONNX Runtime is the normal install and the portable runtime. `prefer_gpu = true`
can select a separately provisioned compatible CUDA provider if available; provider
initialization/execution failure falls back to CPU. MediaPipe remains CPU-based.
The flag alone does not install CUDA or an ONNX GPU package.

Benchmark the demonstration machine before adjusting input size/rates:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark.py --camera-only --seconds 10 --output artifacts\camera-test.json
.\.venv\Scripts\python.exe scripts\benchmark.py --seconds 20 --output artifacts\benchmark-cpu.json
```

The benchmark forces CPU and reports capture FPS, mean/p95 YOLO and MediaPipe
latency, combined monitoring FPS, CPU use, and memory where available. It saves
metrics only. `--models-only` uses a labeled blank-frame diagnostic and does not
measure webcam/human performance. A fixed-shape ONNX model ignores a smaller
configured dynamic input size; inspect the reported effective dimensions before
expecting a speed change. Reduce inference rates/input size as supported, while
keeping freshness limits consistent with observed timing.

## 16. Architecture and project structure

```text
assets/                       Native quiz
config/                       Editable source configurations
docs/                         Operator guides and implementation notes
models/                       Local model binaries and manifest
scripts/                      Model setup, audit, benchmark and Windows build
src/proctoring/
  __main__.py                 Source entry point
  desktop.py, runtime.py      Portable entry point and bundled-resource paths
  config.py, settings.py      Validated configuration
  controller.py              Session, detector, persistence and UI coordination
  session.py, clock.py        Monotonic lifecycle and timer
  domain.py                  Stable event/observation types
  exam/                      Native quiz model
  events/                    Threshold/hysteresis state machine
  vision/                    Capture, inference, calibration, posture and health
  audio/                     Background RMS monitor and microphone calibration
  security/                  PIN, optional checks, Windows helper and recovery audit
  storage/                   Session/evidence writers, PDF and remote dispatch
  ui/                        Registration, calibration, audio, exam and summary widgets
  locales/                   English/Russian/Kazakh catalogs
tests/                        Deterministic regression suite
experiments/                  Isolated research prototypes
build/, dist/, artifacts/     Generated build and verification outputs
sessions/                    Generated evidence, depending on configured output path
```

Vision produces normalized observations, not alerts. The controller routes them
to the existing event engine and health/recovery lifecycle. The same event-engine
class processes audio through a separate stream so an audio sample cannot clear
or extend camera evidence. UI, native protection helper, capture/inference, snapshot
writer, PDF worker, and remote dispatcher have separate responsibilities.
Local evidence remains primary when network delivery fails.

The `experiments/gaze_tracking_demo/` experiment is isolated from production,
with its own environment and upstream dependency requirements. Its dlib build
needs the documented Windows compiler prerequisites; the portable application
does not depend on successfully installing that experiment.

## 17. Tests and validation

Run deterministic tests from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Coverage includes threshold boundaries, deduplication/clearing, monotonic timer,
14.9/15.0-second recovery, overlapping pause reasons, camera freshness, inference
mapping, geometry/calibration, UI/localization, audio calibration and unavailable
devices, session evidence, remote failures with mocked HTTP, PDF output, packaging,
and protection recovery logic. Native audit/shortcut tests are separate commands.

The latest packaging verification recorded on **October 7, 2026** was **1,697
automated tests passed**, eight of eight recovery checks in the source audit,
eight of eight in the packaged audit, and a successful native packaged smoke test.
The smoke test used generated/blank image input for CPU model inference, local-only
WebEngine, audio imports, and PDF generation. These are recorded build results;
editing a README does not constitute a new test run or a new hardware validation.

For portable startup verification without camera/microphone, network upload, or
keyboard blocking:

```powershell
.\LocalProctoring.exe --package-smoke-test C:\path\to\verification-output
```

Separately rehearse real registration, actual-camera calibration, normal reading,
eyes-only targets, head-down posture, microphone quiet/speech/noise, face absence,
phone/person examples, physical camera disconnect, short/long recovery, PIN exit,
and emergency exit. Validate ordinary Windows use after release. Keep restrictions
and remote delivery disabled during initial detector-quality checks. Automated
success does not establish human gaze accuracy or successful Telegram receipt.

## 18. Build the Windows executable

Build on Windows from the prepared project venv with local models. The build needs
the browser add-on and the official PyInstaller tool as well as the normal runtime:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.lock
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.22.3
.\.venv\Scripts\python.exe scripts\build_windows.py
```

Output is `dist/LocalProctoring/LocalProctoring.exe` plus `config.toml`. The verified
October 7 build was approximately 324 MiB; a rebuild can differ with dependency
versions. The builder copies the protected-demo configuration, rewrites portable
asset/output paths, and preserves its settings/credentials in the external config.
The private config is not embedded in the executable. Review it before distributing.

An existing distribution `config.toml` is preserved on rebuild. Only intentionally
regenerate it with:

```powershell
.\.venv\Scripts\python.exe scripts\build_windows.py --replace-config
```

Build metadata, installed versions, model provenance, and dependency notices are
collected under `build/portable` and bundled as appropriate. The new executable
requires its own valid recovery audit. The console-capable bootloader supports
private helper pipes; an owned console is hidden on double-click.
See [WINDOWS_BUILD.md](docs/WINDOWS_BUILD.md) for full packaging behavior.

## 19. Troubleshooting

| Symptom | Check / next action |
| --- | --- |
| EXE startup is initially slow | Allow temporary extraction of Qt/models; use a writable location and sufficient disk space. Run from PowerShell to see startup errors. |
| Configuration cannot load | Check the selected file, TOML quoting, duplicate sections, required core keys, and the exact validation error. Restart after edits. |
| Protected startup is refused | Keep Windows unlocked/desktop active and release the emergency chord. Close other instances and rerun the audit; inspect its failed check instead of editing the report to force a pass. |
| Webcam is unavailable | Close other camera users, check Windows permissions/camera index, try the supported backend settings, and use Retry camera once previous workers release resources. |
| Requested 720p becomes 640×480 | The driver negotiated another mode. Inspect actual dimensions and source eye widths; preview enlargement does not increase measurement resolution. |
| Calibration will not collect | Read the alignment reason: centering, face/eye size, both eyes, pose, stability. Retry the affected target; preserve comfortable posture. |
| Calibration fits fail | Inspect per-axis separation/spread, pixel/constant/spread contributions, and rejected samples in safe diagnostic mode. Do not force ready or count UNKNOWN as correct. |
| DOWN becomes UNKNOWN | Inspect valid iris measurements, closure/aperture reasons, and reference proximity. Separate eye availability from the independent head-down posture cue. |
| Glasses affect measurements | Inspect live matching-frame eye close-ups and lighting/reflections; there is no validated automatic glare diagnosis. Keep necessary corrective glasses. |
| Mic widget is absent | Set `audio.enabled = true` in the file actually launched, then restart. The packaged protected config may preserve false. |
| Mic unavailable / no test spike | Check device/permissions/gain, select Retry microphone, reduce background noise, and repeat quiet/speak calibration. The camera and timer remain operational. |
| Mic ready disappears after slider change | A manual change invalidates the previous verification. Recheck the newly chosen threshold. |
| Low monitoring FPS / recurrent stale pause | Run the CPU benchmark, inspect fixed/dynamic model size, reduce scheduling load, and choose freshness bounds supported by the measured machine. |
| External login/link is blocked | Add only the intended exact authentication host to `allowed_domains`; popup-dependent SSO may remain incompatible. |
| Browser works but LMS timer continued during a pause | The app pauses its local timer; the website controls its own server timer. |
| No Telegram/webhook receipt | Check explicit enable flags/recipient permissions and local `remote_warnings.jsonl`. Delivery is best effort and missed items are not replayed. |
| No PDF | Enable local reporting, allow background finalization, and inspect report status/output permissions. Telegram PDF upload requires its separate flags. |
| No snapshot on an event | It may have no applicable frame, be synthetic/security-only, have capture disabled, or encounter a bounded-writer error. Inspect the final summary. |
| `cv2` or another import is missing | Use the project's `.venv` interpreter and install the appropriate lock; do not use the isolated gaze experiment's venv for production. |

A common microphone edit is:

```toml
[audio]
enabled = true
sample_rate = 16000
voice_duration_threshold = 2.0
energy_threshold = 0.15
adaptive_calibration = true
min_energy_threshold = 0.05
max_energy_threshold = 0.40
```

Replace values in the existing table, rather than appending a duplicate `[audio]`.
Do not paste private configuration or evidence into public issue reports.

## 20. Limitations and further documentation

Eyes occupy few source pixels on many webcams. Glasses, eyelid occlusion, head
motion, lighting, camera placement, and normal reading can overlap gaze targets.
Passing calibration is not proof of accurate classification. A frozen camera image
repeated as apparently fresh driver frames may evade freshness detection. YOLO
can miss small/occluded phones and confuse posters/screens with people or objects.
Raised-phone, audio, identity-shape, VM, and accessory findings all require context
and human review. The Windows layer is a controlled demonstration, not a secure
operating-system boundary.

No project-wide LICENSE file is currently supplied. Do not infer a permissive
license from repository availability. Model and dependency terms still apply;
the YOLO export's source card identifies AGPL-3.0. Retain applicable notices and
review redistribution terms, especially for the bundled executable. Model sources
and checksums are documented in the manifest, and build dependency notices are
collected with the portable metadata.

| Guide | Contents |
| --- | --- |
| [Windows build](docs/WINDOWS_BUILD.md) | Portable files, audit, smoke test, rebuild behavior. |
| [Microphone check](docs/AUDIO_CHECK.md) | Ambient/sound test, manual sensitivity, hardware follow-up. |
| [Registration and remote delivery](docs/REGISTRATION_REMOTE.md) | Candidate records, wire payloads, failure/disclosure behavior. |
| [Optional checks and reports](docs/PROCTORING_EXPANSION.md) | Identity/system/audio/accessory/PDF details. |
| [Guided collection](docs/CALIBRATION_COLLECTION.md) | Automatic targets, bounded extension, local retry. |
| [Face alignment](docs/FACE_ALIGNMENT.md) | Positioning geometry and readiness. |
| [Gaze diagnostic workflow](docs/GAZE_DIAGNOSTIC_RUN.md) | Numerical export and separate validation. |
| [Eye visibility check](docs/EYE_VISIBILITY_CHECK.md) | Close-ups, aperture, and unknown measurements. |
| [Guarded DOWN](docs/GUARDED_DOWN.md) | Updated pixel gate and guarded aperture supplement. |
| [Head-down posture](docs/HEAD_DOWN_POSTURE.md) | Independent posture evidence and test sequence. |
| [Windows implementation](docs/STAGE4_IMPLEMENTATION.md) | Helper/recovery architecture. |
| [Windows test matrix](docs/STAGE4_TEST_MATRIX.md) | Native protection checks and operator gaps. |
| [Offline models](models/README.md) | Sources, hashes, format compatibility, license notes. |

Older investigation guides record the behavior/results of their named stage and
may describe superseded settings. Use this README, current configuration, and
the current implementation together; historical numerical results must not be
presented as new independent human validation.
