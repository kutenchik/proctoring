# Stage 4C camera disconnect and shutdown diagnosis

Date: 2026-10-15. Source build only. **Stage 4C remains FAILED / incomplete.** The subsequently approved standalone camera/normal-close diagnostic succeeded; see the outcome below.

## Findings and evidence limits

The original physical camera-disconnection root cause is **not established**. Neither is the exact cause of the original lingering Electron main/children. This work reproduces and fixes adjacent lifecycle defects; it does not claim those defects caused Session A's native failure.

Read-only retained evidence in `build/localhost-protected/manual-01`:

- `session-a-setup-failure.json`: operator reported Python disconnected immediately after Test camera; admission existed, but `started_at` and `finished_at` were null, no session files, raw backend diagnostics not retained.
- `student-a-processes.json`, `shutdown-verification.json`, `shutdown-final.json`: backend/supervisor were gone by inspection. Electron main and two children remained after normal close. Exact-owned cleanup subsequently completed. An unrelated reused PID was preserved. Operator confirmed normal input and devices off.
- `recovery-audit.json` and `protected-fixtures.json`: historical 21/21 audit and 50 native fixture checks. These are preserved, not rerun or reused as authorization.
- `docs/LOCALHOST_ACCEPTANCE.md` and `docs/LOCALHOST_PROTECTED_ACCEPTANCE.md`: successful earlier unprotected workflow and failed protected preparation, respectively.

The original request arrival, process exit codes, supervisor/backend exit ordering, native exception and stderr cannot be reconstructed. A read-only Windows Application-log query for events 1000/1001 mentioning Python/Electron during 06:15–06:35 UTC returned zero matches. This does not prove there was no native crash or deliberate termination.

## Test camera path and configuration comparison

`SetupScreen` sends `camera.start` through the renderer backend hook, frozen preload API and `proctoring:command`. Main validates sender and command, then `PythonBridge` writes a bounded NDJSON request to the supervisor. Its inherited pipes connect to backend `ControlTransport` and `Protocol`; `WorkflowBridge.dispatch` checks consent, selected device and protected host/media permission. `AppController.prepare_camera_preview` starts the monitor, the selected Qt camera thread and inference worker. A validated response returns through the same chain. Later camera state/health arrives through polling; a successful start response does not itself prove frames arrived.

The selected-device route is `NamedCamera` / Qt device ID. OpenCV/MediaPipe/model initialization can still participate in downstream vision work. There is no evidence here identifying a particular library, camera driver, device conflict or environment variable as the physical cause.

Comparing retained unprotected/protected TOML files found differences only in protection enabled, validation-report path, private PIN, clipboard guard, VM check and session-storage path. Camera/vision/audio settings and model paths matched. The same prepared Python runtime was used; dependencies were not changed during diagnosis. Clipboard enforcement is scoped to an active protected exam, which Session A never reached. Protection being requested is not proof that protection caused the camera failure.

## Reproduced defects and changes

1. **First disconnect overwritten:** a failing regression showed `backend_pipe_closed` replaced by `closed` during cleanup. The first unexpected disconnect now remains the displayed connection reason; local diagnostics also preserve the first failure independently of later cleanup errors.
2. **Partial camera startup leak:** injected initialization failure after opening the mocked device left it active and preview permission latched. Controller now revokes preview permission and attempts monitor cleanup before rethrowing. Workflow returns a sanitized `camera_initialization_failed` operation error. A responsive backend remains connected. Qt capture cleanup independently attempts timer stop, camera stop and session detachment even if one finalizer throws. Native/Python exception text is not exposed as the camera initialization message.
3. **Shutdown interruption:** main performed live-screen, shortcut and tray cleanup before entering guarded finalizers. Those operations now run inside individually guarded steps, so a throwing capture finalizer cannot skip backend cleanup and quit. Tests execute the actual bundled main handlers against mocked Electron/bridge objects. This supports the fix but cannot establish that a finalizer threw during the historical window-close failure.
4. **Transport handling:** stdout end/close/error and stdin error/close settle pending requests, record transport failure and begin bounded cleanup. Stream errors no longer risk an unhandled Node error. Later replies during closing cannot restore the connection. Completed processes are not subjected to another shutdown wait; the shutdown race timer is cleared.
5. **Terminal reconnect guidance:** the disconnected screen explains that a terminal backend lifetime cannot be restored, instructs normal close and operator contact, and says pending evidence is preserved. Reconnect remains available for nonterminal connection states; no automatic backend replacement is added.

