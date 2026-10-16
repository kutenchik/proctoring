# Stage 4C protected localhost acceptance — 2026-10-15

## Final recovery-03 result: normal completion and emergency release observed

Normal protected Session A completed successfully with teacher monitoring, commands, live snapshots, PDF/receipt and local cleanup. Real Session B ended locally via emergency_shortcut, exited 0 and left no owned student processes; operator confirmed input/devices normal. Session B synchronization remains pending and local evidence is preserved; server completion is NOT verified. Startup window visibility required same-instance activation. See [full current results and limitations](LOCALHOST_RECOVERY_AUDIT_03.md). Tests stopped; earlier entries below describe prior states.


## Current recovery-03: normal session passed; emergency session pending

Recovery 21/21 and native fixture 50/50 passed. Real protected Session A completed 2/2 with teacher controls, monitor viewing, live snapshot access, original PDF, verified receipt/local cleanup and restored input. No owned student processes remain. Session B is prepared but NOT LAUNCHED: automatic approval review requires explicit additional-session approval. See [detailed current results](LOCALHOST_RECOVERY_AUDIT_03.md). Older sections below are historical.


## Latest recovery prerequisite: 2026-10-15 recovery-03

ONE authorized current-build audit passed 21/21; completed report validated, foreground launcher/Electron exited 0, owned processes gone, operator confirmed normal input. See [audit results](LOCALHOST_RECOVERY_AUDIT_03.md). Protected fixture and real exam remain unrun pending approval. Earlier evidence below remains historical.


## Latest result - manual-02 audit failed; validation stopped

The fresh current-build recovery audit did not complete: only 3/21 mandatory checks were recorded before an Electron console.log output-pipe EPIPE exception. No blocking fixture or protected student exam was started. The operator stopped validation and closed the audit windows; corrected exact-identity and broader process checks found no remaining audit processes. No forced cleanup was used.

See [EPIPE investigation and fix](LOCALHOST_AUDIT_EPIPE_FIX.md). The output lifecycle was reproduced without native testing and fixed; 13 Node tests, 19 Python tests and the source build passed. Original report, screenshots, bundle and process diagnostics are preserved under build/localhost-protected/manual-02/epipe-failure. A new matching native audit requires renewed operator approval. No retry has run.

Current answer: reliable protected localhost operation remains unestablished. This run stopped before protected camera readiness, PIN, viewing, commands, snapshots, PDF/receipt, normal completion or emergency-session verification.

## Historical manual-01 result (preserved)

Status: **protected localhost acceptance FAILED at Session A setup**. Required current-build native recovery passed 21/21; bounded protected fixtures passed 50 native checks with production PIN checks explicitly NOT RUN. Clicking Test camera disconnected the Python backend before the exam started, and normal window close left Electron processes behind. Session B was not run. The operator confirmed ordinary input restored and camera/microphone indicators off. All owned test processes/services are now stopped; evidence is preserved. No production protection implementation was changed or workaround applied.

## Identity and isolation

Workspace: `C:\Users\kuten\Desktop\proctoring-main`; `.git` is absent. No Git history was created. Fresh source build: Electron 44.7.0, Python 3.11.5; source fingerprint `954d912407f28ed6c5a3ae790ae2efa6ff0367b17265b302448e3e7c8eeeb4ce`, artifact build ID `8b191b49d73fcd3ec65e040f68b4efbcd24943ea21a6f36f105ecf75779fdc76`.

`build/localhost-protected/manual-01/prepared-identity.json` records the existing validator's machine/runtime/source identity and separate SHA-256 values for config, locks, Electron executable and coordinator scripts. This preparation record is NOT an authorizing native audit. Exact config and private operator credentials remain local; do not publish them. Normal unprotected config, previous evidence, and historical audits were preserved.

