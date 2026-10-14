# Stage 4A screen interruption investigation

Date: 14 October 2026, Asia/Qyzylorda.

**Status: authorized unprotected physical run 03 FAILED. The sender's first
failure was `capture_geometry_changed`, preserved through server and teacher
cleanup. The exact failing geometry-guard condition remains unresolved; no
physical streaming fix is established. Stage 4A is not ready for acceptance;
Stage 4B remains blocked. See section 11 for the physical result and cleanup.**

**Follow-up investigation (14 October):** isolated Electron focus/click/scroll
did not reproduce the physical failure. Exact guard operands and bounded native
event diagnostics are now implemented and verified; see section 12. No further
physical retest or service restart occurred. No geometry recovery is justified yet.

**Latest isolated real-capture result:** one separately authorized run reproduced
`after_sources` failure of `content_x` (+6) and `content_y` (−3) during
operator-confirmed window movement. No fix was implemented; ordinary click/scroll
without movement remains untested in that run. See
[the real-capture result](TEACHER_DASHBOARD_STAGE4A_REAL_CAPTURE_RESULT.md).

This continues the existing dirty repository at HEAD
`e54e4f09e7be63929fc00e645d99d53629d405fe`. No earlier stage was restarted or
reverted. Most desktop, teacher and connected source was already untracked, so
`git diff` alone does not describe these changes. The four requested Stage 3/4A
documents were read before editing. Original run artifacts were left intact.

## 1. Original physical evidence

Inspected `build/stage4a-20261014-01/` including both runs' `states.jsonl`,
`operator-result.json`, the original physical notes, candidate source identity,
and the live audit rows in `server/teacher.sqlite3` opened **read-only**.
The resulting numeric extraction and artifact hashes are in
`build/stage4a-stream-fix/physical-evidence-readonly.json`.

| Evidence | Run 01 | Failed candidate retest, run 02 |
| --- | --- | --- |
| Viewer requests / first presentations | 16 / 16 | 1 / 1 |
| Recorded stops | 15, all `disconnected` | 1, `disconnected` |
| First presentation to stop | 1.012–29.854 s; median 6.385 s | 5.063906 s |
| Sampled student control state at ordinary viewing stops | Online, no pause reasons | Online, no pause reasons |
| Retest observer transitions | Multiple short direct views | Starting 148.723 s; live/direct 151.209 s; stopped 156.712 s |

The missing run-01 stop crosses an API restart; it is not sustained-view evidence.
Audit duration measures two events, not continuous delivered FPS. The only earlier
quality sample was 3.0 acknowledged FPS, 1280 px, 271 ms capture-to-display-ACK
round trip. Webcam masking/readability were not physically confirmed.

The earlier temporary teacher trace reported `control_view_stop` with a visible,
focused teacher document and no preceding hidden marker for one reproduction.
That excludes hidden-page cleanup for that observation, not every possible cause.
The operator reported the failure again in run 02. Neither run captured the
original sender exception; it cannot be reconstructed from these files.

Before overwriting the source bundle, the failed candidate's main bundle was
copied to `build/stage4a-stream-fix/pre-change-build/main.cjs`. Its SHA256 matches
the recorded run-02 identity:
`89ae2367393cb30a32016a7784375fb10585b150cd87b11bf61afb21c42a9754`.

## 2. Lifecycle trace and root-cause status

| Component | Finding |
| --- | --- |
| React `LiveExam.tsx`, backend hook | Answer selection/change calls `quiz.answer`; navigation calls `quiz.navigate`. Busy/progress updates rerender the same exam component. No stream-stop call is present in these handlers. |
| Python desktop workflow | Quiz commands update quiz state/revision/checkpoint. They do not revoke the viewer. Actual command regressions retain the current viewer. |
| Electron `main.ts`, bridge | Each authoritative response updates the existing `LiveScreen`. Ordinary snapshots do not construct a new owner. Backend loss and application shutdown do stop it. Protected geometry release is separate and unchanged. |
| Native/external ownership | Native quiz is first-party DOM in the original BrowserWindow. An external WebContentsView is configured only for external exams. External hide/layout does not own native quiz capture. |
| `screen_policy.ts` | Capture authorization depends on consent, attempt/session identity, active session and lease deadline, not quiz revision or answered count. |
| `screen_capture.ts` | First-party preview masks are sampled before and after asynchronous monitor capture. Invalid/missing masks, native bounds/zoom/count changes and missing sources are fatal. Stable valid preview movement during capture discards that frame under the existing candidate. |
| `live_screen.ts` | Async completions are generation-checked; lease replacement invalidates old work. Before this change, all non-transient capture exceptions became `capture_unavailable`; socket cleanup could then become generic `disconnected`. |
| RTC renderer/preload | Separate hidden sandboxed renderer; narrow pixel/signaling IPC; no capability token, camera or audio track. RTC failure uses the existing relay transition, not a new lease. |
| Python live workflow | Consent/display/session/control identity gates remain authoritative. `_stop_viewer` previously replaced the original capture reason with subsequent server cleanup. |
| FastAPI lease/socket | Renewal revalidates teacher ownership and active student. Socket `finally` previously called generic disconnect even after a known protocol error. |
| Teacher viewer/workspace | Progress updates do not recreate the viewer. The control-stop callback previously discarded its reason and reset the displayed state. |

