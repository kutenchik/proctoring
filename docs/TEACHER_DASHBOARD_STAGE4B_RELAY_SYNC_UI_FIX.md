# Stage 4B relay, synchronization and warning presentation investigation

Date: 2026-10-14. **Stage 4B remains unaccepted. No physical success is claimed.**

This change fixes reproducible ACK bookkeeping and event-cache ordering defects, improves warning layout, and adds bounded diagnostics. The exact causes of the historical public relay failure and chunk-upload interruption remain unresolved. Low delivered FPS is informational under the revised requirement; stability, authorization, commands and verified synchronization are the acceptance gates.

## 1. Historical evidence and scope

Read the Stage 4B main report, physical report, Stage 3 live contract, Stage 2 sync contract and production implementations. The physical record remains [unchanged](TEACHER_DASHBOARD_STAGE4B_PHYSICAL_TEST.md).

The actual topology was a remote teacher on another network with server/student colocated. Viewer `87f33be9e1364657894e2d521f932f39` presented eight relay frames over 9.1808 seconds (count/span 0.8714 FPS), then became unavailable. All browser ACK round-trip samples were null. Sender first failure was `frame_delivery_unavailable`, relay, fallback `direct_timeout`; no geometry failure was recorded. These facts do not establish where ACK delivery failed. Browser/server clocks were not independently synchronized.

No tunnel, real monitor capture, camera, microphone, exam or protected test was launched in this investigation. Existing services were not restarted or terminated. Tests used synthetic data, temporary databases, loopback sockets and one headless browser DOM fixture. The supplied video was decoded offline; extracted inspection frames are derived from that supplied file, not a new camera or monitor capture.

## 2. Relay findings and correction

Production flow is `captureExamMonitor` → bounded JPEG → `LiveScreen` → stream WebSocket → `LiveService.frame` → one latest-frame slot → teacher `FrameAssembler` → bitmap decode → canvas draw → ACK → teacher stream socket → `LiveService.stream` → sender `ack`.

The teacher creates ACKs after a successful validated canvas draw, not merely on receipt. Canvas draw is the application's presentation boundary; it does not measure physical monitor scanout. Relay ACK shape is compatible with the sender validator. Connection identity binds the ACK to its viewer; an omitted viewer ID in the forwarded ACK is not itself a defect. Authenticated real loopback relay tests pass.

**Demonstrated defect:** the sender retained only 32 sent-frame timestamps while allowing 12 seconds for delivery. At 5 FPS, an outstanding frame was evicted after about 6.4 seconds. A valid delayed ACK could therefore arrive inside the delivery deadline but be rejected as unknown. The new regression sends 40 frames, ACKs the first at eight seconds, and proves it is recognized. Duplicate ACKs do not extend delivery; no subsequent ACK still produces the original terminal deadline failure.

The correction retains at most 64 numeric timestamps and expires them at the existing 12-second window. Failed relay enqueue attempts are no longer registered as sent. No frame buffer was enlarged, no timeout increased, no authentication weakened and no speculative reconnect added. Expiry, consent loss, wrong viewer, control/backend loss and intentional Stop remain terminal as before. Capture recovery still invalidates pre-recovery ACKs.

**Attribution limit:** the historical run has no sent-sequence/eviction/ACK-arrival trace. The demonstrated eviction defect is not proven to be its cause. Direct-to-relay fallback still uses the existing deadlines. Tests verify fallback and lease continuity; a public network transition has not been rerun.

## 3. Bounded delivery diagnostics

- Sender: capture start/ready/discard, enqueue success/backpressure, ACK receipt/accept/reject/eviction, fallback. Terminal first-failure diagnostics now include `delivery_trace` before cleanup. Schema validation exists in TypeScript and Python. The first terminal cause remains authoritative.
- Server: validated frame receipt, rate/byte-budget drops, pending-frame replacement, socket send start/completion/timeout, ACK receipt/queue forwarding and close. Frame and ACK send rows are distinguished numerically (`value=0` frame, `value=1` ACK for start/completion). A socket send timeout now retains `stream_send_failed`, rather than generic disconnection.
- Teacher: accepted assembled frames, pending-frame replacement, decode start/discard/failure, actual draw and ACK enqueue. These distinguish presentation from receipt and ACK creation from sender acceptance. ACK-send exceptions are not mislabeled as decode failures.
- Each trace keeps fixed-stage counters plus at most 128 numeric rows. Rows contain stage, sequence, local monotonic milliseconds and a numeric value. Local times across machines must not be subtracted as one-way latency. Sender enqueue and server send completion do not themselves prove remote presentation.
- Server keeps the last 16 closed-viewer traces in process memory. `GET /api/v1/live/view/{viewer_id}/diagnostics` requires teacher authentication and matching ownership; unknown/other-owner IDs return not found. Export before stopping the test API, because process shutdown clears these traces.
- Teacher exposes the trace in `data-stream-trace`; the optional numerical observer exports the latest validated trace with schema 2. It no longer marks a null viewer as an expected network interruption. No additional observer network polling is introduced.