Isolated API database/evidence, Python outbox, sessions and explicit Electron `--user-data-dir` live under `build/localhost-protected/manual-01`. Literal API `http://127.0.0.1:8000`; teacher `http://127.0.0.1:5174`. Remote/webhook/Telegram delivery is disabled. Protected config preserves clipboard guard, VM check, single-display readiness and ordinary consent/reference/calibration gates. Protection is opt-in only.

Two disposable protected exams are prepared: A normal (`782bcc2ae643468eaac3b88794efa67b`) and B emergency (`77e661e8a407412ebe439b3101a8e08a`). Both have two native questions, 600-second duration, audio monitoring and event snapshots. A may receive the agreed +60-second extension. Session A admitted one student; Test camera failed before session start. Session B has no admission. Actual camera initialization success is unconfirmed.

## Result matrix

| Item | Implemented | Automatically tested | Native fixture tested | Human verified | Result |
|---|---|---|---|---|---|
| Exact HWND/process ownership and narrow dialogs | Yes | PASS | PASS current build | No active human exam | PASS native |
| Audit identity and startup failure | Yes | PASS | 21/21 matching recovery audit | Not armed | PASS native prerequisite only |
| Fullscreen/focus containment | Yes | Policy/geometry PASS | PASS; cross-process restore 47 ms | NOT RUN active exam | PASS native only |
| Shortcut suppression | Existing explicit list | PASS pure policy | 39/39 across three contexts | NOT RUN | PASS native only |
| Wrong/correct production PIN | Yes | PASS mocked workflow | Explicit NOT RUN in fixture | NOT RUN | NOT RUN physically |
| Renderer/main/backend/helper release | Yes | PASS mocked cases | PASS; renderer/main/backend stalls 5.000 s | Backend exited during setup; devices off confirmed | PASS native, not human active-release acceptance |
| Emergency remains terminal | Yes | PASS | PASS native release | Session B NOT RUN | Physical terminal behavior NOT RUN |
| Release before cleanup/report/network | Yes | PASS | Native release/input probes PASS | No started exam | NOT RUN integrated completion |
| Independent pause/recovery reasons | Yes | PASS | Lease checks PASS | NOT RUN | Protected integration NOT RUN |
| Camera/device preparation | Existing path | Mocked/preflight paths PASS | Audit does not test camera | Test camera caused Python disconnected | FAIL |
| Consent v3 / unmasked authorized monitor | Yes | PASS capture-owner tests | Not part of native fixture | NOT RUN protected viewing | NOT RUN physically |
| Live event snapshots | Yes | PASS production snapshot tests | Not part of native fixture | NOT RUN | Protected upload NOT RUN |
| Teacher commands | Existing authenticated routes | PASS backend integration | Not part of native fixture | Coordinator prepared, not executed | Protected command checks NOT RUN |
| Normal completion/receipt/report | Yes | PASS existing real HTTP integration | Not part of native fixture | NOT RUN | Protected completion NOT RUN |
| Evidence retention and cleanup | Receipt gated | PASS existing integration | Not part of native fixture | Admitted attempt/outbox retained; no final receipt | No protected cleanup claim |
| Owned-process cleanup | Exact handles/identity | PASS mocked cleanup | PASS fixture cleanup/re-registration | Normal close left 3 Electron processes | FAIL normal shutdown; explicit owned cleanup completed |
| Display/geometry change | Terminal protected release | PASS | NOT RUN physical display change | Intentionally NOT RUN | Policy unchanged |

## Inspection findings

Main validates the trusted renderer and main frame; preload exposes narrow workflow intents, not arbitrary native access. Helper binding checks exact HWND ownership, process creation/ancestry and launch stamp. A desktop mutex prevents overlapping owners. No teacher browser or arbitrary Electron/Chromium process is whitelisted.

One-use challenges require fresh committed renderer progress, then main validation and Python controller dispatch. Network/status polling cannot renew a stalled renderer. Missing control progress expires after configured 5 seconds, plus scheduling/cleanup latency. Independent guardian deadline is 2.5 seconds for helper message-loop progress; it retains the exact helper handle. Native measurements for this build are recorded below; these are not hard real-time guarantees.

