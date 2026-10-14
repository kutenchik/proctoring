# Stage 4A — Webcam-visible monitor sharing and remaining fixes

Date: 2026-10-14. **Implementation and targeted checks complete. The authorized physical retest is complete but Stage 4A is NOT accepted. Stage 4B remains blocked.** See [the physical results](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_PHYSICAL_RETEST.md): sustained interaction, unmasked preview, minimize/restore, intentional Stop and verified synchronization passed; delivery was 2.98 FPS and the fresh-viewer check was cut short by the observer safety cap. The implementation-era pending statements below describe the pre-retest state; the physical report supersedes them.

## Preserved physical evidence

The previous run remains FAILED, as documented in `TEACHER_DASHBOARD_STAGE4A_RESILIENCE_PHYSICAL_RETEST.md`. It delivered 761 frames in 274.8103 seconds (2.766 FPS), with 20 successful same-viewer Recovering → Live transitions. The fresh viewer then failed on minimization: `capture_geometry_changed`, `before_mask`, `invalid_geometry`, native content `[-32000,-32000,0,0]`, one unchanged display and zoom 1. Intentional Stop was misclassified as `stream_disconnected`. Six uploaded artifacts had no final receipt.

Original databases, local evidence and prior run artifacts were not repaired, deleted or replaced. Final read-only verification still finds **six complete files and zero receipts** for that attempt. Diagnostic work used an isolated database copy and an in-memory copy of the decrypted local journal. No credentials, answers or image data were printed or added to diagnostics. Existing teacher website PID 10812, creation epoch 1791951230.0156248, executable `C:\Program Files\nodejs\node.exe`, remains on port 5178. Ports 8024 and 5196 were absent at final verification. Existing services were not restarted.

## Webcam visibility and consent

`desktop/electron/screen_capture.ts` now encodes the validated monitor thumbnail directly. Webcam DOM queries, mask rectangles, bitmap painting and mask-related asynchronous waits are removed from production screen capture. The existing local camera preview is consequently included wherever it is visible on the actual monitor. There is no new camera acquisition, second camera connection, webcam media track, audio transmission, or screen/webcam recording.

Screen consent is now **version 2**, across Python control, persisted consent, server start/view authorization, Electron host validation and capture authorization. EN/RU/KK student text explicitly discloses the visible webcam preview, whole-monitor scope, occlusion by other apps and no separate camera/audio stream or screen recording. Teacher explanatory text is updated in all three languages.

Persisted version-1 acceptance restores as NOT accepted. A version-1 acknowledgement does not satisfy readiness. The server rejects version-1 consent; the broker requires accepted, acknowledged version 2. Existing protocol/manifest/receipt versions are unchanged. Consent stays locked after start authorization: an already-started old-consent attempt cannot silently upgrade. Deploy this change for newly consented attempts; an old active attempt needs a later new attempt rather than silently exposing its webcam.

`LiveExam.tsx` retains exactly one existing `CameraPreview`, mounted outside question navigation. A reserved responsive monitor column and sticky preview keep it visible during question and sidebar scrolling. Browser tests cover 1280, 760 and 600 px widths, question changes and preview DOM identity. Monitoring/readiness and camera freshness behavior are unchanged; an unavailable camera still displays its unavailable state.

**Occlusion limitation:** this is actual monitor sharing. Covering or minimizing the exam window hides its preview from the monitor and therefore from the teacher. The stream may show the covering application or desktop instead. No separate feed, composited webcam, always-on-top window or protection change was introduced. Preview visibility through another application's pixels is not claimed.

## Geometry, authorization and recovery

The old minimized failure was a genuine invalid *mask* baseline. That baseline is no longer needed under the approved unmasked policy. `screen_geometry.ts` now separates monitor validation from native content validation. Zero-sized/minimized native bounds are retained only as diagnostic numbers; they are never declared valid native window geometry.

Remaining production capture checks:

- Exactly one active display; non-null identity and finite, positive display geometry/scale.
- Stable display identity, bounds, dimensions and scale across the viewer lease and before/after asynchronous source acquisition.
- Exactly one source matching that display ID; nonempty thumbnail; positive integer, bounded dimensions and the display's aspect ratio (allowing one-pixel rounding).
- Live owner/webContents, current authenticated control connection, accepted and acknowledged consent v2, active matching attempt/session and unexpired viewer authorization.
- Connected viewer, ready stream socket, generation checks after awaits and immediately before sending; existing frame-size, age, buffering and delivery bounds.

