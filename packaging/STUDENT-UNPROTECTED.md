# Local Proctoring Student — Unprotected edition

Double-click `LocalProctoring-Student-Unprotected-0.7.1.exe`. No console commands, Python, Node or manual configuration are required. First launch extracts and verifies the bundled application. This edition does not run or require a recovery audit.

Enter the teacher server URL, click Verify server, and enter the exam code and student details. The teacher exam must use Unprotected Mode. Protected exam codes are rejected; use the Protected edition for those exams. The supported teacher monitoring configuration is applied after admission.

Accept the required consent, test camera/microphone, capture the reference photo and complete calibration/readiness. The teacher server must acknowledge consent before Start. Event snapshots, audio clips, screen viewing/commands, normal submission and PDF synchronization work as in the Protected edition, subject to teacher settings and consent.

This edition does not activate Protected Mode, keyboard shortcut suppression or foreground containment. Alt+Tab and Alt+F4 remain available. Teacher-managed PIN pause/resume and normal exam controls remain available.

Persistent data is separate from the Protected edition, under `%LOCALAPPDATA%\LocalProctoring\Editions\Unprotected`. Reopening reuses this profile. Do not delete profiles containing unsynchronized evidence or switch builds during an unfinished attempt.

Keep the teacher server and website running. For the same computer use `http://127.0.0.1:8000`; remote servers require trusted HTTPS. Use a valid exam code within its admission period. Optional DeepFace identity/liveness is not bundled; exams requiring these features are rejected.

The EXE is unsigned. Automated checks and frozen package integrity checks are recorded with the release; no new physical exam was run for this build. See PACKAGE-INVENTORY.json and THIRD-PARTY-NOTICES for dependencies and licensing.