**Demonstrated defect:** the diagnostic chain discarded the original terminal
classification. Injected capture failures and actual loopback socket errors
reproduce that loss mechanism; the changes below preserve it.

**Before run 03, not demonstrated:** the upstream physical event that made quiz interaction stop
capture. Automatically simulated answer changes, navigation, rapid updates and
valid layout movement did not accidentally revoke the lease. Missing masks,
native geometry races and delivery timeout remain deliberate fatal cases.
No evidence establishes source loss, renderer destruction, lease expiry, websocket
failure, RTC failure or direct-to-relay failure as the original physical cause.
No capture-availability workaround has been added on that assumption.

## 3. Why the previous candidate did not resolve the failure

That patch handles only one case: **both mask samples valid, native geometry
unchanged, but preview rectangles differ across capture**. It drops that uncertain
frame and retains the existing delivery deadline. Run 02 still failed after
5.064 seconds of first-presentation-to-stop time. The original exception was still
collapsed, so evidence cannot distinguish a different fatal guard from an unrelated
transport failure. Claiming a more specific explanation would be speculation.
Run 03 subsequently identified `capture_geometry_changed`, outside the candidate's
valid-mask-rectangle reflow case. This explains why that narrow workaround does
not cover the newly observed failure, but does not recover the lost run-02 code.
The candidate is retained, with its safety regressions; it is not accepted as a
physical fix. No reconnect retry or timeout increase was introduced.

## 4. First-failure diagnostic changes

`shared/screen-diagnostic.ts` and the matching Python validator define a closed
vocabulary and schema. The sender captures one terminal record **before** clearing
its lease, transport or resources:

- UTC timestamp, viewer correlation ID and sender generation.
- Component, lifecycle phase, original known internal code and fixed description.
- Direct/relay transport, capture-in-flight/idle and receiver-attached/pending state.
- Requested versus unexpected shutdown, and the `lease_revoked` transition.
- WebSocket close code/reason when present at that transition; unrecognized close
  text is `redacted`.
- First relay-fallback classification, if applicable; at most four separate
  secondary cleanup/delivery codes.

There is one retained terminal record, not an accumulating log. A new lease's
terminal transition replaces it. Duplicate/generic cleanup cannot overwrite it.
Python exposes it as `live_teacher.screen_diagnostic`, retaining it across viewer
reset and accepting a delayed terminal report for the immediately stopped identity
without reviving that lease or affecting a newer viewer. Late live/starting reports
and duplicate terminal reports cannot replace the first record.

Known capture/DOM/source/encoding errors retain fixed classifications. RTC close,
connection failure and operation failure are distinguished. Unknown native
exception text is deliberately not copied; it receives a safe stage classification.
If `onerror` stops the socket before a close event arrives, its original record may
have no close code. No later event is falsely described as the initiating cause.

The sender sends a bounded existing `transport: unavailable` message before socket
close and includes a safe code in its close reason. The server retains the first
sender failure for its existing stop/audit event, and preserves actual `Problem`
codes through socket cleanup. The teacher retains/displays the safe classification
instead of replacing it with idle/generic cleanup. Delivery over a failed socket
is best effort; local host diagnostic retention is independent of that message.

No pixels, screenshots, webcam images, answers, URLs, PINs, capability tokens or
device credentials enter the diagnostic. Existing server lifecycle audits gain
only a bounded code. No continuous recording or frame persistence was added.

## 5. Code changes and rationale

Production files changed in this investigation:

- `desktop/electron/live_screen.ts`, `screen_capture.ts`, `screen_rtc_renderer.ts`:
  preserve failure/transport context, classify safe boundary errors, isolate
  secondary cleanup errors and handle a throwing socket send without losing cause.
- `desktop/electron/security.ts`, `desktop/shared/contracts.ts`,
  `src/proctoring/desktop_bridge/protocol.py`: strictly validate the optional
  terminal-only host diagnostic and safe public state.
- `src/proctoring/connected/live_workflow.py`: preserve first failure across
  asynchronous host/control cleanup ordering.
