# Localhost audio physical test — 2026-10-15

Status: test finished with a demonstrated early-upload failure, a focused fix, and successful post-submission recovery and user-confirmed playback. This is partial physical acceptance: corrected early delivery during an active exam was not retested.

## Final shutdown

User confirmed inspection finished and authorized shutdown. Recovery app closed normally; backend and supervisor exited code 0. Verified test API and teacher web processes stopped. Final identity-aware audit found no remaining owned processes and no listeners on ports 8000 or 5174. Descendant creation times and exact executable/creation identity distinguish owned helpers from unrelated stale parent links or reused PIDs; unrelated processes were not terminated. See `final-shutdown.json`. Server database, evidence, receipts and diagnostic reports remain preserved. No further physical test, protection test or deployment was run.

## Physical failure observed at 18:26 local time

Attempt `8cfbfe1007ba4f19a35d556919d40f25`, session `session-965d8fbe888342b49337d2c5e2341dd6` started at 13:20:45 UTC. Server independently records accepted consent v5. At investigation time the attempt was still active (`finished_at` null).

Canonical event `audio-event-000001` activated at 13:21:20.561334 UTC; local audio evidence became ready at 13:21:25.692867 UTC. Actual WAV: 8.0 seconds, mono PCM16, 16000 Hz, 256044 bytes; SHA-256 `8bab1fad25b66255868c8e4f581007455e0c67c4366d3388f857d89456aa8793`. One WAV exists for this event. No playback was automated.

Early upload FAILED: durable journal reports needs_attention/request_rejected, incomplete early_audio entry, cleanup false. Server event_audio has zero rows. The ready canonical record did reach sync_records. The student/domain emits uppercase `VOICE_DETECTED`, but both provisional audio declaration and final audio-manifest association in server sync.py require lowercase `voice_detected`. Evaluating that exact predicate against the persisted real record returns false. This explains rejection of the associated event and predicts final manifest rejection too. No server response was fabricated and no active attempt was modified to bypass this check.

Read-only failure evidence is preserved in `build/localhost-audio-physical/manual-01/physical-audio-first-failure.json`; original WAV, events and encrypted journal remain intact. The user's screenshot confirms pending; available-player transition, authenticated playback, amplification, completed-review playback, complete receipt and cleanup remain unverified. Awaiting coordinated normal exam completion; services remain available.

## Isolated environment

Run directory: `build/localhost-audio-physical/manual-01`. Fresh database, evidence, sessions, outbox and Electron profile; historical runs preserved. Migrations 001–007 applied. API `http://127.0.0.1:8000`; teacher `http://127.0.0.1:5174`. User stopped the previously owned API. New test-owned services have separate output logs and process identity records.

Exam: **Local Audio Evidence — Physical Test 01**, code **BK7PKH8XVB**, two native questions, 20-minute maximum. Audio monitoring/evidence enabled, 3-second pre-event and 5-second post-event windows, policy schema 3, consent v5. Protection, keyboard blocking and advanced remote/identity/liveness disabled. Disposable account access is stored separately in the run's private-access.json, not in this report.

## Preflight defects and focused validation

1. Fresh connected state raised TypeError because LiveWorkflow read admission.exam before admission existed. Preserved failing regression in preadmission-regression-before.log. Guarded the preadmission display state; admitted consent still derives from frozen server policy.
2. Electron then rejected the current Python state: its strict validator omitted advanced status and consent feature fields and accepted only consent v3. Preserved lifecycle first failure (invalid_backend_message) in preadmission-contract-failure.json and cross-language failing test in contract-reproduced.log. Updated explicit allowlists, bounded feature values, accepted versions 3/4/5; malformed/unknown data remains rejected.
3. Updated obsolete connected privacy wording in EN/RU/KK to disclose consent-dependent short audio uploads.

Validation: 39 focused Python tests passed; four focused Electron contract/security tests passed; TypeScript and source build passed. Tests use fake devices and do not activate native protection. Latest hashes are in physical-build-identities.json; initial preflight.json hashes describe the earlier preflight build.

The failed-contract app's backend and supervisor exited code 0. After normal close, its windowless Electron processes lingered; their identities were saved and only those verified processes were terminated. The subsequent corrected app shut down normally, with backend/supervisor code 0 and Electron root absence verified (admission-verified-shutdown.json). No broad lifecycle change was made.

