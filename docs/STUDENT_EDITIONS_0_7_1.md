# Student EXE editions 0.7.1

The release contains matching Windows x64 Protected and Unprotected portable EXEs built from the same source revision and desktop bundle. Both use Connected Mode, teacher admission/configuration, current consent, event snapshots, audio evidence and report synchronization. The Protected edition is the explicitly requested **no-recovery-audit** variant. The Unprotected edition does not construct native protection during normal exam operation.

## Differences and preserved behavior

| Setting | Protected | Unprotected |
| --- | --- | --- |
| Trusted host `protection.enabled` | `true` | `false` |
| Trusted host `require_recovery_audit` | `false` | `false` |
| Teacher exam mode required | `protected` | `unprotected` |
| Portable profile identifier | `protected-no-audit` | `unprotected` |
| Local profile directory | `Editions/ProtectedNoAudit` | `Editions/Unprotected` |

The frozen client rejects mismatched teacher exam modes. An Unprotected package cannot accept a Protected exam and silently downgrade it. The public default and alternate template inside each package both use that edition's mode. Startup verifies the exact trusted configuration and shipped runtime files; skipping the audit does not create an audit report or mark one valid. Audit-required source/older editions retain their existing verification path.

Consent acknowledgement, secure local recovery storage, ownership and file-integrity checks remain in place. The Protected edition retains live progress, guardian/watchdog and emergency-release behavior. Profiles are stable across restarts and separate between editions; updating during an unfinished attempt remains blocked. No saved attempts or evidence were removed during preparation.

## Verification

- 224 focused Python checks passed: 223 in the main batch plus the added unprotected start/submit test. Coverage includes mode matching, separate profiles, startup audit policy, package tampering, consent transport, connected workflow and existing protected lifecycle behavior with injected native adapters.
- 13 desktop Node tests passed for startup and connection state, including audit cancellation/failure paths and no-audit startup.
- 16 teacher API tests passed for configuration profiles, audio evidence and teacher PIN handling.
- Student and teacher production builds/type checks passed.
- Each EXE's embedded ZIP/hash/profile metadata was checked. Every packaged inventory entry was hashed; each frozen backend ran its read-only startup integrity check with a nonexistent audit report.

Exact artifact hashes, sizes, desktop build identity and inventory counts are in the release's `VERIFICATION-0.7.1.json` and `SHA256SUMS.txt`. These do not claim a native audit or physical exam passed. No new camera/microphone session, keyboard hook, recovery audit or protected shortcut fixture was launched for this release.

Known limits: unsigned EXEs; optional DeepFace identity/liveness not bundled, and policies requiring those features are rejected. Vite reports its existing bundle-size/config-loader warnings; the teacher tests report an existing Starlette test-client deprecation warning. A physical end-to-end test of these exact artifacts remains unperformed.

## Rebuild on Windows x64

Use the isolated build environment with `packaging/requirements-electron-build.lock`, the pinned desktop npm lock, and model files matching `scripts/build_electron_windows.py`. The builder checks dependency/model versions and refuses to overwrite an existing package. These commands only build artifacts; they do not launch the app.

```powershell
cd desktop
npm ci
npm run build
cd ..

.\build\student-package-venv\Scripts\python.exe scripts\build_electron_windows.py --student --student-no-audit --use-built-ui --output dist\LocalProctoring-Student-Protected-0.7.1
.\build\student-package-venv\Scripts\python.exe scripts\build_student_portable.py dist\LocalProctoring-Student-Protected-0.7.1.zip dist\LocalProctoring-Student-Protected-0.7.1.exe --profile-name protected-no-audit

.\build\student-package-venv\Scripts\python.exe scripts\build_electron_windows.py --student --student-unprotected --use-built-ui --output dist\LocalProctoring-Student-Unprotected-0.7.1
.\build\student-package-venv\Scripts\python.exe scripts\build_student_portable.py dist\LocalProctoring-Student-Unprotected-0.7.1.zip dist\LocalProctoring-Student-Unprotected-0.7.1.exe --profile-name unprotected
```

Use fresh output names for another build and record its new identities. Public source examples and licenses are included in Git; private configurations, databases, student evidence, local build diagnostics and dependency caches are excluded.