- `src/proctoring_server/live.py`, `live_routes.py`: preserve sender and server
  failure codes through disconnect and the existing audit/control notification.
- `teacher-web/src/live-viewer.ts`, `use-live.ts`, `LiveWorkspace.tsx`: retain
  terminal classification and bounded presentation counters/timestamps. The
  `data-stream-metrics` attribute exposes only four numeric measurements for a
  permitted observer, never frame content.
- New shared TypeScript and Python diagnostic validators described above.

Consent, masking, isolation, authorization/renewal, protection, gaze/audio,
buffer bounds and quiz workflow behavior are unchanged. The native geometry guard
still stops uncertain capture. This is an observability correction, not a claim
that the physical streaming bug has been fixed.

## 6. Targeted verification

**28 selected tests passed.** No test used physical camera/microphone/monitor
capture. Synthetic images are not physical capture evidence.

| Command / scope | Result |
| --- | --- |
| Desktop: `node node_modules/tsx/dist/cli.mjs --test tests/live-screen-owner.test.ts` | 13 passed |
| Root: `.venv/Scripts/python.exe -m pytest tests/test_connected_stage3.py -k 'screen_first_failure or screen_diagnostic_schema or quiz_commands or capture_ipc or viewer_token' -q --tb=short` | 6 passed, 20 deselected |
| Root: `.venv-server/Scripts/python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_live.py -k 'screen_failure_classification or screen_progress_status or viewer_expiry or renew_requires or viewer_one_per_teacher' -q` | 5 passed, 31 deselected |
| Root: `.venv-server/Scripts/python.exe -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_live_api.py -k first_stop_reason -q --tb=short` | 2 passed, 3 deselected; real temporary loopback sockets |
| Desktop: `node node_modules/@playwright/test/cli.js test --config playwright.stream-fix.config.ts -g "native quiz interaction"` | 1 passed; mock devices; owned port 5183 |
| Teacher: `node node_modules/@playwright/test/cli.js test --config playwright.live.config.ts -g "direct production sender RTC" --output test-results/stream-fix` | 1 passed; synthetic frames through production RTC script; owned ports 8013/5177 |
| Desktop and teacher `npm run typecheck` | Passed |
| Desktop `node scripts/build-electron.mjs`; teacher `npm run build` | Passed; source bundles only |
| Bounded physical observer `node --check` | Passed before the subsequently authorized run 03 |

Coverage includes selecting/changing answers, question navigation, rapid revisions,
timer/progress updates, React preview DOM retention, teacher viewer continuity,
valid preview relocation/reflow, uncertain native geometry rejection, consent loss,
lease expiry, viewer replacement, terminal end/dispose, delayed old capture
completion/rejection, direct-to-relay transition and unchanged delivery timeout.
First-failure tests cover cleanup exceptions, private-text rejection, server-first
and host-first arrival, stale live updates, duplicate terminal reports, and actual
socket close/server protocol-error preservation.

Initial Node execution hit sandbox `spawn EPERM`; the identical focused run passed
with approved process spawning. Initial new Python tests exposed a validator
generation typo and a single-choice test payload against a multiple-choice fixture;
both were corrected and all six selected tests passed. A test helper return-type
error was corrected before the final desktop typecheck. No timeout/assertion or
production privacy guard was weakened to obtain a pass. Vite emitted its existing
future-config-loader advisory during the student browser test.

Selected final logs and identities are under `build/stage4a-stream-fix/`; browser
results are under the two projects' `test-results/stream-fix/` directories.

## 7. Tests intentionally skipped

No full Python, Electron or Playwright suites; no protected-mode tests, Windows
protection audit, keyboard blocking, packaged EXE, public tunnel, cross-network,
30-student load test, physical display change, or Stage 4B. Student renderer
production code did not change, so no full renderer rebuild was required.
Physical mask correctness and sustained physical FPS remain unverified. Run 03
measured a short direct stream that failed; it does not establish sustained capture.

## 8. Physical retest gate and exact safe procedure

**Historical preflight procedure:** the operator subsequently authorized one run
and the isolated API restart. That run is complete and failed (section 11).
This procedure is retained for traceability, not authorization to launch again.

Read-only process inspection found the original isolated services still running:
API listener 8024/PID 10460, descendant of launcher 23768 created
`2026-10-14T04:46:13.328900Z`; teacher listener 5178/PID 10812, descendant of
launcher 32672 created `2026-10-14T04:13:48.166810Z`. Both launcher creation times
match the saved ownership files. At that preflight, no existing process was terminated. The test
ports were absent after browser-test cleanup.