## Observed readiness

Actual rebuilt student UI shows Python connected, Protection disabled, Join your exam, server address and exam-code fields, and corrected audio disclosure. Connected configuration passed explicitly with isolated user-data directory. Current launch record: student-physical-launch.json; owned process record: physical-owned-processes.json. No consent, camera/microphone capture, reference or calibration was automated.

Actual browser teacher UI is signed in as the disposable owning teacher and open at Live supervision for this exam. It reports the online connection established and no sessions yet. Kept accessible for manual playback testing.

## Submission and source fix

User confirmed normal submission. Read-only journal inspection confirms `ended_locally`, `media_released=true`, `needs_attention/request_rejected`, no receipt and `cleanup=false`. Summary end reason is `completed`, ended at 13:27:10.371580 UTC. Original PDF and WAV exist. User confirmation of physical device indicators is still pending.

Changed both server audio association checks to use `EventType.VOICE_DETECTED.value`, and changed the synthetic server fixture to use that same canonical domain value rather than the incorrect lowercase literal. The corrected fixture reproduced `snapshot_event_required` before the fix. Eight focused audio-server tests passed afterward, including retry, ownership, HTTP audio delivery and final receipt checks. Logs: canonical-audio-red.log (synthetic secrets redacted), canonical-audio-after.log. No consent, ownership or cleanup checks were bypassed.

The running localhost API has not yet been restarted; real pending evidence has not been recovered. Awaiting user coordination for the brief restart while keeping the teacher browser accessible. No additional physical exam or device activation is planned.

## Authorized recovery after submission

User confirmed camera/microphone indicators off and authorized a brief server restart. Verified original server identities before terminating only that owned tree. Corrected API started under server-recovered-launch.json with separate logs and returned health 200. Student app had already closed normally (backend/supervisor exit 0); its lifecycle is preserved as physical-normal-shutdown.json. Reopened the same isolated profile solely for ordinary durable-outbox recovery; no new exam or capture started.

Recovery completed at 13:30:55.780474 UTC. Server receipt `09541061a07146e682ac927209d9b1fd` matches the local receipt; manifest SHA-256 `5665646d90845b8ca352c1e19b17386df3270743287d66cd3780c62d54ab3659`, nine files, 39 records, complete true. Independently reran verify_receipt successfully and checked all nine server blobs against manifest size/hash. Audio matches the original pre-cleanup hash. Local worker reports fully_synchronized, cleanup true, nine removed items. Evidence: physical-recovery-verification.json. Original failure metadata remains preserved; normal receipt-gated cleanup removed the uploaded local bundle.

Actual authenticated browser live-supervision UI now exposes the event's native audio player, amplification slider at 1.0x and reset button. No Play or amplification interaction was automated. This is recovery after submission; early delivery during the active exam remains FAILED, and the live pending-to-available timing was not measured. Manual playback and completed-review checks are pending. Dashboard and services remain open.

## Manual playback confirmation and ownership

After being asked to test play/pause, seek, 1x/2x/4x amplification without speed change, reset, and playback from Review attempt, user replied **worked**. Recorded as user confirmation of that checklist; these actions were not independently observed or automated. No separate explicit confirmation of close-player stopping behavior or absence of autoplay was obtained.

Independent authenticated HTTP check against the actual saved WAV: owning disposable teacher received HTTP 200, 256044 bytes, with original SHA-256 unchanged after manual playback; second disposable teacher received denial (see physical-audio-access-verification.json). Separate HTTP cookie sessions were used without changing the user's browser login.

Physical outcome: real microphone recording and recovered completed-attempt playback passed; early active-exam audio delivery failed and was corrected in source with eight focused automated tests. No second physical attempt was run, so the corrected early-delivery path remains physically unverified. User confirmed device indicators off. Final service shutdown is awaiting explicit confirmation that dashboard inspection is finished.

## Pending physical results (historical preflight checklist)

User readiness, consent v5 acknowledgment, real device readiness, canonical audio event, WAV duration/hash, early upload, pending-to-available transition, real playback, manual 1x/2x/4x amplification and reset/reopen, completed review, other-teacher rejection, PDF/manifest/receipt, receipt-gated local cleanup and final device/process shutdown are pending. Do not treat automated preflight results as physical acceptance.
