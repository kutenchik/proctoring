# Localhost functional acceptance — 2026-10-15

Status: localhost core workflow passed automated and physical acceptance. Remaining physical observation limits are explicit below. Internet/Stage 4B acceptance remains deferred.

## Scope and isolation

Windows, Python 3.11.5, Node 24.19.0. This supplied folder has no `.git` directory; Git status/baseline cannot be established. Historical reports were read, but their private databases/evidence were not present in this source copy and were not modified. No tunnel, firewall change, native protection audit, packaged release, detector threshold change or load test was performed.

Fresh automated databases/outboxes use pytest temporary directories and `teacher-web/.test-runtime`. Physical run: `build/localhost-acceptance/manual-01`, separate teacher database/evidence, student sessions and DPAPI outbox. Electron still used its normal OS roaming profile; setting APPDATA alone did not relocate it. The existing profile was preserved. Literal loopback only; standard FastAPI development application, never a weakened public gateway. Protection, keyboard blocking, clipboard restriction, webhooks and Telegram delivery are off. Normal monitoring, reference, calibration, consent and readiness gates remain enabled.

Initial tests used the installed Python packages read-only. Separate `.venv` student and `.venv-server` server environments were subsequently prepared from their committed lockfiles, with system-site-packages disabled. Both pass `pip check`. The student imports Qt 6.11.2, OpenCV, MediaPipe, ONNX Runtime and sounddevice. Both pinned models were downloaded by the existing script and matched its SHA-256 values. Locked frontend dependencies and the Electron runtime were installed locally; shared environments were not upgraded.

## Result matrix

PASS below describes the named evidence level, not an unperformed physical check.

| Feature | Implemented | Automated verification | Physical verification | PASS / FAIL / NOT RUN | Evidence or remaining issue |
|---|---|---|---|---|---|
| Teacher login and exam creation | Yes | Real browser invitation/login/import/create/ownership | Disposable account signed in in Chrome; native exam created through real HTTP | PASS | Two questions: single choice and exact-set multiple choice; audio/snapshots on; unprotected |
| Student admission and consent | Yes | Duplicate admission, device binding, consent gates | User completed setup; teacher sees one student; consent version 3 persisted | PASS | Physical attempt recorded below |
| Active events | Yes | Canonical identity, old-record ordering, episode lifecycle | Audio activity and downward gaze persisted | PASS | No phone event observed; no detector tuning |
| Live snapshot upload | Yes | Production Requests/SyncWorker, real sockets, multi-chunk JPEG | Audio JPEG available during running exam; no early receipt | PASS | 93,692 bytes; exact local/server hash and size matched |
| Teacher thumbnail/full image | Yes | Actual browser pending→available, decoded thumbnail, disconnect persistence; owner denial in API tests | Live full image decoded at 1280×720; second teacher denied with 404 | PASS | Physical latency not instrumented; synthetic final run 387 ms |
| Warning stability | Yes | Stable DOM nodes, no animation/remount, stale journal rejection, monitoring-unhealthy suppression | User did not provide a specific flicker observation | PASS automated; physical NOT CONFIRMED | Brief yes confirmed summary; not treated as a warning-stability result |
| Monitor viewing / Stop / fresh viewer | Yes | Production sender with mocked capture; real RTC/relay browser tests | Direct viewer sampled 1–3 FPS, mostly 2; Stop and fresh viewer passed | PASS | Second Stop protocol reason teacher_stopped; presentation pauses observed |
| Teacher commands | Yes | Real Python backend outcomes for warning, pause, resume, add time, terminal End; no offline replay | Warning, pause, resume and +60 applied without timer reset | PASS | Terminal End automated only; physical exam submitted normally |
| Original PDF delivery/opening | Yes | Real controller Qt PDF→HTTP→complete receipt; byte preservation; browser download and text extraction | Chrome download byte-identical; pypdf opens 1 readable page | PASS | 53,489 bytes; correct candidate and session; attempt mapped by manifest |
| Reviewed PDF | Yes | Required receipt, teacher ownership, versioned review, browser download and text extraction | Manual test observation, deliberate test conclusion, Chrome download, 3 readable pages | PASS | 299,186 bytes; original unchanged; no academic determination |
| XLSX | Yes | Browser download; openpyxl decoded headers/result row; typed export assertions | Chrome download opened with openpyxl; one finished result row | PASS | Local 1, verified 1, total 2; finalized review; quiz result unchanged |
| Final complete receipt | Yes | Attempt/session/digest/count agreement; server independent verification | 8 files / 57 records / exact attempt and session | PASS | Receipt d00ec79aeb9c4078bb0347ebdaaf69b5; issued about 2.75 s after end |
| Correct local deletion | Yes | Complete receipt only; missing/conflicting material retained; exact file cleanup | All 8 manifest files absent locally after verified receipt | PASS | Only config.json remains in session; server evidence retained |
| Summary after cleanup | Fixed | Browser regression reproduces original bug and passes fix | User confirmed synchronization/removed-copy summary | PASS | No endless preparing state reported |
| Outage/restart synchronization | Yes | Actual listener stop/restart at same URL/port/database, worker restart, lost committed responses, multi-chunk JPEG and JSONL | Deliberately not planned during physical exam | PASS automated | 734,621-byte JPEG; recovered upload availability 0.297 s after restart in tight test loop |
| Background upload and shutdown | Yes | Backend media-release gates; main-handler background/exit tests; restart preserves pending evidence | User confirmed devices stopped; normal student exit; owned processes gone | PASS; pending-upload choice NOT RUN physically | Upload completed quickly; background choice covered automatically |
| Ownership record reader | Fixed | PS5.1/PS7 multi-record roundtrip, exact identity mismatch rejection | No live process termination test needed for parser | PASS | No weakened PID/time/executable/owner/command checks |

