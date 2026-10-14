# Stage 4A resilience physical retest — FAILED

Date: 2026-10-14. One operator-authorized UNPROTECTED full-application exam. **Overall FAIL: the authorized fresh-viewer check terminated before 30 seconds, and final synchronization has no verified receipt.** The sustained phase demonstrated substantial improvement but does not override these failures. Stage 4A is not accepted; Stage 4B remains blocked.

The operator subsequently answered “yes” to the bundled remaining-checks question. Those confirmations are recorded explicitly below; they do not override the measured terminal failure or synchronization discrepancy.

## Scope, identity and safety

The isolated API was absent at preflight; no existing API process was replaced. The existing teacher website was verified as PID 10812, creation epoch 1791951230.0156248, owned by the current Windows user, listening on 127.0.0.1:5178 with the expected 8024 API proxy. Its process was preserved.

The original isolated database was backed up with SQLite's backup operation to `build/stage4a-stream-fix/resilience-run-01/pre-run.sqlite3`. Previous databases, evidence and source files were preserved.

In-memory esbuild output matched all three existing Electron main/preload bundles byte-for-byte before the student launched. Main bundle SHA-256: `29590e721f847c0f85c5436a3ceec53b1089c513b5dc41482c28bade638c7886`. Source, bundle and config identities are in `preflight.json` and `build-verification.json`. A first verification command had an incorrect esbuild working directory; the corrected explicit-directory verification passed. This did not alter the bundles.

The newly owned API PID 18372 was verified by creation time, executable, owner, command line, port and configuration. It used the existing isolated database/evidence directories and was closed after the test, with identity reverified immediately beforehand.

Separate run configuration explicitly disabled Windows protection, keyboard blocking, clipboard guard, VM checks, remote delivery and event snapshots. Exam policy was unprotected, audio monitoring enabled, snapshots disabled. Runtime samples confirmed protection requested=false, enabled=false, state=disabled. Single-display readiness remained enforced. The operator manually completed consent, camera/microphone setup, reference, gaze calibration and exam start; no readiness bypass was performed.

Exam ID: `fd3aa5ba51954743a282301619fd0864`; attempt: `bb21136195944ca28ace5b3a67a67594`; session: `session-d73e32f2cf64493a8b3ae124b0fb1ad0`. One disposable native exam was used. Observers saved numerical/control metadata only, with no screenshots, screen frames or recordings. Normal application report/reference artifacts are distinguished from observer data; no audio transmission or recording was added.

## Measured screen delivery

FPS below is `(presented frames - 1) / (last presentation - first presentation)` using actual browser presentation timestamps. It is not the target capture rate. ACK latency is capture-to-display-acknowledgement round trip, not one-way network delay.

| Measurement | Sustained authorized viewer | Authorized fresh-viewer check |
| --- | --- | --- |
| Viewer ID | `a1e2db1e739a42418a0eb6e438f341b5` | `7c87f7dfeb1a4fce9afc4ce71a4a3011` |
| Presented frames | 761 | 27 |
| First-to-last presentation span | 274.8103 s | 8.8408 s |
| Delivered FPS | 2.766 | 2.941 |
| ACK samples | 238 | 9 |
| ACK latency minimum / median | 239.16 / 265.04 ms | 257.97 / 266.62 ms |
| ACK latency p95 / maximum | 304.50 / 330.29 ms | 303.51 / 303.51 ms |
| Observed Recovering → Live episodes | 20, same viewer ID | 0 before terminal failure |
| Recovery median / longest | 0.625 / 4.031 s | Not applicable |
| Outcome | Retained lease until explicit Stop | Terminal failure before required 30 s |

Recovery durations are observed state durations at nominal 200 ms polling, not exact internal transition times; scheduling can increase that uncertainty. Full per-episode measurements and bounded quality observations are in `measurements.json` and `teacher-metrics.jsonl`.

The explicit interaction phase lasted 194.082 seconds before the Stop request, exceeding the required 180 seconds. Initial instruction/observation lasted longer than the planned 30 seconds; recovery events occurred during the phase labeled idle. That label is not proof that the operator left the window untouched. The six nominal 30-second action blocks were not enforced precisely: phase signals drifted, and the operator had already exercised resizing/scrolling before later scheduled prompts. Actual action confirmations are reported separately; an exact scripted schedule is not claimed.

The operator explicitly reported ordinary clicks in the student Electron window stable; scrolling/resizing could trigger Recovering and then resume automatically; interactions with other Windows applications remained stable. These observations agree with same-lease recovery telemetry. They do not prove every visual privacy check.

## First terminal failure — exact evidence

At **07:23:25.855 UTC / 12:23:25.855 local**, the fresh viewer failed with `capture_geometry_changed`:

- Component/phase: capture/capture; transport: direct; sender in flight, viewer attached.
- Guard: `before_mask`.
- Failed comparison: `invalid_geometry`.
- Before sample 1791962605854 and after sample 1791962605855 both had content bounds **`[-32000,-32000,0,0]`**.
- Native window and webContents were not destroyed.
- One display, ID 3833731472, bounds `[0,0,1920,1080]`, size `[1920,1080]`, scale 1 and zoom 1 were unchanged.
- Focus=false, maximized=false; capture source=null because failure occurred before source capture.
- Previous focus event at 1791962604742 and blur at 1791962605751 had valid content `[961,31,958,1008]`.
- Resize, move and **minimize** events at 1791962605837 all reported `[-32000,-32000,0,0]`, followed by blur at 1791962605838.

