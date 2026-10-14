# Electron migration map

Stage 1 is accepted. **Stage 2 implements the real unprotected exam workflow**
through existing Python services. Operator verification is recorded separately
below; automated or injected measurements are not evidence of human gaze accuracy.
The legacy `python -m proctoring` entry point remains available. Stage 3 protection
and packaging work is tracked in [ELECTRON_PROTECTION.md](ELECTRON_PROTECTION.md).
It requires a current Electron-specific native recovery audit before arming;
the verification gates are still pending. The records below describe Stage 1/2.

## Stage 2 implementation checklist

- [x] Registration, selected-camera reference and real gaze collection.
- [x] Authoritative readiness, native quiz, timer and durable event presentation.
- [x] PIN pause/recovery/end, submission, finalized summary and restricted evidence/report access.
- [x] Isolated external-exam view, native bounds/focus and navigation policy.
- [x] Regression/integration tests, connected-screen inspection and separate safe operator runs.

The Stage 1 sections below are a historical implementation/verification record.
Their setup-only scope and disabled exam commands describe Stage 1, not the current
Stage 2 entry point. Current behavior follows this section.

## Stage 2 implementation and launch

Run from the existing development environment (Node 24+, existing Python `.venv`,
local YOLO and MediaPipe models). No new installer or release is produced:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\desktop'
npm run build
npm start -- --config config/default.example.toml
```

The config path resolves from the repository root even when npm runs in `desktop/`.
The default is the public example: protection and remote delivery disabled; demo
PIN `739261`. Other unprotected TOML files work without being rewritten. Deliberately
configured remote delivery remains owned by Python; the UI lists enabled destinations.
Do not run the legacy frontend against the same devices at the same time.

`npm run dev -- --config config/default.example.toml` uses the live backend with
Vite. `npm run fixture` and browser-only `npm run ui` remain separate, explicitly
labeled presentation fixtures and cannot run capture, an exam or evidence actions.

### Ownership and state

- `desktop_bridge/workflow.py` adapts `AppController`; it does not construct a
  hidden Qt MainWindow. QGuiApplication and its event loop remain alive for camera,
  Qt signals and existing PDF generation. One selected camera and one microphone
  owner span setup and exam. Changing camera invalidates its reference/gaze;
  changing microphone invalidates only its audio calibration.
- Registration/optional reference use existing validation and storage. Setup audio
  does not produce exam events. Quiz answer keys remain backend-only before finish.
  Answer revisions reject stale conflicting selections; duplicate start/end does
  not create another session or remote delivery.
- `calibration_flow.py` orchestrates the existing alignment, bounded collection,
  sample quality and production fit. It does not change thresholds, select a debug
  classifier, or infer gaze from an animation. A target token is acknowledged after
  rendering, then Python starts its monotonic preparation interval. Source-frame
  timestamps exclude previous-target samples. The native host supplies display,
  content, scale and zoom geometry; moving/resizing across incompatible geometry
  requires a new baseline. CENTER is the physical display center; other targets
  explicitly refer beyond physical screen edges. Actual Windows DPI transitions
  still require hardware validation.
- Face alignment, accepted sample count and final fit remain separate. Failed fit
  cannot start an exam. Back to devices preserves compatible references/fit; a
  camera change or explicit new baseline invalidates them. Retained attempt IDs and
  numerical diagnostics remain visible without making the developer validation
  sequence a normal onboarding step.
- Python owns all timing, event thresholds, scoring, PIN checks, summary and report
  generation. Audio continues to count qualifying captured sample duration (not
  JavaScript elapsed time), retains the calibrated gain/adaptive threshold, flushes
  setup/cross-boundary buffers, and keeps the existing 0.75 s clearing behavior.
  Optional microphone loss does not pause the exam. UNKNOWN gaze remains distinct
  from face absence or vision failure. The exact canonical raised-phone label is
  retained in English.

### Reconnection, interruption and cleanup

Snapshots include session identity, increasing sequence, prerequisites, answers,
timer, pause reasons and a durable journal cursor. Large event histories use bounded
`events.get` pages; snapshots show the recent 30, explicitly mark truncated summary
lists, and point to the full journal. React merges updates by stable event ID; it
does not run a second event engine or silently fall back to fixtures.

Minimizing, losing or stalling the exam presentation adds a distinct `presentation`
pause. Reconnect drains the existing journal and acknowledges a delivered snapshot
and cursor before this reason clears. It cannot clear an independent proctor pause
or monitoring-recovery PIN requirement. A dead backend is not restarted into a
supposedly uninterrupted session. Camera/CV recovery retains the existing
14.9 s automatic / 15.0 s PIN boundary and controlled-clock tests. During an active
exam, a failed selected Qt camera is reopened only after its old capture thread
has released, with a monotonic retry throttle. The same camera identity, fit,
reference and original outage clock survive. Fresh frames and vision results,
not a successful open request, establish recovery. Explicit stop/end suppresses
retry; another camera is never substituted. A driver that does not release its
thread, or a device that returns with a different ID, remains paused.

Native window close during an exam opens the PIN end dialog. Normal native quiz
submission remains a separate action. `Ctrl+Shift+Alt+Q` requests safe emergency
termination, including while a PIN dialog or remote content has focus. This is an
application-level unprotected escape, **not** the Stage 3 independent hook-recovery
audit. OS clipboard clearing is deferred in this Electron build; read-only system
checks remain. No kiosk, keyboard blocking, forced foreground or policy changes
are enabled.

EOF/normal shutdown finalizes available local records and closes only owned workers.
The Qt loop receives bounded extra time for an existing PDF worker. A PDF that
cannot finish before shutdown is not labeled successful: `PDF_INTERRUPTED`/exit 4
preserves the already-saved JSON records. A stuck media worker similarly returns
an explicit cleanup failure. The Electron parent uses bounded owned-process cleanup.

### External exam and evidence boundaries

`desktop/electron/external.ts` owns an isolated WebContentsView: no application
preload, Node, IPC bridge, persistent login partition, camera/microphone permission,
downloads, popups or developer-tools shortcuts. Document navigation, redirects and
subframes use parsed HTTP(S) URLs and exact allowlisted hosts. This is not a filter
for every subresource request and not a verified LMS authentication integration.
Cross-domain login flows need deliberate configuration; TLS checks are never bypassed.

The native view loads only after Python starts the exam. Bounds reserve trusted
header/monitoring space. Pause, PIN, summary, minimization and stale layout leases
hide it at the native level, not through React z-index. Hiding preserves page state.
An external page cannot authorize local completion or invent scores; ending local
monitoring is separate from submitting work to the remote site.

Evidence open/save requests use the current session ID and event ID, never a
renderer-supplied file path. Python resolves only saved files under that session,
checks type/signature/size and refuses missing evidence. Main exposes deliberate
open/save actions only. Existing snapshots, event journal, summary/PDF and optional
delivery are reused; no additional video/audio recording is introduced.

### Stage 2 verification record

Automated checks completed so far:

- Python full regression: **1,887 passed** (48.56 s), including final navigation,
  camera-retry, shutdown, timing, evidence and report regressions. Fifteen added
  camera recovery tests cover ownership, startup grace, preserved references,
  outage onset, retry suppression, a terminal late-frame race and the 14.9/15.0 s
  recovery boundary.
- Electron bridge/security/policy: **14 passed**, including a real Python process
  round-trip, owned-child abrupt death, control-pipe EOF and prevention of silent
  backend replacement. No capture or calibration bypass is used in these checks.
- Playwright renderer: **25 passed** (18 retained plus 7 Stage 2 tests). New tests
  use explicitly injected authoritative-shaped state, not physical camera/audio.
  They cover fit failure, registration/reference, quiz revisions, stable event IDs,
  PIN/reconnect, report failure, EN/RU/KK and connected-screen layouts.
- Native external test `node scripts/test-external.mjs`: passed against a controlled
  loopback fixture, including denied permissions/downloads/popups, allowed and blocked
  redirects, blocked foreign subframe, pause/PIN hide retaining an answer, stale
  layout hiding and emergency input. No real academic credentials are used.
- `npm run build`: passed. Non-fatal Vite future-loader and bundle-size advisories
  remain; they do not affect this local source build.

Screenshots and numerical native-test results are under ignored
`artifacts/electron-stage2/`. Layout inspection covers 1280×720 EN, 1366×768 RU,
1920×1080 KK and a 640×360 RU viewport equivalent; this does not test physical
Windows scaling changes.

`node scripts/verify-stage2.mjs` launches the normal production-gate flow with a
safe public-example-derived config and records numerical state/event IDs only. It
never selects devices, authorizes calibration, starts or submits an exam automatically.
Its observer polls keep control traffic alive, so this harness alone is not a
renderer heartbeat-loss test.

**Operator run 1 (13 October 2026, local time): completed by normal quiz submission.**
The operator selected devices, performed microphone calibration, supplied test
registration details, captured the reference and completed the actual four-target
production calibration. Collection required retries after movement; no fit or
positioning thresholds were changed and no gate was bypassed. The existing fit
eventually accepted all four targets. This confirms workflow integration, not gaze
classification accuracy across people, glasses or conditions.

- Actual camera source: 640×480. Opened microphone: 48 kHz, mono. Measured application
  gain 8.0 and adaptive threshold 0.0019423306400893241 survived exam startup; these
  are run measurements, not new defaults.
- Six quiz answers; Python active duration 71.531 s; end reason `completed`.
- Five review events: `VOICE_DETECTED`, `gaze_right`, `phone_visible`, `phone_raised`,
  `gaze_left`. Audio event `audio-event-000001` had 2.1 s of qualifying captured
  activity within a 3.15 s episode. The operator confirmed seeing warnings.
- All five stable IDs matched the journal, live React summary and saved summary.
  Five JPEG snapshots, reference photo, session metadata and a completed 91,584-byte
  PDF were saved; no storage/snapshot errors. No audio recording or remote delivery.
- Source records: `sessions/session-11231c88aff94f4fa6d1b77c2988b4f6/`. Verification:
  `artifacts/electron-stage2/operator-run1-result.json` and `operator-summary.png`.
  These remain local ignored files, not public fixtures.
- Native window and its owned Python worker exited after normal summary close.

**Operator run 2: PIN pause/end passed; physical reconnect exposed a defect.**
The operator paused with the PIN at 9.141 s, then unplugged/replugged the webcam.
The old Qt capture worker exited and the adapter did not reopen it. The exam
correctly remained paused, latched the long-interruption PIN requirement and kept
the active timer at 9.141 s. The operator successfully used PIN End session.
Summary end reason was `proctor_ended`; its 58,993-byte PDF completed and the owned
processes exited. Local records are in
`sessions/session-b6f5883dbd0146488e58938d835be9e3/` and
`artifacts/electron-stage2/operator-run2-result.json`.

The targeted fix adds the selected-camera retry described above and prevents an
old heartbeat from immediately timing out a new open attempt.

**Operator run 3: physical short/long reconnect and PIN recovery passed.**
The operator repeated microphone calibration, reference capture and the actual
four-target gaze fit. Rejected attempts remained rejected (including CENTER/DOWN
0.0276 below the 0.0300 gate); the later fresh baseline passed without changing
thresholds. The same session and accepted calibration survived both reconnects:

- Short interruption: 11.532 s in the backend journal, timer frozen at 15.781 s,
  then fresh monitoring and automatic resume.
- Long interruption: 31.734 s, timer frozen at 48.281 s, fresh monitoring restored
  but `recovery_pin` remained until a successful proctor PIN resume.
- PIN end produced `proctor_ended` at 76.250 s of active exam time. The operator
  confirmed both previews/recoveries and PIN controls worked. The saved traces
  separately show proctor pause in run 2 and recovery PIN resume/end in run 3.
- Two saved event snapshots, no storage/snapshot errors, and a completed
  62,294-byte PDF. Normal close left zero owned demo Electron/Python processes.
- Local records: `sessions/session-a2ba38f9a9254ef3bb4e0cf1f95eb52d/` and
  `artifacts/electron-stage2/operator-run3-result.json`; not public test fixtures.

These are observed outage durations, not a cable-timed test of the exact 15.0 s
boundary; that boundary is covered with a controlled clock. A final read-only
review reproduced an additional late-frame race in memory: a final frame can clear
the camera error after its thread has exited. The final patch removes only the
error-string prerequisite from retry, retaining failed-monitoring, same-source,
finished-thread, consent and lifecycle guards. Its regression passes; that race
was not observed on this operator's camera and this last guard change was not
loaded in the already-running human test.

Actual Windows DPI transitions, active-exam process crashes and arbitrary
university LMS authentication remain separate manual checks. These runs validate
workflow and recovery on this device, not general gaze accuracy.

## Existing application, inspected before migration

| Current surface / transition | Owner and important behavior | Electron parity stage |
| --- | --- | --- |
| Devices before registration | `ui/devices.py`, `devices.py`: friendly catalog; explicit camera test; missing/ambiguous device handling; stable backend-specific keys; QSettings preferences | 1: live setup adapters |
| Quiet → normal speech → microphone result | `ui/audio_check.py`, `audio/monitor.py`, `audio/gain.py`: one worker, session-only application gain, real RMS/progress/reasons, same-device calibration retained | 1: live setup adapters |
| Candidate form and reference photo | `ui/registration.py`, `controller.py`: required fields, explicit preview/capture, fresh frontal single face, reference persistence before readiness | 2; Stage 1 is presentation only |
| Gaze calibration | `ui/calibration.py`, `ui/screen_target.py`, `vision/collection.py`, `vision/calibration.py`: readiness, preparation, bounded collection, backend fit/retry, retained diagnostic attempts | 2; Stage 1 is presentation only |
| Ready to begin | `ui/window.py`, `AppController.start()`: registration/reference, fresh monitoring, accepted calibration, device/system checks and configured protection | 2; no Stage 1 start command |
| Native quiz or external exam | `exam/quiz.py`, `ui/window.py`, `ui/browser.py`, `browser_policy.py`: Python answers and score for native quiz; external browser loads only at session start | 2; Stage 1 is presentation only |
| Active monitoring and review events | `vision/monitor.py`, `vision/rules.py`, `events/engine.py`, `controller.py`: frame-matched observations, sustained thresholds, deduplication, snapshots/journal | 2; Stage 1 does not create events |
| Pause / recovery / PIN / end | `session.py`, `controller.py`, `ui/window.py`: independent pause reasons and Python monotonic timing | 2 unprotected; 3 protected |
| Summary / local evidence / optional remote delivery | `storage/`, `controller.py`, `ui/window.py`: durable local records, asynchronous snapshots/PDF/delivery | 2; Stage 1 is presentation only |
| Emergency release and recovery audit | `security/`, `scripts/validate_protection.py`, `desktop.py` | 3; existing implementation unchanged |

The current Qt window uses a `QStackedWidget`: registration (when required) → setup/calibration → exam → summary. Paused/recovery state is rendered from the same session, not from a separate timer or session. Devices appear before candidate fields. Selecting a different camera invalidates its reference and gaze calibration while preserving unrelated candidate input. Registration submission does not independently authorize exam start.

## Reuse and Qt boundaries

Modules that remain authoritative and can be reused without translating their algorithms to TypeScript:

- `clock.py`, `session.py`, `domain.py`, `events/engine.py`, `exam/quiz.py`, and `registration.py`: monotonic timing, lifecycle, canonical identifiers, event states and answers.
- `vision/`: source-frame geometry, calibrated eye gaze, independent head pose, YOLO, health and diagnostic calculations. The new renderer must never decide whether a gaze fit passes.
- `audio/gain.py` and the existing `AudioMonitor`: calibrated gain/threshold, stream format, sample validity and measured buffer timing. Setup is not a source of exam events.
- `config.py`, `settings.py`, `vision/settings.py`: validated TOML remains the source of configuration. Neither private configs nor Python dependency locks need migration for this UI stage.
- `storage/session_store.py`, snapshots and remote queue semantics: retain canonical records and asynchronous persistence. No Stage 1 session store or dispatcher is needed.
- `browser_policy.py`, `security/policy.py`, PIN verification and recovery policy: reuse policy where appropriate, but do not assume their native adapters support Electron windows.

**Outside `ui/` does not mean headless.** These are real runtime dependencies:

| Component | Qt dependency | Migration implication |
| --- | --- | --- |
| `devices.cameras()` | `QMediaDevices.videoInputs()` | Keep Qt Multimedia installed and initialized; a camera index from a different API is not the selected Qt camera ID. |
| `vision/qt_camera.py` | `QThread`, `QEventLoop`, `QCamera`, `QMediaCaptureSession`, `QVideoSink`, `QImage` | The named camera backend creates/destroys native resources on its capture thread. Preserve its event loop and source-frame conversion; do not replace it with browser `getUserMedia`. |
| `audio/monitor.py` | `QObject`, `Signal`; sounddevice in a Python worker | A minimal Qt application/event loop still hosts signals. Media processing stays off the renderer and Python GUI thread. |
| `security/system_checks.py` | `QGuiApplication.screens()`, Qt clipboard/thread ownership | Later parity must account for screen enumeration and clipboard ownership. They are not safe to port by deleting Qt imports. |
| `storage/report_generator.py` | `QTextDocument`, `QPdfWriter`, Qt font services | Later PDF completion must keep Qt alive until its background job finishes. |
| `i18n.py` | `QObject`, language-change signal | Reuse EN/RU/KK strings/identifiers; the renderer requires its own presentation subscription, not translated event codes. |
| `ui/window.py` and calibration widgets | `QTimer`, geometry, focus, dialogs, cues | Extract/adapt coordination in Stage 2. DOM lifecycle callbacks cannot replace session timing or calibration collection decisions. |

The Stage 1 Python process therefore hosts a minimal **QGuiApplication event loop**, not the old widget hierarchy. The legacy entry point still hosts QApplication. A single frontend must own devices at a time; close the legacy app before starting Electron, and close Electron before returning to the legacy app.

Instantiating the full `AppController` is not a harmless status query: its constructor can start VM checks and a configured remote dispatcher. The setup-only bridge should compose existing device/capture/audio adapters and expose a small allowlist, without starting a session or invoking reference persistence. A setup-only microphone test may reuse the existing preview-only pattern even when exam audio is disabled; it must retain the separate truth that exam audio is **Not enabled**.

## Contracts that must survive migration

- `Observation` carries a monotonic timestamp, condition/confidence mapping, source, and optional measured `duration_seconds` for audio. Vision observations do not acquire fabricated buffer durations.
- Event states are candidate → active → clearing → closed. CV thresholds and the 0.75-second clearing period remain Python settings. Event IDs, canonical `phone_visible`/`gaze_down`/`VOICE_DETECTED` values and `CENTER`/`LEFT`/`RIGHT`/`DOWN`/`UNKNOWN` remain ASCII data.
- The recently verified audio path sums qualifying **sample durations**, not renderer ticks. Short inter-word gaps retain a candidate without adding silence as evidence; the existing clearing period resets it. Duplicate/stale/overlapping samples cannot increase duration. Preserve exact committed adaptive thresholds, including valid values below 0.05, across same-device startup. A different resolved microphone invalidates dependent calibration.
- `SessionController` sums running monotonic segments. A warning never pauses the exam. Unavailable monitoring freezes time; recovery before 15 seconds can resume only if no other pause reason remains; 15 seconds or longer latches PIN recovery. React never runs a replacement exam clock.
- `VisionResult.frame` matches its result/overlays; requested resolution is not proof of actual source dimensions. A stale result must not be relabeled fresh. Missing gaze is distinct from face absence and pipeline failure.
- Local evidence is `session.json`, append-only `events.jsonl`, redacted `config.json`, atomic `summary.json`, explicit `reference_face.jpg`, optional event snapshots, PDF and optional `remote_warnings.jsonl`. Calibration numerical exports are explicit developer actions, not continuous recording. Stage 1 creates none of these session records.
- The canonical English raised-phone warning remains exactly: **Phone raised — possible screen capture attempt.** Localized presentation does not change the stored event identity.
- Config paths, API aliases and raw exceptions belong in controlled diagnostics; PINs, tokens and credential-bearing URLs never belong in renderer status snapshots.

## Stage 1 bridge boundary and review constraints

The intended local boundary is Electron main → spawned Python → versioned NDJSON over inherited stdin/stdout. No HTTP listener or additional local server is needed for hardware control. A Vite development server is renderer tooling, not the Python control boundary.

Required properties:

1. Fixed command allowlist for status, device catalog/selection, explicit camera start/stop, microphone test/calibration and shutdown. Reject unknown commands, malformed fields, excessive lines, incompatible protocol versions and stale request IDs. No generic Python invocation, filesystem path or shell command from the renderer.
2. Request IDs, explicit errors and complete state snapshots. A renderer reconnect reads current state rather than replaying actions. Backend loss makes controls unavailable; there is no automatic exam or device restart.
3. Device catalogs originate in Python. Preserve Qt device IDs and PortAudio signatures/ambiguity checks. Cached refresh must not terminate an active audio stream; a destructive device rescan needs an explicit action and correct worker shutdown.
4. `nodeIntegration=false`, `contextIsolation=true`, `sandbox=true`; main validates renderer identity, frame and command data. The preload exposes only typed setup operations and bounded state/preview requests. Production CSP permits packaged local assets, not arbitrary remote scripts or application bridge access.
5. Preview and high-rate RMS are replaceable state, separate from reliable request responses. Keep at most the latest image and coalesce level updates. A busy image encoder or blocked preview reader must not delay control/cleanup.
6. Preview uses a separate **memory-only Windows named pipe**, with a random application-created name and authentication token. Main pulls at most one bounded frame packet at a time; Python encodes only a requested latest frame, including its source dimensions, sequence and monotonic capture timestamp in the same packet. Camera pixels are not written to a mailbox file, stdout, sessions or logs. The renderer chooses neither a pipe path nor a token. Stop/device changes invalidate pending old frames; a stalled preview pipe must not block the independent NDJSON control channel or device cleanup.
7. Preview frame age is checked independently of process connectivity. Device changes clear old frames. Resizing/letterboxing uses source aspect ratio and coordinate transforms, not stretched overlays.
8. Fixture mode is visibly labeled on every screen and does not start Python or expose real action paths. Normal mode shows unavailable actions with a reason until their backend command exists. No fixture timer, calibration animation or success state authorizes production behavior.
9. Shutdown closes one camera and one microphone worker. Parent EOF/backend crash/renderer loss must have explicit cleanup behavior; don't launch a second worker to hide failure. Never run this setup process and the legacy frontend against the same device simultaneously.

## Windows protection must remain disabled

The existing protection adapter cannot be attached to Electron unchanged:

- Qt configures `int(self.winId())` with Python's own PID.
- `WindowsProtection.configure_window()` requires the configured PID to equal `os.getpid()`.
- The independent helper's `enable` command requires its exact parent PID; `WindowPolicy` allows that PID, including its Qt modal dialogs. It does not authorize an arbitrary process tree.
- Only Qt UI progress sends a protection heartbeat. Reader/writer/CV threads cannot renew the lease. A stalled UI must release restrictions even when the rest of the process is alive.
- `Ctrl+Shift+Alt+Q` is checked before blocking rules in the independent helper. Recovery also handles parent death, stdin EOF, heartbeat expiry and a stalled helper loop. The parent retains a verified handle to its owned hook process for last-resort release.
- Audit evidence is bound to the relevant runtime/artifacts; a successful old source/EXE audit cannot authorize a different Electron main/renderer/window arrangement.

Stage 3 must introduce and test explicit HWND/PID ownership for the native Electron window and permitted dialogs, without allowing all Chromium processes. Renderer liveness must participate in the relevant lease: a healthy main process cannot conceal a frozen exam renderer. Test renderer stall/crash, main stall/crash, Python stall/crash, helper failure, PIN focus and independent chord recovery. Release restrictions before media shutdown, final storage or reporting. Fullscreen is not shortcut protection.

## Future external-exam surface

Keep trusted local renderer content separate from remote exam pages. Stage 2 should use an isolated `WebContentsView` with no application preload bridge, an isolated session, the existing exact-host navigation policy, redirect/frame/popup handling, permission denial by default, blocked downloads and controlled external links. Subresource and authentication requirements must be documented; an allowlisted URL is not proof that a complete LMS works.

Native child views are not controlled by React z-index. The main process must size, clip, hide or detach the exam view for resize/DPI changes, pause overlays and PIN dialogs so it cannot cover monitoring or recovery controls. Test focus restoration and keyboard interception in native content. An arbitrary page's postMessage or URL change cannot finish a session or invent a score. External exams still require their actual network service; only bundled quiz/assets and local processing can work offline.

## Parity checklist and release gates

Stage 1 delivered checks (test scope and remaining manual checks are detailed below):

- [x] Versioned typed bridge with allowlist, payload bounds, sender checks, structured failures and unavailable states.
- [x] Real catalog and explicitly selected camera preview; backend tests cover consent, stale frames, cleanup and device-switching behavior. Physical camera use was also checked.
- [x] Real microphone level and quiet/speak/result calibration; no exam events or OS gain changes. Same-device calibration is preserved; optional exam-audio configuration remains separate.
- [x] Memory-only named-pipe preview with bounded latest-frame requests and matching metadata, independent of control responses. No preview image files are part of the runtime transport.
- [x] Clearly labeled fixture screens for gaze, ready, exam, paused/PIN and summary; unavailable normal-mode actions stay unavailable.
- [x] Local EN/RU/KK text, bundled Nunito/Inter fonts, Cyrillic/Kazakh glyph checks, keyboard dialog focus and reduced-motion checks.
- [x] Laptop/full-HD renderer layouts and smaller viewport equivalents for 125/150/200% scaling checked. Actual Windows display scaling was **not** changed or tested.
- [x] Native Electron production renderer opened and checked; Python regressions retained. Full protected recovery and physical multi-device hot-swap testing remain separate manual work.

Stage 2 implementation parity (operator evidence is recorded separately above):

- [x] Register/reference/save with invalidation and candidate persistence.
- [x] Real gaze sequence, positioning readiness, cues, fit diagnostics, retries and physical screen geometry.
- [x] Backend-owned readiness, quiz answers, external exam lifecycle and timer.
- [x] Live frame-matched CV overlays, audio evidence, durable events, deduplication and warnings.
- [x] Recovery/PIN/overlapping pause reasons, ordinary end and interruption.
- [x] Real summary, missing-evidence/report/delivery failure states and configured destination disclosure.
- [x] Deterministic reconnect/no-duplicate-session tests.
- [x] End-to-end unprotected human flow and physical short/long camera recovery checks (runs 1–3 above).

Stage 3 (only after Stage 2):

- [ ] Electron-specific independent recovery audit and explicit native-window ownership.
- [ ] Protected mode opt-in only after that audit; retain recovery behavior on every failure path.
- [ ] Windows distributable with local interpreter/models/fonts/assets, offline native quiz, cleanup and rollback verification.

Rollback is to close Electron and use the unchanged PySide6 entry point/configuration. Stage 1 must not replace the default frontend, overwrite private configs, remove the published executable, rewrite Git history or publish a release.

## Stage 1 implementation and Windows launch

The implementation lives in `desktop/` (Electron main/preload, typed contracts, React components/screens, styles and frontend tests) and `src/proctoring/desktop_bridge/` (setup-only Python adapter and bounded transports). The reference-led design system is [design-system/local-proctoring/MASTER.md](../design-system/local-proctoring/MASTER.md). Python CV, event, session and evidence engines remain the legacy authority and were not rewritten for React.

Use the existing Python `.venv` with project dependencies installed, and a compatible local Node installation (**Node 24 or newer**, as declared in `desktop/package.json`). The frontend lockfile is `desktop/package-lock.json`. Installing dependencies requires network access once; bundled fonts/styles/icons require no runtime CDN. Do not run the legacy app at the same time as Electron against these devices.

Install frontend dependencies and start the real setup slice in development:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\desktop'
npm ci --ignore-scripts=false
npm run dev -- --config config/default.example.toml
```

