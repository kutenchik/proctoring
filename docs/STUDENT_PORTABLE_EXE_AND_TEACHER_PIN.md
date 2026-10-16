# Current requested edition — Student NoAudit 0.7.0

The separately requested double-clickable Protected Mode edition without an audit prerequisite is documented in [Student NoAudit 0.7.0](STUDENT_NO_AUDIT_0_7_0.md). The audit-required builds below remain historical and unchanged.

## Previous build — Student 0.6.3

See [Student 0.6.3 investigation and validation checkpoint](STUDENT_0_6_3_VALIDATION.md) for the current EXE, hash, supported features, prepared profile and remaining approvals. The previous native fixture failed after 43 passing checks; the corrected build has passed non-native checks only. Do not reuse earlier audits.

## Historical consent fix — Student 0.6.2

Current EXE: `C:\Users\kuten\Desktop\proctoring-main\dist\LocalProctoring-Student-0.6.2.exe`

SHA-256: `15b70f9d04537856bd2e55b81cdea00b61824e0bbbbbc109f10905e05760dad2`

0.6.1 omitted the WebSocket transport from its pinned package environment. Consent stayed checked locally while its connection thread failed before sending it. 0.6.2 bundles websockets==15.0.1, checks that import during packaged startup, and reports a missing transport clearly instead of waiting indefinitely. Teacher server restart is unnecessary.

Verification: 46 focused packaging/transport tests, 50 teacher live/API tests, desktop production build, exact package-file hashes, and the actual frozen read-only startup check passed. The transport test exchanges real synthetic loopback acknowledgements for consent versions 3, 4 and 5. No real native audit or exam ran for this build.

A fresh profile is prepared on D: to preserve the older unfinished attempt and avoid the low-space C: drive. Launch only after separate native-audit approval with `build/consent-fix-0.6.2/launch-student.ps1 -ApprovedRecoveryAudit`; do not double-click the EXE into the old default profile. The script uses separate local recovery storage, Electron profile and temporary directory, checks the EXE hash, and restores the shell environment when it exits. Source/build changes invalidate earlier audits. Protected fixture and real exam remain separate approval checkpoints.

Details: `build/consent-fix-0.6.2/DIAGNOSIS.md`, `preparation.json`, and test/build logs. Earlier releases, audit history and saved attempts remain unchanged. Regenerable compiler files were moved to `D:/LocalProctoring-Builds/consent-fix-0.6.2` for space.

---

## Historical 0.6.1 implementation record

# Protected student portable EXE and teacher PIN

## Current status

The 0.6.1 portable Windows x64 EXE implements automatic recovery validation before Join and accepts only Protected Mode teacher exams. **Implementation and non-native verification only: this artifact has NOT passed a real packaged native recovery audit, protected shortcut fixture or protected exam. Do not double-click it until the first native test is separately approved: startup now automatically runs that test when needed.**

Artifact: `dist/LocalProctoring-Student-0.6.1.exe`. Exact hashes are recorded below and in `build/student-auto-audit/final-identity.json`. Prior EXEs, reports and smoke records remain unchanged. Previous source and 0.5.3 package acceptance do not authorize this build.

## Automatic startup

1. The one-file bootstrap verifies its embedded ZIP, extracts to a stable content-addressed directory, compares the installed inventory to the embedded original and verifies every file. It refuses extra files and unsafe paths. It holds a per-user launch lock and drains the Electron stdout/stderr pipes until actual exit.
2. Electron displays **Checking exam security** in EN/RU/KK using the operating-system locale. A read-only frozen-backend check verifies the trusted configuration, actual extracted executable, Python runtime, resource fingerprint, machine identity and protection policy. It creates no helper, hook, capture or exam.
3. A completed audit and successful launcher receipt are reused only if they match the full portable EXE SHA-256, resource/runtime identity, machine, trusted configuration hash, recovery policy and configured validity period (24 hours). Exactly 21 unique mandatory native checks must pass, with an explicit completed status and suppression disabled. Missing, expired, incomplete or mismatched pre-existing prerequisites trigger a new audit; source reports never qualify.
4. The automatic audit uses the **same corrected foreground `runOwnedAudit` implementation as the source command**, extracted into `desktop/scripts/owned-audit.mjs`. It directly launches the current extracted Electron audit mode, never a recursive bootstrap. The student and audit have distinct instance ownership; the audit holds its own per-user lock even if its parent crashes. A simultaneous second audit is rejected.
5. Progress comes from actual child check records. The screen shows completed checks /21, the current check, expected duration (approximately 2–5 minutes), temporary-window/keyboard guidance and Ctrl+Shift+Alt+Q. Reaching 21 is not treated as success. Both streams remain drained until child `close`; independent backend verification then validates the completed report. Existing exact-owner helper/guardian cleanup and emergency recovery remain unchanged.
6. Only successful validation and process termination authorize Join. Keyboard suppression, focus containment, capture and exams do not start at this stage. Protected Start still requires admission, applicable consent v5, device/reference/calibration readiness, current recovery prerequisites and verified helper/guardian control. Emergency registration precedes hook installation. The active shortcut fixture never runs automatically.