## Defects and corrections

1. **Student summary after verified cleanup:** the backend intentionally sets report availability false after removing local evidence. The renderer treated that state as report generation still pending, retained snapshot/reference buttons, and retained a previous missing-file error. `LiveSummary.tsx` now uses the authoritative `fully_synchronized` cleanup state to explain that server copies remain, hide removed-local-copy actions, and suppress obsolete errors. No teacher-only report access or extra local duplicate was introduced. The new headless browser regression failed before the fix and passes afterward.
2. **Windows PowerShell 5.1 multi-process ownership reader:** `@($raw | ConvertFrom-Json)` wrapped a decoded JSON array as one pipeline result in PS5.1. PS7 read the identical fixture correctly. Normalize the decoded value separately before counting records. The targeted script passes both shells and verifies all five identity fields plus duplicate-PID rejection. Historical ownership files were not changed; no process was killed during this parser test.
3. **Stale test expectations:** migration idempotence expected only migration 1 rather than current migrations 1–5. Browser review seed omitted the required original start timestamp. Corrected the assertions/fixture, without changing production migration or bundle-validation rules.

The first new multi-chunk test reached cleanup but its final query incorrectly reused credentials that cleanup deliberately purges; the test now retains its synthetic query credential separately. The first image-browser check did not scroll a lazy-loaded image into view; correcting the test interaction proved decode without a product change. These are recorded test-harness failures, not hidden clean runs.

## Targeted commands and observed results

Run from the repository root unless a directory is specified. Counts overlap; they are not a unique-test total. No full suite was run.

```powershell
# Initial installed runtime, temporary fixtures only:
python -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_event_snapshots.py tests/teacher_server/test_sync.py tests/teacher_server/test_review.py tests/teacher_server/test_auth.py tests/teacher_server/test_exams.py tests/teacher_server/test_imports.py tests/teacher_server/test_live_api.py -q
# 139 passed, 1 stale migration assertion failed (corrected below).

$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/test_live_snapshot_production.py tests/test_snapshots.py tests/test_connected_stage2.py tests/test_connected_stage3.py tests/test_events.py tests/test_stage4b_request_diagnostics.py -q
# 114 passed.
python -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_exams.py::test_migrations_idempotent -q
# Passed in the focused two-case run; new upload-test harness assertion failed then was corrected.
python -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_event_snapshots.py::test_production_http_multichunk_restart_and_final_receipt -q -s --tb=short
# 1 passed; recovered snapshot 0.297 s, valid JPEG 734621 bytes.

# Prepared pinned student environment:
.\.venv\Scripts\python.exe -m pytest tests/test_live_snapshot_production.py tests/test_snapshots.py tests/test_connected_stage2.py -q --tb=short
# 41 passed.
# Test-only access to server packages; no shared package installation:
$env:PYTHONPATH="$PWD/src;$PWD/.venv-server/Lib/site-packages"
.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage2_api.py tests/test_connected_stage3_api.py -q --tb=short
# 6 passed (also passed earlier on installed runtime).
.\.venv\Scripts\python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_event_snapshots.py tests/teacher_server/test_live_api.py -q --tb=short
# 19 passed.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-localhost-identity.ps1 -OutputDirectory build/localhost-acceptance/identity-ps5
.\scripts\test-localhost-identity.ps1 -OutputDirectory build/localhost-acceptance/identity-ps7
# Both PASS. ExecutionPolicy override is process-local, not a machine setting.
```

