# Teacher audio evidence

Implemented locally on 2026-10-15. This feature is optional and **off by default**. It does not establish that sound is speech or that misconduct occurred. No speech recognition, speaker recognition, emotion analysis, third-party audio service, or second microphone stream is used.

## Capture and limits

`AudioMonitor` offers the same timestamped PCM blocks used by its existing energy detector to an optional recorder. The detector's thresholds, accumulated sample durations, and event timestamps are unchanged. Recording starts only when the exam starts with microphone monitoring enabled and acknowledged consent v5. Setup buffers predating Start are excluded.

A canonical `voice_detected` activation requests one clip using its original `audio-…` event ID. Repeated notifications do not create further clips for that episode. Default capture is 3 seconds before activation and 5 seconds after it. Closing the sound episode does not cancel the requested post-event window. Distinct nearby events can have overlapping clips.

| Limit | Behavior |
| --- | --- |
| Format | Canonical 44-byte-header RIFF WAV, mono, signed little-endian PCM16, 16,000 Hz |
| Pre-event setting | 0–5 seconds, steps of 0.5 |
| Post-event setting | 1–8 seconds, steps of 0.5 |
| Hard file limit | 15 seconds / 480,044 bytes including header; current settings permit at most 13 seconds |
| Ring | Pre-event interval plus a bounded margin; at most 256 blocks, each at most 0.5 seconds |
| Active requests | 4 |
| Writer queue | 4, plus the file currently writing |
| Event deduplication | At most 1,900 identities per recorder lifetime; later events report unavailable |
| Result queue | 2,000 bounded metadata results |
| Upload | At most one 256 KiB chunk per evidence kind per outbox turn |
| Server bundle | Existing 256 MiB final bundle limit; provisional files share the 240 MiB / 1,900 item limit |

Input is converted to mono and resampled with linear interpolation, then clipped to PCM16. Playback amplification is separate and is not applied to recorded bytes. This is evidence-oriented audio, not a high-fidelity recording pipeline.

Only requested clips go to disk. The ring is temporary memory, cleared on interruption/end; it is never continuously written to disk. A writer thread creates an exclusive `.partial`, flushes and fsyncs it, validates its structure and size, and renames it to `audio/<event-id>.wav`. On Windows an existing destination is not replaced. Only then does the controller append a ready result to the journal. Ordinary write failures remove the writer's temporary file when possible and report unavailable.

Insufficient prebuffer or an early stop produces a shorter valid clip with an explicit reason. No samples, queue exhaustion, or write failure produces unavailable rather than a fabricated file. Microphone loss clears the ring and closes pending windows. Optional disk/network work never owns the timer or protection lifetime. Protection is released before final audio/report work; final summary production waits through subsequent ticks for the bounded writer queue, without waiting on disk in the exam UI thread.

## Configuration and consent

The existing server descriptor catalog now has 36 fields and policy schema **3**:

- Basic: `audio_evidence.enabled` — Save audio evidence.
- Advanced: `audio_evidence.pre_seconds`, `audio_evidence.post_seconds`.
- The 15-second safety maximum is fixed, not teacher-editable.

These settings are copied into the student's actual Python configuration through the existing frozen exam policy. Saved profiles persist them. Explicit migrations accept complete schema 1 or 2 policies and add recording disabled with the documented defaults, preserving existing values and stored original profile documents. Invalid/incomplete documents fail closed.

Recording requires `audio.enabled`. Recording settings are fixed before setup and cannot change through live commands. Disabling microphone monitoring while recording is enabled is also rejected during an attempt; this implementation does not support live recording-policy changes. Before an exam, the editor allows an enabled audio-evidence toggle to be turned off even after its microphone dependency was unchecked.

Consent **v5** is required only when audio recording is enabled. Existing v3/v4 acknowledgements do not authorize recording. The student disclosure explains event-associated sound fragments, authorized teacher listening during and after the exam, ambient voices including bystanders, and existing retention/deletion rules. With recording off, the disclosure retains energy-only behavior. All text is available in EN/RU/KK. Both student Start and server authorization/uploads enforce the current consent; setup device consent alone is insufficient.

## Journal, delivery, receipt and retention

Pending/ready/unavailable updates retain the canonical event ID and original start timestamp. They do not create additional canonical events or move the timeline position.

The durable outbox reuses the snapshot queue implementation with separate persisted audio cursor/frontiers. It discovers only acknowledged journal records. A deterministic `audio_<SHA256(event-id)>` item identity is frozen before declaration, so lost acknowledgements and restarts reconcile the same server file. Audio is delivered through authenticated `/student/sync/audio` declaration/chunk endpoints. Server checks include ownership, session, consent v5, enabled policy, associated original sound-event record, bounded size, SHA-256, and strict WAV validation. Malformed files never become playable. Completion emits the existing authenticated teacher availability notification; periodic snapshots recover a missed notification.

