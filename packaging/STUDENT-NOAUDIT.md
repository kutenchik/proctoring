# Local Proctoring Student — Protected Mode, no recovery audit

Double-click `LocalProctoring-Student-Protected-0.7.1.exe`. No console commands, Python, Node, or manual configuration are required. First launch extracts and verifies the bundled application. This edition does not run or require a recovery audit and does not claim that an audit passed.

Enter the teacher server URL, click Verify server, and enter the teacher's exam code and your student details. The teacher exam must request Protected Mode. The app applies the teacher's supported monitoring configuration. Accept required consent, test camera/microphone, capture the reference and complete calibration/readiness. Consent must be acknowledged by the teacher server before Start.

Keyboard restrictions begin only at Start, not on Join. The teacher manages the pause/resume PIN. Emergency release is Ctrl+Shift+Alt+Q. Native ownership verification, file integrity, live control progress, guardian/watchdog release, and normal cleanup remain enabled. Removing the audit requirement does not establish that this build passed a physical protection test.

This edition automatically uses separate persistent storage under `%LOCALAPPDATA%\LocalProctoring\Editions\ProtectedNoAudit`. Older student attempts and evidence remain in their original locations. Reopening this edition reuses its own profile. Do not delete profiles containing unsynchronized evidence.

Teacher-controlled event snapshots, audio evidence clips, screen viewing/commands and PDF synchronization are included. Audio clips require teacher policy and corresponding consent. Optional DeepFace identity/liveness is not included; incompatible exams are rejected. Remote server URLs require trusted HTTPS; literal localhost HTTP is supported.

Keep the teacher server and website running. For a teacher server on this same computer, use `http://127.0.0.1:8000`. An exam code must be valid for a new attempt and within the admission period. The app does not create or reset teacher exams.

This EXE is unsigned. No real protected exam was run during this build. See PACKAGE-INVENTORY.json and THIRD-PARTY-NOTICES for dependencies and licensing.