In `desktop`:

```powershell
node --test tests/summary-cleanup.dom.test.mjs tests/review-warning.dom.test.mjs
# 2 passed; cleanup regression initially failed before renderer fix.
node --import tsx --test tests/review-event-cache.test.ts tests/live-screen-owner.test.ts tests/background.test.ts tests/shutdown.test.ts
# 31 passed.
npm run build
# TypeScript, Vite and Electron source build passed; no installer/package.
```

In `teacher-web`, use the existing isolated Playwright configurations **sequentially** because their seed utilities share `.test-runtime/current.json`:

```powershell
npm run build
node --test tests/event-snapshot.dom.test.mjs
# Build passed; 1 DOM test passed.
npx playwright test tests/ui/workflow.spec.ts
# 5 passed.
npx playwright test --config playwright.review.config.ts
# Initially 2 passed / 2 failed due to missing start timestamp in seed.
npx playwright test --config playwright.review.config.ts --grep 'group review|confirmed deletion'
# Affected 2 passed after fixture correction.
npx playwright test --config playwright.review.config.ts --grep 'group review'
# 1 passed on the isolated pinned server; downloads retained in test-results/review.
npx playwright test --config playwright.live.config.ts
# Existing 4 tests passed: commands, direct RTC, relay/Stop/restart, preparation/recovery.
npx playwright test --config playwright.live.config.ts --grep 'active snapshot'
# New generated snapshot case passed after scrolling lazy thumbnail into view (375 ms).
# Final rerun including full-image decode: 1 passed in 8.9 s; 387 ms thumbnail decode.
```

Initial frontend execution hit sandbox subprocess EPERM and cache-only dependency misses; approved project-local installs and subprocess execution resolved those environment restrictions. Remaining build warnings concern future Vite config-loader behavior and desktop bundle size. Initial installed pypdf emitted a cryptography deprecation warning; pinned server tests retain the Starlette TestClient/httpx deprecation warning.

## Minimal normal-use startup

Dependencies and source builds are prepared in this working copy. From fresh shells, use the same run directory on every launch so pending synchronization resumes the same attempt. Never point these commands at historical public data. The helper only prepares environment/configuration, starts no process, and preserves an existing student config.

Server (repository root):

```powershell
Set-Location 'C:\Users\kuten\Desktop\proctoring-main'
. .\scripts\localhost-environment.ps1
.\.venv-server\Scripts\python.exe -m uvicorn proctoring_server.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers --ws websockets-sansio --ws-max-size 393216 --ws-max-queue 8 --ws-per-message-deflate false
```

Teacher website (second shell):

```powershell
Set-Location 'C:\Users\kuten\Desktop\proctoring-main'
. .\scripts\localhost-environment.ps1
Set-Location teacher-web
npm run dev
```

Student (third shell; only when ready for real device access):

```powershell
Set-Location 'C:\Users\kuten\Desktop\proctoring-main'
. .\scripts\localhost-environment.ps1
Set-Location desktop
npm start -- --config $env:PROCTOR_LOCAL_CONFIG
```

Open `http://127.0.0.1:5174` in a normal browser. Enter `http://127.0.0.1:8000` in the connected student app. Never mix `localhost` and `127.0.0.1`. Check listeners first (`netstat -ano -p tcp`); if a port is occupied, identify its executable/owner/creation time/command rather than terminating by port. The ports were free before this run.

To issue a fresh disposable teacher invitation, in another root shell with the same environment:

```powershell
. .\scripts\localhost-environment.ps1
.\.venv-server\Scripts\python.exe -m proctoring_server invite --email teacher@example.invalid
```

Open the printed private single-use link; accept and sign in. Import a question set, create a native exam with current admission window and unprotected mode, and enable event snapshots/audio if desired. Join with code/name/group/institutional test ID, accept v3, and complete normal readiness. During the exam use Live supervision for events, snapshots, monitor viewing and bounded commands. Submit normally; wait for the verified receipt. Then review evidence, add observations, finalize a conclusion, download original/reviewed PDFs and XLSX. Proctoring decisions do not change the independently calculated quiz score. No diagnostic observer is required for normal use.

## Safe shutdown and limitations

Finish the exam normally. Use Stop viewing. If uploads remain, select the existing background-upload choice or complete exit; complete exit preserves pending evidence. Relaunch with the same run directory to resume uploads. Background mode is synchronization-only and exits after all pending work has a verified receipt and cleanup. Close the student normally, then Ctrl+C in the specific teacher and API shells you started. Do not run blanket `taskkill`, stop an unknown PID, or delete a pending outbox/database/session directory.

