# Stage 4A — Safe physical end-to-end validation (unprotected)

> Follow-up policy: webcam-visible monitor sharing now requires consent v2.
> See [the focused implementation report](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_FIX.md).
> Earlier masking procedures below are historical. Stage 4A remains unaccepted pending a new authorized retest.


Status: **physical checks completed with a screen-viewing failure; Stage 4B is
blocked.** Run 01 established the workflow results below. The focused run-02
candidate retest also lost viewing; it did not validate a fix. No further test,
fix/build cycle, protected run or packaging work is authorized by this report.

Date: 14 October 2026, Asia/Qyzylorda. Explicit UTC timestamps use UTC; observer
durations use a monotonic clock. Synthetic Stage 3 passes are not counted as
physical results. Both student applications closed cleanly; their recorded owned
processes are gone. The isolated API and teacher UI remain available for review.

## 1. Source and configuration

Repository: `C:\Users\kuten\Desktop\case3_proctoring`.
HEAD: `e54e4f09e7be63929fc00e645d99d53629d405fe`; substantial existing dirty and
untracked source from earlier stages. HEAD alone does not identify either run.

| Identity | Run 01 | Focused run 02 |
| --- | --- | --- |
| Source inventory | `build/stage4a-20261014-01/source-inventory.json`, 243 files | Original inventory plus the three-file candidate in section 11; `patched-source-identity.json` records exact hashes |
| Inventory SHA256 | `79cf05413286bbff7402e7a480901c8a173ba46ae85d24d41ba142b4eff9d7d5` | Not represented as the unchanged original inventory |
| Original composite built-artifact identity | `90bda8292e21d396c48ad52be9feb67a5c32cc45c1f6f4259ed888053373ee79` | Superseded for the Electron main bundle |
| `desktop/build-electron/main.cjs` SHA256 | `00bbb315ed8d7184898af73a39701be606e3d4a83e9274b91b56b2237c5f3197` | `89ae2367393cb30a32016a7784375fb10585b150cd87b11bf61afb21c42a9754` |

Runtime: Python 3.11.5, Electron 44.7.0. Both runs used
`build/stage4a-20261014-01/connected-unprotected.toml`, SHA256
`17c037b32f672d11d3773811a73491bccf1a26b843344f0fbc1d0503d86c7cb6`.
It is an isolated copy of public `config/connected.example.toml`: protection and
legacy blocking false, blank/disabled remote delivery, isolated session storage
and child-process `LOCALAPPDATA`. Camera/gaze/identity/readiness and timer gates
were not bypassed. Existing private configuration was not changed.

## 2. Processes and environment

The disposable API uses `http://127.0.0.1:8024`; teacher UI uses
`http://127.0.0.1:5178`. Data and numerical evidence belong to ignored
`build/stage4a-20261014-01/`. Fresh SQLite migrations 1, 2, 3 and 4 were confirmed;
the normal server database and personal connected outbox were not used.

Initial owned API PID 38120 (launcher 5556), Vite PID 10812 (launcher 32672),
run-01 Electron PID 18356; API identities changed during approved restart checks.
Run-02 Electron PID was 37020. The API and Vite were retained for that focused
retest, so run-01 app cleanup is not a claim that all test services had shut down.

Run-01 operator confirmed closing the summary normally without error dialogs.
The observer recorded `application_closed=true`, no uncaught JavaScript markers,
and the read-only cleanup inspection at `09:55:54+05:00` found all 27 recorded
owned process identities absent. Inspection terminated zero processes. Run-02
operator confirmed “Closed cleanly; desktop controls normal”; its observer also
recorded `application_closed=true` and zero renderer/main JavaScript error
counters. The read-only inspection at `10:02:11+05:00` found all 13 recorded
run-02 owned PID/creation-time identities absent and terminated zero processes.
These checks did not close the isolated API or teacher UI retained for review.

Read-only preflight found no conflicting listener; no unknown existing process
was terminated or replaced. No native restrictions or native protection audit
ran in either session.

## 3. Physical workflow

Operator readiness preceded device use. The real teacher UI imported/saved the
public two-question sample and created native exam
`0c9c329854cf47b3ba6addbd739d5b12`, code `BXPZCU9AHH`, with an initial 1800-second
allowance, audio monitoring, camera event snapshots, and **Unprotected** mode.

