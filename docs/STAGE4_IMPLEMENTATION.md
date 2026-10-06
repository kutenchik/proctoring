# Stage 4 implementation inventory

| Files | Change |
|---|---|
| `security/settings.py`, `config.py`, `config/default.toml`, `config/protected-demo.toml` | Validated safe-default/explicit-demo settings and recovery-audit path |
| `security/protection.py`, `security/__init__.py` | Extended adapter interface and safe/Windows factory |
| `security/windows.py` | Parent IPC client, validation gate, UI-only heartbeat, bounded release and owned-helper termination fallback |
| `security/helper_process.py` | Retained Windows process handle for the verified hook owner, including virtual-environment launcher children |
| `security/helper.py` | Separate process, message pump, parent handle, monotonic lease, EOF recovery and independent loop sentinel |
| `security/policy.py` | Pure shortcut/modifier/deduplication/allowlist/watchdog policies |
| `security/win32_backend.py` | Windows low-level hook, global emergency hotkey, exact-PID foreground allowlist and best-effort focus restoration |
| `security/validation.py` | Machine/source/version/age-bound native recovery prerequisite |
| `controller.py` | Session activation gates, security journal/review/summary records and recovery termination |
| `ui/window.py`, `__main__.py` | Fullscreen containment, PIN-safe close, status indicator and release-first cleanup |
| `scripts/validate_protection.py` | Audit-only independent native recovery tests |
| `scripts/test_windows_protection.py` | Five-second-lease real shortcut tests in an owned temporary window |
| `scripts/test_protected_session.py` | Native application lifecycle/containment rehearsal with real protection, a fake camera and deterministic exam clock |
| `tests/test_windows_client.py`, `test_windows_backend.py`, `test_protection_policy.py`, `test_helper_state.py`, `test_recovery_validation.py`, `test_protection_integration.py` | Deterministic policies, client/gate, native-release failures, lifecycle, evidence and Qt containment checks |
| `README.md`, `docs/STAGE4_TEST_MATRIX.md` | Launch instructions, limitations and verification distinctions |
| `pyproject.toml` | Stage 4 package metadata (version 0.4.0); no new runtime dependencies |

Paths in the first column are relative to `src/proctoring/` unless they name
`config/`, `scripts/`, `tests/`, `docs/` or `README.md`.

The helper contains no exam/session logic. The existing session controller owns
timer and pause reasons. Security events are immediate records merged only at the
presentation/evidence layer; the CV threshold/hysteresis engine is unchanged.
No PIN is sent to the helper or included in evidence. No process killer,
continuous recording, cloud service, new AI feature or system-policy modification
was added.

Windows references supporting the implementation limits:

- [LowLevelKeyboardProc](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc): callbacks must remain fast; Windows may remove timed-out hooks. Modifier transitions are tracked instead of querying asynchronous key state inside callbacks.
- [SetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow): Windows restricts focus activation, so containment is best-effort.
- [RegisterHotKey](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey): the independent helper registers the emergency chord before installing suppression.