Physical run completed normally. Student process session exited with code 0. The specifically owned API and Vite sessions were stopped; read-only process verification found none of the recorded student/backend/API/Vite PIDs and no listeners on 8000/5174. No blanket termination was used. Electron logs contained rejected “Untrusted IPC sender” connection calls; they did not prevent completion, and their cause was not isolated by this acceptance run. The synthetic outage test explicitly stopped/restarted only its owned listener. No manual outage is planned. Physical FPS/latency must be reported separately from generated fixtures; the 0.297 s recovery number uses an accelerated test loop, not the production retry scheduler. Retry/backoff and first-failure retention have separate targeted coverage.

Deferred Internet limitations remain in the historical Stage 4B reports, especially `TEACHER_DASHBOARD_STAGE4B_LIVE_SNAPSHOT_PUBLIC_TEST_02.md`. Local success neither diagnoses the historical public first-chunk timeout nor accepts Internet operation.

## Physical run record

- Exam `d6aea18310834b5cafbe327d29df9491`; attempt `eaa12fb2ba9f401b99df8c307fdd4802`; session `session-3d68f6bac3da406f8bcdc0509e69075b`.
- Disposable student Local Test Student / LOCAL-TEST / LOCAL-001. (trailing period is part of entered ID). User explicitly approved device setup, completed v3 consent/readiness and started the exam.
- Started 05:27:03 UTC; normal submission ended 05:34:50.336 UTC. Active exam time 332.968 s; remaining 627.032 s after +60 s extended total duration to 960 s.
- Live audio snapshot opened before completion. Downward-gaze image arrived in the final bundle. No phone event was observed. Snapshot availability during the exam had no final receipt and retained local material.
- Direct viewing observed across several minutes at 1–3 FPS, usually 2, with sampled acknowledgement round trips of 366–512 ms. Fresh viewer remained active more than 30 seconds. Stop cleared the displayed image; second Stop captured `teacher_stopped`. These are samples, not continuous FPS or latency measurements.
- Three presentation-loss/recovery pairs were recorded during window interactions, including the longer 10:29–10:31 local interval. The independent presentation gate paused the exam and recovered normally. No claim of uninterrupted monitor viewing is made.
- Warning applied while running; teacher pause froze elapsed time at 191.593 s; resume preserved that time and cleared the teacher pause; +60 increased duration 900→960 without reset. User did not give specific warning-flicker feedback.
- Receipt at 05:34:53.086 UTC: complete, 8 files, 57 records; manifest SHA-256 `a43a61f1e7c4381a252bcc6565a81153e6c97f38911cd719129b5f9ccb044a1e`. Local durable receipt and server receipt agree. Every stored file size/hash was independently verified; all eight corresponding local evidence files were removed. Session config.json remains intentionally.
- User confirmed camera/microphone activity stopped and the summary reported completed synchronization/local removal. Normal app exit was verified by process state.
- Actual Chrome downloads: `D:/original-report (1).pdf`, `D:/reviewed-report-v1.pdf`, `D:/exam-attempts.xlsx`. PDFs matched stored server bytes and opened with pypdf (1 and 3 pages; 1,433 and 3,500 extracted characters). Spreadsheet opened with openpyxl: one row, client/server scores both 1/2, finalized test conclusion. Original PDF prints session identity; attempt linkage is verified through its manifest. PDF visual rendering in a dedicated viewer was not separately checked.
- Browser download waiting initially timed out and detached that tab's debugger, although the original file downloaded successfully. A fresh Chrome tab restored control and all three downloads were verified on disk. This was a tooling interruption, not an upload failure.
- Independent verification artifacts: `build/localhost-acceptance/manual-01/{active-verification,owner-check,commands,local-receipt,final-manifest,final-verification,shutdown-verification}.json`. Evidence and downloaded reports are local private test material; do not commit them. Process identity records also contain private launch parameters and must not be published.

**Can I currently run a local exam, see snapshots during it, and receive/open all reports in the teacher dashboard?** Yes: this physical localhost run demonstrated admission, live snapshot display, normal submission, verified delivery, cleanup and teacher report downloads. Downloaded PDFs/XLSX opened successfully with document parsers. Physical warning flicker, a deliberately pending background upload, manual network outage, and dedicated PDF-viewer visual inspection remain unconfirmed/not run; relevant automated coverage is recorded above. Internet acceptance remains deferred.
