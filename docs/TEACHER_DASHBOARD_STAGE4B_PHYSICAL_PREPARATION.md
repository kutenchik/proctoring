# Stage 4B — Cross-network physical validation preparation

2026-10-14, Asia/Qyzylorda (UTC+5). **PREPARED, NOT EXECUTED. Separate public-exposure and physical-device approval required.** This is a preparation record; create `TEACHER_DASHBOARD_STAGE4B_PHYSICAL_TEST.md` only after the authorized run, with actual results.

## Evidence and scope

The [public connectivity check](TEACHER_DASHBOARD_STAGE4B_TUNNEL_CHECK.md) passed 24/24 assertions and operator-confirmed remote teacher login/dashboard/logout without a certificate warning. Its tunnel/API are closed. It did not test a remote student, devices, streaming or receipts. Stage 4A measured 2.9815 delivered FPS locally, below the original 5–10 target; that limitation remains.

Current working tree is dirty and includes untracked implementation files. HEAD alone (`e54e4f09e7be63929fc00e645d99d53629d405fe`) cannot identify the tested source. Preparation artifacts are under `build/stage4b/physical-preparation`: explicit source-transfer SHA-256 manifest, source/build/model identity, and service inventory. Existing desktop output hashes were recorded, not assumed to prove a fresh source build; build Electron from the matching source on Machine B before launch. The affected teacher frontend was rebuilt successfully here.

Read-only process verification found only the original website PID 10812, creation epoch 1791951230.0156248, owner DESKTOP-AOTO5TC\kuten, Node executable, listening on 5178. No 8034/8024 listener and none of the previous owned tunnel/API PIDs remained. No service was restarted, no tunnel created, no device or exam launched during preparation.

## Prerequisites and topology

- Machine A: existing Windows server PC, `.venv-server`, built `teacher-web/dist`, official SHA-256-verified cloudflared 2026.10.0. API on 127.0.0.1:8034 behind ONE Quick Tunnel. Fresh run/database/evidence directory, no old accounts/data exposed.
- Machine B: Windows 10/11 x64, Python **3.11 x64** (local verified baseline 3.11.5), Node **24+** (local 24.16.0), npm, current source, local models, writable storage, working webcam/microphone, one active monitor. No GPU required. Windows desktop camera/microphone permission and no competing app holding the devices. Readiness/calibration remains mandatory.
- Teacher computer: remote Windows browser with Edge installed; the prepared numerical observer opens its own ephemeral Edge profile. Node 24+, the manifest-listed observer scripts and `teacher-web` npm dependencies are needed on that computer. No teacher password is copied or stored by the observer: operator logs in manually. Ordinary remote-browser access has passed, but this observer environment on the teacher computer still needs setup confirmation.
- Operator confirms Machines A/B will use **different networks**, and answers yes to Machine B preparation. Exact versions and hashes on B have not been independently checked. Previous teacher test was on a different network; reconfirm its route for this run. Record actual network labels (e.g. A home broadband, B cellular hotspot, teacher separate broadband), not public IPs or credentials. Teacher may share B's remote network, but must be remote from A; label this honestly.

Topology: B Electron/Python -> exact public HTTPS/WSS origin -> Cloudflare -> A loopback API. Remote teacher -> same origin -> same API and built frontend. No inbound firewall/router ports, HTTP exceptions, paid services or external TURN are added. Capture is full-monitor webcam-visible consent v2; webcam is visible only when its actual preview is visible on that monitor. Covered/minimized windows do not create a separate webcam feed.

## Source-only transfer and Machine B setup (no device launch)

Do NOT copy the entire working directory or rely on `git archive HEAD`: current source is partly untracked. Copy only paths listed in `build/stage4b/physical-preparation/source-transfer-manifest.json`, retaining relative paths. Copy that manifest as well. It includes application source, public config example, locks, quiz asset and selected observer/setup scripts; it excludes build outputs, node_modules, virtualenvs, .git, private config, SQLite databases, sessions, evidence, reports, browser profiles, credentials and historical test artifacts. Separately copy only the two verified model files below, or use the pinned model fetcher. No installer/package is built.

On B, in a new project directory, verify every transferred manifest entry with `Get-FileHash -Algorithm SHA256` against its expected value; abort if any differs. Recreate dependencies on B, never copy a virtualenv. Run from that source root:

```powershell
py -3.11 --version
node --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-stage4b-student.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pip check
# Only if the exact two local files are absent:
.\.venv\Scripts\python.exe scripts/fetch_models.py
Push-Location desktop
npm ci
npm run build
Pop-Location
```

