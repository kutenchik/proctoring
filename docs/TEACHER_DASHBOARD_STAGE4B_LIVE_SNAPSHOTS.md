# Stage 4B: active event snapshots and synchronization diagnostics

Implementation and targeted automated verification: 2026-10-14. Public/physical verification of this change: **not performed**. No public tunnel, real exam, device capture, existing-service restart, packaging or native protection test was started. Existing private databases, old pending physical attempt, six preserved evidence files and historical reports were not modified.

## 1. Architecture

The existing event engine and camera snapshot writer remain the only producers. An activated canonical event records pending, disabled or production-unavailable status. The writer flushes/fsyncs its temporary JPEG before atomic publication. Its completion produces a status record with the original event ID, start timestamp and duration, rather than a second canonical event.

The existing background SyncWorker uploads journal records first, then discovers completed event-associated files from those acknowledged records. Queue metadata, discovery offsets, stable IDs and completion flags live in the existing durable encrypted outbox. One 256 KiB chunk is attempted per worker turn. Image validation, hashing and networking run outside capture, exam, quiz, command and screen-stream work. There is no additional capture pipeline.

## 2. API and schema

New authenticated routes under `/api/v1`:

- `POST /student/sync/snapshots`: `{session_id,event_id,size,sha256}` declares provisional evidence and returns its item ID, byte frontier and completion state.
- `POST /student/sync/snapshots/{item_id}/chunks`: `{session_id,offset,data_base64}` uses the existing durable chunk implementation without requiring an ended-attempt manifest.

Student credential, device secret, bound session, enabled attempt policy, consent v3 and an existing canonical journal event/path are required. The item ID is `event_` plus SHA-256 of the existing event ID. Content is limited to 8 MiB and 16 million pixels; declaration totals are bounded at 1,900 files / 240 MiB. Existing chunk bounds remain 256 KiB.

Migration `005_event_snapshots.sql` adds unique attempt/event-to-item mappings and an event lookup index on sync records. It was exercised only in temporary test databases. Applying migrations to an existing private database remains outside this run.

The existing owning-teacher `GET /attempts/{attempt_id}/evidence/{item_id}` supplies both the thumbnail and full image. The thumbnail is the same authenticated JPEG rendered at thumbnail dimensions, not a public static URL or separate derivative. Existing no-cache and owner checks apply.

## 3. Durability and idempotency

Only atomically published canonical `snapshots/{event_id}.jpg` files are considered. Client and server decode/validate JPEGs, size and SHA-256. A local identity is frozen before declaration, including when the response is lost. Repeated declaration returns the stored frontier; interrupted and duplicate chunks use existing idempotent offset/hash rules. Accepted content and identity cannot be replaced.

The queue scans at most 100 new records per turn. At its 1,900-entry limit, discovery stops at the unprocessed journal record; evidence remains on disk and final synchronization remains eligible. Large/invalid or changed evidence requires attention rather than silent discard. This is bounded early delivery, not an unlimited evidence queue.

## 4. Live teacher visibility

After durable completion, the server broadcasts an owning-teacher student projection. Periodic authenticated snapshots reconcile missed notifications. Persisted journal records and file mappings reconstruct availability after student disconnect or server restart.

The live timeline presents pending, available, unavailable (capture/production failure), disabled and not-applicable states. Pending switches automatically to an authenticated thumbnail and full-image toggle. Event keys remain stable, canonical timestamps determine ordering, and the reserved image slot avoids repeated layout movement. Snapshot updates preserve inspection state and do not animate/remount the entire warning timeline. Existing grouping and review decisions remain in place. EN/RU/KK strings were added.

## 5. Offline and backpressure

Connection/server-unavailable failures use the existing bounded exponential retry (up to 60 seconds). Missing late files remain pending and are rediscovered. A restarted worker redeclares the same item and resumes the server frontier, including after a lost successful response. Failed delivery neither pauses the exam nor becomes misconduct. Invalid local JPEGs are retained and skipped, allowing other queued files to progress; a later valid publication can recover before declaration. Authentication/content conflicts require attention.

## 6. Final manifest, receipt and deletion

Early acknowledgements never create a final attempt receipt and never authorize deletion. Final manifests retain the exact provisional item ID, path, size and hash. The server rejects omission or remapping of provisional files. Already completed files are reused; incomplete files resume through final synchronization.

Local cleanup still requires an ended attempt, the complete expected bundle, server-verified final completion and a matching locally validated receipt (attempt/session/manifest and required file identities). Required material missing at finalization is retried so late publication can recover. Missing/conflicting material cannot be excused by early image success.

The existing retention mechanism is unchanged: 30 days using the existing completed/fully-received manifest completion timestamp, with cleanup performed by the existing explicit retention invocation. Provisional mappings are removed with the existing authorized material purge. No new cleanup of incomplete attempts is introduced.

## 7. Policy and consent

Disabled policy prevents snapshot production and early upload while preserving non-image events. Server policy independently rejects prohibited declarations. Consent v3 in EN/RU/KK explicitly discloses event-associated camera snapshots being uploaded and reviewed by the authorized teacher during the exam. Client workflow, IPC/capture boundary and server start/viewer gates agree on v3. Old v1/v2 consent is not silently upgraded; legacy ended Stage 2 evidence synchronization is preserved.

No continuous/periodic webcam capture, audio recording, monitor recording, or second camera path was added. Existing real-time monitor-viewing behavior was not expanded.

## 8. Preserved admission failure