No trace contains frame pixels, base64, SDP, capabilities, credentials, answers or arbitrary exception strings. No persistent screen recording or unbounded message logging was added. Invalid/incomplete assembly still results in no ACK; the trace records accepted assemblies, not every individual SCTP fragment.

## 4. Synchronization findings and changes

The old server has only the session file complete. Its receipt table still has no receipt for the attempt. The retained tunnel log records repeated `context canceled` requests specifically at the events-file chunk endpoint at 10:17:23, 10:17:37, 10:17:50, 10:18:07, 10:18:21, 10:19:02, 10:20:09 and 10:21:18 UTC. This establishes repeated request interruption, not whether the client stalled uploading, the server stalled processing, or a response was lost. There is no recorded HTTP status or phase to settle that distinction.

The worker sends one bounded chunk per iteration, re-queries the server byte frontier, and retries network/server-unavailable failures with bounded exponential backoff. Duplicate committed chunks compare bytes. Authentication failures require attention; the original origin and credentials remain bound to the attempt. After the old tunnel closes, that original endpoint is unavailable and this change does not migrate it.

**Demonstrated classification defect:** malformed successful JSON responses were caught together with request exceptions and labeled `connection_failed`, inviting network retries for a protocol error. They now report `invalid_response`. Non-success malformed bodies report `request_rejected`; non-object error details no longer crash classification. Actual request exceptions retain the existing user-facing connection failure with safe diagnostic categories for connect timeout, read timeout, TLS failure or other connection failure. No request timeout or chunk size was increased.

The HTTP adapter now keeps at most 32 numeric/closed-category request diagnostics: operation class, phase, HTTP status if available, request JSON byte count, response byte count, chunk offset if applicable, elapsed milliseconds and safe code. `request` means Requests has not returned headers; it cannot alone distinguish sending the body from waiting for headers. No URL, body, headers, token or raw exception text is stored. The durable worker preserves the first sync failure and the latest 32 failed request diagnostics in the encrypted journal, separate from transient UI status. Later `uploading` updates cannot erase this first diagnostic.

Read-only re-verification is saved at `build/stage4b-investigation/evidence-readonly-check.json`: all six files still match manifest SHA-256 and size (2015, 480546, 13181, 243, 46862 and 14062 bytes), cleanup remains false, complete receipts remain zero. Historical databases, encrypted journal and evidence were not edited. No receipt was fabricated and no evidence was deleted. The historical upload failure itself remains unresolved pending classified network evidence.

## 5. Supplied video and persistent warnings

The supplied MP4 has 157 frames, 720×1280, approximately 29.81 FPS and 5.2666 seconds duration. Inspection includes half-second samples through the clip.

Observed: the gaze label changes between CENTER and unavailable; People: 2 is visible; a small additional green rectangle appears at the lower-right edge alongside a large person rectangle and a face rectangle. The second-person warning and recent-observation list remain present in inspected samples. Some frames show doubled edges/text across much of the photographed screen. This recording of a monitor cannot conclusively distinguish display refresh/camera motion from every application movement. It does not prove a warning entrance animation restarts on every observation.

Source inspection found stable event-ID React keys and no warning entrance animation. The top-level live application motion key is stable. However, the UI cache accepted journal replay without comparing sequence to snapshot freshness. An older active/clearing record could overwrite a newer closed snapshot, then be corrected by another snapshot. A deterministic test reproduces this ordering defect.

The new `ReviewEventCache` merges snapshots and journal rows using their authoritative cursor/sequence, binds batches to the session, and deterministically sorts by activation time and ID. Old replay cannot resurrect a closed warning. Active/clearing states retain one event identity; new episodes retain new IDs. The warning keeps its selected active event while that event remains active/clearing, reserves space when empty, and has no transition/animation. Monitoring-unhealthy hides the active warning immediately. History remains available for review.

A headless DOM test applies 100 active/clearing updates and checks identical warning and event-row DOM nodes, zero animations, unchanged recent-list vertical position after closure, a distinct new episode, and no active warning when monitoring is unavailable. It uses synthetic records and blocked network, not an Electron exam.

The engine, raw observations, confidence, event timestamps, evidence and timer semantics were not modified. Its existing clearing hysteresis remains authoritative; no extra UI detection is fabricated. The original journal contains 625 review-event change rows representing 23 episodes, including ten second-person episodes. Repeated change rows are not 625 separate alerts. Recorded second-person episodes have distinct IDs and closures; they must not be silently collapsed into one historical event.

