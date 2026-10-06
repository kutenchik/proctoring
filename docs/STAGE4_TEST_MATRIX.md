# Windows protection validation

Real suppression is disabled in the development configuration. The native recovery audit runs the actual Windows helper with `blocking=false`: hooks and the emergency hotkey are installed, but shortcuts are not suppressed and foreground containment is not applied.

Run from the project directory on the demonstration Windows machine:

```powershell
.venv\Scripts\python.exe scripts\validate_protection.py
```

The script creates only its own temporary Qt audit window, PIN dialog, helper processes and parent fixtures. It activates its own window before injecting Ctrl+Shift+Alt+Q and checks the foreground PID immediately before injection. If Windows refuses activation or relevant keys are already held, the check fails without injecting. It never directs input to an existing proctoring application or another user application. PIN entry uses QtTest on the audit's own dialog; no PIN enters the report.

The report is saved to `artifacts/protection-validation.json`. Real protection requires a passing report for the current machine, Python executable and protection/recovery source fingerprint. The report expires after 24 hours by default. This gate is a development safety prerequisite, not an anti-tamper boundary. Re-run after source changes or moving the demo to a different machine.

## Recorded implementation results — 2026-10-04

| Verification | Result | Evidence |
|---|---|---|
| Deterministic unit/Qt suite | **497 passed** | `artifacts/stage4-tests.txt` |
| Independent native recovery audit, suppression disabled | **8/8 passed** | `artifacts/protection-validation.json` |
| Native keyboard suppression and emergency recovery | **14/14 passed; restoration confirmed after every case** | `artifacts/protection-native-tests-final.json` |
| Native application lifecycle/containment, injected camera and exam clock | **9/9 passed; restoration confirmed after every case** | `artifacts/protected-session-tests.json` |
| Dependency consistency | **Passed** (`pip check`) | No broken requirements |
| Physical keyboard and real camera-disconnect rehearsal | **NOT RUN** | Operator matrix below |

The native keyboard cases cover Alt+Tab and its Shift variant, both Windows keys, held Ctrl+C deduplication, Ctrl+V, Ctrl+Insert, Shift+Insert, PrintScreen, Alt+F4, Alt+Esc, Ctrl+Esc, PIN-dialog emergency and emergency during another blocked action. Each case confirms hook/hotkey removal and native Ctrl+C working after release. Ctrl+Shift+Esc and Alt+PrintScreen follow tested policy rules but were not separately exercised with native input.

## Independent recovery audit

| Check | Method | Required evidence |
|---|---|---|
| Normal enable → disable | Native audit helper IPC | Hook and hotkey installed; both removed on disable |
| Emergency shortcut | Windows SendInput to the audit-owned foreground window | Native emergency path releases both hook and hotkey |
| Main graceful exit | Owned Qt parent fixture exits normally | Helper detects parent handle signaled, releases and exits |
| Lost heartbeat | Stop heartbeats for a 0.75-second audit lease | Helper independently releases without the UI event loop |
| Main crash | Owned Qt parent fixture calls `os._exit(23)` | Helper detects parent death, releases and exits |
| Repeated enable/disable | Five native cycles | No hook/hotkey remains after each cycle; subsequent cycle can register again |
| PIN dialog | Native same-process dialog, QtTest entry, native emergency injection | Wrong PIN rejected, valid PIN accepted; emergency works with dialog open |
| Missing release acknowledgement | Production client, audit-only hook, simulated unavailable disable reply | Retained hook-owner handle signals exit before release returns; a new helper can register/release the emergency hotkey |

These are automated native checks. They do not substitute for physical keyboard testing or verify that every target machine permits suppression or foreground activation.

The final-source result and generation time are recorded in `artifacts/protection-validation.json`. The audit runs in the interactive Windows desktop, with suppression disabled throughout. A sandboxed attempt correctly refused emergency/PIN key injection when Windows did not activate the audit-owned window; the interactive-desktop run exercised those input paths. Normal releases confirm `hook_installed=false` and `hotkey_registered=false`; forced release confirms the actual hook owner's process handle is signaled. Regenerate this report after source edits; the production gate checks the current source fingerprint.

## Automated native suppression checks

After the independent recovery report passes, `scripts/test_windows_protection.py --run` exercises transient real suppression against its own temporary test window. Every enabled interval has an independent five-second maximum lease. The harness verifies its own foreground PID before native key injection and refuses to inject when relevant keys are already held. Cleanup always releases the helper. After each test that enabled protection, it checks hook/hotkey removal and native copy behavior in its own text field.