This is a zero-sized minimized-window geometry failure, not the earlier translation-only failure and not evidence of display loss or a zoom change. The guard correctly refused to proceed with an invalid mask coordinate baseline. This implementation classifies that condition as terminal. No speculative recovery or guard relaxation was made during the run.

The teacher recorded Unavailable at 07:23:25.983 UTC, retaining `capture_geometry_changed` and hiding the canvas. The first unavailable sender sample, original terminal diagnostic, numeric geometry and native event history were copied to `restart/sender-first-terminal.json`. They survive later cleanup/status changes. The original teacher record is `restart/teacher-first-failure.json`.

## Stop/restart and deviations

Explicit Stop after sustained viewing cleared the canvas and stopped sender capture. A diagnostic defect appeared: the requested shutdown was reported by the sender as `stream_disconnected`, requested=false, socket close code 1000, with `rtc_channel_closed` fallback. This record followed the intentional teacher stop and is not a spontaneous sustained-phase failure. It is preserved in `stop-verification.json`; the classification race was not fixed during this test.

The single authorized restart obtained a fresh authenticated viewer ID and began delivering. It then encountered the minimized geometry failure above, so the 30-second restart check **failed**.

A third viewer, `a62fd372dd9e440eac076f7e0a0affc4`, appeared after the terminal failure. The observer's control log contains only the single authorized Start for that browser, and its code does not automatically restart after failure. The operator subsequently confirmed minimizing/Show Desktop and manually clicking Start again after the failure. The native event specifically establishes minimization; the bundled answer does not distinguish the exact Windows gesture. This later viewer delivered 105 frames over 35.803 seconds before being explicitly stopped when observed. **It is excluded from acceptance and is not a substitute successful retest.** The failure was captured immediately in the observer, but this subsequent viewing was not stopped until the agent inspected the next sample; this procedural deviation is disclosed rather than counted as a pass. No further viewing was launched.

Both owned teacher browser sessions were then closed. No new exam was started.

## Physical confirmations

Confirmed by the operator: ordinary student clicks stable; scrolling/resizing can recover automatically; interaction with other applications stable; student app closed normally; operator reported synchronization finished.

The operator answered **“yes”** to a single bundled question explicitly listing: initial 30 seconds untouched; selecting/changing answers and question navigation; readable teacher quiz text; webcam fully masked after movement/resizing; minimize/Show Desktop and manual restart after failure; normal desktop controls. These are operator-confirmed observations, not image-based verification by the agent. No screenshots or additional capture were requested. Exact action timing was not instrumented; the first observed recovery was approximately 26 seconds after the first presented frame, so the reported 30-second idle period may have been timed from the instruction rather than the first displayed frame. Do not claim an independently measured 30 seconds without interaction.

## Exam completion, synchronization and cleanup

The exam ended normally with reason `completed`; the local report was available. Last observer state had elapsed 438.344 seconds and final report status complete. The student observer closed normally, with zero renderer page-error, console-error and main uncaught-error counters.

The operator reported synchronization finished, but server verification contradicted final completion:

- Server lifecycle: **`upload_pending`**.
- Six artifacts fully received: answers 244 B; events 13,775 B; PDF 43,057 B; reference 14,170 B; session 1,960 B; summary 3,204 B.
- Every artifact's received byte count equaled its size and complete=1.
- **No `sync_receipts` record** existed for the attempt.
- Last student sample: uploading / ended_locally, fully_synchronized=false, one pending attempt.

Therefore material transfer is demonstrated, but verified end-to-end synchronization is **incomplete**, not passed. No database row was edited or completion receipt fabricated. Local pending state and server files are preserved for separate investigation.

All 15 observed student process identities were absent after normal close. Owned test browsers closed. Owned API and its wrappers exited after re-verification; port 8024 was absent. Existing teacher PID 10812 and port 5178 were preserved. Databases and all previous evidence remain intact.

## Artifacts and limits

Numerical/control evidence: `build/stage4a-stream-fix/resilience-run-01/` and `build/stage4a-stream-fix/resilience-student-01/`. Key files: preflight/build verification, actions, teacher metrics and measurements, sustained-end, stop-verification, restart first-failure and sender-first-terminal, completion-readonly, synchronization-verification, cleanup-readonly and api-cleanup.

No full test suites, Windows protection audits, keyboard-blocking tests, packaging, public tunnel/deployment or Stage 4B ran. No production implementation change was made during the physical experiment. The first minimized-window failure, requested-stop classification defect and missing final sync receipt are reported without attempting fixes.

The requested future webcam-visibility/consent change is **not implemented**. Existing masking remains. Making webcam preview visible, keeping it visible across navigation/occlusion and changing consent require a later approved task; no audio transmission or recording is authorized by that future request.

**Conclusion: FAIL. Sustained same-lease recovery is physically demonstrated; Stage 4A acceptance remains blocked by the failed authorized restart and synchronization discrepancy. The requested visual/interaction checks are now operator-confirmed, subject to the timing and measurement limits above.**