Native movement, resize, focus, scrolling, content zoom and minimized content bounds no longer invalidate monitor pixels. Native calibration, presentation, monitoring-health, display-incident and recovery gates remain independently authoritative. They were not bypassed or changed. Actual display/scale/source changes remain terminal; this does not automatically recalibrate an exam.

Only a `desktopCapturer.getSources` API rejection is retried, and only after authorization and monitor geometry still validate. No rejected attempt produces a frame. The same viewer uses 250/500/1000 ms bounded backoff; no lease or delivery deadline is extended. Recovery clears pending frame acknowledgements and sends the existing sequence barrier to clear the teacher image and invalidate stale decodes. Only a newly displayed, acknowledged frame returns the sender to Live. The existing 12-second delivery deadline terminates unsuccessful recovery; stale teacher images are cleared after the existing 3-second freshness bound. Network loss requires fresh authentication/consent/lease validation, not reuse of a cached sender token.

Display loss/change, invalid/missing/ambiguous/empty/wrong-sized source, owner destruction, consent or authorization loss, exam end and delivery deadline remain terminal. First terminal diagnostic and secondary cleanup errors retain their separate bounded handling. No generic cleanup overwrites the first terminal reason.

The standalone diagnostic fixture was updated to compile against the new monitor pipeline and disclose unmasked capture. Its new output directory is `real-capture-fixture-v2`, preserving the old built fixture/evidence. It was **built only**, not launched.

## Intentional Stop: cause and correction

Previously the teacher closed RTC/WebSocket before the HTTP stop completed. Server `stop_viewer` marked stream peers closed without giving those sockets a stop reason; only the slower control channel received `view.stop`. The sender's socket-close callback therefore won the race and recorded unexpected `stream_disconnected`.

The teacher now sends an authenticated `view.stop` on its stream before teardown, with a bounded recognized close reason as fallback. HTTP Stop still works. The server stores the effective stop message on each stream peer, drops queued frames and sends that message before closing the socket. It validates ownership and preserves any earlier actual failure. Electron receives `teacher_stopped` before generic socket cleanup; teacher UI classifies requested stops as Stopped. Tests exercise both actual WebSocket and HTTP Stop routes through FastAPI's in-process WebSocket client.

## Synchronization: demonstrated defect and forensic limit

Read-only investigation found local `ended_locally`, `uploading`, no error, no receipt, media released, event cursor 22; the server had all six complete files. The uploaded bundle passes the production server `_validate_bundle` on an isolated database copy. Replaying one worker iteration from the preserved pending state reaches `/student/sync/complete` after manifest/status; that diagnostic intercepted completion and did not issue any receipt.

**Demonstrated code defect:** after every uploaded chunk, including the last completed file, `SyncWorker.once` unconditionally returned. Requesting the final receipt required a later worker iteration. Normal summary-window close could shut down the worker in that gap, leaving every file uploaded but no completion request/receipt. The old observer's last state was still uploading; the last file was written afterward. There is no captured final HTTP trace or worker stack that proves the exact interrupt point in this historical run. Thus the handoff defect is reproduced and repaired, but attributing that particular missing receipt exclusively to this race remains an inference, not a proven server rejection.

Correction: still at most one chunk per iteration, but a final successful chunk acknowledgement now proceeds directly to completion when every other present file's server frontier is complete. A new localized **verifying** state distinguishes uploaded files from a verified receipt. Closing the summary with pending synchronization now defaults to keeping it open and explicitly explains that exit retains pending evidence for the next launch. Explicit exit remains possible; there is no indefinite shutdown block.

The server still independently verifies the complete manifest, records and hashes before issuing a receipt. Local receipt identity/hash verification and exact-file cleanup remain unchanged. Lost completion responses preserve local evidence and resume through the existing status/idempotent completion path. Synthetic real-server tests verified actual receipts, response-loss retries and cleanup. No receipt was fabricated for the physical run, and its original evidence was not deleted. Final physical synchronization still needs verification.

## Targeted verification

All final targeted checks passed. No whole-suite commands were used.