1. Obtain explicit operator approval for this **unprotected diagnostic retest**
   and a restart of the verified isolated API so its updated Python diagnostics
   load. Recheck PID/creation identities immediately before any approved restart;
   use the existing isolated database/configuration. Do not touch other services.
   Refresh the existing teacher UI after confirming it serves the changed source.
2. Confirm exactly one display, protection and legacy blocking explicitly false,
   connected mode true, and remote report delivery disabled in
   `build/stage4a-20261014-01/connected-unprotected.toml`. Use the existing test
   native two-question exam only if admissions remain open; otherwise prepare a
   separate unprotected test exam. Do not change ended attempts or private config.
3. After approval, from repository root run:

   ```powershell
   node build/stage4a-stream-fix/observe_unprotected.mjs --operator-approved --unprotected --config C:\Users\kuten\Desktop\case3_proctoring\build\stage4a-20261014-01\connected-unprotected.toml --output-name run-03
   ```

   This observer retains the previous safe-config checks,
   uses new isolated `build/stage4a-stream-fix/student-localappdata`, refuses an
   existing output directory and samples at most 900 times. After that bound it
   stops sampling and waits for normal operator closure; it does not kill the app.
   It selects the validated diagnostic fields, not arbitrary state or images.
4. Operator completes ordinary consent, camera/microphone readiness, reference,
   calibration and native exam start. Do not bypass these gates. Keep the teacher
   viewer visible side by side and select the admitted test student explicitly.
5. Start one teacher viewer. Observe 30 seconds idle, then at least 180 seconds
   continuously with repeated answer selections/changes, forward/back/dropdown
   question switches and ordinary timer/progress updates. Include scrolling, but
   do not resize/move the native window during a pending capture as an acceptance
   criterion: uncertain native geometry remains intentionally terminal. Confirm
   the student viewing indicator and visually confirm that the webcam-preview
   region is masked and quiz text is readable. Do not save screen/webcam pixels.
6. Take only numeric teacher measurements once per second, at most 600 samples:
   parse `.live-screen-panel`'s `data-stream-metrics` and note the existing quality
   FPS/transport/round-trip values and displayed technical code. Counters increment
   only after actual canvas presentation. For N > 1, delivered cadence is
   `(N - 1) * 1000 / (lastPresentedAt - firstPresentedAt)` FPS. Record first-to-last
   presentation duration and, on failure, first-presentation-to-stop duration
   separately. All these timestamps are browser-monotonic; do not subtract them
   from UTC or the observer clock. Keep per-lease results separate.
7. If it stops unexpectedly, mark **FAILED immediately**. Preserve the teacher
   metrics/code and `live_teacher.screen_diagnostic` in the new observer output
   before any restart. Do not repeatedly restart and substitute short successful
   intervals for sustained viewing. Record the last operator action in words,
   without storing answer content. Analyze the first code before proposing a
   physical-capture correction.
8. If continuous viewing succeeds, save its metrics before deliberate Stop,
   confirm capture/indicator cease and frames clear, then explicitly start one
   new viewer and repeat interactions for 60 seconds. Record separate metrics and
   verify stop cleanup again. Operator ends the test normally and closes the
   summary. Inspect only owned processes read-only; leave API/teacher services
   alone unless separately authorized to stop them.

Run-03 measurements and first failure are now recorded in section 11. Physical
mask correctness and readability were not confirmed by the operator.

## 9. Remaining risks

- The exact operand triggering the native geometry guard is unknown. Run 03
  reproduced the interruption before the planned idle phase completed.
- Synthetic DOM rectangles do not model every Windows DPI, focus, capture-source,
  compositor or thumbnail failure. Automated mask checks establish synthetic
  behavior only.
- A dead process/host bridge can prevent a local memory-only diagnostic reaching
  the observer. Unknown native free-text errors are redacted by design. No global
  cross-process event ordering is inferred from independent clocks.
- The authorized isolated API restart loaded the diagnostics. Run 03 verified
  sender classification delivery to server and teacher; that retest API has now
  been stopped under the operator's cleanup authorization.
- A single successful direct physical retest would not establish physical relay,
  protected mode, Internet performance or broader Stage 4A acceptance.

## 10. Acceptance decision

**Not ready for Stage 4A acceptance.** The demonstrated diagnostic-loss defect is
corrected and tested, including physical run-03 preservation. Physical streaming
still fails; the precise upstream condition has not been isolated or corrected.
The authorized retest is complete. Stop here before further substantial changes.
Stage 4B, protected testing and packaging remain blocked.

## 11. Authorized physical diagnostic retest: FAILED

