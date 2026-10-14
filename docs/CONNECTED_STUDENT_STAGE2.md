# Connected student — Stage 2 implementation notes

See [the Stage 2 report](TEACHER_DASHBOARD_STAGE2.md) for server setup, teacher
review, retention and the complete verification record. This note covers the
student integration. No native audit, hardware exam or packaged acceptance was
performed for this changed source.

## Storage and authority

`connected/durable.py` keeps admission/start identities, device credentials,
checkpoints and upload progress in
`%LOCALAPPDATA%\LocalProctoring\connected-stage2.sqlite3`. Current-user Windows
DPAPI encrypts each record with machine-bound entropy; there is no application
plaintext fallback. The test vault is available only through explicit Python
dependency injection, never through config or renderer IPC. Successful cleanup
purges identity, credentials, frozen quiz and checkpoint payloads while retaining
the receipt/manifest tombstone. DPAPI is possession binding, not hardware
attestation or protection against the Windows account owner.

`connected/workflow.py` adapts the existing Python controller. Device algorithms,
event thresholds, timer calculations and native protection implementation remain
unchanged. JavaScript displays the authoritative state and cannot restore the
clock or grant recovery. Saved stable answer IDs never include correctness keys
in renderer responses.

## Reconciliation and recovery

Admission and start operation keys are persisted before sending HTTP requests.
Start authorization is distinct from local start confirmation. After unexpected
exit, the original attempt/session is reconciled using secure device credentials
and requires a fresh teacher grant plus ordinary camera/reference/calibration
readiness. Previously saved answers, elapsed time and independent proctor/PIN
pause reasons survive. Closed/waiting time is not charged.

Checkpoints are saved approximately once per second and at answer/pause/terminal
boundaries. Recovery also reads the durable lifecycle/event tail, preserving the
original start timestamp, newer pause records and event IDs. An abrupt power loss
can lose the fractional running interval that was never persisted. No exact
millisecond or distributed-atomicity claim is made.

Terminal intent is journaled after protection release/timer freeze and before
slow finalization. A later launch can finish that summary using the original end
timestamp and saved answers. It cannot convert terminal emergency exit into a
resumable attempt. Incomplete/corrupt durable records fail closed for operator
attention; there is no silent timer reset or automatic JSON repair.

## Upload and deletion

The separate worker sends at most 100 journal records per batch, with a 64 KiB
canonical per-record bound and approximately 400 KiB batch bound. File chunks are
at most 256 KiB. Matching sequence/file acknowledgements advance progress;
identical repeats reconcile server frontiers. HTTPS validation and redirect
rejection remain mandatory, apart from explicit literal-loopback development
HTTP. Network failure does not pause the exam or generate misconduct events.

Only ended connected attempts may be cleaned after the complete matching receipt
is verified. Manifest identity, SHA-256 digest, complete flag, exact file/record
counts and each local file hash must agree. Cleanup uses an exact evidence
whitelist and durable per-file progress; it never recursively removes sessions.
Configuration, model files, developer exports and standalone evidence are not
uploaded or deleted. Missing required PDF/identity evidence remains incomplete.
Use the existing report retry, then synchronization retry, for repairable errors.

Transport errors retry with bounded backoff; validation/authentication/material
errors show Needs attention with a safe technical reason. Successful request
delivery alone is never displayed as Fully synchronized. Ended evidence can be
delivered with the correctly bound expired credential, but expired credentials
cannot start or recover an exam.

## Background and exit controls

The existing summary offers Continue uploading in background or Exit completely.
Both the main process and backend require the exam to have ended before the
background action. Camera/audio/native cleanup and report generation must finish
first. A backend acknowledgement is checked again before the window hides to a
tray icon. Only synchronization and its host remain; there is no service,
autostart, screen capture or hidden monitoring. The tray offers status and full
exit; verified receipt plus cleanup of all pending attempts exits the host.

Complete exit preserves unsent materials for the next explicit launch. Physical
tray behavior, hardware recovery and forced power-loss behavior still require
coordinated manual validation. Headless tests exercise the actual extracted main
handler and mocked backend/UI, not Windows notification-area rendering.

## Targeted checks and launch

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_connected_stage2.py tests/test_connected_stage2_api.py tests/test_connected_client.py tests/test_connected_workflow.py -q --tb=short
```

That batch passed 65 tests before the final two-line terminal deduplication guard.
The guard's new regression and the three related terminal tests subsequently
passed separately (4 passed, 29 deselected). No deselection was counted as a pass.
The API cases use temporary SQLite directories, owned loopback servers and
simulated readiness, including a real generated/uploaded PDF; they do not open
devices or protection hooks.

From `desktop`:

```powershell
npx tsx --test tests/background.test.ts
npx playwright test tests/ui/connected.spec.ts --grep 'Stage 2'
npm run build
npm start -- --config config/connected.example.toml
```

Five background/IPC tests and four EN/RU/KK synchronization UI tests passed;
typecheck/source build passed. The final Python-only guard did not require
rebuilding JavaScript. The launch command uses an unprotected development policy;
a protected teacher policy cannot silently downgrade. No package was built.