Production files changed: Electron `bridge.ts`, `main.ts`, `shutdown.ts`, new `lifecycle.ts` and `owned_process.ts`; Python controller, Qt camera, bridge protocol/workflow/entrypoint/supervisor, new bridge `diagnostics.py`, and the read-only process-exit query in `security/electron_binding.py`; renderer connection helper, disconnected screen, App wiring and translations.

## Bounded local diagnostics

Location: `<Electron userData>/diagnostics/backend-lifecycle.json`, with one `.previous` generation and an atomic-write `.tmp` file. No upload is added. Fixed schema, first failure plus at most 32 timestamped transitions; tests verify bounded output below 64 KiB. A previous file is copied only if at most 64 KiB. Storage errors cannot prevent recovery.

Records contain phase, validated command names for the last attempted/written request and received response, a local camera-operation counter, fixed error categories, backend/supervisor transitions and available exit codes, including unsigned Windows hexadecimal status. Backend status is read from its retained native HANDLE when available, separately from the supervisor's Node exit notification. A native crash can omit camera exception markers; available exit information remains useful. Timestamps permit later correlation with Windows crash records.

Python emits fixed-format metadata markers. Electron parses marker lines across chunks with a 512-byte line bound, ignores unknown fields/events and discards arbitrary stderr. Exception categories are runtime/value/OS/memory/other; messages, stack traces and raw IPC bodies are excluded. No frames, screenshots, audio, answers, credentials, tokens or device identifiers are recorded. OS process identity includes private command lines **in memory only**, never in these files.

## Shutdown and exact ownership

Preparation and disconnected-backend close reach guarded cleanup and quit. Active-session close still invokes the existing privileged end flow. Emergency still sends `emergency.end` before backend shutdown. Completion/pending-receipt warnings and intentional background synchronization retain their existing contracts; no evidence-deletion policy changed.

Backend shutdown releases protection before media/report cleanup through the existing workflow. Supervisor preserves its independent helper/guardian recovery grace before forced cleanup. Main retains the existing 38-second supervisor grace. A forced fallback now requires unchanged PID, creation time, executable, owner and command line, supplemented by the retained native process HANDLE. Main's identity queries are hidden, bounded local PowerShell/CIM calls; supervisor uses psutil plus native creation identity. Missing, changed or unreadable identity refuses termination and records the failure. No process-name kill or process-tree sweep is added. Forced fallback was tested only with mocks.

No attempt was made to force Electron exit or shorten protection recovery deadlines. If a native failure still strands the real application, the planned physical check must capture that result; mocked quit invocation is not proof of real OS process disappearance.

## Targeted verification

All final checks below passed:

| Check | Result |
|---|---|
| Python camera setup, camera recovery, controller camera, supervisor, bridge transport/protocol | 78 passed |
| Protected workflow with injected native adapter, including failed camera readiness never arming | 24 passed |
| Electron lifecycle, atomic diagnostic retention, exact ownership, actual main-handler shutdown, background contracts, student message | 24 passed |
| Existing setup-only PythonBridge tests, including real IPC and graceful EOF | 6 passed |
| TypeScript, Vite and Electron source build | Passed |

Regression tests first failed for overwritten disconnect reason and partial-device leakage, then passed with fixes. Added coverage includes successful mocked camera, init exception, backend/supervisor exit during pending camera request, independent pipe failure, healthy main after disconnect, safe messages, first-failure retention, partial Qt finalizers, and zero protected arming after failed readiness.

Commands: `.venv/Scripts/python.exe -m pytest` for the six focused camera/bridge/controller/supervisor files and `tests/test_desktop_protected_workflow.py`; `node --import tsx --test` for the six focused Electron test files; existing `bridge.test.ts` selected by `unresolved|closing while|throwing|real setup|control EOF`; `npm run build` in `desktop`. The old tree-kill test was deliberately excluded. A test-only TypeScript narrowing error was corrected before the successful final build. Vite still reports existing future config-loader compatibility and bundle-size warnings.