The operator authorized exactly one bounded UNPROTECTED run, manual readiness,
calibration and exam start, and restart of only the verified isolated API. Before
restart, PID 10460, creation time, executable, owner, parent chain, loopback port
8024, command line and isolated environment all matched the saved identities.
The unchanged configuration SHA256 was
`17c037b32f672d11d3773811a73491bccf1a26b843344f0fbc1d0503d86c7cb6`.
A read-only SQLite backup was saved before restart. The original database,
evidence directory and teacher website process were preserved. Replacement API
PID 26684 was recorded with its creation time and launcher identity.

Configuration explicitly disabled Windows protection and legacy keyboard
blocking; the unprotected workflow disables native clipboard restrictions.
Observed runtime protection was requested=false, enabled=false, state=disabled.
The operator completed ordinary device setup, consent, calibration and start;
readiness checks were not bypassed. The new attempt was
`035d3ae6a7dd48f2a11b544400d96827`. Only one viewer was requested; there was no
automatic or manual stream restart after its failure.

| Measurement | Physical run 03 |
| --- | --- |
| Viewer correlation ID | `7aba643533234d7586327f1c1c990ec7` |
| First terminal timestamp | 2026-10-14 05:38:23.049 UTC / 10:38:23.049 local |
| Original code | `capture_geometry_changed` |
| Component / phase | capture / capture |
| Generation | 0 |
| Transport at failure | direct |
| Capture / viewer state | in_flight / attached |
| Requested shutdown | false |
| First stopping transition | lease_revoked |
| WebSocket close code/reason | null / null at the first failure |
| Relay fallback / secondary errors | none / empty |
| Presented frames | 25 |
| First-to-last presentation | 10.041700 seconds |
| First presentation to stop | 10.357700 seconds |
| Delivered cadence | 2.390034 FPS: (25 - 1) / 10.041700 |
| Last quality sample | 3.0 acknowledged FPS, 1280 px, 300 ms capture-to-display-ACK round trip |

The teacher document was visible in the collected failure samples. The sender
reported the exam still running, no pause reasons, and control online at failure.
Server audit recorded `transport_unavailable` with `capture_geometry_changed`
at epoch 1791956303.055454, then stopped with the same reason at
1791956303.0644538. The teacher displayed that classification. The same diagnostic
survived subsequent normal exam completion and disconnected control state.
WebSocket closure is not established as the initiating failure.

The operator reported: “if i ever touch student window or scroll/clicking the
quiz and etc viewing stopping”. This associates the symptom with interaction;
it does not identify the precise action or guard operand at the failure instant.
Although instructed to leave the quiz idle initially, this run cannot be described
as a verified no-interaction baseline. It failed before the planned 30-second idle
phase completed. The 180-second continuous interaction phase and conditional
60-second stop/restart check were therefore not performed. Mask correctness and
quiz readability were not explicitly confirmed and remain unverified. No screen
or webcam pixels were saved by the diagnostic observer.

### What the failure establishes, and what remains unknown

`desktop/electron/screen_capture.ts` emits this code at two asynchronous capture
guards. Their combined conditions cover native window/webContents destruction,
display count other than one, changed native content bounds, and (at the later
guard) changed zoom. The diagnostic establishes that this guard terminated the
stream, but does not distinguish these operands or the first versus second guard.
The sampled single-display state does not resolve a race inside capture.
It does not prove that answer selection itself changes geometry, nor establish
which Windows/Electron behavior triggered the guard. That is the remaining
root-cause investigation, not a demonstrated safe basis for weakening the guard.

The earlier candidate skips a frame only when valid preview rectangles change
with stable native geometry. It cannot handle this observed terminal branch.
No reconnect retry, timeout increase, geometry-guard relaxation, or further
production change was made after this diagnostic run.

### Evidence and cleanup

Evidence is under `build/stage4a-stream-fix/run-03/`:
`first-failure.json` was frozen immediately and not overwritten;
`screen-audit-at-failure.json`, `teacher-metrics.json`, `stream-result.json`,
`states.jsonl`, `operator-result.json`, `resources.jsonl`, and
`operator-observation.json` preserve the independent observations. The original
pretest source-identity manifest remains unchanged. A separate final evidence
hash manifest records the completed run artifacts.

The operator confirmed “Student closed cleanly; desktop controls normal”. The
observer exited normally with application_closed=true. Final public state showed
end_reason=completed, fully_synchronized=true and zero pending attempts. A
read-only server check independently found the completed attempt and verified
sync receipt (epoch 1791956421.25424). All 13 distinct observed student process
identities were absent at cleanup. Renderer page/console and main uncaught-marker
counts were zero; 11 observer read errors and zero resource errors were recorded.
Those read errors limit observation continuity; zero exception counters do not
prove absence of every native failure.

