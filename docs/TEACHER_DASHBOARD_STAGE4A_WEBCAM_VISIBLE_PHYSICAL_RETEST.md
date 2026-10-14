# Stage 4A — Webcam-visible physical retest

Subsequent operator decision (2026-10-14): Stage 4B may proceed with the FPS target
and incomplete fresh-viewer check explicitly deferred. This does not change any
measurement or turn this historical result into full PASS. See the
[Stage 4B acceptance record](TEACHER_DASHBOARD_STAGE4B.md).

Date: 2026-10-14. **Overall acceptance: FAIL / Stage 4A remains unaccepted. Stage 4B remains blocked.** The sustained webcam-visible stream, intended Stop and final verified synchronization passed. The original 5–10 delivered FPS target failed, and the fresh-viewer 30-second check was cut short by a diagnostic observer error. No further physical test was started.

## Scope, identity and safety

This was the one operator-authorized bounded UNPROTECTED full-application retest of the implementation in [the webcam-visible fix report](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_FIX.md). No production implementation changes or speculative fixes were made during the run.

- Exam: `d316ebba839a45e996fb3ef965c460fa`.
- Attempt: `9db5e4478d284bef8a0ee48388b5229d`.
- Session: `session-fcacba41995a41318944ccce4d4c594f`.
- Electron main source-build SHA-256: `b4da74492b8b10f1847e84391ea9360bbb876ef881b0226c65d2464e3a17c75c`.
- Full source/build/config hash inventory: `build/stage4a-stream-fix/webcam-visible-run-01/preflight.json`. All inventoried source/build hashes remained unchanged at cleanup.
- Isolated server database: `build/stage4a-20261014-01/server/teacher.sqlite3`; backed up to this run's `pre-run.sqlite3` before launch. The prior isolated API was absent; only this test's API was launched on loopback port 8024.
- Existing teacher website PID 10812, creation epoch 1791951230.0156248, owner `DESKTOP-AOTO5TC\kuten`, executable `C:\Program Files\nodejs\node.exe`, port 5178, was verified and preserved.
- Protection, keyboard blocking, clipboard restrictions, VM and remote restrictions were explicitly disabled in the isolated configuration. Authoritative student state reported protection requested=false, enabled=false, state=disabled. No native protection or blocking tests ran.
- The operator manually accepted consent v2, completed camera/microphone setup, calibration and exam start. Authoritative consent was version 2, accepted and acknowledged. Readiness checks were not bypassed.

Observers saved bounded state, numerical metrics and diagnostic metadata, not screenshots, screen/webcam frames, recordings, answers or credentials. Ordinary application evidence synchronization remained enabled. The teacher received actual monitor capture with the existing local preview; no separate webcam or audio stream was added.

## Physical results

| Required check | Result | Evidence / limit |
| --- | --- | --- |
| At least 30 seconds idle after first display | PASS | 71.2697 seconds first-to-last displayed idle span; operator explicitly confirmed untouched window |
| Whole monitor and unmasked webcam | PASS | Explicit operator confirmation |
| At least 180 seconds active interaction | PASS | 200.5952-second interaction phase |
| Clicks, answer changes, question navigation | PASS | Operator confirmed continued live viewing |
| Webcam visible during scrolling/navigation | PASS | Explicit operator confirmation |
| Window movement and resize | PASS | Operator confirmed no stream stop; same sustained viewer identity |
| Minimize/restore during sustained viewing | PASS | Operator confirmed continuity and visible webcam after restore |
| Recovery | Not exercised | No observed Recovering/Unavailable episodes; no recovery-duration claim |
| 5–10 delivered FPS target | FAIL | Sustained delivery 2.9815 FPS |
| Explicit teacher Stop classification | PASS | Requested `teacher_stopped`, not unexpected `stream_disconnected`; teacher image cleared |
| Fresh authorized viewer for 30 seconds, including minimize/restore | FAIL — incomplete procedure | Only 18.3839 seconds; observer cap stopped it. Fresh-viewer-specific minimize/restore was not separately verified |
| Complete matching synchronization receipt | PASS | Independent read-only production-verifier check against actual server receipt |
| Local cleanup after receipt verification | PASS, with sampling limit below | Six files retained while incomplete; none remain after verified receipt; production cleanup verifies first |
| Normal shutdown / controls | PASS | Operator closed normally and confirmed normal desktop controls; owned processes exited |