The connected source lock adds `websockets==15.0.1`, required by pyproject but missing from the historical base lock. Base lock includes Qt, OpenCV, MediaPipe, ONNXRuntime, NumPy, sounddevice, requests and psutil. No server environment is needed on B. Do not use `--no-deps -e .` without first installing the complete connected lock and checking dependencies.

Models (checked locally during preparation):

| File | SHA-256 |
| --- | --- |
| yolo11n.onnx | 7d8fd1717d9d5bbab6986cd134afb620649c7a394303d55b1e09fc00804cc5c1 |
| face_landmarker.task | 64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff |

Do not invent the upcoming hostname or reuse the closed check's hostname. **After approval and after A assigns/pins the real new origin**, run on B:

```powershell
$publicOrigin = Read-Host 'Exact HTTPS origin verified on Machine A'
.\.venv\Scripts\python.exe scripts/prepare_stage4b_student.py --origin $publicOrigin
```

This verifies both model hashes, refuses an existing `config/stage4b-student.toml`, and writes a public-example-derived configuration with connected=true, exact HTTPS, allow_loopback_http=false, protection=false, blocking=false, clipboard guard=false, VM heuristic=false; one-active-display/readiness/monitoring remain enabled. Legacy webhook/Telegram delivery remains off. Local sessions use `build/stage4b-student/sessions`; observer isolates LOCALAPPDATA. The public example PIN is a disposable development PIN, not a copied teacher credential. Never reuse these disposable settings for protected work.

Only after physical approval, launch the source student using:

```powershell
node scripts/observe_stage4b_student.mjs --operator-approved --unprotected --config config/stage4b-student.toml --output-name physical-01
```

The source observer enforces the safe flags and exact HTTPS origin before launching; it does not accept consent, start devices, answer questions, calibrate or begin the exam. It samples bounded sanitized Python state, timer, command-event metadata, synchronization classification and valid first-failure diagnostics. No pixels, answers, credentials, raw message bodies or recordings are collected. It waits for normal app closure and never kills a healthy unsynchronized exam at its sample limit. Existing application consented reference/event evidence is distinct from diagnostic capture; no new screen/webcam video or audio recording is added.

## Observer correction and targeted results

The historical ignored `teacher-observer.mjs` stored a shared `startedAt` only on its own scripted Start action. A manually created second viewer inherited that first viewer's five-minute deadline. Historical evidence/scripts are preserved unchanged; **do not use those old observers**.

The new `scripts/observe_stage4b_teacher.mjs` observes the actual viewer ID emitted by `LiveViewer`, persisted through terminal cleanup, and existing first-presented-frame timestamps. It does not depend on which person/tool clicked Start. Each identity gets its own clock; repeated notifications/recovery cannot reset it. The first frame starts 30-second/210-second measurement milestones; a separate seven-minute per-viewer safety cap starts on observing the identity even if no frame arrives. A maximum of three identities accommodates initial, explicitly authorized post-network reconnect, and final Stop/fresh viewer checks. No observer creates/reconnects a viewer.

An immutable overall deadline remains independent of all viewer clocks. The observer closes its owned browser on cap/unexpected terminal failure, preserves the original failure before cleanup, and never automatically restarts. It records at most 1800 one-second numerical samples. Actual UI state, transport, delivered counts, canvas visibility and ACK round trip are sampled; timing milestones alone do NOT assert continuous viewing, operator interaction, readability or FPS success.

The teacher frontend change adds numerical diagnostic DOM attributes plus the actual viewer ID to ViewState; it changes no auth, lease, capture, decoding or teacher command behavior. Terminal IDs survive lease disposal. The new observer reads explicit state instead of guessing it from translated prose.

For the single planned network interruption, the remote teacher operator writes `control.json` inside its NEW observer output directory immediately before disconnect:

```powershell
@{action='network_interrupt';at=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()} | ConvertTo-Json | Set-Content -Encoding utf8NoBOM <observer-output>\control.json
```

On Windows PowerShell 5 write the same JSON with `[IO.File]::WriteAllText($path, $json, (New-Object Text.UTF8Encoding $false))` instead of Set-Content. Wait until `planned-network.json` is written before disconnecting. Only the then-active viewer's `connection_lost` is classified as expected; first disconnect is still preserved. Privacy/authorization/other errors remain unexpected terminal failures. This marker cannot authorize new viewing or excuse another viewer's failure. For unexpected terminal failure stop the run and preserve sender/teacher evidence; do not repeatedly restart.

Focused verification performed, no physical/network launch:

| Check | Result |
| --- | --- |
| Node viewer-clock tests | 9 passed: manual fresh viewer, first frame, recovery, immutable overall limit, no-frame timeout, first failure, Stop, identity bounds, planned network classification |
| Python setup tests | 7 passed: safe config, exact-origin rejection, changed unsafe template fails closed |
| Teacher synthetic viewer-recovery tests | 11 passed, including actual viewer ID retained through terminal cleanup |
| Teacher source build | TypeScript and Vite passed |
| Observer JavaScript syntax | Passed (teacher and student); no browser/devices launched |

Initial Node test runner process spawn was blocked by sandbox; in-process `--test-isolation=none` passed. One command used the wrong working-directory-relative test path; corrected command passed. No full suites, native audits, protection, keyboard tests, packaging, load test or later stages ran. Remote observer UI/runtime and Machine B dependencies remain to be verified on their actual machines; synthetic tests are not physical evidence.

## Proposed bounded execution — approval required

**Maximum total public exposure: 30 minutes**, beginning BEFORE launching the tunnel, including setup and final synchronization/cleanup. Begin normal exam completion by minute 20; reserve ten minutes for receipts and shutdown. If preparation is not complete by minute 12, abort before starting an exam. Do not extend the exposure or create a replacement tunnel silently. At deadline close ingress even if receipt incomplete, retain all local evidence and mark synchronization incomplete. No forced deletion or credential migration.

A coordinator starts the independent `scripts/stage4b-exposure-deadline.py` on A before the tunnel, using the same fixed absolute deadline supplied to the teacher observer (seconds for Python, milliseconds for Node). The guard starts ownership-aware Stop at minute 29, reserving its maximum 60-second command timeout inside the 30-minute exposure budget. Begin normal cleanup earlier; treat any overrun/failure as a failed bounded-exposure check. Operator remains responsible for confirming guard is running and ingress closes; a crashed guard is not a guarantee. Use hidden Start-Process, output/error files, and record the guard's PID/creation/owner/executable/command. No script is started during this preparation.

A startup, from repository root, AFTER approval:

```powershell
$run = Join-Path $PWD 'build\stage4b\physical-01'
.\scripts\stage4b-demo.ps1 -Action Prepare -RunDirectory $run -Port 8034
$deadlineSeconds = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 1800
# Start the following guard in a separate owned hidden process, verify it stays alive:
# .venv/Scripts/python.exe scripts/stage4b-exposure-deadline.py --operator-approved --run $run --deadline $deadlineSeconds
$release = Get-Content build/stage4b-tools/2026.10.0/verified-release.json -Raw | ConvertFrom-Json
.\scripts\stage4b-demo.ps1 -Action Tunnel -RunDirectory $run -Cloudflared (Join-Path $PWD 'build\stage4b-tools\2026.10.0\cloudflared.exe') -CloudflaredSha256 $release.sha256 -OperatorApprovedPublicExposure
# Read ONLY this run's tunnel logs and copy its uniquely assigned origin:
$publicOrigin = Read-Host 'Exact assigned HTTPS origin'
.\scripts\stage4b-demo.ps1 -Action Pin -RunDirectory $run -PublicOrigin $publicOrigin
.\scripts\stage4b-demo.ps1 -Action Start -RunDirectory $run -OperatorApprovedPublicExposure
.\scripts\stage4b-demo.ps1 -Action Invite -RunDirectory $run -Email 'stage4b-physical@example.invalid'
```

Before launch recheck source/model/binary hashes and listener ownership; refuse occupied 8034. No restart is planned. If needed, obtain approval and reverify PID, creation, owner, executable, full command, origin, database/evidence paths before using Restart. Existing teacher website 5178 and prior DB/evidence are not involved. Invitation is shared privately, never included in diagnostics.

On the remote teacher computer prepare `npm ci` in teacher-web without starting anything. AFTER approval run:

```powershell
node scripts/observe_stage4b_teacher.mjs --operator-approved --origin <exact-HTTPS-origin> --deadline <same-deadline-in-epoch-milliseconds> --output <new-local-output-directory>
```

Operator logs in manually in that observer's browser; verify no certificate warning. Recheck public health, exact Origin, Secure/HttpOnly cookie flags, CSRF rejection and authenticated WSS using disposable credentials and bounded numerical outputs. Never dump tokens, bodies or browser storage. Reuse the previous public-check methodology, not its used invitations or hardcoded run paths.

### Sequence and evidence

