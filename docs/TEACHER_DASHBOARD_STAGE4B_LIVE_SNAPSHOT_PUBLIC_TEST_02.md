# Stage 4B synthetic snapshot public test 02

Run `build/stage4b/snapshots-02`, consent v3, 2026-10-14. One authorized bounded Quick Tunnel experiment; no retry. Historical snapshots-01 and earlier admission-failure evidence were not modified.

Attempt: `7e2a5654765645e3a3fdc0ffa933f17f`.
Event: `snapshot-7a0c86128a0f452c8684f4a63439ebc9`.

## Results

| Criterion | Observed result |
|---|---|
| Synthetic admission | Passed: HTTP 201, 750 ms; start and confirm HTTP 200. |
| Live event notification | Passed: remote owning teacher on an operator-confirmed different network saw the event and Snapshot pending without refresh while the attempt was active. |
| Pending to available | Failed to complete: remote observer pending=true, thumbnail=false. |
| Remote authenticated full image | Not reached; full_image_loaded=false. |
| Cross-teacher image rejection | Not reached; no claim of a public-test pass. |
| Durable upload / retry | Declaration HTTP 200; first chunk at offset 0 failed with read_timeout after 5625 ms, no HTTP status and zero response bytes. JSON request size 349618 bytes. No whole-experiment retry. Controlled lost-response injection and reconnect were not reached. |
| Server validation/storage | Incomplete: event/image mapping and declaration exist, but received_bytes=0 and complete=0. Full JPEG validation and durable completed image storage were not demonstrated. |
| Early acknowledgement safety | No successful chunk acknowledgement; this scenario's early-ack invariant was not exercised. No final receipt exists and local evidence remains. |
| Final matching receipt | Not reached. Read-only database inspection found zero sync_receipts for this attempt. |
| Local evidence cleanup | Not performed. The 438950-byte JPEG, events.jsonl and session.json remain, with hashes saved. Receipt-gated successful cleanup remains untested publicly. |
| Actual snapshot availability delay | Not measurable: no thumbnail or full image became available; pending_to_thumbnail_ms=null. |

The JPEG was published at epoch milliseconds 1791982160007 after the pending confirmation and controlled delay. First failure occurred at 1791982167077. The remote sample series spans 1791982083138–1791982192648 and remained pending. The operator also confirmed that no image appeared and no HTTPS certificate warning occurred. A clearly labeled summary is saved as remote-observer-summary.json; the full pasted export is retained in the conversation/operator download.

The tunnel log records an abruptly ended request/context cancellation at the chunk failure time. This does not identify the root cause of the read timeout or establish Cloudflare fault. Admission succeeded in this run; it did not repeat the previous admission failure. No timeout was increased and no implementation was changed during this run.

## Shutdown and additional blocker

The automatic ownership-aware Stop returned 1 with `Duplicate or missing ownership field` while reading the multi-process server ownership record. This is a separate demonstrated launcher failure, despite the prior focused tests. The independent deadline guard invokes the same Stop reader, so its cleanup path must also be treated as affected until locally corrected and tested.

Recovery parsed the preserved records individually and used the shared strict identity and termination functions. Each process was checked against PID, exact UTC creation ticks, executable, owner and command line; termination held a process handle and revalidated identity. No PID-only termination or timestamp tolerance was used. Original records were preserved.

CIM verification confirmed recorded tunnel/server PIDs 40592, 42744, 22520 and 532 absent; port 8036 had no listener. A closed marker was then written, and a subsequent CIM query confirmed the deadline guard and its Python process absent. Closure verification was recorded at epoch 1791982298.486, 449.744 seconds (7 minutes 29.744 seconds) after the exposure start, below 15 minutes. This is an upper bound on exposure, not an exact tunnel termination duration.

Read-only SQLite verification found started_at populated, finished_at=null, no receipt, and zero committed snapshot bytes. Local JPEG SHA-256 is `2db74ec445556aeb31d5ea188ec0411d0c85d4f0b3b2302887992e436a5e19e0`, matching its declaration. Evidence was retained rather than completing or cleaning up this failed attempt.

## Evidence and next gate

Run files: snapshot-results.json, snapshot-progress.json, public-security-checks.json, operator-pending.json, remote-observer-summary.json, scenario-stop-result.json, scenario-stop.log, closed.json, post-stop-verification.json, ownership records and server/tunnel logs. All 121 prepared source/build hashes were verified before launch. Pin and Start succeeded under Windows PowerShell 5.1; prior local preparation recorded 12 identity plus 9 lifecycle tests under each of PowerShell 5.1 and 7.6.5. Those results do not cover away the newly observed Stop reader failure.

Remaining blockers: diagnose the first chunk read timeout locally, correct and reproduce the ownership-reader failure with the preserved multi-process record, and verify independent deadline cleanup. No new public tunnel is authorized by this report. A future run requires fresh isolation and explicit approval after local verification. No real camera, microphone, monitor capture, real student exam, protection test, packaging or full regression suite was performed.
