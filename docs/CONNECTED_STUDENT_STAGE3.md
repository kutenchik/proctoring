# Connected student — Stage 3 implementation notes

> Current policy update (2026-10-14): [Stage 4A webcam-visible follow-up](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_FIX.md)
> supersedes masking and consent-v1 implementation details below. Historical test results
> remain unchanged. Webcam-visible sharing requires new consent v2. No new physical test has run.


The [Stage 3 contract](TEACHER_STAGE3_CONTRACT.md) defines the authenticated live
protocol. Existing Stage 2 admission, device binding, evidence upload, receipt
validation and same-device recovery remain authoritative. Standalone mode does
not create the live worker.

## Python and Electron boundary

`connected/live.py` owns a bounded daemon WebSocket client using official
`websockets==15.0.1`. TLS certificate verification stays enabled; remote origins
use WSS and the existing explicit literal-loopback development exception uses WS.
Redirects/proxies are not followed. Attempt/device credentials remain in Python;
the transport logger is disabled to prevent DEBUG-level header disclosure.
Controller callbacks never wait for network I/O.

`connected/live_workflow.py` receives messages on the controller thread and applies
only the defined command types. Every command must match the current attempt,
session, exam and connection, and its conservative monotonic deadline. A
reconnection cannot replay an old connection's command. Valid duplicates reuse
the durably recorded outcome; conflicting payloads are rejected.

Authoritative status is sent once per second, only while the latest controller
snapshot is fresh. It includes answered/total counts, never answer selections or
provisional scores. Journal notifications are limited to four per 250 ms and
retain their original line sequence. Queue backpressure retains the cursor and
reserves capacity for command acknowledgements. Permanent storage still comes
through Stage 2, not the live channel.

Screen pixels never pass through Python or the evidence outbox. Only the
host-only `live.poll` response carries an ephemeral viewer token and the validated
server origin to trusted Electron main. Ordinary renderer state contains no token.
`live.capture` reports actual transport state; a request alone displays Starting,
not Teacher is viewing. Disconnect, terminal end, display incident and shutdown
emit a stop. Queue overflow stops control/capture instead of silently discarding
an authorization change.

## Consent, time and recovery

Screen consent is explicit, persisted in the encrypted attempt and local session
metadata, and must be acknowledged by the server before start. Reasserting the
same consent after a control reconnect does not reset the exam.

Teacher pause is an independent pause reason. Teacher resume clears only that
reason; it cannot remove monitoring, presentation, local-proctor, display or
recovery-PIN gates. A specific healthy monitoring outage of at least 15 seconds
can have its PIN gate cleared by an authenticated teacher command. Normal local
PIN recovery remains available. Network loss alone neither pauses time nor
creates a misconduct event; a teacher pause already applied stays in effect.

Add-time commands allow integer deltas from 1 to 3600 seconds, with an effective
total allowance of at most 172800 seconds. Elapsed time and the original exam
policy are not reset. Effective duration and command IDs are stored in checkpoint,
lifecycle and summary. Journal-tail reconciliation preserves a durable pause or
extension if the process dies before its encrypted command-result commit. A
missing acknowledgement remains unconfirmed; it is not invented as success.

Teacher End uses existing release/finalization and Stage 2 synchronization.
Emergency exit is still terminal. Neither command submits an external LMS exam.
An unexpected application exit continues to require the existing teacher grant
and fresh readiness before resuming the same attempt.

## Display condition and protected limitation

Connected preparation requires exactly one display reported by the native Qt
screen inventory. Zero/unknown counts block too. A bounded one-second check runs
throughout the workflow; preparation commands also recheck immediately. An extra
display invalidates a partial/prepared baseline. During an active exam it creates
a technical display pause and stops viewing.

In unprotected mode, removing the extra display enables fresh gaze calibration
against the current geometry. Only a matching teacher approval then clears the
display reason; independent pauses remain. Reusing the pre-incident fit is not
accepted. Restart also reconstructs pending incident identity from the canonical
lifecycle tail if an encrypted metadata commit was interrupted. A durably
recorded teacher recovery clears stale incident approval metadata; neither case
avoids the normal same-device restart grant and fresh calibration.

The existing protected geometry-change rule remains **terminal** and takes
priority. This implementation does not rearm native protection or enable active
protected recalibration. If a protected display-count incident leaves geometry
unchanged, the display pause still cannot clear using its old fit; authorized
End remains available. Physical display changes and protected capture must be
validated later under a fresh matching native audit. Historical rc8 audits do
not authorize this changed build.

## Targeted verification performed

No real devices, Electron exam windows, keyboard interception or physical monitor
changes were used by these Python checks.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage3.py tests/test_session.py tests/test_connected_stage2.py -q
# 92 passed: 20 new Stage 3 cases and 72 affected timer/durable regressions.

.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage3_api.py -q
# 2 passed using actual WebSocket/HTTP against isolated temporary FastAPI servers.

.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage3.py -k display -q
# After the narrow display crash-reconciliation fix: 5 passed, 17 deselected.
# Includes two new crash-boundary cases; the prior 92-case batch was not rerun.
```

The actual-API cases cover consent/start confirmation; warning, independent
pause/resume, add-time and terminal teacher End; reconnect with consent
reassertion/no replay; and server loss without a local timer pause or misconduct.
Both owned worker threads and temporary server processes are closed by the test
fixtures. Synthetic readiness does not validate physical calibration, protected
capture, readable text, frame-rate targets or multi-network latency.

After the affected desktop source build, the existing safe connected command is:

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring\desktop'
npm start -- --config config/connected.example.toml
```

Packaging, public deployment, protected hardware acceptance and Stage 4 remain
paused. Do not use an old protection audit with this changed source.
