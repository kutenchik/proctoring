# Teacher Dashboard Stage 2 — durable synchronization, review and reports

Implementation checkpoint: 14 October 2026. Stage 2 extends the existing student
Electron application, Python WorkflowBridge, separate FastAPI server and teacher
React website. Python still owns devices, calibrated detection, the exam clock,
local lifecycle, evidence and native protection. No teacher command can directly
start or resume that clock.

This is a source implementation with targeted automated verification. It is not
a new protected-hardware, human-exam, deployment or package acceptance result.
Historical rc8 audits and operator runs do not validate this changed source.
Packaging and native protection audits remain paused. Stages 3 and 4 have not
been started.

## Implemented behavior

### Durable student outbox

Connected admission credentials and operation identities are saved before their
first HTTP request. The local SQLite journal lives at
`%LOCALAPPDATA%\LocalProctoring\connected-stage2.sqlite3`, outside session evidence.
Rows are protected with Windows current-user DPAPI and machine-bound entropy;
there is no plaintext fallback. A copied database alone, an exam code or a student
ID does not authorize recovery on another computer. This is device/credential
possession binding, not hardware attestation or protection against a compromised
Windows account.

A background Python worker streams original journal records by canonical session
ID and zero-based sequence, then uploads ended-session files in chunks of at most
256 KiB. Identical retries are idempotent; altered records/chunks are conflicts.
Server uniqueness constraints enforce this independently of the client. Chunk
offsets are reconciled with the server after lost responses/restarts. Network
failures never enter monitoring health or create cheating events.

The evidence whitelist includes session metadata, original events JSONL, final
summary, native answers by stable question/option IDs, saved snapshots, available
identity/reference photographs and the original local PDF. It excludes private
configuration, PINs, credentials, developer calibration exports and all continuous
video/screen/audio recordings. Local files are not renamed into new event IDs.

The manifest distinguishes present/required, disabled by policy, optional absent
and production-error material. A missing required PDF or identity artifact stays
incomplete. The existing report retry is the controlled recovery path for a failed
PDF; it does not invent a report or erase a recorded capture error. Unrecoverable
production errors require attention and retain local evidence.

The worker presents Pending, Uploading, Offline, Retrying, Needs attention or Fully
synchronized. The last state requires the complete receipt and completed local
cleanup; ending the quiz or receiving a single HTTP 200 is insufficient.

### Receipt and deletion boundary

Before committing a receipt, the server verifies all present/required files,
sizes, SHA-256 hashes, allowed structures, session/attempt identities and exact
correspondence between the uploaded events file and immutable journal records.
JPEG/PDF signatures alone do not count as valid structure. Server files are
private, durably flushed before acknowledgement, with SQLite FULL synchronous
commits. The receipt includes attempt ID, session ID, canonical manifest digest,
file/record counts and a unique receipt identity.

Automatic local deletion requires **all** of the following:

1. This is an ended connected attempt, with media/protection cleanup complete.
2. All required manifest items are present and the server has issued a complete
   receipt for that exact attempt, session, manifest and counts.
3. The client validates the receipt and checks that local material has not changed
   since upload.
4. Cleanup acts only on whitelisted manifest files in that exact session directory.

A durable cleanup marker and per-item progress allow restart between unlink and
progress commit. There is no recursive student-session deletion. Unlisted config
files, unrelated sessions, standalone records, models and application settings
remain. The encrypted outbox retains a minimal receipt/manifest tombstone after
cleanup, not a second full copy of the evidence/credentials.

After monitoring has stopped, the student may choose **Continue uploading in
background** or **Exit completely**. Background mode hides the window to the tray
and keeps only synchronization/its host alive; it does not run media, protection,
screen capture or a service. It exits when all pending uploads and cleanup finish.
Complete exit retains incomplete material for the next explicit application
launch. No autostart is installed.

### Reconciled start and authorized recovery

Start authorization and confirmation are separate. The server first authorizes
the durable start operation; Python performs normal readiness and actual local
start, saves a checkpoint, then confirms. Lost replies reconcile the original
operation/session. The server does not label an authorization as proof that the
local exam ran. This is explicit reconciliation, not distributed atomicity.

Unexpected interruption retains the original attempt/session, saved answers,
event history, elapsed time and independent proctor/recovery-PIN pause reasons.
After restart, the original device authenticates, records the interruption, and
waits for a reasoned owning-teacher authorization for that interruption. The
student must repeat normal device/reference/calibration readiness. No closed or
waiting time is charged. Monitoring/presentation readiness is established anew;
an existing human pause/PIN requirement is not silently cleared.