| Run | Attempt | Local session | Outcome |
| --- | --- | --- | --- |
| 01: primary workflow | `b8ebc77fc6384296b8e2be92b1236821` | `session-97d3db19b8c649fdafcd2fa584cff3b7` | Normal setup/start, warning, commands, two server interruptions, teacher End, synchronization and review completed; direct viewing unstable |
| 02: candidate retest | `c0248873bce9407fa2eb659f511802a3` | `session-dc2b4b9076f0484bbe4a1e2ccc1e8f80` | Normal setup/start; direct viewing stopped again; explicitly approved teacher End applied; synchronized |

The operator confirmed setup and the student viewing indicator. Consent was
acknowledged and exactly one display passed. Neither session started with
protection enabled. Run 01 ended through the teacher command, not quiz submission:
one of two questions had an answer, elapsed time was 1019.374 seconds, effective
allowance 1860 seconds and remaining time 840.626 seconds. Run 02 ended through
the teacher command at elapsed 100.156 seconds of 1800 seconds.

## 4. Webcam, microphone and calibration

Actual camera input was **640×480**, approximately 30 capture FPS, despite the
1280×720 request. The operator completed the normal microphone, reference-photo
and gaze flows. Backend calibration was ready with 30 accepted samples in run 01
and 40 in run 02; reference readiness was true in both. This establishes usable
setup for these runs, not gaze accuracy, glasses robustness or a new calibration
validation study.

Run 01 saved six suspicious events: two `gaze_down` events (6.094 and 13.140
seconds) and four `face_absent` events (51.594, 58.344, 3.344 and 6.625 seconds),
with six snapshots. They remain review flags, not findings of misconduct. The
approved server interruptions did not make camera monitoring unavailable:
monitoring was healthy in every sampled outage state. Stopped camera/audio
telemetry at the final summary reflects session shutdown, not a new outage test.

## 5. Screen viewing

**FAILED sustained usability in both source builds.** Direct transport delivered
the real monitor and the operator confirmed the viewing indicator, but scrolling
or interacting with the Electron quiz repeatedly stopped viewing, including when
the operator reported the windows side by side.

Run-01 server audit recorded 16 viewer requests and 16 first presentations, all
`direct`; 15 ended with generic `disconnected`. First-presentation-to-stop time
for those 15 was 1.012–29.854 seconds (median 6.385). One lease lacks a stop entry
across an API restart; that omission is not a successful continuous-view result
or, by itself, proof of a leaked process. First presentation also does not prove
continuous frame delivery between the two audit entries.

A temporary developer trace at `04:40:56.465 UTC` recorded stop origin
`control_view_stop`, teacher document visibility `visible`, and focus `true`,
without a preceding hidden-page marker or stream error. This excludes hidden-page
cleanup for **that observed reproduction**. It does not establish the original
sender exception: the terminal cause had already been reduced to `disconnected`.
Temporary teacher logging was removed and both teacher source hashes restored.

Run 02 used the section-11 capture candidate. First presentation occurred at
epoch `1791953765.122714`, followed by generic `disconnected` at
`1791953770.186620`: **5.064 seconds later**. The operator reported “Viewing still
stops.” The candidate therefore **has not fixed the physical failure**.

The capture path implements webcam-preview masking and rejects uncertain frames.
The operator did not explicitly confirm the requested visual mask/readability
check, so neither is counted as a physically passed check. No screen frames were
recorded by the observer.
**Relay transport was not physically tested.** Stable viewing, deliberate
hide/close lifecycle coverage and reliable fallback are not accepted on the
basis of these short direct connections.

## 6. Performance

One actual teacher quality sample showed **3.0 acknowledged FPS**, **1280-pixel
width**, **271 ms capture-to-display-ACK round trip**, and frame age 0.0 seconds.
It includes capture, delivery, rendering and return acknowledgement; it is not
one-way network latency. A single sample is not sustained performance acceptance.

Run-01 numerical observation collected 1249 state and 454 resource samples.
State sampling median gap was 1.041 seconds (maximum 5.080); resource median gap
was 3.007 seconds. The analysis checkpoint had 27 state-read errors; the final
observer total was 34, with zero resource errors. These gaps limit exact timing.