Early upload acknowledgement is **not** an attempt receipt. Published clips are required final-manifest items. Previously declared early files must remain byte-for-byte identical in the final bundle. Complete receipts still require matching journal records, images, original PDF, quiz/summary material, hashes and identities. Failed audio production is represented as required missing material; pending or unavailable audio prevents complete receipt/cleanup. The exam itself continues. No automatic waiver or fabricated replacement audio is implemented.

Local cleanup verifies the complete matching receipt and every current local file's hash before deleting listed material. A stopped app retains the outbox and evidence for recovery. If a crash occurs after atomic publication but before its journal result, recovery validates the deterministic file and records it as ready with an interruption reason. Lost in-memory audio becomes explicitly unavailable. A crash-created partial file is never promoted to valid evidence.

Server migration `007_event_audio.sql` adds the event/file association. Audio uses existing private evidence storage, owner-scoped reads, tombstones, explicit material deletion, and retention **30 days after actual attempt completion**. Migration and upload tests ran only against isolated test databases; historical audit reports and user evidence were not modified.

## Teacher playback

Live timeline and later review show Audio pending, Audio unavailable, or an embedded player, keyed to the same event. Shortened clips show a disclosure. The player uses native Play/Pause, seek and progress controls and never autoplays. Errors expose a retry action and never imply no sound occurred.

The playback-only Web Audio graph is media source → GainNode (1–4×) → DynamicsCompressor → output. The compressor uses a −6 dB threshold, 20:1 ratio and short attack to reduce clipping; it is not a guarantee against every transient or hardware distortion. Reset restores 1×. The label explicitly distinguishes amplification from playback speed. The graph is created/resumed on interaction and disconnected/closed on leaving the player. Original WAV bytes are never rewritten or re-uploaded.

The source is the existing authenticated teacher-owned evidence endpoint, with `audio/wav`, no-store, inline disposition and HTTP range support. There are no public or bearer-token-in-URL audio links. Unauthenticated requests are rejected and another teacher receives not-found. Cream/moss styling and a responsive player are retained. A pre-existing duplicate React sibling key in the live panel was corrected after the browser check exposed it.

## Automated verification

Focused results on this implementation:

- **54 passed**: audio recorder/controller/shutdown/recovery tests, policy catalog/migration, existing capture timing, exam delivery and event timing, and the affected legacy advanced-policy migration test.
- **14 passed**: audio outbox/server/HTTP tests and configuration/profile tests. Includes late publication, lost chunk ACK and restart, unchanged bytes, wrong teacher, consent v3/v4 rejection, early availability, byte ranges, malformed/oversize WAV, wrong event, complete final receipt/cleanup, missing-audio retention, and audio's 30-day retention deletion.
- **48 passed**: existing snapshot and durable-sync regression tests using the shared outbox and server paths.
- **1 browser scenario passed** in headless Edge: actual isolated API, saved audio settings and dependency handling, synthetic WAV playback/pause/seek, no autoplay, 1–4×/reset, unchanged playback rate and SHA-256, live and later review, EN/RU/KK, mobile screenshot. An offline render of the production graph measured approximately 4× PCM amplitude at 4× gain for a quiet synthetic signal.
- Teacher web and desktop **source builds passed**, including TypeScript checks. Existing Vite future-loader/chunk-size warnings remain; no packaging was run.

The browser scenario is `teacher-web/tests/ui/audio.spec.ts`, configured by `playwright.audio.config.ts`. Its temporary server uses only `127.0.0.1:8019` and `127.0.0.1:5179` and an isolated `.test-runtime` database. Python server integration tests used the server environment with the existing student site-packages as fallback for already-installed client dependencies; no dependency installation was performed.

An extra run of the existing advanced-monitoring test file had **one timeout** in `test_real_offline_worker_generated_nonface_and_process_exit` while waiting six seconds for an optional face-model result (74 tests passed in that broader invocation). It was not changed or claimed as passing. The affected schema-migration case passed separately. A process inventory found no leftover test face worker. This does not establish face-model reliability.

No real microphone/camera test, real exam, keyboard suppression, native audit, load test, Internet deployment, or packaging was performed. Source/build changes invalidate previous native protection audits; a new matching audit and separate authorization are required before future native protected validation.

## Remaining limitations and separately approved physical check

Physical microphones, driver buffering, background sound quality and speaker/headphone output have not been validated. Linear resampling and 4× playback gain cannot recover inaudible or clipped source sound. Many events still share existing total evidence limits. A permanently stalled disk can leave report preparation pending; shutdown remains bounded and retained evidence is reconciled on a later launch. Failed/missing required clips deliberately prevent complete synchronization; there is no new operator repair/waiver UI. Abrupt process death can lose pending memory audio. Historical recordings made with this feature disabled cannot be reconstructed.

Only after separate approval: create a short **unprotected localhost** synthetic quiz with recording enabled, review and accept v5, complete normal device gates, trigger one harmless sound episode, check pending→player live availability, listen at 1× then 2× and reset, submit normally, verify the final receipt and local cleanup, close the app, and confirm microphone/camera indicators are off. A second approved check can stop during the post-event window to inspect shortened-clip disclosure. Stop on the first error; do not automatically retry or activate protection. This plan was not executed.