Running checkpoints are durably saved about once per second and at lifecycle
boundaries. A hard process/power loss can lose the fractional interval since the
last completed checkpoint; recovery cannot claim exact elapsed milliseconds that
were never persisted. Journal tails retain original event identities.

Terminal intent is saved after protection release/timer freeze and before slow
media/report cleanup. An emergency exit remains ended across restart, even when
its final summary was not yet written. It never becomes teacher-recoverable.

Admission/start/recovery keep their credential expiry. Only the five evidence
sync endpoints accept an expired bearer together with its matching device secret
for an already authorized canonical session. This prevents old offline ended
evidence becoming undeliverable without enabling a new exam or late recovery.

### Teacher review and reports

The attempt screen shows saved synchronization state, a material checklist,
timing, client and independently recalculated native results, historical images,
behavioral observations and technical records. These are not live video or online
presence indicators. External exams have no invented LMS grade.

Related same-type events within ten seconds are grouped for presentation, capped
at 100 records so each group fits an atomic bulk request. Bulk
decisions and individual exceptions append teacher-authored, timestamped versions
with comments; raw detections remain immutable. Optimistic versions reject stale
edits. Observation confirmed is separate from an academic-violation conclusion.

Manual notes preserve actual creation time, author, during-exam/later-review phase,
corrections and cancellation history. They create no fake screenshot. Relevant
later edits mark the latest conclusion as needing reconsideration.

Finalization requires an ended attempt and a currently verifiable complete
receipt. The teacher deliberately chooses no violations confirmed, violation
confirmed, or insufficient evidence. Unreviewed behavioral observations require
an explicit count confirmation, recorded in the conclusion and reviewed PDF.
Neither event count nor conclusion changes the quiz grade.

The original local PDF is preserved byte-for-byte. Each conclusion creates a new
reviewed PDF using its frozen evidence/review snapshot; old versions remain.
Generation runs in a background server task, with safe retry after failure or a
pending job interrupted by server exit. Concurrent workers cannot replace a
ready version. The PDF contains identifiers, timing, technical interruptions,
event thumbnails, decisions/comments, manual notes, author/time, conclusion,
unreviewed count and receipt. It needs a Unicode TrueType font: Windows Arial or
Linux DejaVu Sans by default, or `PROCTOR_REPORT_FONT`.

The XLSX export contains student/group/ID, attempt/status, UTC timestamps, local
and verified native results, counts, review/conclusion and mismatch information.
IDs and user strings are text cells, preventing formula interpretation and lost
leading zeros. PDF/XLSX download and evidence access require the owning teacher.
Students receive no teacher decisions or reviewed PDFs. UI additions support
EN/RU/KK with the existing sand/moss design, Nunito and Inter; technical event
identifiers stay unchanged.

### Retention

The development server installs no scheduler. Explicit
`python -m proctoring_server retain` removes only complete, ended material at
least 30 days after actual completion. When the server is off, cleanup waits for
the next invocation. Active or incomplete attempts are never deleted by admission
window age. Early teacher deletion requires ownership, a complete receipt, an
explicit confirmation and a reason.

Deletion first commits a pending tombstone, blocks readers/writers, removes only
the exact private attempt directory and purges raw/review/comment/report content.
Interrupted cleanup is retryable. Minimal attempt/conclusion identities, decision
tombstones and deletion audit remain. The retained receipt is historical, not a
claim that deleted material is still available.

## Main implementation files

| Area | Files |
|---|---|
| Durable student storage | `src/proctoring/connected/{durable,vault,sync,workflow,client}.py` |
| Existing authority integration | `src/proctoring/desktop_bridge/{workflow,protocol}.py`, `controller.py`, `session.py`, `storage/session_store.py` |
| Background presentation | `desktop/electron/{background,main}.ts`, shared contracts/protocol, renderer workflow/locales |
| Server synchronization/recovery | `src/proctoring_server/{sync,sync_routes,service,settings,database,__main__}.py` |
| Review/export | `src/proctoring_server/{review,review_reports,review_routes}.py` |
| Teacher UI | `teacher-web/src` review screen, API/types, localization and styles |
| Server-only dependencies | `server/requirements.txt`, `server/requirements.lock.txt` |
| Protocol and plan | `docs/TEACHER_STAGE2_CONTRACT.md`, `docs/TEACHER_STAGE2_PLAN.md` |

