# Stage 3 — Live teacher monitoring and remote controls

> Current policy update (2026-10-14): [Stage 4A webcam-visible follow-up](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_FIX.md)
> supersedes masking and consent-v1 implementation details below. Historical test results
> remain unchanged. Webcam-visible sharing requires new consent v2. No new physical test has run.


Implementation report, 14 October 2026. Stage 1/2 remain in place. This is a
changed **source build**, not the historical rc8 build and not a packaged release.
Packaging, public deployment and Stage 4 remain paused.

| Evidence level | Result |
|---|---|
| Implemented | Authenticated live presence/events, consent, selected monitor viewing, direct/relay transports, remote commands, unprotected display recovery and localized UI |
| Automated verification | Focused Python, server, Electron policy/owner and browser tests; actual loopback authenticated sockets and synthetic direct/relay frames; affected source builds |
| Physically verified in this stage | **None**: no webcam exam, monitor capture, human calibration, monitor switching or native protection audit |
| Deferred | Protected physical capture, protected display-recovery policy change, multi-network/tunnel performance, capacity testing and packaging |

## 1. Implemented features

- Fresh student presence comes from the authenticated connection and Python status,
  not a saved attempt row. Status becomes offline after six seconds without a
  fresh update. Saved lifecycle/preparation/restart records remain explicitly separate.
- The teacher sees identity, active attempt/session, authoritative remaining time,
  answered/total counts, monitoring health, independent pauses and recent events.
  The website neither advances the clock nor receives live answer selections/grades.
- Canonical journal notifications retain their sequence and event identities.
  Behavioral counts and technical interruptions are separate. Existing evidence,
  grouping, bulk review and reports remain under Stage 2.
- One selected monitor viewer per teacher account, with full-screen/stop controls,
  actual transport, freshness and measured quality. No automatic student switching
  or notification sounds.
- Explicit per-attempt screen consent; the student viewing badge follows recent
  verified frame-presentation acknowledgements, not a request alone.
- Warning history; independent teacher pause/resume; reasoned terminal end;
  reasoned time extension; specific monitoring/display recovery authorization.
- Existing five-minute preparation extension and same-device restart authorization
  are available from the live workspace. Closing admissions affects new joins only.
- Exactly-one-display admission/readiness and bounded runtime checks. Unprotected
  recovery requires fresh calibration/geometry and teacher approval.
- Changed student and teacher screens support EN/RU/KK and the existing sand/moss
  design system. The installed UI UX Pro Max guidance was used.

## 2. Main files

| Area | Created or changed |
|---|---|
| Plan/contracts | `docs/TEACHER_STAGE3_PLAN.md`, `docs/TEACHER_STAGE3_CONTRACT.md`, `docs/CONNECTED_STUDENT_STAGE3.md` |
| Server | `src/proctoring_server/live.py`, `live_routes.py`, `migrations/004_live.sql`; affected `app.py`, `service.py`, `sync.py` |
| Python client | `src/proctoring/connected/live.py`, `live_workflow.py`; affected connected workflow, controller, session and desktop bridge/protocol |
| Trusted capture | `desktop/electron/live_screen.ts`, `screen_capture.ts`, `screen_policy.ts`, `screen_rtc_preload.ts`, `screen_rtc_renderer.ts`; `main.ts`, security validation and source build script |
| Shared frames | `shared/live-screen.ts`; `desktop/shared/contracts.ts` |
| Student UI | `desktop/src/components/LiveTeacher.tsx`, `locales/liveTeacher.tsx`; setup, calibration/workflow, exam, header and app integration |
| Teacher UI | `teacher-web/src/LiveWorkspace.tsx`, `live-model.ts`, `live-viewer.ts`, `use-live.ts`, `live-i18n.ts`, `live.css`; app, API/time and development proxy integration |
| Tests | `tests/test_connected_stage3.py`, `test_connected_stage3_api.py`; `tests/teacher_server/test_live.py`, `test_live_api.py`; desktop `live-screen*.test.ts`, `ui/live-teacher.spec.ts`; teacher live unit/browser tests and isolated Playwright configuration |
| Dependencies/docs | Official `websockets==15.0.1` in the existing student/server dependency declarations and their respective environments; server/teacher README updates |