Before shutdown, API PID 26684 was reverified against creation time, executable,
owner, parent chain, command line, port and configuration. Only that authorized
retest API was terminated. Both wrappers exited naturally and port 8024 was
absent. Original teacher PID 10812 retained its recorded creation identity and
remained running on 5178. Database and test evidence were retained. See
`cleanup-preflight.json` and `cleanup-result.json`.

No full suites, protected tests, packaging, public/cross-network deployment,
load testing or Stage 4B were run. No new automated test result is claimed from
this retest; section 6 records the earlier focused verification. **Physical result:
FAILED. Diagnostics verified for this failure; streaming issue unresolved.**

## 12. Focus/content-geometry follow-up investigation

### New observation and scope

The operator reports that viewing remains stable while the student window is
untouched, including when interacting with other Windows applications. Clicking
almost anywhere inside the student window, scrolling, or otherwise interacting
with it stops sharing; this is not limited to quiz answers. This is valuable
physical evidence of association, but run 03 did not retain the individual
geometry comparison. That lost detail cannot be reconstructed retrospectively.

This follow-up changed capture diagnostics and their validators, inspected the
window lifecycle, and ran isolated synthetic tests only. The existing dirty
repository, original run artifacts and failed-candidate evidence were preserved.
No real camera exam, microphone or desktop capture was started. No service was
restarted. The old physical result remains FAILED.

### Original guards, precisely

At the run-03 source version, `capture_geometry_changed` could originate from:

| Guard location | Each condition that could make it throw |
| --- | --- |
| Immediately after awaited `desktopCapturer.getSources` | Window destroyed; webContents destroyed; display count not exactly one; serialized native content bounds differ from the initial sample |
| Immediately after awaited final preview-mask DOM query | The same four conditions, plus zoom factor differs from its pre-capture sample |

Content bounds are x, y, width and height in Electron's native coordinate system.
The original comparison combined them into one JSON-string comparison. It did
not indicate the field, delta, guard stage or active/focused state. Display
identity, bounds, size and scale were not individually compared by these guards.
Source matching happened later: absent matching display ID or an empty thumbnail
raised `monitor_capture_unavailable`, not `capture_geometry_changed`. Source names
and arbitrary source IDs have not been added to diagnostic output.

The pre-capture initial destruction/display-count check used
`single_display_required`. Missing/invalid preview masks use
`privacy_mask_unavailable`. A change between two valid preview rectangles uses
`TransientMaskLayoutChange`, discarding only that frame. These are distinct paths.

### Window ownership and activation findings

`main.ts` creates one framed, sandboxed, isolated BrowserWindow and removes its
menu. Native quiz rendering remains in its original webContents. `ExternalExam`
has no WebContentsView for a native quiz; its layout method returns without
changing native quiz geometry. The screen transport window is separate, hidden
and nonfocusable.

The main window's move/resize/fullscreen and display events call
`geometryChanged()`. `GeometryOwner.snapshot()` reads native bounds, selected
display geometry and zoom and assigns a new calibration geometry identity when
they change. It does not move the window or set zoom. The main handler sends
geometry to Python; its native safety release is conditional on protection being
enabled. No ordinary focus/blur handler revokes streaming. Window control setters
run when protection enabled-state changes, not on each unprotected quiz update.
The fullscreen setup in `connect()` is conditional on protection being requested.

`screen_policy.ts` checks consent, attempt/session identity, active exam and lease
deadline. It does not consume quiz revisions, focus state, clicks or scrolling.
No renderer zoom setter, native move/resize request or draggable CSS region was
found in the student renderer search. None of these source findings alone rules
out an OS/window-manager transition during the real test.

### Implemented bounded diagnostics and safe validation

New `desktop/electron/screen_geometry.ts`, `shared/screen-geometry.ts` and
`src/proctoring/connected/screen_geometry.py` define and validate a closed numeric
record. `CaptureGeometryError` carries it into the existing first terminal
diagnostic in `LiveScreen`; generic cleanup cannot replace it. Existing teacher
status still receives the safe terminal code. Detailed numeric evidence is
retained in the sender's public `screen_diagnostic.geometry` for the bounded
observer, rather than adding raw internal data to the teacher's main UI.

The geometry record includes:

- Stage: `before_mask`, `after_initial_mask`, `after_sources`,
  `after_final_mask`, or `source_selection`.
- All failed checks, with separate `content_x`, `content_y`, `content_width`,
  `content_height`, destruction, display-count/identity/geometry and zoom codes.
- Before/after sample timestamps in epoch milliseconds; native content rectangle
  `[x,y,width,height]`; display ID, bounds, size and scale; zoom; focused and
  maximized state. Unavailable values are null, not invented coordinates.
