# Teacher service — Stages 1–3

Stage 4B adds an optional single-origin demo gateway for the **built** teacher UI
and this same application. See [the Stage 4B runbook](../docs/TEACHER_DASHBOARD_STAGE4B.md).
Public exposure requires separate approval; never tunnel the Vite development server.
The HTTP development exception now requires a literal loopback IP such as 127.0.0.1.

This is a separate FastAPI application and SQLite database. It imports only the
existing pure Python quiz validator/scorer package; it does not initialize Qt,
camera, audio, Electron or Windows protection. The desktop still owns local exam
timing, calibrated monitoring, immediate scoring and local evidence. Stage 2 adds
durable synchronization, server answer recalculation, versioned teacher review,
reports and same-device recovery approval. Stage 3 adds authenticated live status,
teacher commands, explicit screen-viewing consent and bounded memory-only relay.
See the [Stage 2 report](../docs/TEACHER_DASHBOARD_STAGE2.md) and
[Stage 3 protocol and limits](../docs/TEACHER_STAGE3_CONTRACT.md), plus the
[Stage 3 implementation and verification report](../docs/TEACHER_DASHBOARD_STAGE3.md).

SQLite is appropriate for the initial single-host development service. Each
operation opens its own connection, enables foreign keys and uses WAL. Mutations
use `BEGIN IMMEDIATE` so duplicate admissions, repeat grants and deadline/start
races serialize. Numbered SQL migrations in `src/proctoring_server/migrations`
are recorded in `schema_migrations`. This is not a 30-student capacity claim.

Stage 3 live routing uses one server process (`--workers 1`, the default); its
bounded presence, viewer leases and relay slots are intentionally in memory.
Do not add multiple Uvicorn workers without a separately designed live-state
broker. A server restart closes live connections and leases; durable exam
evidence and command audit records remain in SQLite, while the local exam
continues under Python's authority. TLS/public deployment, physical capture
validation and native protected-display changes are separate checks.

## Development commands (PowerShell, repository root)

Use a separate environment; do not install these dependencies into the desktop
environment or change its lockfile:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
py -3.11 -m venv .venv-server
.\.venv-server\Scripts\python.exe -m pip install -r server\requirements.lock.txt
. .\server\environment.example.ps1
.\.venv-server\Scripts\python.exe -m proctoring_server migrate
.\.venv-server\Scripts\python.exe -m uvicorn proctoring_server.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers --ws websockets-sansio --ws-max-size 393216 --ws-max-queue 8 --ws-per-message-deflate false
```

The example explicitly opts into HTTP **only for literal loopback origins**.
Open the separate teacher website at `http://127.0.0.1:5174`; do not substitute
`localhost` in just one of the URLs. It uses a development `/api` proxy. Run the
teacher frontend's documented Vite command in a second shell.

`requirements.lock.txt` records the versions actually installed and tested in
the isolated Python 3.11 environment. `requirements.txt` states the supported
direct dependency ranges. The first installation on this machine encountered
DNS failures for PyPI's file host. The successful installation used an explicit
read-only DNS lookup and a process-local resolver for that official host, with
normal HTTPS hostname/certificate checks; no OS DNS or desktop environment was
changed. This workaround is not part of application code or its launch command.

For local HTTPS instead, unset `PROCTOR_ALLOW_LOOPBACK_HTTP`, set both origins
to HTTPS and give Uvicorn `--ssl-certfile <certificate.pem> --ssl-keyfile
<private-key.pem>`. Configure the frontend/reverse proxy with a certificate
explicitly trusted by the test machine. Never disable certificate validation.
An Internet-facing deployment requires separate TLS/reverse-proxy, firewall,
same-site cookie, deployment security and capacity validation in a later stage;
this example is deliberately bound to loopback.

In another shell with the **same environment variables**, generate a teacher
invitation:

```powershell
. .\server\environment.example.ps1
.\.venv-server\Scripts\python.exe -m proctoring_server invite --email teacher@example.edu
# Password reset for an existing teacher:
.\.venv-server\Scripts\python.exe -m proctoring_server reset --email teacher@example.edu
```

Share the printed link privately with that teacher. Tokens have 256 bits of
randomness, are stored only as SHA-256 hashes and expire after one hour. They are
single-use; issuing a replacement revokes previous outstanding links of that
kind. There is no public registration. Passwords use salted scrypt
(`N=32768,r=8,p=1`); password reset revokes all teacher sessions. Links keep the
token in the URL fragment, which is not sent in HTTP requests or referrers; the
web application removes the token from its location after reading it.

Sessions use random opaque, hashed credentials in HttpOnly, SameSite=Strict
cookies. Secure is the default; only the explicit loopback HTTP setting relaxes
it. Mutations require an exact configured Origin and a session CSRF token in
`X-CSRF-Token`. Login is throttled persistently per email and direct client IP.
The launch command disables Uvicorn's proxy-header interpretation so clients
cannot forge the peer IP used by that budget. Production reverse proxy integration and
operational abuse protection remain unverified.

Settings are environment-only:

| Variable | Default |
|---|---|
| `PROCTOR_SERVER_DATABASE` | `server/data/teacher.sqlite3` |
| `PROCTOR_SERVER_URL` | `https://localhost:8443` |
| `PROCTOR_TEACHER_ORIGIN` | `https://localhost:5174` |
| `PROCTOR_ALLOW_LOOPBACK_HTTP` | unset |
| `PROCTOR_SESSION_SECONDS` | `43200` (12 hours) |
| `PROCTOR_TOKEN_SECONDS` | `3600` |

No account/password/session secret is committed. Protect and back up the SQLite
database, including its WAL files during use. It contains teacher/student data.
Do not put real emails, database files, tokens or exported records in Git.

## Question imports

Examples: `server/samples/questions.json` and `server/samples/questions.xlsx`.
Imports are limited to 2 MiB and 200 questions. Every question is worth one point.
Multiple choice requires the exact set of answers, with no partial credit.

JSON:

```json
{
  "title": "My question set",
  "questions": [{
    "id": "q1",
    "type": "multiple_choice",
    "prompt": "Select the even numbers.",
    "options": [{"id":"a","text":"2"},{"id":"b","text":"3"},{"id":"c","text":"4"}],
    "correct_option_ids": ["a", "c"]
  }]
}
```

Question IDs are unique across the set. Option IDs are unique within each
question. IDs remain stable through shuffling. `single_choice` requires exactly
one correct option. Options and prompts must be nonempty. Duplicate object keys,
non-finite JSON numbers, invalid answer references and unsupported types fail
validation. The save endpoint validates the preview again.

XLSX contains exactly one sheet named `Questions`. Its header is exactly:

```text
question_id | type | prompt | option_id | option_text | is_correct
```

Use one option per row; repeat the same ID/type/prompt for all options of a
question. IDs and prompt/option fields must be text; `is_correct` must be a
literal Excel TRUE/FALSE or numeric 1/0. The filename becomes the set title.
Formula cells, external links, macros, encrypted archives and excessive archive
expansion are rejected. No formulas are evaluated. No spreadsheet editor is
implemented.

An exam stores an immutable copy of the selected set and teacher policy.
Admission creates a second frozen snapshot with the optional question/option
shuffle applied once; reconnect and start return the same order and stable IDs.
Answer keys are returned only through the attempt credential to the trusted
desktop Python scorer; its renderer must receive the existing sanitized quiz
view. Stage 1 cannot prevent the owner of a modified student process from
inspecting local answer keys, and reported scores are not server-verified.

## API and semantics

All routes are under `/api/v1`. JSON failures use
`{"detail":{"code":"...","message":"..."}}`. No raw request/password/token
is echoed in validation errors. Responses have `Cache-Control: no-store`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | API version and UTC server time |
| `POST /auth/accept-invite` | Single-use invitation/name/password |
| `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` | Teacher cookie session |
| `POST /auth/reset-password` | Single-use reset/password; revoke sessions |
| `GET/POST /libraries`, `GET /libraries/{id}` | Teacher-owned question sets |
| `POST /libraries/preview` | Authenticated multipart import (`file`) |
| `GET/POST /exams`, `GET /exams/{id}` | Teacher-owned immutable exams |
| `GET /exams/{id}/attempts` | That teacher's attempts only |
| `POST /attempts/{id}/extend` | Required reason; preparation +300 seconds |
| `POST /attempts/{id}/allow-repeat` | Required reason; one new admission |
| `POST /student/admit` | Code/name/group/Student ID; attempt bearer credential |
| `GET /student/attempt` | Credential-owned immutable admission state |
| `POST /student/start` | Server deadline check; idempotent authorized start |
| `POST /student/finish` | Optional best-effort **client-reported** terminal result |

No teacher endpoint exposes an attempt's bearer credential or its hash. Resource
ownership is enforced by backend SQL queries, including libraries referenced
at creation and attempts modified by ID.

Admission timestamps require explicit offsets and are stored/returned in UTC;
the exam also requires a valid IANA timezone (Windows uses `tzdata`). Admission
opens inclusively at the start and closes exclusively at the end. Exam list
phase remains active while admission is open, an admitted preparation deadline
is valid, or an unfinished started attempt is recorded. `admission_open` reports
the window separately. These are **recorded states**, not a live connection or
monitoring claim: a missing client finish can keep an exam active. Participant
and attempt counts come from persisted rows.

Student IDs are trimmed at their outer edges, then matched **case-sensitively**,
without Unicode/case/numeric coercion. Group and Student ID each allow at most
128 characters, matching the desktop. Students must use their institutional ID
consistently. Student ID alone never retrieves or starts an attempt. The initial
300-second preparation period uses server time. At the exact deadline, first
start is rejected. A teacher extension uses `max(previous_deadline, now)+300`
and stores the old/new deadlines and mandatory reason in the audit log. Already
admitted students can start after admissions close if their preparation is valid.

A repeat can be granted only after client-reported completion or expired,
unstarted preparation. Each grant is consumed atomically by one new admission.
It does not override a closed admission window. A superseded credential cannot
start/read/finish a newer attempt. A running attempt cannot be repeated just
because its original preparation deadline elapsed.