## Failure, retry and history

Before starting a child, startup writes an incomplete receipt. Failure, cancellation, crash, EPIPE, report mismatch or unsuccessful exit blocks Join. There is no automatic retry in the same launch. On reopening after an interrupted or failed attempt, the operator must address the cause and explicitly confirm Retry; Close is the default. Closing the progress window requests safe audit cancellation and waits for its existing owned cleanup. It does not blanket-kill Electron/Python or unrelated processes.

Per-user paths:

- `%LOCALAPPDATA%/LocalProctoring/Portable/builds/<24-character archive digest>/app`: verified extracted resources.
- `Portable/student-launch.lock`: held until the student child exits. `Portable/last-launch.json`: child exit and output counts.
- `%LOCALAPPDATA%/LocalProctoring/Student/config-<runtime-path digest>.toml`: exact per-build defaults, preserving older configurations. Even an explicit packaged config must match trusted defaults.
- `Student/audits/history/<identity digest>/<timestamp>-<UUID>.json`: immutable original audit attempts, with `.launcher.json` diagnostics. A failed or pending report remains evidence of failure, never authorization.
- The history directory's `receipt.json` is mutable startup state, preserving the first launcher failure for that attempt. `Student/audits/startup-current.json` is a replaceable prerequisite copy; historical reports and the previous manual `electron-recovery.json` are not overwritten.
- `Student/sessions` and the existing DPAPI connected journal remain outside extraction/temp. No failed audit deletes evidence. Unfinished attempts from another distribution remain blocked and preserved for recovery using their original build.

A changed EXE, extracted runtime, backend, configuration, protection policy or machine invalidates reuse. Expiry also requires a new check. No previous audit was reused or regenerated during this implementation.

## Teacher policy and supported features

The trusted packaged host requires Connected and Protected Mode. Unprotected teacher admissions fail with an EN/RU/KK explanation; there is no student toggle or silent policy conversion. Separate source development workflows retain Unprotected Mode.

Teacher profiles still govern detection timing/categories, microphone monitoring, audio evidence and snapshots. Consent v5, real evidence upload, screen viewing, commands and PDF synchronization remain the existing implementations. **Optional DeepFace identity/liveness is not bundled in this edition**; exams requiring it are rejected. Source optional DeepFace support is unchanged. No model downloads occur at startup.

## Teacher PIN trust model

PIN scope is **teacher**, shared by that teacher's exams. Dashboard **Security → Protection PIN** provides initial set/change, confirmation, last update and EN/RU/KK feedback without displaying the stored PIN. Changes require the existing authenticated teacher cookie, trusted Origin and CSRF. A stale settings revision fails with 409. Accounts cannot select another teacher's PIN row.

SQLite stores a unique salted scrypt verifier (N=32768, r=8, p=1, 16-byte salt), revision and timestamp. PINs are 6–12 ASCII digits. Neither plaintext nor verifier is returned in policies, profiles or status. Audit logs record action/revision/outcome, not the PIN.

Connected pause/resume/end requests are asynchronous in Python, leaving the control heartbeat responsive. Each request fetches the current revision and verifies against the owning teacher through the admitted attempt's authenticated origin/credential. The response is bound to an action and fresh nonce; it is not a reusable bearer token. The client accepts it only within five seconds, consumes the action once on the controller thread and ignores ended sessions. The server compares revisions transactionally; changes invalidate earlier revisions. Rotation does not retroactively undo an already authorized action. No PIN/authorization is persisted in the durable journal.

Server verification is limited to ten syntactically valid requests per teacher per fifteen minutes, including successes, across attempts. Wrong-PIN attempts commit their rate-limit/audit records before returning failure. This bounds guessing but can temporarily deny a teacher's privileged actions if students abuse it; emergency release remains independent. Low-entropy PINs are not strong offline secrets even with salted hashing, so client-side verifiers are not distributed.