The working tree already contained substantial earlier-stage changes. This list
describes Stage 3 ownership, not every entry in `git status`. No history, private
configuration, release or old audit report was rewritten.

## 3. Migration and contracts

Migration **004_live.sql** adds durable consent, command/outcome/audit records and
early-admission-closure state. Existing migrations are preserved. It was exercised
on temporary databases; the user's running database was not migrated by the tests.

All paths below use `/api/v1`; exact payloads and bounds are in the
[Stage 3 contract](TEACHER_STAGE3_CONTRACT.md).

| Route | Authentication and purpose |
|---|---|
| WS `/live/student` | Existing attempt bearer + device secret, then attempt/session hello; Python status/events/consent/command ACKs |
| WS `/live/teacher` | Teacher cookie, exact Origin and CSRF handshake; ownership-scoped updates |
| POST/GET `/attempts/{id}/commands` | Owned attempt, validated command/idempotent request ID; actual outcome history |
| POST `/attempts/{id}/view` | Fresh active consented session; one renewable viewer lease per teacher |
| POST `/live/view/stop` | Stop the owned viewer |
| WS `/live/stream` | Teacher cookie+Origin+CSRF, or short-lived sender capability held by Electron main |
| POST `/exams/{id}/close-admissions` | Owning teacher, reason and explicit confirmation; no effect on admitted attempts/uploads |

Existing preparation extension, recovery-grant and Stage 2 synchronization routes
remain authoritative. Commands expire after **10 seconds**, viewer leases after
**30 seconds** unless reauthorized. Authentication and ownership are rechecked.
Operational commands never enter a reconnect execution queue.

## 4. Direct streaming

Python receives a viewer-only capability, passes it through host-only IPC to
Electron main, and never handles screen pixels. Electron main owns the authenticated
stream socket, lease, display capture and lifecycle.

An invisible, sandboxed, isolated Electron renderer implements WebRTC. It receives
only bounded pixels and signaling through a narrow preload, not attempt/device
credentials or the viewer token. It has no Node integration, remote exam access,
downloads, device permissions or arbitrary navigation. No microphone/webcam media
tracks are created. Remote exam WebContents remain separate.

WebRTC uses an unordered, non-retransmitting **screen data channel** carrying JPEG
frames, rather than an audio/video track. Frames use 12 KiB chunks, at most 32 chunks;
the receiver retains one incomplete frame for at most one second. Older sequences
are dropped. Host-only ICE is attempted without external STUN/TURN. Failure or
negotiation timeout selects the authenticated own-server relay.

The actual production sender script interoperated with the teacher receiver in a
local browser test using synthetic pixels and real signaling. This does not prove
physical Electron monitor capture, NAT traversal or Internet performance.

## 5. Server fallback

The fallback uses the same authenticated stream socket and validated JPEG packet.
Remote configuration requires valid HTTPS/WSS; only explicit literal-loopback
development origins permit HTTP/WS.

- Maximum JPEG **256 KiB**, JSON message **384 KiB**, dimensions **1920 per axis**.
- Maximum **5 FPS** and **1.5 MiB/s** per sender.
- Exactly one replaceable pending frame per viewer; bounded control queues of 32.
- Student/cache cap 256, teacher socket and viewer caps 128; oversized roster
  snapshots explicitly report truncation (200 students / 1.8 MB).
- JPEG format/dimensions, viewer/session identity, role, ownership, rate and lease
  are checked. Frames are never put in SQLite, logs, evidence, outbox or temporary files.
- Disconnect, switch, session end, expiry or stop revokes both transports.
  Reconnection needs fresh authorization; old operational commands are not replayed.

Capture starts at a maximum long edge of 1280, JPEG quality 72 and a 200 ms interval
(5 FPS). Congestion reduces size/quality and can reduce rate to 2 FPS. This is an
implemented adaptation policy, **not a measured hardware throughput claim**.

The viewer hides images after three seconds without a replacement. Frame age uses
local monotonic receipt time. Sender telemetry measures capture-start-to-display-ACK
**round trip**, including processing and ACK return, and counts acknowledged FPS.
It is not one-way network latency; no 2–3 second physical latency target is claimed.

This implementation requires **one Uvicorn process**. Its memory-only live state is
not shared across workers. The documented WebSocket transport limits must be used.

