# Current-build recovery audit Р Р†Р вЂљРІР‚Сњ 2026-10-15

Result: **PASS, 21/21 mandatory native recovery checks**. Exactly one authorized audit ran, without active keyboard suppression, using the corrected foreground launcher. No protected shortcut fixture, student exam or camera/microphone capture ran.

Fresh evidence directory: `build/localhost-protected/recovery-03`. Previous reports were not modified.

## Identity and completion

Source fingerprint: `ec0a8574e19f2f1bd6f7132b4c648635d1d84d90b00ab02fa929bd4387b65a00`.

Artifact build ID: `be582039a67deaa6e65085456ef17536ff7379b471d87a7493ec652415e2f0e4`.

Configuration SHA-256: `63f68b5996f28599dff57c56af8fda4c8f26db3cac43d0438a89c9e188122600`.

Runtime: Electron 44.7.0, app 0.1.0, source build, CPython 3.11.5 AMD64. Machine/runtime/policy matched the tested EPIPE fix before launch and remained unchanged after completion.

Foreground launcher ran from 2026-10-15T07:43:29.436Z to 2026-10-15T07:45:44.326Z. Electron and launcher exited 0; no cancellation, retry or spawn failure. Both streams were drained through child close: stdout 3978 bytes, stderr 0 bytes. Report status `completed`, `passed:true`, `blocking_enabled:false`, stable run identity; production validator accepted all 21 unique mandatory native checks.

Report SHA-256: `b4eeb5ce00c86beeac9977788b8f0e297926284633ec82c9d75d2b4a4e23854d`.

## Exact checks

- PASS `binding_identity`
- PASS `wrong_hwnd_rejected`
- PASS `wrong_stale_identity_rejected`
- PASS `normal_release`
- PASS `repeated_cycles`
- PASS `emergency_shortcut`
- PASS `pin_modal_emergency`
- PASS `external_focus_emergency`
- PASS `renderer_loss_observer_alive`
- PASS `main_stall`
- PASS `backend_stall`
- PASS `main_loss`
- PASS `backend_loss`
- PASS `control_eof`
- PASS `lost_release_ack`
- PASS `helper_suspension`
- PASS `helper_loop_failure`
- PASS `forced_release`
- PASS `replay_rejected`
- PASS `overlapping_helper_rejected`
- PASS `recovery_reregister`

## Cleanup and operator confirmation

The audit verified exact retired helper/guardian ownership and exit between checks and after the final reporting fixture. External verification found zero surviving matches among 17 recorded process identities (PID plus creation-time UTC ticks), and zero project audit Electron/Python/launcher processes in a broader scan. No external forced termination occurred. The mandatory forced-release case intentionally exercises owned helper termination.

An initial sandbox process query was denied; the successful elevated baseline query confirmed zero before launch. During observation, an owner lookup raced an expected short-lived fixture's exit; a process snapshot then recorded 17 identities without that lookup. Neither observation issue was an audit failure or a native retry.

The operator confirmed audit windows closed and ordinary typing/Alt+Tab normal. Evidence: `prepared-identity.json`, `baseline-processes.private.json`, `observed-processes.private.json`, `recovery-audit.json`, `recovery-audit.json.launcher.json`, `verified-result.json`, `cleanup-verification.json`.

## Stop boundary

Recovery prerequisite passed for this exact current build. Protected shortcut fixture and real Protected Mode exam remain unrun and require user approval. No further native test is authorized by this completed single-audit permission.


## Subsequently authorized protected fixture and Session A preparation

Operator approved the fixture followed by the real exam, then explicitly confirmed Ready. The fixture ran once from 07:52:20 to 07:56:41 UTC (12:52:20РІР‚вЂњ12:56:41 Asia/Qyzylorda): **50/50 native checks PASS**. The aggregate report correctly remains `passed:false` because `wrong_pin` and `correct_pin` are explicitly NOT RUN in this fixture; no PIN success is claimed. No native checks missing or failed, no partial report. Cross-process foreground restoration measured 78 ms. Emergency release, maximum lease, failure releases and normal input probes passed.

Foreground launcher and Electron exited 0, stdout 10,272 bytes drained, stderr 0. External exact-identity and broad checks found no remaining fixture processes; no external forced cleanup. Operator confirmed temporary windows closed and typing/Alt+Tab normal. Evidence: `protected-fixtures.json`, its launcher record, and `fixture-cleanup.json`.

Prepared a fresh database/evidence directory and disposable teacher with protected, audio-monitored, snapshot-enabled two-question exam A. Both literal loopback services are healthy. Current source/build/config and recovery validation were rechecked unchanged; one display confirmed. Student app launched through the foreground owner; normal consent/readiness is pending, exam not yet started. Session B is not prepared. PIN and integrated protected workflow remain unverified.


Student launch visibility observation: the original process was running but no student window was targetable. A one-time same-profile single-instance activation exited 0 and restored the existing window; no backend restart or exam start was requested. UI inspection then confirmed Python connected, input unrestricted, and Join your exam. This startup visibility issue is recorded separately from native protection results; cause not yet established.


## Session A completed normally; Session B not launched

