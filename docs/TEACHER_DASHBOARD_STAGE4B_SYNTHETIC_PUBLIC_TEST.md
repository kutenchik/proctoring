# Stage 4B — bounded public synthetic test, 2026-10-14

The separate-network synthetic relay passed sustained viewing. Synchronization failed at student admission before upload. Overall Stage 4B remains incomplete.

## Authorization and closure

The operator authorized one public Quick Tunnel exposure, maximum 15 minutes, using build/stage4b/synthetic-02. All 109 sealed source/build hashes matched before launch. No implementation changes or retries were made during the experiment.

The exposure budget began at 16:27:36.539 Asia/Qyzylorda. Owned tunnel/API process exit and absence of the port 8035 listener were verified by 16:39:13.923: 697.384 seconds, within the 900-second limit. The ownership-aware Stop script verified process identities. closed.json then allowed the independent deadline guard to exit; guard PID 41516 was subsequently absent. Existing website process 10812 remained running. Logs, databases and pending journals were retained.

The operator confirmed a genuinely different teacher network, changing visible numbered images, no HTTPS certificate warning, and closure of the remote tab. Public checks returned HTTPS page 200, unauthenticated request 401 and foreign-origin request 403.

## Relay: PASS scoped to synthetic separate-network viewing

One viewer (37d50d6e9d664f88b95d5c216358d4cb) presented 377 frames over 144.8589 seconds, exceeding 120 seconds. Delivered rate was 2.6025 FPS. The export recorded no first failure and ended with intentional stopped; the sender recorded requested teacher_stopped. The same viewer lasting beyond the lease duration supports successful renewal in this run.

| Measurement | Result |
|---|---:|
| Sender generated/enqueued | 671 |
| Server received | 668 |
| Server accepted | 377 |
| Server rate-dropped | 291 |
| Teacher received/decoded/presented/ACK sent | 377 each |
| Server ACK received/forwarded | 377 each |
| Sender ACK accepted | 377 |
| Server sends started/completed | 754 each |
| Server closed | 1 |

The 754 sends include frames and ACK forwarding. Rate drops account for all received but unaccepted frames (668 = 377 + 291); these are server rate-limit decisions, not proof of network packet loss. The three-frame sender/server difference is an unconfirmed tail at intentional shutdown. Two sender fallback notifications do not establish two viewer reconnections.

Deduplicated sender ack_accepted trace records cover all 377 ACK sequences: minimum 660 ms, median 1588 ms, nearest-rank p95 2948 ms, maximum 4003 ms. These are elapsed send-to-ACK round trips measured on the sender clock, not one-way latency.

The browser reports max_presentation_gap_ms = 1675. Its observer samples the most recent presentation timestamp once per second, so this is a sampled freshness gap, not an exact maximum interval between consecutive frames. Browser/server tail traces are bounded; aggregate counters cover the run.

## Synchronization: FAILED BEFORE UPLOAD

The separate attempt failed on student admission: connection_failed, request phase, 468 ms, no HTTP status, zero response bytes, request JSON 336 bytes. This preceded session start, synthetic evidence bundle creation, manifest and chunk upload. No retry was performed.

Read-only database verification found one attempt (relay) and zero synchronization receipts. Multi-chunk transfer, lost-response recovery, final receipt verification and post-receipt cleanup were not reached. This does not reproduce or explain the historical upload context canceled failure. The underlying admission connection failure cause is not established by the available diagnostics.

## Evidence and limits

Artifacts under build/stage4b/synthetic-02 include relay-results.json, ack-statistics.json, relay-admission-http.json, relay-http-diagnostics.json, sync-admission-http.json, sync-failure-preservation.json, screen-audit-export.json, public-security-checks.json, closed.json and ownership/deadline/log files. remote-teacher-export-summary.json is explicitly an extracted summary; the full operator export was supplied twice in the conversation, not copied as a raw file into that summary.

Historical pending evidence was not deleted or moved. No receipt was fabricated or historical upload retried. Synthetic sender traffic originated on this computer and traversed the public endpoint; only the teacher browser was on a confirmed different network. Direct WebRTC unavailability was simulated by the fixture. Real ICE/NAT negotiation, monitor capture, webcam, microphone, warning behavior, protected mode and physical exams remain outside this result. No further public or physical tests, packaging, Stage 4C or Stage 4D were performed.
