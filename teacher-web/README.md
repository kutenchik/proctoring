# Teacher website — Stages 1–2

For the approved Stage 4B demo design, use the built frontend and single-origin
gateway described in [the Stage 4B runbook](../docs/TEACHER_DASHBOARD_STAGE4B.md).
Do not expose this Vite development server publicly. Public/physical verification
is separately gated and has not been performed during implementation.

Separate React/TypeScript/Vite website for a normal browser. It calls the real
FastAPI service through same-origin `/api/v1` requests. There are no production
fixture records, public registration, admin pages, video streams or evidence
uploads. The existing desktop remains the student application and exam authority.

## Run locally (PowerShell)

Start the server using `../server/README.md` in a separate terminal first. Its
public example binds to `http://127.0.0.1:8000` and explicitly allows the teacher
origin `http://127.0.0.1:5174` for loopback-only HTTP development.

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\teacher-web'
npm ci
npm run dev
```

Open `http://127.0.0.1:5174`. Do not mix `localhost` and `127.0.0.1`. The Vite
proxy retains the browser Origin so backend CSRF/origin validation still applies.
For a different local API port, set `TEACHER_API_PROXY` in this shell or copy
`.env.example` to private `.env.local`. API certificate verification is never
disabled. These commands do not deploy publicly. HTTPS deployment, reverse proxy,
multi-network connectivity and capacity validation are deferred.

Use the server CLI to generate an invitation or password-reset link. Links use
`/#/invite?token=…` and `/#/reset?token=…`. The website immediately removes the
token from browser location, retains it only in memory, and sends it once to the
corresponding endpoint. Reloading that stripped link requires opening the
original unused invitation/reset link again. Successful acceptance prompts login.

## Pages and behavior

- **Exams** is the homepage. Active, Upcoming and Completed use server phase;
  cards show persisted participant/attempt counts. Active can include recorded
  unfinished attempts after admission closes. Counts and statuses are not live.
- **Library** uploads JSON/XLSX for server validation, previews questions and
  answer keys, and saves only on a separate action. Teachers see their own sets.
  Examples and EN/RU/KK schema notes are linked at `/samples/README.txt`.
- **Create exam** configures admission window, explicit IANA timezone, duration,
  native library or external HTTPS URL, shuffling, audio, snapshots and protection
  mode. Wall times are converted using the selected zone, not the browser zone;
  DST gaps and ambiguous repeated times require another time. Default protection
  is unprotected; no desktop hook or recovery gate is changed here.
- **Exam details** show frozen policy, native question snapshot, saved attempts,
  reasoned five-minute preparation extensions, and reasoned one-repeat grants.
  Scores are explicitly client-reported, not server-verified. Missing finish
  reports can leave a stale started status. Open **Review attempt** for the
  Stage 2 verified score and durable evidence receipt; an ended flag alone does
  not establish receipt or current connectivity.
- EN/RU/KK switch without losing form values. Only language preference enters
  localStorage. Session credentials remain HttpOnly cookies; CSRF stays in memory.
  Server validation detail is available verbatim as technical diagnostic text;
  primary navigation, forms, statuses and explanations are localized.

The existing design-system master governs warm sand/moss tokens, Nunito headings,
Inter body, local Latin/Cyrillic/Cyrillic-extended font assets and rounded cards.
The skill's design-system search and one narrower retry returned landing-page
patterns unsuitable for this task; those were not persisted. Its React focus,
error-boundary and async-error guidance was applied. No master override was made.

## Focused verification

```powershell
npx tsx --test tests/review.test.ts
npm run build
npx playwright test --config playwright.review.config.ts
```

These Stage 2 commands select review helpers and the four new review workflows,
not the existing Stage 1 browser suite. The tests use headless Microsoft Edge,
the real API and a fresh
synthetic SQLite database under ignored `.test-runtime/`. It requires the separate
repository `.venv-server` from the server README. It starts API port 8012 and Vite
5176, refuses to reuse an existing process, and closes its own servers afterward.
No webcam, microphone, Electron exam, keyboard restriction, native audit,
packaging or broad existing regression suite is started. Screenshots and output
go to ignored `test-results/`; do not publish its synthetic authentication data.

The lockfile is independent of desktop/package-lock.json. During implementation,
registry DNS was unavailable and a clean npm install could not complete. The
independent lock was resolved offline from the already-installed official pinned
desktop versions, then pruned by npm. Local verification used copied matching
packages in this directory (not a junction; desktop dependencies were untouched).
A fresh network install is a separate environment step, not a claimed pass.

## Short safe manual check

1. Invite and sign in as a test teacher. Import a sample, preview, then save.
2. Create an unprotected native exam with current admission window and explicit
   timezone. Open details and verify its code and frozen settings.
3. Join using the desktop's explicit connected mode. Follow normal readiness;
   after a genuine completion, refresh details and see the client-reported result.
4. Grant a repeat with a reason. For a separate unstarted attempt, grant five
   additional preparation minutes and confirm the persisted deadline changes.
5. Switch EN/RU/KK, sign out, and verify another teacher cannot see these records.

No student hardware or human gaze/protection accuracy is established by these
website tests. Later live monitoring, general remote controls, deployment and
packaging remain separate work.

## Stage 2 review workflow

Open an attempt from exam details. The amber receipt banner remains until the
server verifies the complete expected bundle. The material list distinguishes
received bytes, pending files, disabled policy, optional absence and production
errors. Timing is saved server data, never a JavaScript exam clock or online
indicator. Original local scores and server-recalculated scores remain separate;
an inconsistency is visible, and external exams have no invented LMS grade.