The config argument is resolved from the **repository root**, not `desktop/`. The default is the public safe example. The bridge exposes no protection/exam/remote-dispatch command, including when the chosen configuration contains those options. It reports which optional destinations are configured without activating them. Private config files are not overwritten.

Browser-only UI preview (all workflow data is visibly labeled as fixtures; no Python or devices):

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\desktop'
npm run ui
```

Open `http://127.0.0.1:5173/`. The preview-state selector and `?scene=exam`, `?scene=gaze`, `?scene=pause-pin`, or `?scene=summary` select presentation states. Their controls never create a real session.

Build and run the local production renderer in the native shell:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\desktop'
npm run build
npm start -- --config config/default.example.toml
```

For a native shell with fixtures only, use `npm run fixture` after the build. This is a source development build, **not a new packaged Windows EXE/release**. To use a different existing Python interpreter, set `$env:PROCTORING_PYTHON` to that interpreter's absolute path before launching.

Return to the complete legacy application after closing Electron:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
.\.venv\Scripts\python.exe -m proctoring --config config/default.example.toml
```

The existing default frontend, private configs, published release and existing executable are unchanged. Stage 1 does not transfer the temporary Electron microphone calibration into a separately launched legacy process; each process has its own session baseline.

## Verification record — 13 October 2026