The operator's visual confirmations establish preview visibility and interaction behavior. No frames were saved for later visual inspection. Specific movement/minimize action timestamps were not independently instrumented; the continuous metric history and operator confirmation support the sustained result, not a per-action native event timeline.

## Measured delivery and transport

| Metric | Sustained viewer | Fresh viewer |
| --- | --- | --- |
| Viewer ID | `60beeaf880c34efa8c02d82946534105` | `b610ac00e8f540cabbc060d279929148` |
| Delivered frames | 812 | 55 |
| First-to-last displayed span | 272.0107 s | 18.3839 s |
| Delivered FPS, `(frames − 1) / span` | 2.9815 | 2.9374 |
| Transport during delivery | Direct WebRTC | Direct WebRTC |
| Observed recovery episodes | 0 | 0 |
| Recovery duration | Not exercised | Not exercised |
| Distinct ACK-latency samples | 251 | 17 |
| ACK round-trip median | 261.8152 ms | 266.5149 ms |
| ACK round-trip p95 | 295.1337 ms | 307.6384 ms |
| ACK round-trip min–max | 239.5297–333.3231 ms | 252.4409–343.3540 ms |

Latency is capture-to-display-ACK round trip, not one-way latency. No capture failure or viewer-identity replacement was observed during the sustained interval. The final sender teardown records relay/fallback `rtc_channel_closed` after RTC teardown; that is not evidence that sustained delivery failed or ran over relay. Throughput remains below the original target; this run did not establish its bottleneck or tune it.

## Stop and the incomplete fresh-viewer check

The explicit Stop command was recorded at epoch milliseconds `1791965871126`. The first sender terminal record was `2026-10-14T08:17:51.187Z`, code `teacher_stopped`, requested=true, generation 0, with no secondary errors. Teacher state became Stopped and the canvas was cleared. This physically verifies the intentional-stop classification correction for this path.

The operator manually clicked **View exam monitor** afterward and confirmed that action. The fresh identity became ready at `1791965877273`; no second Start command was issued by the observer. Its first requested terminal record was `2026-10-14T08:18:16.595Z`, `teacher_stopped`, generation 1, with no secondary errors.

**The diagnostic observer caused the premature second Stop.** Its five-minute safety clock was still anchored to the first script-initiated viewer. It did not reset for the operator's manual fresh Start, so `five_minute_cap` fired at `1791965896570`, after only 55 frames / 18.3839 seconds on the fresh viewer. `actions.jsonl`, `observation-cap.json`, stream-ready events and sender records agree. This is a procedural failure, not a demonstrated product capture failure or an operator-confirmed manual Stop. It cannot count as the required 30 seconds. No third viewer was started and no shorter interval was substituted as a pass.

No unexpected terminal capture failure occurred, so there is no new failing geometry operand to report. Requested first-terminal Stop records were preserved independently before generic cleanup.

## Final receipt and evidence cleanup

The operator ended the disposable exam normally and kept the summary open for independent verification. The UI reported fully synchronized with matching receipt verified.

Read-only local-journal and server-database checks independently established:

