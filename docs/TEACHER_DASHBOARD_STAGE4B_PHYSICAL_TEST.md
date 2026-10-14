# Stage 4B â€” Remote-teacher physical test

2026-10-14, Asia/Qyzylorda (UTC+5). **IN PROGRESS â€” no physical PASS claimed.**

## Authorized topology and limits

Operator narrowed the conditionally authorized single test to server and student on this Windows computer, with a normal teacher browser on a different network. Remote-student admission/network isolation and full cross-network integration are NOT tested by this topology. One public exposure only, maximum 30 minutes. Run: `build/stage4b/physical-01`; student numerical diagnostics: `build/stage4b-student/physical-01`.

Exposure clock started at epoch 1791972021.3482654 (15:00:21.348 local), hard deadline 1791973821.3482654 (15:30:21.348). Independent identity-aware Stop guard begins shutdown at 15:29:21.348. Guard PID 39536; its exact ownership record is in the run directory. No additional exposure or automatic capture restart is authorized.

The new HTTPS origin is pinned from the owned tunnel log. API binds only 127.0.0.1:8034 with one worker, new database/evidence, matching HTTPS API/teacher origin and HTTP exception disabled. Existing website PID 10812 / port 5178 is preserved. Exact source/build/process/environment identity is preserved in `physical-build-identity.json` and ownership records.

## Preparation corrections

Local pip check found the historical shared student environment had NumPy 2.4.6 against the project's <2 requirement, plus conflicting OpenCV package families. A first isolated overlay attempt exposed the incompatible opencv-python 5 requirement; that overlay was removed. A fully isolated `student-venv` was then installed from the connected student lock and editable source. Final pip check passed; NumPy 1.26.4, OpenCV 4.11.0 and MediaPipe/ONNX imports passed without devices. The original shared environment was not changed. This changed runtime must be identified in physical comparisons; results cannot be attributed solely to transport changes.

The student observer accepts an explicit isolated Python path. The exact current student TypeScript/Vite/Electron source build passed, with existing nonfatal Vite future-loader and bundle-size advisories. No packaged application was built.

Because the remote teacher has only a normal browser, a same-origin browser-only numerical observer was added as an optional built asset. Operator explicitly installs it via one console command. It reads existing numerical DOM metadata, keeps bounded records in memory, exports only numerical JSON on request, and neither intercepts frame payloads nor starts viewing. It shares the independently tested per-viewer clock, preserves first failure and planned teacher-network disconnect classification, and caps at 1800 samples. Three focused synthetic browser-adapter tests and nine clock tests passed. No full suite was run. The first attempted esbuild lookup used the wrong dependency directory; the corrected desktop esbuild invocation bundled successfully.

Remote observer activation remains pending operator confirmation. Its controls require English UI. Teacher-network interruption will be used instead of disconnecting the colocated server/student network. A separate student-network recovery claim is prohibited.

## Actual public preflight

Five checks passed: HTTPS health, frontend, numerical observer asset, unauthenticated teacher rejection, foreign-Origin rejection. Six authenticated checks passed using a separate disposable probe account: invitation, login, Secure/HttpOnly/SameSite cookie flags, missing-CSRF rejection, authenticated WSS snapshot and logout. The probe's exam metadata is connectivity-only with no student admission; the real disposable exam belongs to the remote teacher account.

The initial authenticated probe interpreter lacked requests and stopped before sending requests. The same probe then passed using the isolated student interpreter and the existing server timezone data. No security checks were relaxed.

## Physical status

The source student application opened with an isolated LOCALAPPDATA and explicit unprotected configuration. Initial Python state confirms protection requested=false, enabled=false, disabled; consent version 2 unaccepted, exam not started, viewer stopped. Operator must manually complete consent, devices, reference, calibration and exam start.

Remote login/certificate/observer activation, admission, sustained viewing, FPS/ACK measurements, commands, teacher-network interruption, final fresh viewer, verified receipt/cleanup and final shutdown are pending. Do not interpret preparation/public checks as physical success.

## Observed terminal failure — run stopped, cleanup pending

Operator confirmed remote sign-in, browser observer activation and student ready. Inspection before the coordinator's viewing signal found that two viewer identities had already run. No viewer start/restart was performed by the coordinator. Operator clarification of these starts and remote display behavior is pending.

First failure: 2026-10-14 15:10:55.833 +05:00, viewer `87f33be9e1364657894e2d521f932f39`, generation 0. Original diagnostic: sender / stop / `frame_delivery_unavailable`, relay transport, capture `in_flight`, viewer `attached`, requested=false, transition `lease_revoked`, fallback `direct_timeout`; WebSocket close code/reason null, secondary errors empty. Second viewer `b29ac089edee46619697d362f4c0596b`, generation 1, failed with the same classification at 15:11:59.419.

The source guard is `now - Math.max(lastAck, negotiationAt) > 12000` when transport is selected. This establishes delivery-ACK deadline termination, NOT why ACKs were absent. No geometry failure was recorded. Capture in-flight is a point-in-time state, not proof that desktop capture blocked or that Cloudflare dropped frames. No speculative fix or timeout increase was made.

Sampled sender states remained starting -> relay -> unavailable; no sampled Live transition occurred. Actual remote delivered frames/FPS/ACK measurements require the operator's saved browser numerical JSON; zero delivery cannot be inferred solely from these sender samples. The observer's first-terminal file was preserved separately from the later latest diagnostic, plus a bounded state window and per-viewer transition summary under `failure-preservation/`.