Raw gaze availability and frame-local boxes can still fluctuate. This change stabilizes warning identity and layout; it does not claim to eliminate every raw detector fluctuation visible in the video.

## 6. Operator correction: second person was present

**Correction supplied after this investigation:** the operator confirms that a real second person was sitting in the corner of the camera frame. The video therefore supports the displayed People: 2 and Second person detected; it is not evidence of a false-positive person detection. The earlier suggestion about the small corner rectangle was an unconfirmed interpretation and is withdrawn.

There is no demonstrated person-detector defect requiring changes. YOLO thresholds, NMS, person counting, gaze algorithms and event activation thresholds remain unchanged. The synthetic disjoint-box test describes generic aggregation behavior only and is not a reproduction or diagnosis of this video.

The remaining video concern is presentation jitter during a sustained episode. Preserve the sequence-aware event cache, event IDs, authoritative clearing lifecycle and original evidence. Raw gaze labels and bounding boxes may fluctuate independently from the stable episode warning. Physical visual stability still requires a separately approved human test.

## 7. Targeted verification

| Run | Result |
| --- | --- |
| Sender ownership/recovery + initial event-cache tests | 22 passed; includes new eight-second delayed ACK, duplicate ACK and terminal deadline regression |
| Final cache/trace schema tests | 3 passed (overlaps two tests above) |
| Headless synthetic warning DOM test | 1 passed |
| Final teacher viewer presentation/recovery tests | 12 passed |
| Numerical browser observer tests | 3 passed |
| Server live, demo loopback, server sync, connected Stage 2 API modules | 82 passed |
| Request diagnostics, connected Stage 2, event lifecycle, YOLO, new relay-trace ownership test | 94 passed |
| Follow-up changed diagnostic/schema/NMS/relay loopback checks | 9 passed (overlapping prior runs) |
| Final HTTP/durable diagnostic and retry scheduling module | 7 passed (overlapping prior runs) |
| Desktop source typecheck + Vite + Electron-source build | Passed |
| Teacher source typecheck + Vite build; numerical observer bundle | Passed |

These are per-invocation counts, not a sum of unique tests. Event tests cover continuous conditions, brief clearing, new episodes and monitoring interruption. Sync tests cover lost replies, repeated uploads, partial frontier across service restart, checksum conflicts, ownership, full receipt verification and cleanup only after verification. Loopback tests traverse the production single-origin boundary and actual sockets; they do not reproduce Cloudflare or real remote bandwidth.

Initial test invocations encountered missing dependencies in separate environments and sandbox-blocked esbuild process spawning. Resolved without installing/modifying shared dependencies: used the isolated student interpreter with existing server site-packages on test-only PYTHONPATH, and approved targeted subprocess execution. Final tests above passed. Build warnings remain for future Vite native-config behavior and desktop bundle size; the server tests report a Starlette/httpx deprecation warning.

Skipped: full Python/Electron/Playwright suites, physical devices/capture, public exposure, native blocking/protection audits, protected exams, load testing and packaging. No production throughput claim follows from these tests.

## 8. Remaining gate and short safe verification plan

Separate operator approval is required before another service restart, public tunnel or physical test. Preserve the current pending attempt and old origin. A new disposable attempt, consent v2 and verified isolated service identity/configuration are required for a new run; never repoint the old journal.

1. Agree a maximum exposure duration and verified owned shutdown procedure. Keep protection/blocking/native restrictions disabled. Operator manually completes consent, devices, calibration and exam start.
2. Start one remote authorized viewer. Collect 30 seconds idle and at least 180 seconds interaction. Measure actual FPS as informational; require stable usable viewing, accurate stale-frame state and viewer identity continuity. Export teacher trace, server owned-viewer diagnostics and sender terminal diagnostics on any failure. Stop immediately; do not restart to hide it.
3. If sustained viewing passes, exercise agreed teacher commands and explicit Stop. A fresh viewer or planned network interruption must be part of that separately approved bounded plan. Confirm a new connection authenticates and obtains a new valid lease; no expired-viewer reuse.
4. Observe one sustained warning, a brief detector dropout and a genuinely cleared/new episode. Check stable layout and IDs. The operator confirmed the second person was real; do not suppress that valid evidence to smooth the UI.
5. Finish normally. On sync failure export the encrypted journal's safe first-failure fields and server numeric status. On success independently verify complete receipt against attempt/session/manifest and all artifacts before local cleanup. Preserve evidence if incomplete.
6. Close only verified owned test processes, preserve numeric results and report actual PASS/FAIL. Stop; no packaging or further stage automatically follows.

**Current conclusion:** reproducible local defects corrected and targeted checks passed; historical relay interruption and public upload interruption are not yet fully explained. The operator-confirmed second person is not an unresolved false positive. Physical stability and complete public synchronization remain unverified.