- Actual server receipt exists and is byte-equivalent as parsed JSON to the retained local receipt.
- Production `verify_receipt` accepts it, checking complete=true, version, receipt identity, attempt, session, manifest, record count and file count.
- Manifest SHA-256: `427c0133eff2643768cbce473f00897dbf118fe425bd6d3a5687f10e180f12ef`.
- All **6/6** server files are complete; local sync status is `fully_synchronized`, cleanup=true, with **0/6** manifest-listed local files remaining.
- At epoch `1791966003.5975125`, synchronization was incomplete (4/6 server files complete), all six local files remained, and cleanup had not started. At `1791966004.1045117`, a matching valid receipt and complete cleanup were observed.
- The half-second sampler cannot order receipt persistence and each unlink within that last interval. The production cleanup path calls `verify_receipt` before any deletion and verifies local file hashes before deleting. The physical samples, retained receipt and unchanged tested code support receipt-gated cleanup; an exact sub-sample deletion trace is not claimed.
- Independent final verification was saved in `final-sync-verification.json`. No receipt was fabricated and no evidence was manually deleted.
- The earlier failed attempt `bb21136195944ca28ace5b3a67a67594` still has **6 complete files and 0 receipts**. Its historical evidence was not repaired or removed.

The operator also reported summary text “Evidence file is unavailable” and “Preparing the session report…” despite successful sync. This run verifies the actual receipt and file-cleanup state, not final rendering of every summary/report widget. Those UI messages remain a separate unverified presentation limitation; they were not treated as proof of missing server evidence.

## Shutdown and preserved artifacts

The operator closed the summary/student normally after receipt verification and explicitly confirmed normal desktop controls. The observer reported zero renderer page errors, zero renderer console errors and zero main uncaught markers. Every recorded owned student process identity had exited. The owned teacher observer browser and read-only sync observer closed.

Before terminating API PID 3860, its creation epoch 1791965385.047058, owner, executable, full launch arguments, port and isolated configuration were reverified against the launch record. Only it and its verified launch wrappers were closed. Port 8024 is absent; existing teacher PID 10812 still listens on 5178. Database, server evidence, old test evidence and source files remain preserved.

Primary numerical evidence directory: `build/stage4a-stream-fix/webcam-visible-run-01/`:

- `preflight.json`, `api-owner.json`, `api-launcher.json` — source/config/process identity.
- `teacher-metrics.jsonl`, `measurements.json`, `idle-end.json`, `interaction-start.json`, `sustained-end.json` — measured delivery.
- `actions.jsonl`, `observation-cap.json`, `operator-confirmations.json` — actions, cap and visual confirmations.
- `stop-60beeaf880c34efa8c02d82946534105.json`, `stop-b610ac00e8f540cabbc060d279929148.json` — preserved sender requested-stop states.
- `sync-history.jsonl`, `final-sync-verification.json` — actual receipt and cleanup checks.
- `teacher-cleanup.json`, `api-cleanup.json`, `final-operator-confirmation.json` — shutdown.

Student numeric state/process evidence remains under `build/stage4a-stream-fix/webcam-visible-student-01/`. Its observer uses public state/event reads, which refresh presentation traffic; this run is not a renderer-loss/watchdog or native-protection audit. The bounded teacher sampler reached 1800 samples and stopped sampling; the required sustained measurements and both Stops precede that limit.

## Remaining work and boundary

No regression suites, builds, protection audits, keyboard blocking, packaging, public deployment, load tests or Stage 4B were run during this physical retest. Prior focused automated verification is listed in the implementation report and was not rerun unnecessarily.

The new monitor-only geometry policy passed sustained physical movement, resize and minimize/restore checks in this run. It does not promise webcam visibility while its actual window is covered/minimized; visibility after restore was confirmed. Real display/source changes, authorization loss and other fail-closed conditions were not deliberately induced.

Acceptance still requires resolving or explicitly revising the unmet FPS target and a separately authorized valid fresh-viewer test. Before any later run, the observer must bind its bounded timer to the actual viewer identity so a manual Start cannot inherit an earlier viewer's clock. This report does not implement that change or authorize another physical run. Stop after Stage 4A; Stage 4B remains blocked.