Ctrl+Shift+Alt+Q registration is required before suppression. End releases protection before device cleanup, PDF work and synchronization. Ordinary active close requests route to privileged end UI. Emergency/liveness failure and active geometry changes are terminal; the same session cannot rearm. Teacher Resume clears only its own pause reason. A suspicious-activity warning does not itself pause the timer.

Supported policy: Alt+Tab and Alt+Shift+Tab; left/right Windows keys; Ctrl+C/V; Ctrl+Insert; Shift+Insert; PrintScreen; Alt+F4; Alt+Esc; Ctrl+Esc; Ctrl+Shift+Esc. Windows secure-attention surfaces are outside scope. Foreground containment is best effort: if the exact exam window cannot be restored within 1 second plus poll/scheduling delay, the attempt ends and releases. No display change is planned for the manual sessions.

## Focused preflight

From the repository root:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv/Scripts/python.exe -m pytest tests/test_electron_protection.py tests/test_electron_audit.py tests/test_electron_protected_fixture.py tests/test_desktop_protected_workflow.py tests/test_protection_policy.py tests/test_protection_integration.py tests/test_recovery_validation.py tests/test_desktop_camera_recovery.py -q --tb=short
# 326 passed in 10.95 s. Mocked adapters/native boundaries; no active hooks.
$env:PYTHONPATH="$PWD/src;$PWD/.venv-server/Lib/site-packages"
.venv/Scripts/python.exe -m pytest tests/test_connected_stage2_api.py tests/test_connected_stage3_api.py tests/test_live_snapshot_production.py tests/test_connected_stage3.py -q --tb=short
# 36 passed in 27.67 s. Isolated fixtures; no real camera/microphone.
```

In `desktop`:

```powershell
node --import tsx --test tests/control-progress.test.ts tests/recovery-identity.test.ts tests/protected_assertions.test.ts tests/audit_client.test.ts tests/security.test.ts tests/shutdown.test.ts tests/live-screen-owner.test.ts
# 45 passed. Initial sandbox spawn EPERM prevented execution; approved subprocess rerun passed.
npm run build
# Passed TypeScript, Vite and Electron source build; no installer/package.
```

Build warnings remain future Vite config-loader compatibility and bundle size. No full suite or load test was run. No speculative product correction was made: the later physical setup failure has no retained root-cause trace. New scripts only prepare isolated configuration and coordinate already-existing local routes. The command driver accepts warning/pause/resume/+60 only, binds to exam A, records a single request per action, uses cookie login/CSRF and observes durable outcomes for a bounded period. It does not retry an uncertain mutation. The viewer uses the production teacher page in headless Edge for 35 seconds with a 60-second cap, then stops/closes its own viewer. This is coordinator-driven verification, not human teacher-browser interaction during protection.

## Approved sequence and stopping rule

The operator explicitly approved one readiness checkpoint covering: existing 21-case non-suppressing recovery audit; existing bounded protected fixture (13 shortcuts in three focus contexts plus release/failure probes, each native lease at most 15 seconds); then at most one normal and one emergency human session. The protected fixture deliberately records production PIN checks NOT RUN; human session A was intended to cover those separately but failed during setup. A failed required recovery audit prevents protected arming. Stop at the first failed native safety requirement; preserve the report and ordinary-input evidence.

Owned process family: `desktop/node_modules/electron/dist/electron.exe` audit launcher and its fixture children, configured `.venv/Scripts/python.exe`/underlying Python runtime for audit endpoints or supervisor/backend, the independently bound native helper and guardian. Also the isolated uvicorn and Vite services. Record PID/creation/executable/command before managing these; never kill by name or port. Temporary audit windows and deliberate stalls/crashes belong only to fixtures, never the human exam.

Expected fixture work is several minutes; allow up to 12 minutes before stopping for inspection. Each fixture's enforced native maximum lease is 15 seconds. Manual A targets 3–5 active minutes (configured cap 600+60 seconds), B less than 1 active minute (configured cap 600 seconds), plus normal readiness. No hardware replug, display settings change or server outage is planned.

## Startup and recovery instructions

The following are the prepared source-launch commands, not a claim that the current protected workflow is usable. Resolve the recorded camera-test disconnection before another physical campaign; a relevant code/build change requires a fresh audit and operator coordination. These commands do not substitute for explicit operator readiness. From fresh repository-root shells:

```powershell
. ./scripts/localhost-protected-environment.ps1
.venv-server/Scripts/python.exe -m uvicorn proctoring_server.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers --ws websockets-sansio --ws-max-size 393216 --ws-max-queue 8 --ws-per-message-deflate false
# Separate shell:
. ./scripts/localhost-protected-environment.ps1
Set-Location teacher-web
npm run dev
```

After operator readiness, create the current audit using the existing runner (never overwrite a historical audit):

```powershell
. ./scripts/localhost-protected-environment.ps1
Set-Location desktop
npm start -- --validate-electron-protection --native-input --config $env:PROCTOR_LOCAL_CONFIG --audit-output "$env:PROCTOR_PROTECTED_RUN/recovery-audit.json" --user-data-dir $env:PROCTOR_ELECTRON_PROFILE
# Only after the matching required audit passes:
npm start -- --validate-electron-short-protection --allow-short-protection --config $env:PROCTOR_LOCAL_CONFIG --recovery-report "$env:PROCTOR_PROTECTED_RUN/recovery-audit.json" --test-output "$env:PROCTOR_PROTECTED_RUN/protected-fixtures.json" --user-data-dir $env:PROCTOR_ELECTRON_PROFILE
# Only after safety validation, for normal operator readiness and session:
npm start -- --config $env:PROCTOR_LOCAL_CONFIG --user-data-dir $env:PROCTOR_ELECTRON_PROFILE
```

Audit must be Electron schema 2/audit_only, all 21 mandatory native checks passing, suppression false, exact machine/runtime/source/artifact/policy identity, and no more than 24 hours old. Missing, failed, future, expired or mismatched audits fail closed. Relevant source/artifact/runtime/policy changes require a fresh audit; do not rebuild between passing audit and human sessions. Separately recorded config hash must still match the prepared config.

Operator PIN is in local `build/localhost-protected/manual-01/operator-private.json`, not in this report. During protection use permitted mouse/UI controls; wrong PIN must not authorize pause, correct PIN permits the intended local pause/resume. Do not Alt+Tab to a teacher browser to conduct command tests; use the agreed coordinator. Normal submission ends and releases; emergency Ctrl+Shift+Alt+Q releases independently and permanently ends that attempt. Confirm normal typing/Alt+Tab and devices stopped afterward. Preserve pending evidence if synchronization is incomplete; never delete outbox/session material to force success. Close the student normally, then stop only the server/teacher shells owned by this run.

To return to the accepted unprotected mode, open a fresh shell, dot-source `scripts/localhost-environment.ps1` (not the protected helper), and use its `$env:PROCTOR_LOCAL_CONFIG` with ordinary `npm start`. Protected mode has not become the default.

## Current-build native recovery result

The corrected invocation passed all 21 mandatory native cases at 2026-10-15T06:13:59.363872+00:00. `require_electron_validation` accepted the exact prepared identity; source unchanged was true. Renderer, main and backend stalls released at 5.000 seconds since native-confirmed progress. Main/backend/EOF exact helper-death observations were 115/103/116 ms before fixture cleanup. Emergency injection passed in trusted, PIN-modal and external-focus contexts; helper suspension, loop failure, lost release ACK, replay rejection, overlapping owner and re-registration passed. This audit did not suppress shortcuts. The first invocation is preserved byte-for-byte as `recovery-audit-no-native-input.json` (18 PASS, 3 NOT RUN); it is not authorizing evidence. Bounded protected fixture results follow; the subsequent human setup failure is recorded separately.

## Bounded protected fixture result

Current identity/config matched after the run. 50 native checks PASS, 51 post-release ordinary-input probes PASS. All 13 shortcuts passed in trusted/PIN/external contexts (39). Exact cross-process foreground was restored in 47 ms in this fixture. Normal/emergency/maximum-lease release, renderer loss (5.000 s), suspended helper death, main/backend loss and repeated cleanup passed. The unchanged report overall flag is false because wrong_pin and correct_pin are explicitly NOT RUN production-workflow checks; they are not reclassified as native passes. Native fixture/helper processes were absent before Session A launch. Session A subsequently failed during camera setup; no protected human exam started.

## Physical failure, diagnosis limits and cleanup

Session A attempt `fa0794f902fb4541b7684a49907f11c8`, student Stage 4C Student A, was admitted. The operator reported the Python-disconnected screen immediately on clicking **Test camera**, and Reconnect did not recover it. Database `started_at` and `finished_at` are both null. No session evidence files were created. This is a failed protected setup/device path, not a failure proven to occur while native suppression was Active.

Read-only process inspection found the supervisor, backend, helper and guardian gone, with Electron UI remaining. The tool session retained no backend error. No matching recent Windows Application Error/WER event was returned. `PythonBridge` intentionally drains arbitrary child stderr and exposes only a fixed marker; therefore the underlying exception/exit cause was not retained. Native screenshot inspection also timed out; it is not evidence about the application's camera initialization. The user's exact symptom, admission state and file inventory are preserved in `session-a-setup-failure.json`.

The diagnosing-bugs workflow did not reach a deterministic agent-run reproduction of this camera-start failure. Only the single operator-triggered failure is established. No unverified theory, timeout increase, disabled readiness, protection downgrade or detector change was used as a fix. A next explicitly scoped diagnosis needs a bounded local capture of the backend exit code/stderr at the Test camera boundary and a reproducible test before modifying product code. That is future work, not a claimed completed correction. No second calibration campaign was requested or run.

The operator closed the app and confirmed ordinary typing/Alt+Tab worked and camera/microphone indicators were off. Window enumeration confirmed the student window disappeared. After the normal shutdown grace, Electron main PID 4848 and two children remained; this is a second acceptance failure. The saved PID/creation/executable/owner/command identity was checked and a retained process handle used to terminate only the owned Electron main. A subsequent child-owner lookup refused during exit, and no unverified termination followed. Final verification found no matching owned student process and no listeners on 8000/5174. PID 30836 had been reused by an unrelated Windows service with a different creation identity and was preserved. Uvicorn and Vite were stopped via their own task sessions.

The server database/evidence directory, encrypted outbox, configs and reports are preserved. No complete receipt was expected or fabricated for this never-started attempt; no receipt-gated evidence cleanup claim is made. Session B, human shortcut/PIN/emergency checks, protected monitor viewing, live snapshots, teacher commands and normal completion remain NOT RUN. The native fixture's `passed:false` remains unchanged because its two production PIN records are explicitly NOT RUN.

Evidence under `build/localhost-protected/manual-01`: `prepared-identity.json`, `recovery-audit-no-native-input.json`, `recovery-audit.json`, `protected-fixtures.json`, `session-a-setup-failure.json`, `student-a-processes.json`, `service-processes.json`, `shutdown-verification.json`, `shutdown-final.json`. Private configs/process command records can contain sensitive local parameters and must not be published.

## Direct answer

**Can the current source build run a protected localhost exam with working teacher monitoring, live snapshots, report delivery and safe release? No�not established by this run.** The current native recovery and restriction fixtures pass, but the real protected workflow failed at Test camera before Start and required explicit cleanup of leftover Electron processes after window close. The successful earlier unprotected run is not promoted to protected acceptance. No packaging, Internet work, Stage 4D or 30-student capacity validation was performed.