| Verification | Result and actual scope |
| --- | --- |
| Frontend build | `npm run build` passed: TypeScript, Vite and Electron bundles. |
| TypeScript tests | 6 passed. Includes setup allowlist/payload and preview validation, malformed audio-field rejection, a real Python subprocess round-trip, close-during-startup and unresolved process-cleanup regressions. |
| Playwright renderer checks | 18 passed. Layout/fixture isolation, EN/RU/KK form-state retention, focus restoration, reduced motion, palette contrast and locally bundled Kazakh glyphs were covered. Mocked-live checks prove explicit device actions before registration, disabled Stage 2 actions, and preview/meter clearing with no automatic restart after disconnect. |
| Python regressions | Full suite: **1,833 passed** (including 40 setup-bridge tests). Hardware and human accuracy are not inferred from these tests. |
| Native production shell | Real `file://` renderer opened. Observed `nodeIntegration=false`, `contextIsolation=true`, `sandbox=true`, `webviewTag=false`; production CSP blocked an injected inline script. Fixture mode had no Python bridge/session side effects. |
| Physical camera | Native live setup displayed the selected camera at actual **640×480**. Requested capture dimensions were not substituted for measured dimensions. |
| Physical microphone | Fifine input opened at **48,000 Hz, mono, float32**. Quiet → normal speech calibration reached `ready`, gain **8.0**, committed threshold **0.003007401052334594**. The result was gain-limited but usable, not represented as an error. |
| Operator confirmation | The user confirmed that camera preview, microphone prompts, responding meter and the calibrated result after the quiet/speech sequence worked. This confirms setup usability on that run, not gaze/exam accuracy. |

