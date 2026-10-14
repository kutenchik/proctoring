# Teacher Dashboard — Stage 1 implementation plan

The teacher application is a separate React/TypeScript website. A separate
FastAPI service owns accounts, libraries, exam snapshots and admissions. SQLite
uses numbered SQL migrations, foreign keys and transactional writes. This is a
single-host development foundation, not a verified Internet deployment or load
capacity claim. Existing desktop Python retains devices, calibration, scoring,
monotonic exam timing, evidence and native protection authority.

1. Implement server persistence, CLI invitations/resets, secure cookie sessions,
   per-resource ownership and bounded validated imports.
2. Implement teacher exam list, library preview/import, creation and attempt
   administration. Reuse the existing design tokens and EN/RU/KK conventions.
3. Add explicit connected student mode with a narrowly scoped Python HTTP client,
   admission credentials, immutable policy application and server start approval.
   Extend the existing quiz model for exact-set multiple choice; no JS scoring.
4. Run targeted tests and affected builds only. Document commands, contracts and
   remaining limits; stop before Stage 2.

## Working API contract (v1)

Base `/api/v1`. JSON errors: `{detail: {code, message}}`. IDs are opaque strings.
Times are UTC ISO-8601 with offsets; exam `timezone` is an IANA identifier.

- `GET /health`: `{service:"local-proctoring-teacher", api_version:1, server_time}`.
- `POST /auth/accept-invite`: `{token,name,password}`.
- `POST /auth/login`: `{email,password}`; returns `{teacher,csrf_token}` and an
  HttpOnly session cookie. `GET /auth/me` returns the same authenticated payload.
- `POST /auth/logout`: authenticated with `X-CSRF-Token`.
- `POST /auth/reset-password`: `{token,password}`; invalidates all old sessions.
- `GET /libraries`: `{items:[{id,title,question_count,created_at}]}`.
- `POST /libraries/preview`: multipart `file`; returns normalized question set.
- `POST /libraries`: normalized question set; validates and saves it.
- `GET /libraries/{id}`: normalized set plus id/created_at, teacher-only.
- `GET /exams`: `{items:[exam]}` with phase and persisted attempt counts.
- `POST /exams`: `{title,exam_type:"native"|"external",admission_start,
  admission_close,duration_seconds,timezone,library_id?,external_url?,
  shuffle_questions,shuffle_options,audio_monitoring,save_snapshots,
  protection_mode:"protected"|"unprotected"}`.
- `GET /exams/{id}`: exam detail, snapshot and immutable policy, teacher-only.
- `GET /exams/{id}/attempts`: `{items:[attempt]}`, teacher-only.
- `POST /attempts/{id}/extend`: `{reason}`, adds 300 seconds; teacher-only.
- `POST /attempts/{id}/allow-repeat`: `{reason}`, authorizes one new admission
  after the old attempt is finished or its preparation expired; audited.
- `POST /student/admit`: `{exam_code,full_name,group,student_id}`; returns
  `{attempt_id,credential,server_time,preparation_deadline,exam,quiz}`. `exam`
  includes the fields above, id/code and a policy snapshot. `quiz` is the frozen
  question set including answer keys for the trusted Python scorer, never React.
- `GET /student/attempt`: Bearer credential; returns same public admission state
  without issuing another credential. Credentials never enter teacher views.
- `POST /student/start`: Bearer credential; validates preparation deadline using
  server time and atomically marks started. Idempotent retries on same credential.
- `POST /student/finish`: Bearer credential; best-effort terminal status and local
  score/total/end_reason. No events, images, recordings or durable sync in Stage 1.
  Teacher UI must label these as client-reported results, not verified grading.

Teacher mutations use authenticated cookies and CSRF headers; student endpoints
use per-attempt bearer credentials. No public teacher registration.

## Shared quiz format

`{title,questions:[{id,type:"single_choice"|"multiple_choice",prompt,
options:[{id,text}],correct_option_ids:[id]}]}`. IDs are nonempty stable strings.
Each question is one point, multiple choice requires exact set equality. The
desktop Python `Quiz.from_document()` adapts this to the existing model. Desktop
display indices remain an internal convenience; option IDs survive shuffling.

## Safety and scope

Use a separate server environment; do not edit private configs. Standalone mode
stays available. Local connected development uses HTTPS (development certificate
trusted explicitly); a loopback-only HTTP exception may be enabled explicitly
for development and must never apply to remote hosts. Network loss after an
authorized start is not an exam pause or misconduct event. Protected policies
cannot arm an unprotected launch. No native audit, keyboard blocking, operator
hardware tests, packaging, release or Git-history changes are part of Stage 1.

New source changes invalidate prior protection identities. Historical rc8 reports
remain evidence for rc8 only, not permission to arm this new source build.