No entire preflight, native audit, keyboard suppression, real webcam/microphone capture, protected exam, tunnel, load test or packaging was run. No Session A/B was restarted. The earlier unprotected physical acceptance is preserved; this build has not been physically reaccepted.

Final read-only OS inspection found zero remaining Python desktop-bridge processes from the setup tests. The prepared diagnostic configuration passes the production configuration loader; it has not been launched.

## Camera-only diagnostic plan (subsequently approved and run once)

Prepared configuration: `build/localhost-camera-diagnostic/prepared-01/camera-diagnostic.toml`. It retains the original camera/vision/model settings, uses separate session storage and a new private unused PIN, disables protection/clipboard enforcement and connected admission for this standalone diagnostic. Remote delivery is disabled. It does not point to the old audit. This is deliberately narrower than the original connected protected environment and cannot certify that environment.

After explicit approval, perform exactly one attempt:

1. Launch the built source application with that config and explicit isolated `--user-data-dir` under `build/localhost-camera-diagnostic/prepared-01/electron-profile`. Use the existing project Python environment. Record the exact owned process identities privately. No API/Vite service is needed for the built UI.
2. Operator accepts normal consent, selects the intended camera and clicks **Test camera once**. Observe for at most 15 seconds. Do not test microphone, capture reference, calibrate, start an exam, enable viewing or arm protection. Do not retry on failure.
3. Operator closes the application normally. Allow up to 50 seconds for bounded cleanup; verify camera indicator off, ordinary typing/Alt+Tab functional, and exact owned processes gone. A lingering process is a failed diagnostic, not a pass.
4. Preserve only the bounded lifecycle files, timestamps, sanitized OS exit/crash metadata and operator outcome. If cleanup is needed, revalidate complete identity and confirm restrictions released before any forced action. Never terminate an unverified/reused PID.
5. Stop and report. No automatic second attempt, Session A/B, calibration campaign or protected test.

## Audit status and remaining uncertainty

**A new matching protection audit is required before any future protected activation.** Source and supervisor changes invalidate the historical 21/21 result for this build. Nothing in these automated checks renews it. Protected focus, keyboard restrictions, emergency chord, PIN, guardian/liveness, display-change policy, consent v3, teacher authorization and receipt-gated cleanup were not relaxed.

Remaining unknowns: original physical device/library crash cause, original request receipt and exit ordering, and original Electron orphan cause. The standalone success below does not establish behavior in the original connected protected environment.

## Approved physical diagnostic outcome

The operator explicitly approved the proposed single camera-only test. It ran once on 2026-10-15 using the built source UI and isolated configuration/profile above. No API/Vite server, microphone test, reference capture, calibration, exam or protected activation was started.

- Operator reported the camera test **“worked.”** Lifecycle records show exactly one `camera.start`, received by Python, followed by `camera_opening` and `camera_started`. The pre-close diagnostic snapshot also recorded the camera response returning successfully through IPC.
- Camera request: 07:07:28.775 UTC. Normal close began: 07:07:55.745 UTC. Actual request-to-close interval was **26.970 seconds**, longer than the planned maximum 15-second observation; this is recorded as a timing deviation, not silently counted as meeting that bound. There was no second attempt.
- Python backend exited at 07:07:56.661 UTC with code **0 / 0x00000000**. Supervisor exited at 07:07:56.684 UTC with code **0 / 0x00000000**. Main requested quit at 07:07:56.685 UTC, about 0.94 seconds after close began. No first failure or forced-termination event was recorded.
- OS inspection found **zero remaining processes matching the ten saved owned creation identities**. No forced cleanup was used.
- Operator explicitly confirmed the camera indicator was off and ordinary typing and Alt+Tab worked normally.

Evidence: `build/localhost-camera-diagnostic/prepared-01/result.json`, `normal-close-check.json`, `launch.json`, and `electron-profile/diagnostics/backend-lifecycle.json`. Complete process identities remain in the private ownership files; their command lines are not reproduced here. No images, audio or answers were retained as diagnostic evidence.

Result: **standalone camera initialization and normal shutdown succeeded**. The original failure was not reproduced. Stage 4C remains incomplete and the historical protection audit remains invalid for this changed build. Stop here; no further physical test or Session A/B is authorized by this one-attempt approval.
