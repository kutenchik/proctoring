# Stage 4A — authorized viewing and safe capture recovery

> Current policy update (2026-10-14): [Stage 4A webcam-visible follow-up](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_FIX.md)
> supersedes masking and consent-v1 implementation details below. Historical test results
> remain unchanged. Webcam-visible sharing requires new consent v2. No new physical test has run.


2026-10-14. **Implemented with targeted automated verification only. Physical acceptance is pending; Stage 4B remains blocked.**

## Demonstrated cause and scope

This follows `TEACHER_DASHBOARD_STAGE4A_STREAM_FIX.md`, including section 12, and `TEACHER_DASHBOARD_STAGE4A_REAL_CAPTURE_RESULT.md`. The prior standalone physical run demonstrated movement during `desktopCapturer.getSources`: at `after_sources`, content bounds changed from `[328,151,1264,761]` to `[334,148,1264,761]` over 253 ms. Only `content_x` and `content_y` failed (+6, -3). Zoom remained 1; display count 1, identity 3833731472, bounds `[0,0,1920,1080]`, scale 1, focus and maximized state were unchanged. The operator confirmed “moved window”; the recorded phase label “untouched” did not describe that action.

Rejecting the frame was necessary because its old mask mapping was uncertain. Terminating the entire authorized lease was unnecessarily broad. The previous candidate recovered only from preview-rectangle reflow and therefore could not handle native content-bounds changes.

This does **not** prove that an ordinary click or scroll caused the same operands to change in the original full application. That physical question remains unresolved. No speculative focus or zoom workaround was added.

The original `build/stage4a-stream-fix/real-capture-run-01/first-failure.json` was reread; its SHA-256 remains `c149d63849b78ef2c872b2eee0268f80bb81e5a0900de3bc5782bf1d78d118e4`.

## Recoverable and terminal conditions

| Condition | Behavior |
| --- | --- |
| Click, quiz update, scroll or focus with stable capture geometry | Continue; these events do not revoke the lease. |
| Native x/y change during capture | Reject the frame, then freshly validate and recapture on the same lease. This is the demonstrated physical mechanism. |
| Positive native width/height change with unchanged valid display and zoom | Reject and independently revalidate the next capture and both mask samples. Automated tests establish discard/recapture behavior, not physical correctness. |
| Valid but different preview-mask samples | Reject and retry with fresh samples; explicit recovery state replaces silent frame dropping. |
| Invalid/missing mask, mask-query failure, bitmap or encoding failure | Terminal; no generic retry. |
| Window/webContents destruction, changed display count/identity/bounds/size/scale, changed zoom, invalid geometry | Terminal; these can invalidate independent safety/calibration assumptions. |
| Missing, ambiguous, empty or invalid source | Terminal. Simultaneous content movement does not make an invalid source recoverable. |
| Lost consent, active exam, identity, backend/control connection or authorization | Stop capture. |
| Teacher stop/switch or exam end | Intentional terminal cleanup. |
| Direct transport failure | Existing direct-to-relay fallback remains unchanged. |
| Stream network disconnect | Old lease closes. Restoration requires a new authenticated lease, current consent and a connected peer. No automatic reuse of the old capability. |
| Persistent instability/no verified delivery | Existing 12-second delivery deadline terminates viewing as unavailable/needs attention. |

Retries wait 250, 500, then 1,000 ms, capped at 1,000 ms; timer scheduling may make the actual wait longer. Recovery does not reset the generation, authorization deadline, negotiation time or last acknowledged delivery. Acknowledgement of a newly sent validated frame ends recovery and resets backoff. No timeout was increased.

## Code changes and privacy

`desktop/electron/screen_geometry.ts` classifies only nonempty subsets of `content_x`, `content_y`, `content_width`, `content_height` as potentially recoverable. Both snapshots must independently be valid. Available source metadata must identify exactly one nonempty source with positive dimensions. The production geometry assertions still reject the original frame.

`desktop/electron/live_screen.ts` separates the authorized lease from individual capture attempts. It keeps one bounded first rejected-geometry record in memory. During recovery it also compares the new native display/zoom state with the retained identity before attempting capture. Every retry then enters the complete production capture path with a fresh baseline.

