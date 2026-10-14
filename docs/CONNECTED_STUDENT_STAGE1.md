# Connected student mode — Stage 1

Historical Stage 1 behavior below is preserved for comparison. The current
durable outbox and teacher-authorized restart behavior are documented in
[Stage 2](TEACHER_DASHBOARD_STAGE2.md); the former best-effort/memory-only limits
below do not describe the new connected client.

Standalone launch stays available. Opt in with the public, unprotected example:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\desktop'
npm run build
npm start -- --config config/connected.example.toml
```

The example uses `http://127.0.0.1:8000`. Its explicit HTTP exception accepts only
literal loopback IPs. Remote server origins must use HTTPS with a trusted
certificate. Requests verify TLS, refuse redirects and use bounded timeouts and
response sizes. The renderer has no network access or attempt credential.

1. Start the teacher server and create an unprotected exam with a current admission
   window. Use an institutional student ID, not a national identity number.
2. In the student app, verify the server and enter exam code, full name, group and
   student ID. Only successfully verified server origins are remembered, in
   `%LOCALAPPDATA%\LocalProctoring\last-server.json`.
3. After admission, the immutable policy and server-frozen quiz order are applied
   before device setup. Complete ordinary consent, camera/microphone checks,
   reference capture and gaze calibration. The five-minute preparation clock is
   mapped conservatively from server time to the existing monotonic clock.
4. If preparation expires, ask the teacher for an extension, then use **Refresh
   preparation extension**. This queries the authenticated existing attempt; it
   does not admit a new student or replace the quiz.
5. Start requires local readiness and a server start acknowledgment. Readiness and
   the deadline are checked again after that acknowledgment. A protected teacher
   policy cannot arm an unprotected launch. Existing native audit gates remain.
6. Select one or multiple options as requested; use Previous, Next or the question
   selector freely. Early submission confirms unanswered count. Python scores one
   point only for the exact answer set and the UI shows score and percentage.
   Correct-answer keys never enter renderer state, including summary state.
7. An external exam uses the existing isolated WebContents path and exact-host
   navigation guard. End session stops local monitoring; it does not submit LMS
   answers. Internet loss after start does not pause timing or create review events.

The optional finish request is best effort and includes only client-reported
score, total and end reason. There is no event upload, evidence sync, recording,
durable queue or remote command channel. Local evidence remains authoritative for
this prototype. Teacher results must not be described as independently verified.

Attempt credentials stay in the Python process's memory. Same-process renderer
reconnection retains them; restarting the backend does not provide same-device
recovery in Stage 1. A lost admission response may leave an existing attempt on
the server, requiring teacher assistance after expiration. A delayed or lost
Start acknowledgment can likewise leave the server marked started without a local
exam. The app refuses local start after its conservative deadline; it does not
invent success or bypass the deadline to repair this state.

New source changes invalidate the historical rc8 protection identity. No native
protection audit or protected operator session was run for this feature. Packaging
remains paused. The unit/UI tests use simulated devices and responses; they do not
establish hardware behavior, Internet deployment or 30-student capacity.