Connected PIN actions fail closed offline. There is no automatic local-PIN fallback for connected exams. Explicit standalone development retains its host-managed local PIN verifier; it is not a competing connected PIN system. Blank packaged local PINs never authorize. Ctrl+Shift+Alt+Q remains independent of both PIN and network.

## Build and non-native verification

Build from the pinned package environment; use fresh artifact names:

```powershell
cd C:\Users\kuten\Desktop\proctoring-main\desktop
npm.cmd run build
cd ..
build\student-package-venv\Scripts\python.exe scripts\build_electron_windows.py --student --use-built-ui --output dist\LocalProctoring-Student-NEW-UNVALIDATED
build\student-package-venv\Scripts\python.exe scripts\build_student_portable.py dist\LocalProctoring-Student-NEW-UNVALIDATED.zip dist\LocalProctoring-Student-NEW.exe
```

This build regenerates the backend and UI from current sources. The bootstrap remains unsigned; internal Electron app metadata is legacy 0.4.0, so hashes identify the actual build. The archive includes pinned dependency/model hashes and THIRD-PARTY-NOTICES; existing YOLO/Qt and other license obligations apply. Do not disable Windows security tools.

Targeted results are recorded in `build/student-auto-audit`:

- 194 Python tests passed: mocked startup report validation, missing/expired/different/incomplete/failed audits, trusted config enforcement, duplicate launch lock, package integrity, Protected-only admission, prior evidence preservation, native ownership/release invariants and output-failure rejection. Native APIs and helpers were mocked.
- 23 startup/IPC/shutdown/output-lifecycle Node tests passed; results are in `node-tests.log`. Synthetic Node children test stream draining, exit/cancellation and no authorization before close. Startup runner dependencies are mocked; no Electron audit runs.
- Current desktop production build/typecheck passed.
- EN/RU/KK static startup screens rendered and visually inspected with no overflow; these used headless Edge, not Electron or native input.
- Safe frozen-backend/package checks and final identity are recorded alongside the build logs. No normal student launch smoke is performed, because it would now automatically request real native input observation.

## Remaining approval checkpoints

After separate approval, launch this exact EXE once on the local keyboard with other work saved and remote control disconnected. Its automatic 21-case recovery audit must pass with a complete matching report, successful exit and no owned audit/helper/guardian processes remaining. Confirm normal typing and Alt+Tab. Stop on any unexpected error; preserve diagnostics and do not retry automatically.

Then request separate approval for the existing active protected-shortcut fixture. After it passes, request Ready before a real protected exam. Verify fullscreen, Alt+Tab/Alt+F4, teacher PIN pause/resume, real camera/microphone, snapshots/audio playback, viewing/commands, normal submission/PDF receipt, emergency release and restored input. None of these physical gates is claimed passed for 0.6.1.

## Final artifact identity

- artifact: `C:\Users\kuten\Desktop\proctoring-main\dist\LocalProctoring-Student-0.6.1.exe`
- exe_sha256: `72bb5131fcc7a7d76451b357f97e62565231d429dc1be385a5ebb0d9a9a911e9`
- bytes: `339146862`
- archive_sha256: `7d92edfdfabc269da3305bb4ab90911d3a107169e5881ead505beb471e7ddf55`
- renderer_build_id: `ea70b96a0428f7b09c6f810ab2ab181ec04946723c72d4f5aa749d58c5a4b249`
- packaged_resource_fingerprint: `88ae8855ff4937ccb9b6ea5b09d9ffc89908e2fb6feb0865b1986a53a8e3e5e0`
- inventory_sha256: `14f66829952f93a6662c6fcc2c19d7307975164d97e317435f3573390d642e16`
- default_config_sha256: `491df359016dc97ff3cbead125b53380259a920ab4f18bdb53c25a5e8a1b8540`

Final safe checks passed: complete inventory hashes, embedded payload equality, latest desktop artifact identity and actual frozen read-only verifier exit 0 with missing audit rejected. No normal EXE launch or native audit occurred.

One intermediate rebuild exhausted disk space; the error log is retained. Only disposable artifacts generated in this implementation were removed. Final EXE and ZIP remain in dist; the unpacked build copy and temporary compiler output were removed after verification to leave space for first-launch extraction. Earlier releases, audits and evidence were not changed.