The credential remains valid for 30 days after the preparation deadline for
scoped reconnection and best-effort finish, but never removes the start gate.
Repeated `start` on the same already-started, unfinished attempt is idempotent;
`finish` is terminal and subsequent submissions cannot overwrite its result.
Network loss after an authorized start must not pause/end the local exam. Stage
1 has **no durable finish retry queue**, verified server score or automatic
closure for a disappeared client. A teacher may therefore see a stale `started`
status; the interface must not present it as live monitoring. A lost start
acknowledgement or crashed client can also leave that state. Stage 1 deliberately
has no teacher command to terminate it or approve a repeat of a started,
unfinished attempt. This is an operational limitation to resolve with an
explicit recovery policy in a later stage. External exams accept no local score;
ending local monitoring does not submit answers to the external LMS.

## Stage 2 durable evidence and recovery

The Stage 1 best-effort behavior above describes **legacy unbound clients only**.
Current connected clients persist a device-bound admission request before HTTP,
then use two-phase start authorization/confirmation, immutable journal batches,
resumable file uploads and a verified complete receipt. The server retains the
original quiz and policy snapshots and independently recalculates native scores.
See [the exact API contract](../docs/TEACHER_STAGE2_CONTRACT.md) for every payload.

Migration `002_sync.sql` adds device/start/recovery state, unique journal sequences,
manifests, file progress and complete receipts; `003_review.sql` adds versioned
teacher reviews and report conclusions. Existing Stage 1 databases migrate on
startup. No private config, credentials, answer keys, video or audio recordings
belong in uploaded evidence. Teacher evidence routes require session ownership;
student routes require both the attempt bearer and `X-Device-Secret`.

Evidence defaults to `server/data/evidence`; `PROCTOR_EVIDENCE_ROOT` overrides it.
Keep this directory outside every public static/document root. Files use server
owned opaque names, bounded chunks (256 KiB), SHA-256 checks, structural PDF/JPEG
validation, fsync before acknowledgement and SQLite FULL synchronous commits.
JSONL records are immutable by `(attempt_id,sequence)`; changing a retry is rejected.
Both metadata files must name the canonical local session and server attempt.
Present/required files are reverified before a final receipt or conclusion; missing
required PDF/identity or production errors cannot count as complete. File ACKs
alone never authorize local deletion. The complete receipt must match the entire
ended attempt manifest, counts and session on the student device.

Start authorization does not start the server's recorded timer. A durable local
start is confirmed separately. Lost responses reconcile the same operation/session;
they never authorize a duplicate timer. Unexpected restart requires the original
secure device credentials, a saved checkpoint, owning teacher approval for that
specific interruption, and fresh local readiness checks. Recovery preserves elapsed
time, remaining time, answers and pause reasons. Terminal emergency completion
cannot be resumed. This is possession/device binding, not hardware attestation or
proof that a compromised student machine is untamperable.

The development server does **not** install a scheduler or service. Run cleanup
explicitly from the root (with the same server environment) when desired:

```powershell
. .\server\environment.example.ps1
.\.venv-server\Scripts\python.exe -m proctoring_server retain
```

It deletes only completely received ended material at least 30 days after the
actual completion timestamp. If the server is off, cleanup waits for this command.
An owner can delete earlier through the teacher UI with confirmation and reason.
Incomplete or active attempts are never age-deleted. A committed deletion-pending
marker blocks reads/writes before the exact owned directory is removed; retry
completes interrupted deletion. Raw journal/manifest contents, snapshots, original
and reviewed PDFs, review/comment histories and manual observation contents are
purged. Minimal decisions, receipt tombstones and deletion audit remain; deleted
material is not presented as synchronized or available for final review.

The 30-day credential lifetime still gates admission/start/recovery. To avoid
stranding ended offline evidence, only the five `/student/sync/*` endpoints accept
an expired bearer together with its matching device secret, and only for a
previously authorized canonical session. This capability cannot start or recover
an exam. Late final evidence reconciles a lost start ACK using its original local
start timestamp. No general credential renewal or administrative override exists.

## Focused verification

```powershell
. .\server\environment.example.ps1
.\.venv-server\Scripts\python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_sync.py tests/teacher_server/test_review.py -q
```

`--confcutdir` deliberately excludes desktop/UI fixtures, devices and protection.
Only the changed Stage 2 server paths are selected. The main Python/Electron suites,
native audits, hardware, packaging, public deployment and load tests are excluded.

For a safe manual check: invite two teachers; sign in as one; import and preview
the sample; create an **unprotected** exam with an open window. Verify the second
teacher cannot see it. Join from the existing desktop's explicit connected
mode, complete normal setup, start and finish; confirm the attempt appears as a
client-reported result. Try the same Student ID again, then use a reasoned repeat
authorization and retry. Let a separate admission exceed five minutes; verify
start is blocked until its teacher grants a reasoned extension. No native
blocking or new model/hardware test is required for the server test suite.
