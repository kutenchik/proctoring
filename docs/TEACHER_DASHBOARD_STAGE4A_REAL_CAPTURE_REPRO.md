# Stage 4A — isolated real-capture fixture preparation

> Current policy update (2026-10-14): [Stage 4A webcam-visible follow-up](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_FIX.md)
> supersedes masking and consent-v1 implementation details below. Historical test results
> remain unchanged. Webcam-visible sharing requires new consent v2. No new physical test has run.


14 October 2026. **Historical preparation report. One separately authorized real
run has now completed; see [the result report](TEACHER_DASHBOARD_STAGE4A_REAL_CAPTURE_RESULT.md).
The command below is not authorization for another launch.**
The physical failure and its exact guard operand remain unresolved. No production
fix, geometry recovery or privacy-check relaxation was added in this task.

## Prepared fixture

Sources: `desktop/tests/fixtures/real-capture/`; build-only command:

```powershell
cd desktop
node scripts/prepare-real-capture.mjs
```

The standalone output is `build/stage4a-stream-fix/real-capture-fixture/main.cjs`.
Its real mode calls the actual Electron `desktopCapturer.getSources` through the
existing production `captureExamMonitor`, with its unchanged geometry checks,
preview masking and encoding. It has a synthetic student-like window and fixed
synthetic preview rectangle, but no Python, backend, exam, teacher account, API,
WebSocket or WebRTC dependency. Camera/microphone/device permissions and network
requests are denied. It installs no protection, blocking or global keyboard hooks.

The preparation build inserts observation calls into its own bundled copy of the
production capture/geometry modules. Original source files are untouched. The
hooks record the exact local values used by each guard, without extra native
geometry reads or awaits. Build preparation fails if an insertion anchor changes.
`build-identity.json` records original source hashes and bundle dependencies.

Each attempt retains all four guard probes (including successful checks), before/
after timestamps, content bounds, zoom, display identity/geometry, focus/maximized
state, up to 16 native events, and source match count/dimensions. Initial/final
mask samples contain only bounded numeric rectangles. If an awaited API rejects
before a guard executes, its sanitized error code and last completed probes are
retained; no nonexistent guard result is invented.

Only one capture can be in flight. No frames go to the renderer, network or disk;
the returned encoded buffer is cleared and released. The recorder retains at
most 12 attempts, four guard probes and two mask samples per attempt, one frozen
first failure and four secondary codes. Serialized evidence is capped at 512 KiB.
`first-failure.json` is written exclusively before cleanup; existing run directories
are rejected. There is no restart button or automatic retry after a rejection.
Even a production transient-mask discard stops this diagnostic experiment, and
is explicitly marked `terminal_in_production=false` rather than misrepresented.

## Proposed experiment — requires new explicit permission

Do not execute until the operator authorizes this isolated real-monitor run:

```powershell
# From repository root, AFTER authorization; use a new output directory.
& .\desktop\node_modules\electron\dist\electron.exe .\build\stage4a-stream-fix\real-capture-fixture\main.cjs --operator-approved-real-capture --output C:\Users\kuten\Desktop\case3_proctoring\build\stage4a-stream-fix\real-capture-run-01
```

The launch approval flag alone does not start capture. The operator must also
check the in-window monitor-consent checkbox and press Start. Arrange the window
before starting; do not intentionally resize/move it for this interaction test.

| Scheduled phase | Duration |
| --- | --- |
| Countdown, hands off | 5 seconds |
| Window untouched | 30 seconds |
| Click ordinary background inside the window | 20 seconds |
| Click different synthetic buttons/toggle/selector | 20 seconds |
| Scroll inside the window | 20 seconds |
| Switch focus away and back | 20 seconds |
| Interact with another Windows application | 20 seconds |
| Return focus and click/scroll | 20 seconds |

The schedule totals 155 seconds, with at most four capture attempts per second
and 750 attempts as an additional bound. A pending native call has a 10-second
watchdog; on timeout, numerical evidence is saved and the owned window closes.
A final in-flight call can extend the schedule by up to that watchdog interval.
Stop or close is available at any time. Phase labels are scheduled prompts, not
proof that the operator performed each action; confirm actual actions separately.

On the first rejection: save the original code/guard comparisons, stop capture,
and inspect the evidence. Do not restart or implement a workaround. A timeout is
reported as a fixture timeout, not a geometry diagnosis. Successful capture counts
are not delivered teacher-viewer FPS; this fixture has no viewer transport.

If this real-capture experiment does not reproduce the failure, propose ONE short
unprotected full-application test and obtain separate permission before starting
it. No such test is authorized or launched by this preparation.

## Preparation verification

- Five recorder unit tests passed: approval/consent, countdown, bounded histories,
  single-flight behavior, first-failure retention, deadline/stop races and transient
  classification.
- Mock-only Electron integration passed: zero capture calls before consent,
  all four production guard probes, numeric mask samples, a deliberate synthetic
  missing-mask failure, preserved first failure, no restart and window cleanup.
- Desktop typecheck and standalone fixture source build passed.
- The first mock driver used an asynchronous page predicate that returned too
  early; it was corrected to await the actual main-process counter. Final tests
  assert a completed mocked capture before proceeding.

Logs and mock-only results: `build/stage4a-stream-fix/real-capture-preparation-tests/`.
No actual desktop capture, physical devices, full suites, protected tests,
packaging, service restarts, public deployment or Stage 4B were performed.
At preparation completion, execution was pending operator permission. The later
authorized run and its physical evidence are documented in the separate result report.