Read-only inspection of `build/stage4b/synthetic-02/sync-admission-http.json`, preservation metadata, server log and the historical public report confirms a separate admission request failed with `connection_failed`: request phase, 468 ms, 336 request bytes, no HTTP status and zero response bytes. It preceded session start, bundle creation, manifest and chunks. The available server log does not establish receipt of that HTTP request.

These facts cannot distinguish DNS, TLS, tunnel connectivity, origin/authentication rejection with a lost response, server availability or another transport failure. They do not prove a client timeout. No root cause is asserted. The older Cloudflare `context canceled` chunk interruptions occurred at a different phase and are not assigned the same cause.

Future diagnostics add an explicit admission operation and a bounded, fixed-vocabulary transport failure classification by exception types/errno (DNS, certificate/TLS, connect/read timeout, refusal/reset, unreachable network and interrupted response), falling back to connection_failed. Exception text, URLs, credentials and response bodies are not copied. Existing request measurements and first-failure preservation remain. Timeouts were not globally extended; no historical request was retried.

## 9. Targeted automated verification

Python used the existing runtime and installed libraries, without installation:

```powershell
$env:PYTHONPATH="$PWD/src;$PWD/.venv-server/Lib/site-packages"
$python = 'build/stage4b/physical-01/student-venv/Scripts/python.exe'
& $python -m pytest tests/teacher_server/test_event_snapshots.py tests/teacher_server/test_sync.py tests/teacher_server/test_live.py --confcutdir=tests/teacher_server -q
# 89 passed (initial implementation; before additional focused cases)
& $python -m pytest tests/test_live_snapshot_production.py tests/test_snapshots.py tests/test_stage4b_request_diagnostics.py tests/test_connected_stage2.py tests/test_connected_stage3.py -q
# 77 passed
& $python -m pytest tests/teacher_server/test_event_snapshots.py tests/teacher_server/test_live.py --confcutdir=tests/teacher_server -q
# 57 passed after timeline ordering and consent rejection changes
& $python -m pytest tests/test_live_snapshot_production.py tests/test_stage4b_request_diagnostics.py tests/test_connected_stage2.py -q
# 45 passed after producer duration and diagnostic offset changes
& $python -m pytest tests/teacher_server/test_live_api.py --confcutdir=tests/teacher_server -q
# 5 passed after updating current protocol consent fixtures
& $python -m pytest tests/teacher_server/test_event_snapshots.py -k queue_cap --confcutdir=tests/teacher_server -q
# 1 passed, 12 deselected
```

Teacher-web directory:

```text
node --test tests/event-snapshot.dom.test.mjs   # 1 passed
npm run build                                # TypeScript + Vite passed
```

Desktop directory:

```text
npm run typecheck                                                    # passed
node --import tsx --test tests/live-screen-owner.test.ts tests/review-event-cache.test.ts
# 24 passed, including old-consent rejection and stable event cache
node --test tests/review-warning.dom.test.mjs                          # 1 passed
```

New tests cover active/late production, same canonical identity, local HTTP and authenticated WebSocket notification, image access/owner rejection, duplicates, lost-response restart recovery, invalid JPEG/hash, disabled policy, final reuse/receipt-only deletion, blocked transport with concurrent checkpoint persistence, stable timeline DOM and inspection state. Temporary databases, synthetic JPEGs and mocked capture were used. Headless Edge DOM checks and Node workers needed subprocess permission after sandbox EPERM. A Starlette/httpx deprecation warning remains; dependencies were not changed. Counts above overlap and are not a total unique-test count. No full suites were run.

## 10. Limits

This establishes implemented behavior and local automated checks, not public-network reliability, real-device performance or physical end-to-end latency. Healthy-connection delivery within a few seconds is a goal, not a guarantee. The latest public relay success predates this change and does not verify these snapshots or synchronization. Overall public Stage 4B synchronization acceptance remains incomplete.

Live event history remains bounded (latest 100 persisted events before existing projection/payload limits); full evidence/review uses the existing review flow. Thumbnail transfer currently fetches the original bounded JPEG. Transport classification improves diagnosis but cannot conclusively identify infrastructure causes in every wrapped error. Queue-cap overflow is deferred to final synchronization; final bundle limits still apply. Invalid local files can remain pending until repaired or a canonical production failure is recorded.

## 11. Safe local verification

Run only the focused commands above against their temporary fixtures. The new HTTP/WebSocket case owns and closes its ephemeral loopback server; it does not use existing services. For visual inspection, use the isolated synthetic DOM fixture to inspect pending-to-available, open-image state and disabled policy. Do not point these fixtures at old private databases/outboxes or the preserved physical session. Do not launch the student application or real devices for these checks.

## 12. Recommended future bounded public retest (not executed)

Obtain separate permission for one fresh isolated synthetic public run, at most 15 minutes, with an independent deadline shutdown and fresh disposable account/database/outbox. Rebuild and prepare a consent-v3 fixture; prior sealed preparation is not reusable as validation of this changed build. Use only generated event JPEGs, no real devices. Preserve safe diagnostics and the current failure before retrying anything.

Within that bound: admit the synthetic student; obtain fresh consent; persist an active event; publish its JPEG late; verify the remote owning teacher sees the pending transition and authenticated image; verify another teacher cannot access it. If time and permission permit, use one controlled upload interruption and reconnect with the same item ID, then end the synthetic attempt and independently verify the complete matching receipt before local cleanup. Stop on unexpected admission/sync failure, preserve artifacts, close the tunnel and report the phase accurately. Do not automatically restart viewing or create another tunnel. Real-device and physical exam verification require separate explicit permission.