**Sustained viewing: FAILED.** The required coordinated 30-second idle + 180-second interaction sequence was not completed. Commands, planned teacher-network interruption and final fresh-viewer check are not performed after this unexpected terminal failure. Local exam remained running and monitoring healthy, consent v2 accepted/acknowledged, protection disabled, one display ready. Operator was instructed not to restart viewing, to save remote numerical diagnostics, and to end normally while leaving the summary open for receipt verification. Final synchronization and process cleanup remain pending.

## Remote browser evidence received

The operator explicitly confirmed manually starting viewing, laggy display and termination after a few seconds. The pasted numerical export covers the FIRST viewer only; its observer correctly stopped at that first terminal failure. It does not measure the second manually created viewer. Selected exact measurement fields are preserved in `failure-preservation/remote-observer-extract.json`; the full pasted export remains in the conversation. This extract is not falsely labeled as the original complete downloaded file.

| Measurement | Actual result |
| --- | --- |
| Transport delivering frames | WSS relay |
| Direct WebRTC | Timed out; no demonstrated direct delivery |
| Displayed frames | 8 |
| First / last browser presentation timestamps | 551506.599999994 / 560687.3999999762 ms (same browser monotonic clock) |
| First-to-last frame interval | 9.1808 seconds |
| Delivered count / presentation interval | 0.8714 FPS |
| Interframe rate (7 intervals / 9.1808 s) | 0.7625 FPS |
| First frame to sampled terminal state | 9.9523 seconds; 0.8038 FPS over that window |
| Capture-to-display ACK round-trip latency | Unavailable: all supplied samples null, not zero |
| Teacher terminal state | unavailable / disconnected; canvas hidden |
| Sender ORIGINAL terminal code | frame_delivery_unavailable |
| Recovering transitions in measured browser viewer | None recorded |
| Required 30-second idle / 180-second activity | Not completed; failed sustained-view test |
| Original 5–10 FPS target | FAILED in this short sample; sustained performance not established |

The original sender diagnostic and generic teacher `disconnected` are both preserved; do not replace the former with the latter. Frames did reach and render in the browser, so this is NOT a zero-frame result. Browser/server wall clocks were not independently synchronized; do not derive one-way delay or claim post-revocation capture from their absolute timestamp differences. Root cause of the missing timely acknowledgements remains unresolved. No geometry/privacy error was demonstrated. No recovery workaround, retry or timeout increase was implemented.

Browser startup samples with null viewer IDs sometimes show expected_network=true because both IDs were null; this is an observer metadata limitation, not a planned interruption. All actual viewer samples show expected_network=false. No planned network interruption was performed. Fixing that cosmetic diagnostic flag is outside this frozen run.

## Final synchronization failure and evidence retention

Python confirms normal completed exam, active duration 405.313 seconds. Student UI reports connection_failed / offline / ended_locally; durable journal remains uploading, cleanup=false, receipt absent. Independent server read found no complete receipt: session JSON 2015/2015 bytes complete; answers 0/243, events 0/480546, PDF 0/46862, reference 0/14062, summary 0/13181. Thus only 1 of 6 artifacts completed. This is a different observation from the earlier Stage 4A six-files-without-receipt issue; its cause is not established here.

All six local manifest-declared artifacts were independently checked for presence, exact size and SHA-256; all matched. No evidence was deleted. `incomplete-sync-verification.json` preserves numerical verification without file contents or secrets. The pending attempt remains pinned to the now-closed origin. Do NOT silently migrate its credentials, edit journals, delete pending evidence or create a replacement attempt. URL-change delivery recovery remains unsupported.

| Acceptance item | Result |
| --- | --- |
| Current public endpoint/auth/TLS protocol checks | PASS: 11 bounded assertions |
| Remote teacher login and observer | PASS: operator confirmed |
| Browser certificate-warning absence | Not explicitly confirmed in this run |
| Student admission/consent/manual readiness | PASS on colocated student; online, consent v2 acknowledged, running healthy |
| Remote student admission | NOT TESTED — revised topology |
| Real remote-teacher sustained viewing | FAILED |
| Warning/pause/resume/add-time | NOT TESTED after terminal failure |
| Teacher or student network interruption/reconnect | NOT TESTED after terminal failure |
| Explicit Stop/final authorized fresh viewer | NOT COMPLETED; second manual start is not a passing scheduled check |
| Complete receipt / verified local cleanup | FAILED / correctly withheld |
| Local evidence retention | PASS: all six size/hash matched |
| Teacher original/reviewed report and XLSX access | NOT VERIFIED; incomplete upload |

## Public service shutdown

Identity-verifying Stop completed at approximately **2026-10-14T15:22:22.405+05:00**, 1320.995 seconds from exposure-budget start, inside 30 minutes. Independent verification at 2026-10-14T15:22:25.953+05:00 found owned tunnel/API/console PIDs absent and 8034 closed. Existing teacher website PID 10812 retained its original identity and 5178 listener. Run database, server evidence and historical evidence were preserved. Guard was signaled by verified closed.json; no further tunnel is authorized.

The operator selected Upload in background, which hides the student window and retains a tray process. Operator subsequently confirmed Exit completely. Independent verification at 15:24:06 local found student root PID 28200 absent, observer application_closed=true, and guard PID 39536 absent. The student observer exited successfully with ended=true and zero recorded renderer page/console/main-uncaught error counters. Desktop controls were not explicitly confirmed normal and remain unverified. Remote browser logout/tab closure was requested but not explicitly confirmed. No unrelated process was terminated.

No full suites, protected tests, native blocking/audits, screen/audio recording, packaging, Stage 4C or Stage 4D were performed. Stage 4B is NOT accepted. Stop after preserving this run; any investigation changes or further physical execution need the corresponding new scope/approval.