## 6. Capture, consent and privacy

Consent explains possible teacher viewing throughout the exam, no additional prompt
per request, full exam-monitor scope and no stream recording/audio/live webcam.
It is recorded against the attempt/session and acknowledged before start.

Capture requires the current active session, consent, a connected authorized
receiver and an unexpired lease. A pending request alone does not capture. Each
asynchronous capture completion rechecks authorization/generation before sending.

The entire selected monitor is captured in trusted main. The application's own
webcam-preview rectangle is masked in memory so it does not become a webcam stream.
The mask uses the native content position, display coordinates, image scale and UI
zoom. Preview rectangles are checked both before and after asynchronous capture;
missing/changed geometry fails closed, without sending that frame. Enlargement or
mock images are never substituted for failed production capture.

Only recent acknowledgements for frames actually sent activate the student badge.
Starting, unavailable and degraded states are distinct. Server audits distinguish
request, first displayed frame, failure and stop; they contain no image pixels.

Closing/switching/hiding the teacher viewer, disconnects, terminal end, emergency
end and application shutdown clean up the owned socket/RTC/capture resources.
Screen-viewing failure does not pause an otherwise healthy local exam.

Browser-test screenshots contain synthetic fixtures only. Runtime screenshot/video
recording was not introduced. Entire-monitor consent still matters: other visible
desktop information is in scope; the application cannot control independent OS or
third-party recording tools.

## 7. Commands and audit guarantees

Every command binds teacher, exam, attempt, local session and live connection, with
a stable ID, creation/deadline, bounded payload and durable outcome/audit. Python
validates current local state before applying it, then persists its result. Duplicate
delivery returns that result; it cannot add time twice or affect a later attempt.

| Command | Actual semantics |
|---|---|
| Warning | Up to 400 characters, nonblocking student history, timer continues; delivered/applied does not mean read |
| Pause/resume | Add/clear only the independent teacher reason |
| End | Required reason + confirmation; existing safe terminal lifecycle, finalization and Stage 2 sync; no LMS submission |
| Add time | Required reason, 1–3600 seconds per command, total allowance <=172800; old/new/delta/actor/time recorded, elapsed time preserved |
| Monitoring recovery | Current specific >=15-second outage must genuinely be healthy; clear its approval gate only |
| Display recovery | Current incident, exactly one display, fresh calibration/geometry and teacher authorization |

Sent/delivered/applied/rejected/not-delivered/execution-unconfirmed are separate.
Lost ACKs never become invented success or failure. Reconnect reconciles actual
status; a teacher can issue a new action only after assessing it. A teacher pause
already applied survives network loss.

Time-adjustment IDs and effective allowance are part of durable checkpoints and
summary. The server validates them against issued matching commands before recovery
or complete receipt acceptance, including a lost applied ACK. Lifecycle-tail
reconciliation handles a crash between local application and command-result commit.
The client and server both bound adjustment IDs at 2048. Pending display incident
identity is also reconstructed from durable lifecycle records if a crash occurs
before its encrypted metadata update; a durable recovery clears stale approval
metadata. Neither case bypasses fresh readiness or teacher authorization.
Retention/early deletion purges command text/reason/result content while retaining
minimal audit metadata; screen frames never enter these records.

## 8. Safety and recovery boundaries

Python remains the clock, lifecycle, detector, health and protection authority.
Internet/viewer failure alone does not pause the exam. Monitoring failure retains
the existing immediate pause and <15-second automatic / >=15-second authorized
recovery boundary. Teacher resume cannot remove proctor, monitoring, display,
presentation, calibration or other independent gates.

Exactly one display is required before readiness and start. Runtime display checks
are bounded at one second. Unprotected incidents create a technical pause; removing
the extra display is insufficient without fresh calibration and teacher approval.
Turning off a monitor does not establish that Windows removed the active display.

**Protected-mode limitation:** the existing native geometry-change rule is terminal
and takes priority. It was not changed into resumable recovery. A protected count
incident with unchanged geometry also cannot reuse its old fit to clear the pause;
authorized End remains available. Supporting resumable protected display changes
would require separately approved native policy/recovery work.