Attempt 9c7a2562bdc443d9bcb77cde2239cbe7 passed real camera/reference/calibration, microphone energy monitoring, consent and protected readiness. UI confirmed Protection active, Python connected, camera available and teacher Online. Operator confirmed Alt+Tab/Alt+F4 blocked, wrong PIN rejected, correct PIN pause/resume, normal submission/close, devices off, typing/Alt+Tab restored. No specific flicker/interruption was reported; the generic yes did not separately describe flicker.

Teacher warning, pause, +60 seconds and resume all had applied backend acknowledgements. Pause held elapsed time at 60.671 seconds across add-time/resume; UI showed 09:00 twice. Duration increased from 600 to 660 seconds; resume cleared teacher pause. The run-local coordinator initially failed parsing its copied Windows path before any request; only that harness path was corrected, without application-source changes or replayed mutations.

Teacher monitor received 65 frames and stopped cleanly, with protection Active during viewing. Three live snapshots uploaded during the attempt; an authorized image download matched its file hash. Production teacher dashboard opened a 1280x720 event snapshot during the active exam. Actual behavioral events included gaze deviations; phone detection specifically is not claimed.

Normal end reason completed, score 2/2. Start 13:06:55, end 13:09:41 Asia/Qyzylorda; active elapsed time 138.609 seconds. Server verified complete receipt and fully_synchronized. Authorized original PDF download: 63,392 bytes, SHA-256 a60da73a7a9137a4de1a5f7ef6b1204af3e9f30aa2442d4c80b73eada03f5152, matching the server file. PDF header checked; visual page rendering not performed. Encrypted local journal confirms cleanup=true and fully_synchronized. Local session retains only config.json; snapshots directory is empty. Receipt remains outside the session directory.

Student launcher/Electron exited 0 at 13:11:25 local time. Exact recorded and broader process checks found no remaining student/backend/helper/guardian processes; no external forced cleanup. Launcher drained stdout 2 bytes and stderr 3,750 bytes. It retains counts rather than raw stderr; student stderr is not claimed empty. Evidence: session-a-readiness.json, active-checks.json, command-*.json, viewer-observation.json, teacher-live-snapshot-ui.json, pre-submit-sync.json (final completion state despite filename), delivered-original.pdf, session-a-completion.json, student-a-cleanup.json.

Session B was prepared with a separate planned profile/outbox, and exact current identity was rechecked. Automatic approval review rejected its launch because it interpreted earlier approval as covering only one real exam. No workaround, second-session launch or rearming followed. Explicit additional-session approval is pending. Local teacher services remain running for that pending session.

Conclusion: one real protected localhost exam completed monitoring, teacher controls, live snapshots, original PDF delivery, verified local cleanup and normal input release. Real-session emergency termination and inability to resume remain unverified. Native fixture emergency release passed. Full Stage 4C acceptance remains pending.


## Final Session B result — emergency release, synchronization pending

Explicit additional Session B approval was subsequently received. No application source/config changes were made; current recovery identity was revalidated. Exactly one additional student launch ran with a separate profile/outbox. Existing single-instance activation restored its window.

Attempt 80df08df08414d0d887ba362f07fed68, session session-08e7a0d79f7e499a9234e14a4606c9d0. Local lifecycle records start at 13:20:41 Asia/Qyzylorda, PIN pause/resume, then EMERGENCY_RELEASE and terminal end_reason=emergency_shortcut at 13:21:20. Active elapsed 33.219 seconds. The operator reported the shortcut worked and exam ended, then confirmed everything good in response to the input/device-off question. Exact close mechanism/message was not separately described.

Student launcher/Electron exited 0 at 13:21:22; exact observed and broad checks found zero remaining student/backend/helper/guardian processes. No external forced cleanup, relaunch, rejoin or rearming occurred. The original process/lease is gone; no runtime resume attempt was performed. Launcher retained counts: stdout 2 bytes, stderr 3,000 bytes, not raw stderr.

Pending evidence remains preserved: local summary and journal show terminal emergency end, cleanup=false, sync_status=uploading, receipt=null. The server attempt still has finished_at/end_reason unset. This is NOT a completed emergency-session synchronization claim. Evidence inventory with hashes is saved in session-b-preserved-evidence.json. Do not clear it or silently restart capture/protection to finish synchronization.

Final assessment: the current build demonstrated a successful normal protected localhost exam with teacher monitoring/commands, live snapshots, original PDF receipt, local cleanup and safe input release. The additional real emergency test demonstrated local terminal emergency release, process exit and restored input, with evidence retained. Remaining limitations are emergency server completion/sync, startup window visibility requiring activation, unrendered PDF visual review and no separate detailed flicker confirmation. Two sessions are evidence of these observed outcomes, not a broad reliability guarantee. No further physical tests or Stage 4D/Internet work are planned.

Final cleanup: stopped only two recorded identity-matched local service processes after student shutdown. Service shell exits were 1 from this explicit stop, not student failure. Final process/listener check at 13:24:01 Asia/Qyzylorda found zero matching test processes and zero listeners on 8000/5174. All tests/services are stopped; pending Session B evidence remains untouched.