| App process-tree measurement | Active exam, 377 samples | Observed viewing, 48 samples |
| --- | --- | --- |
| CPU, median / sampled peak | 5.84% / 15.76% | 10.83% / 12.43% |
| Summed working set, median / peak | 2311.9 / 3153.5 MiB | 1827.3 / 3107.6 MiB |
| Summed private bytes, median / peak | 3103.2 / 3969.7 MiB | 2548.6 / 3873.5 MiB |

CPU is normalized to logical processor count, not whole-PC utilization; new or
exited processes can lose partial intervals. Working sets double-count shared
pages; private bytes are commitment, not physical RAM. Teacher browser, API,
observer and unrelated applications are excluded. Phase boundaries use the
preceding sampled state, so these groups are not a controlled overhead comparison.

Vision telemetry over 1034 samples had median capture 29.964 FPS and combined
monitoring 4.462 FPS; MediaPipe latency median 6.239 ms, sampled maximum 1150.231
ms; YOLO median 21.058 ms, maximum 43.641 ms. Observer overhead and per-process
network throughput were not measured. Its read-only RPC refreshes presentation
traffic, so this was not a watchdog or renderer-loss test. These figures do not
certify the 8 GB minimum machine target.

## 7. Teacher commands

Run-01 production command records and operator observations establish these
results; each command reached `sent → delivered → applied` for this session.

| Command | Command ID | Actual result |
| --- | --- | --- |
| Warning | `1b7b38c0942343daa7ce693ca1d046d5` | Warning shown; timer continued without a pause reason; application acknowledgement at elapsed 563.156 s |
| Pause | `4328ff49254a48ceabc6f81a1fadf192` | Added `teacher`; froze elapsed at 743.812 s / remaining 1056.188 s |
| Resume | `d9e6a577abcc469fa56259bf01498a06` | Removed `teacher`; resumed from the same elapsed/remaining values after the first server interruption |
| Add 60 seconds | `329b08b9266e49d5bfe11f601388212f` | Allowance 1800 → 1860 s; one 60 s increment, elapsed preserved at application (912.577 s) |
| Teacher End | `3cf64f8f740944de8668dc17631c8732` | Explicitly approved terminal command; `teacher_ended`, elapsed 1019.374 s |

Repeating the same HTTP +60 request ID and body returned the same command: the count remained four
before End, allowance remained 1860 seconds, and no duplicate increment occurred.
This verifies request idempotency; deliberate WebSocket command-packet redelivery
was not separately tested.
The fifth distinct command was the subsequent terminal End. No deferred command
execution was observed after reconnect. This does not test every command expiry
or every overlapping pause-reason combination.

Run-02 approved End also reached `applied`; no full warning/pause/time sequence
was repeated in that focused retest.

## 8. Server interruption

Only the positively identified disposable API was stopped, after operator
approval. These were **control-server outages, not camera outages**. Durations
below bound backend `offline`/`reconnecting` states using adjacent online samples;
they are not inferred from process-stop or cable-unplug duration.

| Run-01 check | Backend unavailable interval | Local result |
| --- | --- | --- |
| API restart while teacher-paused | 31.640–33.796 s; 29 unavailable samples | Monitoring healthy throughout; `teacher` retained; elapsed and remaining changes both 0.000 s |
| API restart while running | 20.670–22.834 s; 20 unavailable samples | Monitoring healthy throughout; no pause reasons; inner observed interval 20.670 s advanced elapsed by 20.672 s and reduced remaining by the same amount |

The running interval's outer sample bracket was 22.834 seconds, with elapsed
change 22.844 seconds. API-stop-to-restart-launcher gaps were only 22.733 and
15.272 seconds, respectively; launcher creation is neither API readiness nor
client reconnection. State reconciled after reconnect, the retained teacher pause
was resumed explicitly, and old viewers did not automatically replay: a new lease
was required. Final durable synchronization completed after the later teacher End.

## 9. Synchronization and receipt

**Run 01 passed the post-cleanup consistency check.**
`receipt-verification.json` independently read the frozen local manifest and
server records at `04:49:19 UTC`. Both sides identified the same session, manifest
and complete receipt:

- Receipt `d12fa2cf8e5c459eac01614ca5b9da35`, verified `04:49:09.127339 UTC`.
- Manifest SHA256 `96ac57126426e38fa3a2c76429709ddb1880955cb7a018405530a2f955a366a3`.
- 550 records and 12 files; every server file's bytes/hash matched the frozen
  local manifest. Server lifecycle `synchronized`, local `fully_synchronized`.
- Local cleanup recorded all 12 removals and completion; credentials cleared.
  The session directory retained metadata. The server evidence was not deleted.

The original PDF hash matched the locally frozen manifest after local removal.
An initial verification helper selected the wrong PDF kind instead of
`original_pdf` and reported a false mismatch. Correcting that ignored helper
resolved the check; it was not a production storage fix.

This is a one-shot post-end checkpoint, not independent observation of every
receipt commit and unlink. Source inspection confirms receipt persistence, hash
verification and persisted cleanup-start state precede unlinking. Sequential
local/server reads are not an atomic cross-process snapshot.

Run 02 independently passed `receipt-verification-run02.json` after
`teacher_ended`: receipt `f3480f24dcfa454d8850e7909db45a44`, 6 files and 6 records;
all six server hashes matched its frozen manifest, local/server receipts matched,
cleanup completed with six removals and credentials cleared. Its summary reached
`fully_synchronized`, pending attempts zero, and PDF generation complete. The
44508-byte original PDF SHA256 was
`d8cb95a56f0fd2fb6c6ff21f2a70c5280f209e348037450bf37587a6bba44568`.
This is a separate run-02 verification, with the same post-cleanup observation
limitations as run 01.

## 10. Review and reports

The real teacher UI displayed run-01 event groups and snapshots. Events 4, 5 and
6 received a group decision `insufficient_evidence`; event 5 was then changed
individually to `not_reviewed`, version 2, preserving the exception/history. A
manual technical observation was added. The deliberate conclusion was
`insufficient_evidence`, explicitly acknowledging four unreviewed events. These
test reviews make **no academic judgment** about the operator.

| Artifact | Verified result |
| --- | --- |
| Original PDF | 2 pages, 120596 bytes; SHA256 `71aa6b92d59f7729fc9a76a3fe37100af3e3a09147cbdb814048c758af892ead` |
| Reviewed version-1 PDF | 3 pages, 433367 bytes; SHA256 `ad3082d3120189e306655053f60135690440d034abe23b0fcd3fe6a12dee27c5` |
| XLSX | Real UI download `exam-attempts.xlsx`, 5847 bytes; parsed 3 rows including header and the newer preparation attempt, 16 columns; SHA256 `e8d5c8f102813e0d36ba5ba8d5de23510be876f7a30e8a51f3a0561f56014662`. Earlier run-01-only parse: 2 rows, 16 columns. |

Rendered PDF pages were visually checked: text and evidence were readable without
overlap. Two unchanged presentation limitations remain: some raw decimal durations
wrap, and the reviewed report's Duration field shows the base 1800 seconds rather
than the effective 1860-second allowance after +60. Receipt/hash correctness does
not resolve that report-label ambiguity.

A current student credential received HTTP 200 for its permitted own-attempt
request and HTTP 401 for the attempted teacher-review access. This documents that
probe; it is not a new exhaustive authorization audit. Existing report/evidence
retention was not changed. No live screen frames were added to reports.

## 11. Findings and changes

The concrete unresolved product failure is viewing termination during ordinary
quiz interaction. The generic terminal reason loses the original capture or
transport exception, so the exact upstream trigger remains uncertain. The
visible/focused teacher trace rules out one proposed explanation for that
reproduction; it does not prove a particular replacement explanation.

One narrow candidate was made in three files:

- `desktop/electron/screen_capture.ts`: identifies a valid webcam-mask layout
  change across capture as `TransientMaskLayoutChange`, only while both mask sets
  are valid and native bounds, zoom and single-display geometry remain stable.
- `desktop/electron/live_screen.ts`: discards that uncertain frame without
  encoding or sending it, then retries on the existing lease. The original
  acknowledgement/delivery deadline remains; repeated reflow cannot extend it.
- `desktop/tests/live-screen-owner.test.ts`: focused regressions for the retry,
  continuous reflow deadline and unchanged fatal guards.

