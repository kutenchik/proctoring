# Student 0.6.3 — investigation and validation checkpoint

## Current status

The new portable EXE is built and non-native checks passed. It has **not** passed a native recovery audit, protected shortcut fixture, or real exam. Do not reuse 0.6.2 reports. A new native recovery audit requires operator approval, followed by separate approval for the shortcut fixture, then Ready before a real exam.

EXE: `C:\Users\kuten\Desktop\proctoring-main\dist\LocalProctoring-Student-0.6.3.exe`

SHA-256: `a3b6435b02cd56b354598e3a252ab4407c8e9387a9edb6f4c5119b93caba7727`

Desktop build identity: `02896c0358558e4fa5c1749a39bfaa64c3873689b2a763cfb7568a858aa9edcf`

## What the investigation established

The original 0.6.2 recovery audit completed 21/21 and exited successfully. Its separately approved shortcut fixture passed 43 checks, then failed `maximum_lease` with “Maximum lease was not the release cause”. Remaining checks were not run. All owned processes exited and the operator confirmed normal input. Original reports remain unchanged in `build/consent-fix-0.6.2/protected-fixture-01` and the isolated profile's audit history.

The old maximum-lease scenario created a new fixture and armed it without requesting and independently verifying foreground ownership. Its error omitted the actual native/public release reason and timestamps. Thus the original physical cause cannot be reconstructed from that report. Foreground containment failure, lost control progress, and status classification were investigated as alternatives; none can be declared the proven historical trigger.

A deterministic reproduction extracted that exact scenario into `maximum_lease_check.ts`. Before correction, three tests failed: missing foreground preparation could produce the same competing-release symptom, an error dropped the actual cause, and a failed foreground prerequisite did not prevent arming. After correction all passed. This demonstrates fixture defects, not proof that focus caused the original run.

The corrected case requests foreground, verifies it through the exact retained native binding using a read-only private endpoint, and only then arms a two-second lease. Failure to acquire focus stops before arming. It still requires `lease_expired`, all native restriction flags false, and the existing real ordinary-input probe. A different release remains a failure and now records fixed diagnostic fields. Native release policy, guardian, emergency shortcut, ownership validation and consent gates were not weakened or changed.

Deterministic tests against the real helper state machine showed that healthy presentation progress permits the two-second maximum lease to expire and that a competing foreground release remains the first reason through later status polls. No keyboard hooks or native fixtures were used for those tests.

## Admission and consent

The 0.6.2 consent fix is retained: `websockets==15.0.1` is pinned and bundled, its actual client import is checked before packaged Join, and missing transport is an explicit error rather than silent worker death. Synthetic real-loopback WebSocket tests verify consent acknowledgements for versions 3, 4 and 5.

The EXE supports teacher address verification, exam-code admission, immutable student identity, teacher monitoring configuration, policy-derived consent, teacher-managed PIN actions, screen viewing/commands, event snapshots, audio evidence, and report synchronization. These workflows have automated coverage; complete physical behavior is not certified by those tests. Device use and Start still require their normal gates. Startup reuses only a valid matching audit; missing, expired, changed, incomplete or crashed audits cannot authorize Join. It never automatically runs the active shortcut fixture.

This edition does not bundle optional DeepFace identity/liveness. Teacher exams requiring them are rejected, not silently downgraded. Audio evidence is available when the teacher enables it and the matching consent is acknowledged. Localhost HTTP is supported for literal loopback; remote servers require trusted HTTPS. Only Protected Mode exams are accepted.

One older teacher-command test assumed synchronous local PIN verification. It was updated to simulate the current asynchronous teacher authorization, wait for its result, and assert proctor pause before testing teacher resume. Production PIN behavior was unchanged.

## Verification

- 398 distinct Python tests passed across protection/helper, fixture, packaged startup/build, connected admission, consent, teacher policy/PIN/live controls, audio evidence and workflow suites.
- 22 distinct Node tests passed for fixture assertions, connected IPC/state, and automatic startup audit gates. The regression was observed failing before correction.
- Desktop TypeScript and production build passed.
- 810 packaged inventory files matched hashes; packaged and current desktop identities matched; embedded EXE payload matched the ZIP and payload manifest.
- Actual frozen read-only startup preflight imported the WebSocket transport, verified the package, and rejected a missing audit. A separate frozen check rejects the old build's audit.
- Fresh Windows DPAPI journal and ConnectedClient initialized with no saved attempts and no storage errors. No network admission, camera/microphone, or native protection test was performed.

Server audio tests needed the already-installed student test dependencies appended to the server interpreter's search path. No server environment packages were installed or changed. The initial missing-dependency collection failure and obsolete PIN test were resolved before the final passing runs. One upstream Starlette deprecation warning remains.

## Prepared launch

Use the prepared isolated profile for this machine so unfinished earlier attempts stay intact. The latest EXE is standalone on a clean Windows profile; it does not require Python, Node, or configuration editing.

After explicit approval for one native recovery audit:

```powershell
cd C:\Users\kuten\Desktop\proctoring-main
.\build\student-0.6.3\launch-student.ps1 -ApprovedRecoveryAudit
```

The launcher verifies the exact EXE hash, refuses overlapping student processes, uses `D:\LocalProctoring-Builds\student-0.6.3\profile` for isolated application storage/profile/temp, retains the foreground owner until exit and restores its environment. It does not join an exam or activate devices. A new default-profile double-click could encounter an old unfinished attempt, so use this prepared profile for the approved validation.

Other artifacts: `build/student-0.6.3/verification.json`, `frozen-preflight.json`, `old-audit-rejected.json`, `package-build.log`, `portable-build.log`. Verified unpacked resources are preserved at `D:\LocalProctoring-Builds\student-0.6.3\package`. Three older unpacked 0.5.x build copies were moved intact to `D:\LocalProctoring-Builds\preserved-before-0.6.3` to free C: space; existing EXEs, ZIPs, audits and student evidence were retained.
