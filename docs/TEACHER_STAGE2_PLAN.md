# Teacher Dashboard Stage 2 — implementation plan

This stage extends the existing FastAPI/SQLite service, Python WorkflowBridge
and separate teacher React website. Python remains the sole owner of devices,
exam timing, detection, evidence capture and native protection. Stage 1 tests and
historical operator runs do not validate the new recovery/upload paths.

1. Agree an explicit versioned protocol for canonical session/journal identities,
   idempotent start confirmation, same-device recovery, manifests, resumable
   uploads and verified receipts. Add numbered server migrations.
2. Add a durable Python outbox and Windows user-scoped credential vault. Persist
   answers, elapsed active time and independent pause reasons for authorized
   recovery; preserve terminal emergency exits. Resume only after teacher approval
   and fresh device/calibration readiness. Never run another timer in JavaScript.
3. Verify expected material, hashes, sizes and persistence on the server before
   issuing a complete receipt. Permit recoverable, scoped local cleanup only for
   ended connected attempts with an exact matching receipt. Missing required PDFs
   or evidence remain incomplete. Exclude secrets, configuration, developer exports
   and all continuous recordings from uploads.
4. Add immutable raw evidence with separately versioned event reviews, manual
   observations and deliberate receipt-gated conclusions. Recalculate native
   answers against the frozen server snapshot without overwriting local results.
5. Add authenticated original/reviewed PDF and XLSX access, versioned conclusions,
   30-day completed-material retention and audited early deletion. Extend the
   teacher UI in EN/RU/KK using the existing design system.
6. Offer explicit post-exam background upload or complete exit. Background mode
   is allowed only after media and protection have stopped; no service/autostart.
   Verify all changes using focused tests, temporary stores, controlled clocks,
   simulated devices, real loopback API requests and affected source builds.
7. Review security, cleanup and changed-file scope; document results and known
   limits, then stop. No hardware exams, native audits, packaging, streaming,
   public deployment or large load tests are part of this stage.

Detailed shared implementation contracts are in `TEACHER_STAGE2_CONTRACT.md`.
Private configuration and historical artifacts are preserved.