This is a separate automated native test suite; it does not fill the physical operator matrix below. The final implementation run is recorded in `artifacts/protection-native-tests-final.json`. Windows can deny test-window activation. Such a refusal must be recorded as an input test not performed, rather than bypassed by directing keystrokes to another application.

## Native application integration

`scripts/test_protected_session.py --run` exercises the actual `MainWindow`, controller and Windows helper, with five-second maximum restriction leases. Camera observations, calibration inputs and exam time are explicitly injected test data; this is not a physical webcam rehearsal.

The nine cases cover fullscreen/minimize/close, proctor PIN end, an owned foreign-process foreground window, simulated 14.9/15.0-second monitoring outages, proctor pause, timer completion, shutdown, and application emergency shortcuts during an active quiz and monitoring pause. Global emergency interception is tested separately by the native shortcut suite. Results are recorded in `artifacts/protected-session-tests.json`.

Each armed case confirms hook/hotkey removal and restoration of the main window's ordinary state. Foreground containment checks require a security event naming the owned foreign PID; focus restoration remains best-effort. The harness verifies the actual interpreter's process ancestry because Windows virtual environments can launch it through a separate redirector process.

## Physical Windows test matrix

Status is **NOT RUN** until an operator records the result on the demonstration machine. Do not infer a physical pass from a deterministic unit test or the audit-only script. Actual shortcut suppression must only be exercised after the independent audit passes.

For every row, record the application version/source fingerprint, result, event log entry, and whether normal Windows controls work after ending the test. Keep a second person ready to use the emergency chord. Do not attempt to suppress Ctrl+Alt+Del or test with unsaved work in other applications.

| Test | Expected behavior during protected exam | Restoration check after release | Current physical result |
|---|---|---|---|
| Alt+Tab (including Shift variant) | Switch suppressed; one event per held key | Alt+Tab switches normally | NOT RUN |
| Left/right Windows key | Start/Win shortcuts suppressed; security event | Windows key opens Start normally | NOT RUN |
| Ctrl+C | Copy suppressed; security event | Copy works in an operator-owned scratch document | NOT RUN |
| Ctrl+V | Paste suppressed; security event | Paste works in the same scratch document | NOT RUN |
| PrintScreen (including Alt variant) | Screenshot key suppressed; security event | PrintScreen behaves normally | NOT RUN |
| Minimize exam | Exam remains/restores fullscreen; security event | Normal minimize works after release | NOT RUN |
| Close exam | Ordinary close cannot bypass proctor PIN | Normal window close works after release | NOT RUN |
| Activate an operator-owned application | Unauthorized-window event; best-effort return to exam | Operator-owned application can be activated normally | NOT RUN |
| Proctor PIN dialog | Dialog belongs to allowed PID; wrong PIN rejected, correct PIN accepted | Dialog and normal keyboard work after release | NOT RUN |
| Emergency: active quiz | Ctrl+Shift+Alt+Q immediately releases restrictions | Alt+Tab, Windows key, copy/paste work | NOT RUN |
| Emergency: PIN open | Same immediate release, independent of modal UI | Same restoration check | NOT RUN |
| Emergency: monitoring paused | Same immediate release without camera dependence | Same restoration check | NOT RUN |
| Emergency: restriction attempted | Emergency has priority over blocked shortcut | Same restoration check | NOT RUN |
| Camera disconnect while protected | Exam/timer pause; protection remains active | End via PIN/emergency restores controls | NOT RUN |
| Monitoring recovery at 14.9 seconds | Automatic resume if no other pause reason; protection remains | End via PIN restores controls | NOT RUN |
| Monitoring recovery at 15.0 seconds or longer | PIN required to resume; protection remains | End via PIN restores controls | NOT RUN |
| Normal completion | Release occurs before evidence finalization | Normal controls work while summary is shown | NOT RUN |
| Normal application shutdown | Helper and hooks released; evidence finalized | Normal controls work after application exits | NOT RUN |

Camera disconnection and recovery rows require real hardware. Exact 14.9/15.0-second boundary behavior is additionally covered with the existing injected monotonic clock in automated tests; a hand-timed cable test cannot measure those boundaries precisely.

## Limits of the demonstration

Windows can deny foreground activation, and secure desktop transitions are outside this application's control. The prototype does not block Ctrl+Alt+Del, kill unrelated processes, change persistent Windows policy, or provide production kiosk isolation. Hook and hotkey resources belong to the helper process; helper termination removes them. The parent handle, heartbeat timeout, global emergency chord and normal release paths are independent ways to end transient restrictions.

Keep the development configuration as the default. Complete and record the physical matrix on the final demonstration machine before describing the protected environment as validated.