- At most 16 recent native focus, blur, move, resize, maximize, unmaximize,
  restore, minimize, fullscreen, close, webContents-destroyed and zoom-changed
  events. Events contain only time, content rectangle, zoom and focus state.
  Programmatic zoom changes are detected by snapshots even without a zoom event.
- Source match count, thumbnail width/height and empty status when available.
  An empty/absent/ambiguous source has its own `source_selection` record.

There is one fixed-size event ring per sender, active only during a viewer lease,
reset for a new lease, frozen into the first failure, and detached on sender
closure. Nothing continuously appends to disk in production. Validators reject
unknown fields, arbitrary text, nonfinite numbers, duplicate failure labels and
overlong arrays. No pixels, camera frames, answers, input payloads, titles, URLs,
tokens or credentials are captured by these diagnostics.

The masking origin, display mapping and zoom now derive from the same initial
numeric snapshot that the guards validate, avoiding a second independent
baseline read. Each awaited boundary is checked, including the initial mask
query. Display identity, bounds, size and scale are also explicitly checked;
source selection requires exactly one matching nonempty source with positive
dimensions. These are fail-closed validation changes, not geometry-retry logic.
Stable valid mask reflow retains its earlier discard-only behavior. Consent,
lease deadlines, capture buffering, transport and frame-delivery deadlines remain
unchanged. No protection, gaze/audio or quiz behavior was modified.

### Isolated Electron reproduction and exact observed comparisons

`desktop/tests/capture-focus-electron.mjs` launches only a standalone fixture,
not `main.ts` or a real exam. It creates two owned unprotected windows with
synthetic DOM, a fixed synthetic preview rectangle and a scrollable page.
Permissions are denied; there is no backend connection. `desktopCapturer.getSources`
is replaced with a gated synthetic image provider before any capture request.
Each action runs while capture is pending. Finally, the fixture process and both
windows close. No desktop or webcam pixels are read or persisted.

The original guard version was tested first; the final instrumented version was
then tested with assertions. Both behaved identically for the tested actions:

| Action during pending mocked capture | Final result / exact failed comparison |
| --- | --- |
| Idle | Frame accepted |
| Activate student window | Focus false → true; bounds and zoom unchanged; frame accepted |
| Click synthetic button | One click handled; bounds and zoom unchanged; frame accepted |
| Scroll | Actual DOM scroll offset 120 px; native bounds/zoom unchanged; frame accepted |
| Activate other window, then reactivate student | Focus true → false → true; bounds/zoom unchanged; frames accepted |
| Move | `after_sources`: content x 48 → 68 and y 71 → 91 |
| Resize | `after_sources`: content width 784 → 804 and height 561 → 581 |
| Maximize | `after_sources`: content `[68,91,804,581]` → `[0,23,1920,1017]` |
| Restore from maximize | `after_sources`: the reverse content rectangle change |
| Set zoom | `after_sources`: zoom 1 → 1.1; native content rectangle unchanged |

**The physical focus/click/scroll failure was not reproduced in this fixture.**
The deliberate geometry cases explain their own changes (native move, resize,
maximize/restore or explicit zoom), not the operator's ordinary click failure.
Synthetic capture removes real capture/compositor timing and does not reproduce
every DPI, snap-layout, application-content or physical-input condition. It cannot
prove that a real focus transition is harmless or that physical masking is correct.

The earlier candidate handles preview-rectangle reflow with stable native geometry.
It cannot handle either original native geometry guard. There is still no evidence
that substituting a retry for those failures would be the correct physical fix.

### Focused verification and artifacts

| Scope | Result |
| --- | --- |
| `node node_modules/tsx/dist/cli.mjs --test tests/live-screen-owner.test.ts` in desktop | 18 passed; includes 30 injected combinations of 3 async guard stages × 10 operands, zero uncertain frame transmission, bounded event retention, same-viewer continuity, intentional stop, source loss and cleanup |
| `.venv/Scripts/python.exe -m pytest tests/test_connected_stage3.py -k 'screen_first_failure or screen_diagnostic_schema or screen_geometry_diagnostic or capture_ipc' -q --tb=short` | 5 passed, 22 deselected; detailed geometry survives host/server cleanup order and remains schema-restricted |
| `node tests/capture-focus-electron.mjs` in desktop | 11 isolated native-window action cases passed their expected success/failure assertions; confirmed actual focus transitions, handled click and scroll |
| Saved real-Electron diagnostic records through Python validator | All 5 deliberate geometry failures accepted |
| Desktop and teacher typechecks | Passed |
| Desktop `node scripts/build-electron.mjs`; teacher `npm run build` | Passed; source bundles only |