These are Stage 2 areas, not a claim that all existing working-tree changes were
made in this stage. Private configs, Git history, published releases and legacy
entry points were preserved. ReportLab and pypdf were installed only in the
separate `.venv-server`, following explicit user approval.

Migration `002_sync.sql` creates `sync_attempts`, `sync_records`, `sync_manifests`,
`sync_files`, `sync_receipts` and `recovery_grants`. Migration `003_review.sql`
creates `event_review_versions`, `manual_observation_versions` and
`attempt_conclusions`. Startup/`migrate` applies numbered migrations; tests used
isolated databases, not a live user database.

The exact payloads and endpoints are in
[TEACHER_STAGE2_CONTRACT.md](TEACHER_STAGE2_CONTRACT.md). New routes cover start
confirmation, interruption/recovery consumption/confirmation, the five sync
operations, teacher synchronization/evidence, recovery authorization, deletion,
review/bulk decisions/manual notes/conclusions, original/versioned PDF downloads
and retry, and exam XLSX export. Existing cookie/CSRF/Origin ownership and student
TLS/credential validation remain in force.

## Verification record

| Targeted check | Result |
|---|---|
| Server `tests/teacher_server/test_sync.py` | 33 passed before the final recovery-confirmation crash correction |
| Final changed server recovery paths, `test_sync.py -k 'recovery or new_interruption'` | 4 passed, 30 deselected; includes the new consumed-grant/lost-confirmation regression. These overlap the earlier 33 and are not four additional full-suite passes |
| Selected affected legacy server admission/start/repeat/expiry cases | 10 passed, 26 deselected |
| Server `tests/teacher_server/test_review.py` | 21 passed on final review/report code |
| Client `test_connected_stage2.py`, `test_connected_stage2_api.py`, `test_connected_client.py`, `test_connected_workflow.py` | 65 passed, 0 skipped: 32 new Stage 2 unit cases, 4 real loopback API cases, 29 affected existing connected regressions |
| Final changed client terminal fallback, `test_connected_stage2.py -k 'terminal_dpapi or terminal_marker or terminal_emergency or restart_after_final_summary'` | 4 passed, 29 deselected; includes the new failed-DPAPI-commit/durable-terminal-journal case and overlaps the earlier client batch |
| Desktop `tests/background.test.ts` | 5 passed |
| Desktop `tests/ui/connected.spec.ts --grep 'Stage 2'` | 4 passed: changed EN/RU/KK/recovery/receipt screens |
| Teacher `tests/review.test.ts` | 7 passed |
| Teacher `playwright.review.config.ts` | 4 real-API browser workflows passed |
| Electron TypeScript/source build | Passed |
| Teacher TypeScript/Vite source build | Passed |
| Server environment `pip check` | No broken requirements |

One existing Starlette/httpx test-client deprecation warning remains in server
tests. Deselected checks are not passes. Earlier failing assertions/crash-boundary
regressions were corrected and rerun in their affected batches. The final recovery
correction was verified by its four selected cases, not presented as a new full
34-case server run. Likewise the final terminal-journal duplication guard received
four focused client checks; the 65-case batch was not rerun after that guard.

The four real client/API cases use the actual controller journal/answers and
generated original PDF: dropped record/chunk acknowledgements, lost start
authorization with teacher recovery, expired-credential ended-outbox delivery,
and a crash after the durable original start but before its encrypted checkpoint.
Receipt/cleanup tests include restart during deletion, changed bytes, mismatching
receipts and no deletion of unrelated files. Separate recovery tests retain
independent proctor/PIN pauses and reject terminal emergency recovery. The Windows
current-user DPAPI roundtrip ran automatically; another physical PC/user account
was not tested. The recovery-consume/lost-confirmation follow-on has focused
server coverage, not an additional real client/API case.

Reproduce only these affected checks (repository root unless noted):

```powershell
$env:PYTHONPATH = (Join-Path $PWD 'src')
.\.venv-server\Scripts\python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_sync.py -q
.\.venv-server\Scripts\python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_sync.py -q -k 'recovery or new_interruption'
.\.venv-server\Scripts\python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_exams.py -q -k 'start_idempotent or preparation_boundary or duplicate_admission or repeat_ or running_attempt or phase_ or expired_credential'
.\.venv-server\Scripts\python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_review.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage2.py tests/test_connected_stage2_api.py tests/test_connected_client.py tests/test_connected_workflow.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage2.py -k 'terminal_dpapi or terminal_marker or terminal_emergency or restart_after_final_summary' -q --tb=short

Push-Location desktop
npx tsx --test tests/background.test.ts
npx playwright test tests/ui/connected.spec.ts --grep 'Stage 2'
npm run build
Pop-Location

Push-Location teacher-web
npx tsx --test tests/review.test.ts
npx playwright test --config playwright.review.config.ts
npm run build
Pop-Location
```