`desktop/electron/screen_capture.ts` still obtains two fresh first-party preview rectangles around monitor capture, verifies all native geometry boundaries and requires valid matching masks before masking and JPEG encoding. A rejected image is never encoded, queued, transmitted, reused or saved. Existing mask padding, frame limits and bounded buffering remain.

The broker supplies an authorization callback at entry and between asynchronous stages. Stop while the first mask query is pending prevents the subsequent monitor capture. An already-issued OS capture cannot be retroactively canceled, but its completion cannot proceed to a subsequent stage or transmission after revocation. Final generation, authorization, connected-peer and socket checks still precede sending.

No calibration, monitoring-health, independent recovery or protection gate is cleared. The native owner continues forwarding geometry to the existing workflow. Protected geometry changes can still trigger its existing safety release/emergency end, which ends viewing. These policies and teacher commands were neither changed nor tested here.

## Viewer states and races

The Electron/Python host contracts accept `recovering`; student UI keeps a recovery-labeled viewing indicator. Teacher UI explicitly shows Live, Temporarily recovering, Unavailable / needs attention, and Stopped, alongside existing starting/stale states.

The authenticated server accepts a strict student-only `capture.recovering` message with viewer identity and an integer `through_sequence`. It neither renews authorization nor creates a viewer. The teacher immediately clears the old canvas, pending frame and partial assembly, and prevents any pending decode at or below that sequence from painting or acknowledging delivery. Only a newer validated frame restores Live.

Sequence barriers also handle direct-channel/socket reordering: a late notification cannot hide an already-presented newer frame. Late decoder errors cannot overwrite recovery or terminal status. Pre-recovery sender acknowledgement entries are cleared, so old ACKs cannot extend delivery deadlines. The existing three-second stale-frame clearing remains the fallback when no recovery message arrives.

Teacher-page focus loss alone no longer invokes Stop through `visibilitychange`. Page exit/unmount, explicit Stop and student switching still clean up. Background browser throttling can still cause existing authorization deadlines to expire.

Network reconnection requires a **new** lease through the existing authenticated Start route and current consent/attempt/session checks, followed by sender authentication and connected-peer validation. The UI does not automatically issue that request. No old capability or expired lease is reused.

## Diagnostics

Existing first-terminal diagnostics and bounded secondary cleanup errors remain. A recovered attempt is not falsely reported as terminal. One first rejected geometry record per lease is retained in memory: exact guard/operands, numeric snapshots and at most 16 native events. Delivery-timeout termination attaches that record to `frame_delivery_unavailable`; the actual terminal classification remains the delivery deadline. A subsequent unrecoverable geometry failure carries its own terminal geometry.

No screen images, webcam frames, answers, credentials, capabilities or URLs were added to logs. No recording or persistent frame storage was introduced.

## Exact targeted verification

| Command / scope | Final result |
| --- | --- |
| Desktop: `node node_modules/tsx/dist/cli.mjs --test tests/live-screen-owner.test.ts` | **23 passed**: 30 guard/operand combinations; focus/scroll and 60 quiz/progress updates; movement/resize, fresh masks, frame discard, backoff, old ACK rejection, delivery deadline, consent/network/new lease, pending-operation stop, privacy/source failures and cleanup. |
| Teacher: `node node_modules/tsx/dist/cli.mjs --test tests/viewer-recovery.test.ts tests/live.test.ts` | **12 passed**: production decoder with mocked sockets/bitmaps; barriers, stale clearing, late notifications/errors, lease expiry, stop and live contracts. |
| `.venv-server/Scripts/python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_live.py -k 'capture_recovery or quality_is_bounded or viewer_one_per_teacher' -q --tb=short` | **4 passed, 34 deselected**: strict recovery identity/role/schema/deadline, reconnect consent/new lease, quality and viewer switch. |
| `.venv/Scripts/python.exe -m pytest tests/test_connected_stage3.py -k 'screen_first_failure or screen_diagnostic_schema or screen_geometry_diagnostic or capture_ipc' -q --tb=short` | **5 passed, 22 deselected**: recovering IPC acceptance and first-failure/numeric diagnostic contracts. |
| Teacher: `node node_modules/@playwright/test/cli.js test --config playwright.live.config.ts -g "direct production sender RTC" --output test-results/viewing-resilience` | **1 passed**: production RTC script, authenticated temporary server, synthetic pixels, progress continuity, recovery clearing and same-lease resumption, terminal reason and stop cleanup. |
| Desktop `npm run typecheck`; `node scripts/build-electron.mjs`; final `npm run build` | Passed, including affected renderer and Electron source bundles; no packaging. Vite emitted nonfatal future native-config-loader compatibility and >500 kB chunk warnings. |
| Teacher `npm run build` | Passed, including typecheck. |