The initial isolated-run driver incorrectly read the Electron evaluate argument
slot, so native mutation requests did not run. That driver was corrected before
the recorded baseline, and final assertions require actual focus/geometry changes,
click handling and scroll movement. Initial fixture type errors were fixed. A
temporary `.ts` import suffix failed the existing typecheck; the production
import convention was restored, and the prepared physical observer now bundles
the validator for Node resolution. It was not launched for a physical run.

Artifacts are in `build/stage4a-stream-fix/focus-investigation/`, including
`isolated-electron-before.json`, `isolated-electron-diagnostics.json`, targeted
test logs and `verification.json`. Read-only cleanup inspection found no fixture
process remaining, original teacher PID 10812 unchanged on 5178, and API port
8024 still absent. No existing service was stopped or restarted in this follow-up.

### Decision and remaining unknown

No recovery was added. For any measured geometry change during an in-flight
capture, that frame's mapping is uncertain and must never be transmitted. Whether
the physical failure is a harmless transition after which a fresh frame could
safely resume remains unknown. The new diagnostics can distinguish exactly which
comparison fails on a separately authorized physical run; they cannot retroactively
identify it in run 03. A future recovery would need demonstrated cause, fresh
valid geometry and mask sampling, unchanged authorization, and bounded instability.

No additional physical retest or service restart is authorized by this work.
No full suites, protection audits, keyboard blocking, packaging, public deployment
or Stage 4B were performed. **Stage 4A remains unready; the original physical
streaming failure is unresolved. Stop here pending further operator direction.**

## 13. Minimal real Windows capture reproduction prepared — NOT RUN

Following the operator's new direction, a standalone consent-gated Electron
fixture is ready to call real `desktopCapturer` with the production capture and
masking checks. No production fix or guard relaxation was made. Test-bundle-only
probes preserve exact values at each guard, bounded numeric mask/source metadata,
native events and the first failure. No frames are displayed, sent or saved.

Five recorder tests and a mock-only Electron integration test passed; desktop
typecheck and the fixture source build passed. No physical capture, exam or
service restart occurred. The physical cause remains unresolved.

See [the real-capture preparation report](TEACHER_DASHBOARD_STAGE4A_REAL_CAPTURE_REPRO.md)
for the 155-second scenario schedule, bounds, evidence paths and launch procedure.
Both explicit operator authorization and in-window consent are required before
real capture. Stop at this execution gate; do not start a full-application test
without separate permission.


## 14. Authorized viewing resilience implemented — physical verification pending

The subsequent isolated real-capture run demonstrated translation during capture (content x +6, y -3; other geometry unchanged). The operator then authorized implementation of bounded same-lease recovery. See [the viewing resilience report](TEACHER_DASHBOARD_STAGE4A_VIEWING_RESILIENCE.md) for the narrow recovery classification, discarded-frame and authorization boundaries, explicit viewer states, 45 targeted passing tests, and the separately gated sustained UNPROTECTED retest. No physical capture or service restart was performed for this implementation. Earlier sections describe their historical states; physical acceptance remains pending and Stage 4B remains blocked.


## 15. Authorized resilience physical retest — FAILED

See [the physical retest report](TEACHER_DASHBOARD_STAGE4A_RESILIENCE_PHYSICAL_RETEST.md). Sustained viewing delivered 761 frames over 274.8103 seconds (2.766 FPS), with 20 observed same-lease Recovering-to-Live episodes and median ACK round trip 265.04 ms. The fresh-viewer check terminated after 27 frames: a native minimize event produced content bounds [-32000,-32000,0,0], failing before_mask/invalid_geometry. The operator confirmed minimization and a later manual restart; that extra viewer is excluded from acceptance. The operator confirmed readability, masking and normal controls. The exam ended normally and all six report artifacts arrived, but the server still has upload_pending and no final receipt. Owned processes were closed; the existing teacher website and evidence were preserved. No implementation or webcam-visibility change was made. Stage 4A remains unaccepted and Stage 4B blocked.

## 16. Approved webcam-visible policy and remaining Stage 4A fixes

See [the focused follow-up report](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_FIX.md).
Production monitor capture now requires explicit consent v2 and includes the existing
webcam preview when visible. Monitor geometry is separated from native mask geometry;
intentional Stop has an ordered stream notification; final-upload completion requests
no longer wait for an extra worker tick. Original evidence/receipts are preserved.
The old physical result remains FAILED. The subsequently authorized webcam-visible
retest is documented in [the physical report](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_PHYSICAL_RETEST.md).
It delivered 812 frames over 272.0107 seconds; sustained interaction, minimize/restore,
intentional Stop and final verified synchronization passed. The 2.98 FPS performance
target check failed, and the fresh-viewer 30-second check was cut short by the observer's
old-viewer safety clock. Stage 4A remains unaccepted; Stage 4B remains blocked.