These commands are a verification record, not a request to repeat them all after
every edit. Select the affected cases for subsequent fixes. Builds regenerate
source assets only; no installer/EXE package was produced.

Owned test API/Vite/Playwright processes exited. Existing user development servers
were preserved. No restrictions or native helper were armed by these checks.
See also [the focused student implementation notes](CONNECTED_STUDENT_STAGE2.md).

Automatic verification uses temporary SQLite/session directories, simulated
devices, controlled clocks, real loopback HTTP and real teacher cookie/CSRF
requests. Synthetic reviewed PDFs were rendered and visually inspected: readable
Unicode names, inline evidence, concise time columns and two clean pages. XLSX
cell types, values and formats were inspected with openpyxl. No human evidence is
implied by these synthetic fixtures.

**Intentionally not executed:** full Python/Electron/Playwright regression suites,
native protection/recovery audits, keyboard blocking, webcam/microphone hardware,
human exams/calibration, package/installer validation, public HTTPS deployment,
multi-network testing and load/stress tests. Existing detector accuracy and
notification/DPI limitations are unchanged. No current protected-build acceptance
is claimed.

## Exact local development startup

Use three PowerShell terminals. These commands bind to loopback only. They do not
start a protected session. Existing dependencies are installed here; for a fresh
server environment use `py -3.11 -m venv .venv-server` and install
`server\requirements.lock.txt`. Fresh teacher `npm ci` remains a separate
environment check (see its README for the earlier registry limitation).

Server:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
. .\server\environment.example.ps1
.\.venv-server\Scripts\python.exe -m proctoring_server migrate
.\.venv-server\Scripts\python.exe -m uvicorn proctoring_server.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Teacher website:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\teacher-web'
npm run dev
```

Open `http://127.0.0.1:5174`. If another process already owns that port, coordinate
its use; do not terminate an unknown process. To invite a local test teacher in a
separate root shell:

```powershell
. .\server\environment.example.ps1
.\.venv-server\Scripts\python.exe -m proctoring_server invite --email teacher@example.edu
```

Student, using the existing **unprotected** connected example:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\desktop'
npm start -- --config config/connected.example.toml
```

`npm run build` in each frontend directory rebuilds source assets after an edit;
it is not a Windows package. A protected exam policy cannot silently fall back to
this unprotected launch. Remote connections require validated HTTPS; never turn
off certificate checks or repurpose the loopback exception for LAN/public use.

## Short safe manual follow-up (not performed here)

Use disposable test data and unprotected policies only. Do not interrupt a real
student exam or reuse a historical protection audit.

1. With two test teachers, verify ownership isolation. Create a short native exam
   from the sample question set. Use ordinary student setup if testing hardware.
2. End with local evidence saved. Stop only the owned development API, choose
   background upload or exit completely, then restart the API/app explicitly.
   Verify pending/offline becomes complete only after the receipt and exact cleanup.
3. In a separate disposable attempt, close unexpectedly while unprotected; on
   restart require the owning teacher's recovery grant and fresh readiness. Check
   saved answers, original session ID and remaining time; preserve any proctor pause.
4. Review a group, set one exception, add/correct/cancel a manual note. Confirm an
   incomplete bundle cannot finalize, then finalize deliberately after receipt.
   Compare original/reviewed PDFs, new conclusion version and XLSX; switch EN/RU/KK.
5. Test early deletion only on those disposable complete materials. Confirm other
   attempts remain. Do not use an active/incomplete session for a retention test.

Physical tray behavior, power-loss recovery, hardware readiness after restart and
the changed protected runtime still need separate coordinated verification. This
checklist is guidance, not a request to start those tests now.

## Remaining limits and next stage

SQLite/private filesystem durability depends on the host disk, backups and
permissions; this is not replicated storage. Checkpoints bound recoverable time,
not proof of a tamper-proof exam. Server-verified scores validate submitted stable
answer IDs against the immutable snapshot; a compromised client can still lie
about its observations/answers. Large datasets, multi-process deployment, live
network failure timing and fresh-host dependency installation have not been load
or deployment validated.

Stage 3 may separately add authenticated live teacher commands and screen-stream
design, with explicit authorization, bounded data and authority/safety review.
It should start only after this stage's acceptance and a scoped manual check.
Public deployment/capacity and Windows packaging remain separate deferred work.