Missing/invalid masks, destroyed owner, multiple displays and consent loss remain
fatal. No unmasked fallback, timer change, recovery relaxation or new viewing
permission was introduced. **Run 02 still failed, so this candidate is not an
accepted resolution.** No further edit/build/retest cycle was started afterward.

Temporary teacher-only DEV stop diagnostics were removed. Restored SHA256 values:
`LiveWorkspace.tsx` =
`bce5a6d5a99cf6fd1d3fd0483086fe55e21510baf84596b11766819b772388dd`;
`live-viewer.ts` =
`3985ef1972f6cf6868b289a4aeaf7395e51cb779a509e56f185cabe7da1f2508`.
No teacher behavior change remains from those diagnostics.

Preparation also isolated the old protected-only observer and personal connected
outbox instead of enabling protection or touching existing attempts. Those
ignored run helpers are separate from the product change.

## 12. Targeted tests

Only checks affected by the concrete capture candidate were run; no broad suite
or native audit was rerun. From `desktop`:

```powershell
node .\node_modules\tsx\dist\cli.mjs --test tests/live-screen-owner.test.ts
npm run typecheck
node scripts/build-electron.mjs
```

The owner test file passed **7 tests, 0 failures** (329.6485 ms). Its initial
sandbox process-spawn `EPERM` was followed by an approved identical retry; no
assertion or timeout was weakened. Tests cover valid reflow retry, continuous
reflow delivery expiry, missing/invalid masks, owner destruction, multiple
displays, consent loss, prior authorization/lease cleanup and malformed messages.

Desktop typecheck passed. The Electron main build script passed after its
environmental `EPERM` retry and produced the run-02 main-bundle hash in section 1.
From `teacher-web`, `npm run typecheck` also passed after temporary diagnostic
insertion and after its removal. These are automated/source checks, **not evidence
that human screen viewing is fixed**; the subsequent physical retest failed.
No full renderer/UI rebuild or packaged executable was validated by this focused
main-build step.

## 13. Excluded tests

No full regression suites, native recovery/keyboard/protected audits, physical
second-monitor changes, emergency exit, public tunnel, multi-network/load test,
packaging or installer validation. No deliberate camera unplugging was part of
these server-outage checks. No forced-relay physical run was performed. Historical
rc8 results and earlier synthetic Stage 3 results do not fill these omissions.

## 14. Known limitations

- Direct screen delivery is not stable during the demonstrated interaction; the
  exact sender-side terminal cause is still missing. The candidate retest failed.
- Relay, Internet NAT traversal, free-tunnel behavior, concurrency and a separate
  teacher machine/network remain unverified by this localhost test.
- A single quality packet is not sustained FPS/latency evidence. Resource sampling
  has the limits in section 6 and does not certify an 8 GB machine.
- Successful calibration is not a new study of gaze accuracy or glasses behavior.
- Reviewed duration labeling and decimal wrapping remain as described in section 10.
- Run-02 final observer reported 13 aggregate state-read errors and no resource
  errors; their causes were not classified. They are not being labeled product
  failures or proof of a perfectly sampled run. Operator clean-close confirmation
  and owned-process verification were obtained separately for each run.

## 15. Stage 4B readiness

**Blocked by the repeated physical screen-viewing failure. Stop at Stage 4A.**
The accepted command, timing, synchronization and review results remain tied to
run 01; they do not turn this into an all-passed physical acceptance report.

The smallest proposed next action, requiring a new explicit approval, is bounded
diagnostic preservation of the original terminal capture/transport reason along
the existing channel, without images, secrets or a new diagnostic framework.
Then address only the demonstrated cause with a focused regression and one
separately approved capture test. Do not begin another automatic fix → audit →
build loop, reopen full exam checks or enable protection to investigate this.

## 16. Protected-mode risks

The current source and candidate build are newer than historical rc8 audits.
Protected capture, containment, independent recovery and protected display-change
behavior require separately authorized verification against matching runtime,
build and policy identities. Existing terminal protected geometry rules and
emergency recovery were not changed or tested in Stage 4A. No earlier audit is
being reused as current approval. Packaging remains deferred and unvalidated.

Notification focus restoration and terminal failure when restoration is refused
remain distinct historical outcomes; this report does not claim that notifications
are universally blocked. Stage 4A provides no authorization to start Stage 4B,
another protected session or packaging work.
