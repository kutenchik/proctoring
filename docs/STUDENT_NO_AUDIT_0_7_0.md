# Protected student EXE without recovery-audit requirement

The user explicitly selected keeping Protected Mode keyboard restrictions while removing the recovery-audit prerequisite. This is a separate edition; standard builds still require recovery validation by default.

EXE: `C:\Users\kuten\Desktop\proctoring-main\dist\LocalProctoring-Student-NoAudit-0.7.0.exe`

SHA-256: `1b871fab9eeee76326c1d4f8e7e35f9094a71ff0c72127984c78c471553d4c48`

Desktop identity: `479aecd0f88fd780866847b66c9659ee82af06886d71879b91d599971554a450`

The trusted packaged configuration explicitly enables protection and Connected Mode and sets `require_recovery_audit=false`. The startup verifier still checks package and config integrity but does not read/run an audit. No fake passing report or audit receipt is generated. Native preparation and Start still require verified resources, exact host binding, fresh control progress, guardian and emergency release; other device, teacher policy/PIN and consent gates remain. The two-second diagnostic fixture correction from 0.6.3 is retained but no fixture or real exam ran for this edition.

The bootstrap's embedded `profile_name=protected-no-audit` selects stable separate Local/Roaming storage under `%LOCALAPPDATA%\LocalProctoring\Editions\ProtectedNoAudit`. The EXE manages that automatically on double-click. Old profiles, audit reports and unfinished attempts were not deleted or migrated. The observed `secure_storage_unavailable` screenshot was reproduced as a mislabeled old-build attempt conflict: read-only examination decrypted the existing journal and found one unfinished attempt from another distribution. That conflict now receives a distinct error, and the separate edition starts with its own profile.

Validation: 218 distinct focused Python tests and 13 Node tests passed. This covers no-audit startup, normal default-audit behavior, resource changes, control progress, emergency release, guardian ownership, teacher policy/PIN, consent, packaged configuration and profile separation. TypeScript/renderer/main production build passed. The actual frozen backend verified 810 packaged files and returned `audit_required=false, valid=false` with a nonexistent report path: startup is permitted by explicit policy, not an invented successful audit. The final EXE's embedded archive, inventory and profile metadata were checked against its release archive. No app was launched and no native input restrictions were installed during these checks.

Build evidence: `build/student-no-audit-0.7.0/verification.json`, `frozen-preflight.json`, `package-build.log`, `portable-build.log`. Unpacked resources and release ZIP are preserved under `D:\LocalProctoring-Builds\student-no-audit-0.7.0`. Completed compiler caches were moved there to leave room for first-launch extraction.

Usage: double-click the EXE, verify the teacher URL, enter the exam code and identity, and complete normal consent/readiness. Keep teacher services running. Use a valid Protected Mode exam code; this EXE does not reset previous server attempts. Optional DeepFace identity/liveness remains unavailable in this portable edition; incompatible teacher policies are rejected. Real protected exam behavior has not been physically certified by the automated checks. Emergency release is Ctrl+Shift+Alt+Q.