1. A creates one disposable native quiz/exam and closes unneeded admissions. B enters the SAME exact HTTPS origin and disposable identity/code. Record successful remote admission separately from teacher login. Operator manually accepts webcam-visible consent v2, selects/tests webcam/mic, completes reference, gaze calibration, readiness and begins. No gate bypass.
2. Confirm Online, Python running state and matching remaining time. Start viewer 1 on coordinator signal. From its first displayed frame: 30 seconds untouched, then at least 180 seconds clicks/answers/navigation/scroll/focus/movement/resize/minimize/restore. Verify visible unmasked preview when window visible and after restore. Capture actual selected direct/relay transport, frames, elapsed time, ACK median/p95/max, recovery counts/durations, stale periods and canvas hiding. Separate direct failure plus successful relay from total failure. No screen frames saved.
3. During an agreed phase send warning, pause/resume and add 60 seconds with disposable recorded reason. Correlate command ID/status/result with B's Python timer/session/pause evidence; a teacher button click is insufficient. While paused, elapsed active time must not advance; extension must reconcile without clock reset.
4. After sustained phase, mark the one network interruption. B disconnects only its network for about 20 seconds, leaving local app/devices healthy. Teacher verifies stale/offline and hidden stale canvas. Coordinate one warning at disconnect boundary if allowed; after its ten-second expiry confirm it never executes on reconnect. If UI refuses/offline prevents submission, record refusal and mark physical expiry-race check unverified rather than fabricate a passed stale command. Do not forge commands or weaken checks. Verify local timer continuity from B's numeric state.
5. Restore SAME origin/network. Verify state/sync reconciliation and no duplicate attempt/reset timer. Old viewer must not capture on cached authorization. Operator explicitly starts viewer 2 with fresh authorization, verifies fresh frames. Then explicitly Stop; record `teacher_stopped`, canvas clearing and sender cleanup, distinguishing local UI reason `stopped` from authoritative sender reason.
6. Start ONE final viewer 3; measure its own full 30 seconds, including minimize/restore. No inherited clock. Any unexpected failure preserves first diagnostics and fails that check; no repeated Start attempts.
7. End normally by minute 20; leave summary open. Independently read server receipt and manifest: attempt/session identity, manifest digest and expected artifact count/hash/size must match complete stored artifacts. Compare B's verified receipt/local-cleanup state; incomplete sync must retain evidence. Do not hardcode six artifacts: compare this actual manifest. Teacher opens original/reviewed report and XLSX under ownership; record access/result without copying student contents to diagnostic logs.
8. After verification B closes summary/app normally and confirms desktop controls. Logout/close teacher browser. A uses `stage4b-demo.ps1 -Action Stop -RunDirectory $run`: exact identity verification, tunnel first, server second. Independently verify owned PIDs gone and 8034 absent, original 5178 website preserved. Only then write run `closed.json` for guard early exit. Preserve run DB/evidence, observer records and incomplete student journals; never terminate unrelated processes.

For duration/FPS compute delivered frame deltas over their measured presentation interval, report start/end and stale gaps, not configured send FPS. ACK round-trip is capture-to-display acknowledgement, not one-way network latency. Sampled state timing has approximately one-second granularity. Numerical diagnostics cap at 1800 samples per observer; no HAR, screenshots, recordings, credentials, answers or sensitive URLs.

## Execution blockers / acceptance boundary

Operator has now conditionally authorized ONE maximum-30-minute public exposure and UNPROTECTED physical run. Local source/build/binary hashes and process ownership were reverified unchanged; remote prerequisites remain pending. The exposure clock has not started and no devices have launched. This approval is not permission to bypass the remaining prerequisites. Before execution also require B source/model/version verification, teacher observer environment availability, actual network labels and clock/deadline agreement, and preserved build identity. These are setup checks, not reasons to launch a trial exam.

Final physical report must separately grade public endpoint, remote teacher, remote student admission, sustained screen viewing, direct vs relay, commands, offline/reconnect, final fresh viewer, matching receipt/local cleanup and 5–10 FPS goal. Report unverified checks explicitly. No physical success is claimed now. No Stage 4C/4D or packaging.

## Operator topology revision � before execution

The operator chose a remote-teacher test with server and student on this computer, teacher on the other computer. The existing one-run maximum-30-minute conditional authorization applies to this narrower scope. This is NOT remote-student or full cross-network integration evidence. Confirm the teacher network and observer availability before starting the clock. No public exposure/device launch has begun. Do not disconnect this computer's network as though it were an independent remote student: doing so also disconnects the tunnel/server. Adapt the interruption to the remote teacher network, label it teacher-network loss, and leave student-network isolation untested. Preserve the same manual consent/readiness, sustained viewing, command, Stop/fresh-viewer and verified-receipt checks.