Renderer screenshots are under the ignored `artifacts/electron-stage1/` directory. Generated coverage includes 1280×720, 1366×768 and 1920×1080; effective scaled-space cases use 1024×576, 853×480 and 640×360. The setup English 720p, Russian exam Full HD, English gaze 720p, Kazakh paused 720p, Kazakh setup at the 150% viewport equivalent, English summary and native fixture screenshots were explicitly visually inspected. Screenshot fixtures are clearly labeled and are not evidence of working exam integration. The native test records are `native-fixture-result.json` and `native-live-result.json` in that same local artifacts directory.

Final review corrected setup-only defects: unbuffered Python pipe handling, dialog focus restoration, pending-start/shutdown ownership races, optional audio-field validation, stale readings during reconnect, and cached microphone enumeration. Idle microphone refresh rebuilds the PortAudio catalog. While the microphone is active or releasing, refresh reports its cached-catalog limitation; stop it and refresh to discover newly attached inputs. Physical hot-plug discovery is not claimed from these regression tests. A process whose termination cannot be confirmed blocks a replacement bridge.

**Not run / not claimed:** a real Electron gaze calibration; reference-photo persistence; a complete Electron exam; detection/event/report parity; native Windows 125/150/200% DPI transitions; external LMS/PIN native-view focus; independent renderer/main/backend/helper crash and watchdog recovery audits; protected keyboard/focus restrictions; a packaged Electron distributable. These belong to the Stage 2/3 gates above. The current emergency shortcut can close the unprotected setup shell, but it is not the independent protected-exam audit.

Reproduce automated checks:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\desktop'
npm test
npm run test:ui
npm run build
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
.\.venv\Scripts\python.exe -m pytest -q
```

Playwright uses locally installed Microsoft Edge (`channel: msedge`). The real subprocess test uses the existing project `.venv` and Windows named pipes but does not open camera/microphone capture. To repeat the human setup test, open the native live shell, accept local device access, select/test the camera, select Fifine (or the intended microphone), run quiet/normal-speech calibration and verify the live level plus result. Close through the normal window control and confirm the camera indicator goes off. Do not treat the unavailable Continue/Start actions as an exam migration failure: they are intentionally blocked until Stage 2 is implemented.