**45 targeted tests passed.** The browser test preceded the final decoder catch guard; that final branch was verified by the additional late-decoder test and final teacher typecheck/build. No claim that the browser test exercised that final error branch.

Initial mock-test execution hit a sandbox spawn denial; the same targeted command passed with permitted execution. An initial server test tried to revoke consent through a route intentionally locked after exam authorization; it was corrected to exercise current-status consent at the fresh-lease gate. Final runs passed.

Browser result: `teacher-web/test-results/viewing-resilience/.last-run.json` reports passed. Owned temporary test API PID 14496 and test web PID 22024 were absent afterward, with no listeners on 8013/5177. Existing teacher PID 10812 (09:13:50 local creation time) remains on 5178. Port 8024 has no listener. No existing service was restarted or terminated, and existing databases/evidence were preserved.

Skipped: full Python/Electron/Playwright suites, physical devices/exams, protection audits, keyboard blocking, packaging, public/cross-network deployment tests, load tests and Stage 4B.

## Prepared physical retest — NOT AUTHORIZED OR RUN

Request separate authorization for one bounded **UNPROTECTED** full-application sustained-view test and any isolated API restart. Before launch, verify source/build identity and intended process PID, owner, creation time, executable, configuration, ports and isolated database. Explicitly confirm protection, keyboard blocking and native restrictions are disabled. Preserve the teacher website and all prior evidence. The old standalone fixture intentionally stops on a rejected frame; it does not exercise the broker's new lease recovery.

The operator manually completes device setup, calibration, consent, readiness and exam start. No readiness bypass. Use one monitor and a test desktop without sensitive content. Record numerical metadata only.

1. Start teacher viewing once; observe **30 seconds idle** with increasing delivered-frame counters, readable content and correct webcam masking.
2. Keep that viewer open for **at least 180 seconds**: 30 s repeated clicks/selections; 30 s changed answers/question navigation; 30 s scrolling and timer/progress updates; 30 s focus switches to another application and back; 30 s small deliberate window translations; 30 s resize and mixed interactions. Record actual actions and phase timestamps.
3. Measure viewer identity continuity, recovery start/end, transport, presentation count/timestamps, cumulative and phase delivered FPS (frame deltas / measured elapsed time), stale-image clearing and sender/first-failure state. Inspect masking after translations/resizes. Synthetic assertions are not physical masking evidence.
4. On a terminal failure, immediately preserve the first diagnostic and attached rejected geometry, teacher metrics, sender state, transport and timestamps. Stop; do not restart or count a short interval as success. A temporary recovery alone is not terminal: measure whether fresh validated delivery resumes within existing limits.
5. Only if sustained viewing succeeds, Stop explicitly and verify canvas/capture cleanup. Start once with a new lease and observe **30 additional seconds**. End the exam normally, confirm owned-resource cleanup and preserve metadata.

Approximately four minutes of viewing, with a five-minute observation cap excluding manual setup. Further network, protection or configuration tests require separate scope/authorization.

## Remaining risks and acceptance

Real compositor timing, DPI/source freshness and mask alignment during physical movement/resize remain unverified. The original click/scroll-only failure is not proven to share the isolated movement cause.

Ordinary interactions no longer terminate a lease merely because a valid content translation/resize or valid preview reflow invalidates one frame. They may still expose a terminal privacy/authorization issue, trigger existing independent exam safety behavior, or remain unstable until the unchanged delivery deadline expires. Those cases fail closed.

**Ready for the separately authorized retest, not Stage 4A physical acceptance. Stop here; no Stage 4B or packaging.**
