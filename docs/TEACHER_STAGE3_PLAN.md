# Stage 3 — live teacher monitoring and controls

Scope: extend Stage 1/2; preserve Python clock/lifecycle authority, durable evidence,
teacher ownership, local safety and existing design system. Packaging, public
deployment, full suites, physical device exams and native protection audits are paused.

1. Add authenticated bounded WebSocket presence/event notifications, short viewer
   leases and append-only command/viewing audit (numbered migration).
2. Apply expiring attempt/session/connection-bound commands in Python. Persist
   independent teacher/display pauses, time allowance and command idempotency with
   the existing recovery journal. Reuse Stage 1 extension and Stage 2 recovery.
3. Capture the exam monitor only under current consent and viewer authorization
   in trusted Electron main. Use an isolated local WebRTC transport renderer with
   no attempt/device credentials, and bounded memory-only WSS frame relay fallback.
4. Add localized consent/actual-viewing/message UI and one teacher live workspace;
   preserve existing evidence/review routes. Frames never enter evidence/outbox.
5. Add exact-one-display readiness and bounded detection. Preserve existing
   protected geometry-change terminal release; do not change it into resumable
   recovery without separate authorization. Unprotected display recovery requires
   new calibration/geometry readiness and explicit teacher approval.
6. Run only focused auth/protocol/command/relay/cleanup/display/UI regressions and
   affected source builds. Inspect privacy/security boundaries and write the final
   report with actual counts and physical/multi-network/protected gaps.

Inspection found no active `SetWindowDisplayAffinity`, `WDA_EXCLUDEFROMCAPTURE` or
`setContentProtection` implementation in current Electron/native source. No such
policy is disabled for this feature. OS capture failure is reported, never replaced
with fixture pixels. Existing rc8 audits are historical and cannot authorize this
changed source. Protected capture remains physically unverified.

UI uses existing warm sand/moss MASTER, Nunito/Inter, EN/RU/KK and installed
UI UX Pro Max accessibility guidance. Live timer/FPS updates must not flood screen
reader announcements; state changes use text as well as color.