| Target | Result |
| --- | --- |
| Desktop `live-screen-owner.test.ts` | 19 passed: consent v2, unmasked output, movement/resize/minimize/zoom, interaction continuity, source validation, bounded recovery, first failure, Stop and disconnect/reconnect |
| Desktop `live-screen.test.ts` | 6 passed: bounded framing/assembly, authorization policy and transport limits |
| Desktop `background.test.ts` | 6 passed: media-release gate, receipt-based completion and pending-close warning |
| Teacher `live.test.ts`, `viewer-recovery.test.ts` | 15 passed: viewer/command state, stale-frame invalidation, recovery, expiry, Stop and cleanup |
| Python selected Stage 2/3 tests (`final_chunk or receipt or cleanup or consent or quiz_commands_and_progress`) | 17 passed, 46 deselected |
| Server selected consent/viewer/recovery tests | 9 passed, 29 deselected at that run |
| Server new old-consent / intentional-stop / first-failure tests | 3 passed |
| Server actual stream Stop routing (HTTP and stream) | 2 passed |
| Synthetic controller → disposable loopback server sync integration | 2 passed, 2 deselected; real verified receipts and cleanup, including lost responses |
| Single desktop UI file `live-teacher.spec.ts` | 5 passed; EN/RU/KK disclosure assertions separately rechecked, 3 passed |
| Diagnostic recorder unit tests | 5 passed; fixture built without launching |
| Desktop `npm run build` | Passed: TypeScript, renderer and Electron source builds |
| Teacher `npm run build` | Passed: TypeScript and renderer source build |

89 distinct targeted cases passed (repeat verification runs not added to the total). Initial test-only issues were corrected: strict nullable diagnostic assertions and an in-process test WebSocket URL using the wrong host. Final source builds have existing nonfatal Vite native-config/chunk-size warnings; server tests report a Starlette/httpx deprecation warning. No physical image was captured. UI tests use mock state only.

Main source build SHA-256: `b4da74492b8b10f1847e84391ea9360bbb876ef881b0226c65d2464e3a17c75c`.

New bounded investigation metadata: `build/stage4a-stream-fix/followup/sync-cause.json`, `final-verification.json`; isolated copy `diagnostic-copy.sqlite3`. Existing evidence remains under `resilience-run-01` and `resilience-student-01`.

Intentionally skipped: full Python/Electron/Playwright suites, physical camera/microphone/monitor capture, protected exams, native protection audits, keyboard blocking, packaging, public tunnels/deployment, cross-network/load testing and Stage 4B.

## Safe UNPROTECTED physical retest — separate authorization required

1. Obtain separate operator approval. Record exact source hashes and process PID/owner/creation time/executable/ports/configuration before any authorized isolated API restart. Preserve the current database, website and previous evidence. Use a fresh output directory and disposable attempt; do not silently resume or clean up the failed evidence bundle.
2. Confirm protection mode unprotected; keyboard blocking, native restrictions and clipboard blocking disabled. Keep monitoring/readiness requirements. Operator manually accepts the new webcam-visible consent, selects devices, completes microphone setup/calibration and starts the exam. No readiness bypass.
3. Authenticated teacher starts one viewer. Measure **30 seconds from the first displayed frame** untouched, then at least **180 seconds** with timestamped answer changes, question navigation, scrolling, focus switching, movement and resizing. Include cover/uncover and minimize/restore. Expect monitor continuity; the webcam is visible only when its preview is actually on the monitor.
4. Record delivered frames/FPS, viewer ID, Live/Recovering/Unavailable/Stopped transitions, recovery duration and capture-to-display-ACK round-trip latency. Confirm readable text and **unmasked** live preview after navigation/scroll/restore. Do not save stream frames/screenshots/video or application content. If no real recovery occurs, report that recovery duration was not exercised rather than inventing a measurement.
5. On any terminal failure stop immediately, preserve original first failure, numeric geometry/source evidence, sender state, teacher metrics, transport and timestamps. Mark FAILED. Do not automatically restart or substitute a shorter interval.
6. Only after sustained success: explicit teacher Stop; verify capture ends, canvas clears, requested=true and `teacher_stopped` (not `stream_disconnected`). Start one new authorized viewer, measure another 30 seconds, including minimize/restore. Stop normally.
7. Operator completes the exam normally. Wait for **Fully synchronized — matching receipt verified**, then independently verify the server's complete receipt, manifest identity and file counts and local receipt/cleanup status. “All files uploaded” alone does not pass. If incomplete, keep evidence and record verifying/error state before exit. Confirm devices released and desktop controls normal.
8. Close only owned test processes after verifying identities. Preserve numerical results. Report PASS only if sustained viewing, fresh viewer, intended Stop, preview behavior and final verified synchronization all pass. Stop after Stage 4A.

## Remaining limitations / acceptance

Real Windows minimized/covered capture and the new unmasked preview have not been physically verified. Independent exam monitoring or display safety can still legitimately pause/end an exam. A real display/source change intentionally fails closed. Occluded/minimized webcam content cannot remain visible through unrelated windows in a pure monitor stream. The old missing receipt's exact final scheduling interruption is unresolved despite the demonstrated handoff fix. Old active consent cannot be migrated implicitly. **Do not claim a physical fix or Stage 4A acceptance from these automated results.**