Behavioral observations and technical records are separate. Related detections
are grouped without removing originals. Review a group, then change an individual
decision as an exception. Comments and each version's author/time are retained.
An observation being confirmed does not automatically imply an academic
violation. Saved snapshots and identity references use authenticated evidence
URLs and are explicitly historical images. Nothing here starts camera streaming.

Manual observations have required category/description. Their during-exam or
later-review label comes from the server. Corrections and explicit cancellation
preserve version history; changing evidence/review marks an existing conclusion
for reconsideration. Adding a note does not create an image.

Choose the final conclusion deliberately. The form is locked until the server
says the attempt ended and its complete receipt is verified. If behavioral
events remain unreviewed, explicitly confirm their displayed count. Saving
creates a versioned reviewed PDF in the server background task. Refresh to see
the ready download; retry is available for pending/failed generation (including
a server restart). Earlier reviewed PDFs and the unchanged original PDF remain
separately downloadable. Exam details offer the consolidated XLSX download.

Same-device recovery is only a reasoned authorization for a recorded pending
interruption, not a remote resume command. Student readiness is still required.
Early deletion needs a complete ended attempt, a reason and explicit confirmation.
It removes server materials, reports and review contents, leaving a minimal
deletion audit. Scheduled retention is handled by the server's explicit CLI;
see `../server/README.md`, including behavior while the server is off.

## Short safe Stage 2 check

Use an isolated synthetic/development attempt, never an active student session.
Check incomplete receipt prevents finalization; inspect a historical snapshot;
review a group and set one exception; add/correct/cancel a manual note. After a
verified receipt, deliberately finalize with the explicit unreviewed warning if
needed. Refresh, download original/reviewed PDFs and XLSX, then update the
conclusion and confirm the earlier PDF version remains available. Switch EN/RU/KK
and narrow the browser. Test irreversible deletion only on disposable materials.
The automated suite follows these paths through real cookie/CSRF authentication,
real manifests/chunks/receipts and generated synthetic PDF/JPEG evidence.

## Stage 3: live supervision

From an exam's overview, open **Live supervision**. Choose a student in the roster.
The list shows current server-confirmed presence, last confirmed contact, the device's
reported exam state, monitoring state, independent pause reasons and remaining time.
The website never runs the exam timer. When contact becomes stale, values are marked
stale and operational commands are disabled. Native progress is answered/total only;
answers and provisional scores are not sent. A capped snapshot explicitly identifies
a partial roster; the exam overview retains the saved attempts.

Recent notifications keep the original event ID. Behavioral observations and technical
records are separate; notification duplication does not create another event. Use
**Review attempt** for historical evidence, manual notes and teacher decisions.

**View exam monitor** starts a short authenticated viewer lease for the selected
student only, after the student's session consent. The view is the entire exam
monitor with the webcam preview masked, not a webcam/audio stream. It has no remote
input or recording feature. Direct WebRTC uses a data channel, with no audio/video
tracks or external STUN server; authenticated own-server JPEG relay is the fallback.
The UI reports the transport actually delivering frames. It hides a frame after
three seconds without a replacement. Frame age uses the browser's monotonic receipt
clock. Reported capture-to-display-ACK round trip includes capture, encoding, network,
presentation and acknowledgement; it is not one-way network latency. Adaptive quality
can be reduced while fresh frames remain visible. Stop viewing, change selection,
leave the route, hide the page, sign out or lose the lease to stop/clean up capture.
Server account ownership enforces one selected viewer across browser tabs.

Commands require a fresh active student connection. Send a warning/message, add time
with a reason, pause, clear only the teacher pause, or deliberately end the attempt
with a reason and confirmation. Monitoring/display recovery is offered only for the
corresponding healthy/readiness-validated pending gate. A local PIN/proctor pause or
another active cause is not cleared by teacher resume. Command history distinguishes
sent, delivered, applied, rejected, not delivered and execution unconfirmed. Delivery
is not evidence that a message was read. An ambiguous HTTP retry reuses the command
request ID rather than applying a second change; older HTTP responses cannot overwrite
an already received device acknowledgement.

Preparation extension and recorded same-device restart use the existing persisted
Stage 1/2 routes. They do not remotely start or resume an exam. Closing admissions
requires a reason and confirmation and affects only new admissions. Existing attempts,
recovery and material uploads continue.

### Focused Stage 3 verification

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\teacher-web'
npx tsx --test tests/live.test.ts
npm run build
npx playwright test --config playwright.live.config.ts
```

The dedicated browser configuration owns localhost ports 5177/8013 and a new ignored
`.test-runtime` database. It does not reuse another running service. Tests use synthetic
students and generated in-memory monitor pixels through real cookie/CSRF/WebSocket
authentication. The direct case loads the existing production
`../desktop/build-electron/screen-transport.js` with a test-only trusted transport
bridge; that artifact must already have been built by the approved desktop source
build. No sender credentials are exposed to the production teacher page, saved in
screenshots, or used as URL tokens. Test code is never imported by production.

These tests are local protocol/UI checks, not human exam, physical monitor capture,
protected-mode, LAN/NAT/firewall, multi-network WebRTC or public deployment validation.
They do not enable Windows restrictions, open cameras, run old full suites or build
packages. Runtime screen frames are never stored in the browser's storage, database,
evidence outbox or screenshots. Browser-test screenshots contain only synthetic data.
The stream's FPS figure is the sender-reported count of display acknowledgements
per second, not camera capture FPS. The decoder closes each temporary bitmap and
keeps at most one pending replacement frame. SDP offers with audio/video media
tracks are rejected; only the screen data channel is accepted.
