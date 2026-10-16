# Native recovery audit EPIPE investigation — 2026-10-15

Status: **FAILED prerequisite; Stage 4C stopped. No native retry has run.**

## Original failure and preservation

Fresh run `build/localhost-protected/manual-02` saved only three of 21 mandatory checks: `binding_identity`, `wrong_hwnd_rejected`, `wrong_stale_identity_rejected`. The operator screenshot shows **EPIPE: broken pipe, write**, through `console.log` → `record` (`main.cjs:1063:13`) → `async check` (`1135:7`) → `runRecoveryAudit` (`1158:5`).

The original report, both screenshots, original bundled main file, hashes and first-error summary are preserved under `manual-02/epipe-failure`. Full process identities remain private; credentials and raw command lines are not reproduced here. The byte-preserved `recovery-audit.original.json` has `passed:false`, `status:pending_or_incomplete`; the production validator explicitly rejected it. A separate `failure-summary.json` labels the outcome FAILED without rewriting the original evidence.

## Root cause and evidence limits

The failure is an **output-reader lifetime mismatch combined with an unguarded audit progress write**. My PowerShell launch invoked the GUI Electron executable directly with the call operator. The command returned after **0.760 seconds with shell exit code 0**, while Electron and its fixtures continued. That shell completion was not the audit's completion or Electron exit status. The live GUI process continued using its inherited output endpoint after the launch/output reader's lifetime ended. This was a launch-management error on my part, not evidence of a camera or native emergency-release failure.

A deterministic Node-only reproduction closed the parent reader after child startup and performed the same `console.log` operation. It produced **EPIPE, an unhandled stream error and exit 1**, with the same console/Socket write stack. The initial single-write probe was too early; waiting for reader closure and using bounded periodic writes reproduced the failure.

Inspection found no recovery-runner code closing its own stdout/stderr. RPC/cleanup timeouts manage separate fixture children, not the runner's output reader. The initial tool launch reported normal shell completion, not a timeout or cancellation. The operator closed the windows later at our request. The exact host-side pipe-handle close was not traced, and the original Electron exit code was not captured; these remain evidence limits.

The stream error is asynchronous, so the audit's surrounding async `try/catch` did not reliably contain `console.log`. Electron displayed an uncaught-exception dialog with processes still alive. Suppressing that exception alone would conceal the lost observation channel.

## Narrow changes

- `desktop/scripts/run-recovery-audit.mjs`: a foreground Node launcher owns/drains both child output pipes and waits for `close`. It saves only bounded allowlisted progress names/results, byte counts, timestamps, PID and exit status. Raw stderr/details are discarded. Cancellation closes the reader to trigger the guarded audit's own cleanup, without process-tree termination. Existing report paths are refused. CLI success requires both clean process exit and a completed passing audit report.
- `desktop/electron/audit_output.ts`: awaited writes and stdout/stderr error/closure handlers preserve one fixed first-failure code. Output loss aborts rather than authorizes. Late errors remain handled throughout cleanup; nothing recursively logs into a broken stream.
- `desktop/electron/recovery_audit.ts`: stops creating fixtures after output failure, closes existing exact-owned fixtures, persists `status:failed`, `passed:false` and the first failure, and quits. Completion is committed only after cleanup and successful final output. The fixture-construction boundary is injectable for automated tests; production still uses the existing native fixture.
- `src/proctoring/security/electron_validation.py`: explicitly rejects failed/incomplete/cancelled status even with a contradictory pass flag and all check names. Existing identity, age, check-kind and mandatory-check requirements remain.

No native helper/guardian behavior, protection policy, emergency shortcut, PIN, focus policy, ownership guarantee or device workflow changed. The prepared configuration hash is unchanged.

## Safe closure and corrected observation

An initial process check incorrectly compared JSON-deserialized DateTime values with timestamp strings and reported processes exited. A broader query showed them alive, and that conclusion was corrected. It was not accepted as cleanup evidence.

After the operator closed the windows and confirmed **Alt+Tab worked**, corrected UTC-tick comparison and a broader current-project Electron/Python audit query found **zero remaining processes**. See `cleanup-verification.json`. No forced or unrelated-process termination occurred. No matching Windows Application Error/WER 1000/1001 record was returned; the screenshot preserves the first error.

## Targeted verification

**13 Node tests passed:** real closed output pipe, stderr/synchronous/closed-stream failure, immutable first error, actual bundled recovery runner with mocked Electron/fixtures proving FAILED output and cleanup without a later fixture, launcher drain/wait/cancellation/spawn/exit behavior, and existing audit client/identity tests.

**19 Python tests passed:** incomplete-status rejection and existing audit endpoint/release-observation tests. **Source build passed:** TypeScript, Vite and Electron bundles. Existing Vite config-loader/bundle-size warnings remain. Test-only nullable-stream typing and mock `resourcesPath` omissions were corrected before final passing checks.

Commands in `desktop`: `node --import tsx --test tests/audit-output.test.ts tests/recovery-runner-output.test.ts tests/audit-launch.test.mjs tests/audit_client.test.ts tests/recovery-identity.test.ts`, then `npm run build`. From the root: `.venv/Scripts/python.exe -m pytest tests/test_electron_audit_output_failure.py tests/test_electron_audit.py -q`.

No second native audit, protected fixture, real exam, keyboard-hook activation or device test ran during this investigation.

## Build identity and approval boundary

Failed source: `345ad308b285dc7bfbdf198f8fac5dce8b2888703cb4bde6ac352fbf75faf1ac`.

Failed artifacts: `6c19b5b725d145e5863049883af35a2231ef4f2fcbceecb1aff79681ba204812`.

Fixed source: `ec0a8574e19f2f1bd6f7132b4c648635d1d84d90b00ab02fa929bd4387b65a00`.

Fixed artifacts: `be582039a67deaa6e65085456ef17536ff7379b471d87a7493ec652415e2f0e4`.

`fixed-build-identity.json` is preparation evidence, not an audit. **A new matching 21-case audit is required and needs renewed operator approval.** After approval, use a fresh output/config identity and the foreground launcher: `node desktop/scripts/run-recovery-audit.mjs --native-input --config <prepared-config> --audit-output <fresh-report> --user-data-dir <isolated-profile>`. This launcher has not been run against Electron.

Student A was not launched, B was not prepared, and teacher services were not started for manual-02. Protected localhost acceptance remains unestablished. Stop and wait for permission before another native protection test.