Inspection found no active `SetWindowDisplayAffinity`,
`WDA_EXCLUDEFROMCAPTURE` or Electron `setContentProtection` call in the current
capture/protection source. No exclusion policy, containment, interception,
independent recovery or emergency shortcut was disabled for streaming. OS capture
failure reports unavailable. Protected physical compatibility remains unverified.

`Ctrl+Shift+Alt+Q` and emergency completion remain terminal. Historical rc8 audits
cannot authorize this changed build. No native audit or protected run was launched.

## 9. Targeted verification

All commands below selected Stage 3 or specifically affected existing paths. Counts
refer to the indicated invocation, not historic full suites or a physical exam.
The 92-case client and 36-case server runs preceded the final narrowly scoped
crash-reconciliation/limit corrections. Their affected paths were then verified
by the two focused five-case invocations below; broad suites were not repeated.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage3.py tests/test_session.py tests/test_connected_stage2.py -q
# 92 passed; 0 failed, 0 skipped, 0 deselected.

.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage3_api.py -q
# 2 passed; 0 failed, 0 skipped, 0 deselected. Actual loopback HTTP/WS.

.\.venv-server\Scripts\python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_live.py tests/teacher_server/test_live_api.py -q
# 36 passed; 0 failed, 0 skipped, 0 deselected. One Starlette/httpx deprecation warning.

.\.venv-server\Scripts\python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_sync.py -q --tb=short -k 'two_phase_start or teacher_specific_same_attempt_recovery or receipt_verified_server_score or retention_uses_actual_end or early_delete_requires or expired_bearer_can_only or receipt_reconciles_missing_start_ack'
# 7 passed; 0 failed, 0 skipped, 27 deselected.

.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage3.py -k display -q
# Final display crash-boundary fix: 5 passed; 0 failed, 0 skipped, 17 deselected.

.\.venv-server\Scripts\python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_live.py -q --tb=short -k 'allowance or added_allowance or addtime_ack or final_receipt_accepts_added_time'
# Final aligned 2048-ID bound: 5 passed; 0 failed, 0 skipped, 29 deselected.
```

From `desktop`:

```powershell
npx tsx --test tests/live-screen.test.ts tests/live-screen-owner.test.ts tests/connected.test.ts
# 12 passed; 0 failed, 0 skipped, 0 cancelled.

npx playwright test tests/ui/live-teacher.spec.ts
# 3 passed; 0 failed, 0 skipped. EN/RU/KK with mocked backend/devices.

npm run build
# PASS: TypeScript, Vite student build and Electron main/preload/transport bundles.
```

From `teacher-web`:

```powershell
npx tsx --test tests/live.test.ts
# 5 passed; 0 failed, 0 skipped.

npx playwright test --config playwright.live.config.ts --output test-results/live-isolated-final
# 4 passed together; 0 failed, 0 skipped, 26.5 seconds.

npm run build
# PASS: TypeScript and Vite teacher build.
```

Coverage includes real authenticated handshakes, cross-owner denial, presence staleness,
event deduplication, consent/lease/switching, bounded frame relay and decoded-frame
ACKs, direct production sender interoperability, fallback/stale cleanup, command
expiry/offline/no-replay/duplicate behavior, independent pauses, terminal completion,
time extension, monitoring approval, restart integration and mocked display recovery.
EN desktop/KK narrow teacher screenshots and RU student screenshot were inspected.

Review-driven capture regressions verify no zero-width quality telemetry before the
first frame, no transmitted frame after a preview-mask layout race, and malformed
stream JSON closing the owned viewer without an uncaught main-process exception.

Initial test-environment issues were corrected: sandboxed Node child-process creation
was refused before execution; focused runs succeeded with approved execution. A
Windows text locator and synthetic account/CSRF fixture isolation caused earlier
browser failures; the corrected four-case batch passed together. Earlier output
directories were retained. These were not native-protection failures.

Source builds retain Vite advisory warnings about future config-loader imports and
student bundle size; they complete successfully. No production dependency was
silently replaced with an unofficial build.

## 10. Intentionally not executed

No full Python/Electron/Playwright suite; no Windows blocking/shortcut/recovery
audit; no human gaze/webcam exam; no physical monitor switching/capture; no public
tunnel, LAN/two-network or load test; no installer/package/release validation.
Owned temporary server/socket/test threads were cleaned up. Pre-existing user
services on ports 8000/5174 were not stopped or reused by browser tests; those tests
owned separate ports 8013/5177, which were closed afterward.

## 11. Remaining issues and risks

1. Physical full-monitor capture, webcam-mask placement across real DPI/zoom,
   readable text, hardware FPS and end-to-end latency are unverified.
2. Protected capture requires a fresh matching native safety audit and authorized
   human test. Protected resumable display recovery is deliberately not implemented
   over the existing terminal policy.
3. Host-only direct ICE can fail across NAT/firewalls; own-server WSS fallback is
   implemented but public endpoint/tunnel behavior and bandwidth are untested.
4. Single-process server memory limits are defensive bounds, not proof of capacity.
   Thirty concurrent students and multiple real simultaneous teachers are untested.
5. There has been no single physical end-to-end test combining capture, commands,
   monitoring recovery and final receipt. Automated layers are identified separately.
6. This is not a tamper-proof client or a detector of actual misconduct. Existing
   heuristic events still require teacher review. Device identity remains the
   existing credential/device binding, not remote attestation.

## 12. Safe local startup

These are **manual startup instructions**, not actions performed against the user's
running service during this stage. Stop your own old local server before restarting
it; do not open duplicate listeners. Preserve/back up an existing database before
applying migration 004. Use existing private settings if already configured; the
example below is explicitly loopback-only and does not overwrite a TOML file.

Server, in a fresh PowerShell at the repository root:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
. .\server\environment.example.ps1
.\.venv-server\Scripts\python.exe -m proctoring_server migrate
.\.venv-server\Scripts\python.exe -m uvicorn proctoring_server.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers --ws websockets-sansio --ws-max-size 393216 --ws-max-queue 8 --ws-per-message-deflate false
```

Teacher UI, in a separate PowerShell:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\teacher-web'
npm run dev
```

Open `http://127.0.0.1:5174` and use the existing teacher account. For a new local
account, the existing `python -m proctoring_server invite --email <address>` command
prints a single-use link to share privately; no automatic email is sent.

Unprotected connected source student, in another PowerShell:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\desktop'
npm start -- --config config/connected.example.toml
```

Choose an **unprotected** exam policy on the teacher side as well. The public
connected example alone must not be treated as authorization to accept a protected
exam policy. Local model files and the existing student/server environments are
still required. Source assets were built; no packaged EXE is validated or supplied.

## 13. Short manual checklist — unprotected only

This checklist is pending; it was not performed during implementation.

1. Create an unprotected native quiz with the existing teacher UI. Join with one
   active display, accept screen consent and complete normal device/identity/gaze
   readiness. Verify refusal prevents start and start enables live status.
2. Select that student, start viewing, confirm the entire monitor is represented
   with the webcam preview masked, and check the student badge only after live
   frames arrive. Stop/restart viewing; hide the teacher tab and verify cleanup.
3. Send a short warning and verify the timer continues. Pause, then resume the
   teacher reason. Add 60 seconds with a reason; verify elapsed time is unchanged.
4. Briefly stop/restart the local server: local healthy examination continues,
   teacher status becomes stale, viewing stops, and commands do not execute later.
   Reconnect and explicitly request a new viewer/action if still needed.
5. End through the teacher's reasoned confirmed action. Verify local summary/PDF
   and Stage 2 receipt/review. No external LMS is submitted by that action.

Do not turn this checklist into native restrictions, physical display switching or
a full human calibration/recovery campaign without a separately agreed run.

## 14. Stage 4 gates

Stage 4 has **not started**. Before any later protected run: freeze the exact source
identity/policy, explicitly authorize native work, run its matching recovery audit
and bounded safety verification, and coordinate operator readiness. Old rc8 reports
are historical. If resumable protected display changes are required, approve that
specific policy/independent-recovery design first.

Then, only when authorized, validate physical capture/masking/DPI, actual frame rate
and measured latency, terminal cleanup and emergency release. Multi-network direct
and secure own-server relay need separate network tests; a free tunnel cannot be
assumed to support unlimited traffic. Capacity, TLS deployment hardening, retention
operations and packaging each require their own scoped verification. Do not claim
these from synthetic localhost results.

Work stops at this report, awaiting the next instruction.
