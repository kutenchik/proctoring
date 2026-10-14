# Electron protection and Windows distribution — Stage 3

This is a controlled-demonstration prototype. Passing the local recovery audit authorizes a particular runtime to attempt protection; it is neither a gaze-accuracy result nor proof of an unbreakable kiosk.

## Gates and current verification status

The gates are sequential: **3A native recovery without input suppression → 3B bounded protected tests and operator exercise → 3C packaged-runtime validation**. Unit tests and renderer fixtures do not substitute for native or physical checks. A package built before operator validation is **UNVALIDATED**.

| Gate | Required evidence | Status |
| --- | --- | --- |
| 3A | Current-machine Electron HWND ownership, independent release, process failures, cleanup and hotkey re-registration, with suppression/containment disabled | Frozen rc8 source after the release-intent correction: 21/21 passed |
| 3B | Bounded real shortcut/focus tests, actual protected workflow, independent emergency and restored desktop input | Matching rc8 source: 50 native checks passed; 2 production PIN checks explicitly NOT RUN. Final copied-runtime and human workflow checks remain required |
| 3C | Self-contained copied package, separate package audit, real devices/exam/PDF and cleanup | rc8 built, inspected and copied; its native audits and ordinary app/device/operator tests remain pending. rc7 and earlier failed artifacts remain preserved and non-promotable |

## Ownership and process tree

```text
Electron main (verified native exam HWND)
├── trusted React renderer (sandboxed; narrow preload API)
├── external WebContentsView (no application preload/control API)
└── Python supervisor (inherited pipes; retained process handles)
    └── Python/Qt controller backend (session/timer/events/media authority)
        └── native hook helper (separate message loop)
            └── independent guardian process (supervises exact helper handle)
```

The Electron main process sends its HWND as an unsigned hexadecimal pointer and a per-launch random identity over inherited IPC. Python verifies native window ownership, the live ancestor chain, process creation identity and a window property stamp. A destroyed/reused numeric HWND cannot silently replace the registered window. Only explicitly registered exam/dialog HWNDs are foreground-allowed; executable names and arbitrary Chromium PIDs are never allowlisted. React PIN dialogs and the external child view remain inside the registered top-level window. Process supervision is separate from that foreground policy.

The legacy PySide6 adapter keeps its original own-PID checks. A desktop-scoped native mutex prevents overlapping protected helper owners. A failed second binding cannot arm or open media. Cleanup uses verified process handles; it does not terminate unrelated Electron/Python processes by name or stale PID.

## Control progress and recovery

The helper issues one-use monotonic challenges. The trusted React renderer commits a matching session snapshot and acknowledges after a paint opportunity. Electron main validates the sender/main frame, session, snapshot, sequence and freshness. Python forwards progress only from its controller dispatch after a completed domain tick. Preview traffic, status polling and camera/CV worker heartbeats cannot manufacture this receipt. The external exam page has no privileged lease API.

With the public profile, missing control progress expires the helper lease after **5 seconds**, plus scheduling/cleanup latency. A separate guardian supervises actual helper message-loop progress with a **2.5-second deadline**, then terminates only its retained helper handle if necessary. The helper also retains its independent thread sentinel. These bounds must be measured by native tests; they are not hard real-time guarantees under a stalled operating system. Windows does not expose a universal proof that a low-level keyboard hook remains installed and effective.

The independent **Ctrl+Shift+Alt+Q** recovery chord must register before any suppression. If recovery registration fails, arming fails. Native hooks release before pipe acknowledgements, media shutdown, PDF work or remote delivery. Slow cleanup does not add exam time after ending.

Camera/CV loss is different from loss of control progress. Responsive controls keep protection active during a monitoring pause. Monitoring recovery before 15 seconds auto-resumes subject to other pause reasons; at 15 seconds or later PIN recovery is required. Proctor pause remains independent. Optional microphone loss does not pause the timer.

Emergency, helper failure, controller/main/renderer liveness loss or active display-geometry change is a **terminal safety release**, not a recoverable monitoring pause. A reachable backend records the interruption and ends the exam. The same protected session cannot automatically re-arm. If the backend died, preserve the journal; do not invent a successful final summary.

## Protected lifecycle and geometry

Protection is disabled by default. The public `config/electron-protected.example.toml` explicitly requests it, uses a public demonstration PIN and has blank remote credentials. It has a separate Electron validation-report path. Private configs and the legacy published executable are not overwritten.

Requested protection is distinct from actual state: disabled, awaiting audit, preparing, arming, active, releasing, released/fault. **Active** requires the helper's actual acknowledgement. A lost backend connection displays unavailable state rather than claiming continued protection.

An unprotected, normally escapable fullscreen preparation view establishes final native geometry before gaze collection. Start does not silently change geometry and reuse old calibration. It rechecks backend readiness, settled fullscreen geometry, current host binding and current audit, then arms the helper and awaits acknowledgement before starting the session/timer. Failure rolls back; failed calibration is never bypassed.

During the exam, trusted PIN controls remain accessible and the external view is hidden for pause/PIN/summary. A genuine geometry transition invalidates the protected presentation and ends it safely. Physical DPI transitions remain a separate Windows check from simulated browser viewport sizes.

## Existing restriction policy

The existing policy covers Alt+Tab (including Shift variants), left/right Windows keys, Ctrl+C/V, Ctrl+Insert, Shift+Insert, PrintScreen, Alt+F4, Alt+Esc, Ctrl+Esc and Ctrl+Shift+Esc. Deterministic policy tests are not proof of native suppression. Windows secure attention sequences are outside this prototype's scope.

Shortcut and unauthorized-foreground technical actions use existing stable event IDs and repeat suppression; they do not inherit the three-second CV threshold or pause time merely for a warning. Foreground containment is best effort and Windows may refuse foreground activation.

Windows can reject `SetForegroundWindow` even when its documented prerequisites
appear satisfied; this application cannot promise to force other applications
or notifications out of the foreground. See Microsoft's
[SetForegroundWindow documentation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow).
The post-rc3 correction retries only the exact verified exam HWND and checks the
actual foreground result on each helper poll. If containment remains lost for
**1.0 second**, measured by the helper's monotonic clock, it ends protection with
terminal reason `foreground_containment_failed`, releases restrictions and ends
the reachable session. The default 100 ms polling interval and scheduling/cleanup
add latency to that bound. This stops the exam claiming continued protection;
it does **not** guarantee that a notification click is blocked. Native and human
validation of this changed behavior is still required.

The configured clipboard guard runs on Qt's main thread only while the actual protected exam is active (including its ordinary pauses). Queued clipboard callbacks recheck that scope after release. Clipboard contents are not persisted, and deliberately cleared contents cannot be promised restoration. Registration/setup and the post-exam desktop are outside this guard.

## Audit identity

Electron reports use their own schema and require all native scenarios to pass. Missing, failed, expired, future-dated or mismatched audits block arming. Identity includes the current machine, host executable, runtime/build identity, relevant source/artifacts or immutable package files, and protection implementation. A PySide6 report cannot authorize Electron; a source report cannot authorize the packaged process arrangement. No machine's passing audit belongs in a distribution.

Audit fixtures use owned temporary windows/processes and a private inherited control channel. Fault injection is not exposed to normal renderer or remote content. Native key injection must verify the owned window is foreground first; denied focus is NOT RUN/FAIL, not permission to send keys elsewhere. Native scenarios are individually bounded and must demonstrate cleanup/re-registration afterward.

## Distribution constraints

The planned local distribution uses Electron plus a **one-directory frozen Python backend**, with native libraries and models at real filesystem paths outside ASAR. It must run without installed Python, Node/npm, a Vite server, the repository or `PROCTORING_PYTHON`. Build dependencies are installed in an isolated packaging environment from the existing lock; the development environment and lock are preserved.

An explicit allowlist includes public configs, assets/models, runtime libraries, bundled fonts/translations and required license notices. It excludes sessions, selfies, diagnostic exports, private TOML, credentials, cookies, passing audits and Git history. Writable config/session/log/audit paths are separated from immutable installed resources. Ordinary package launch is safe; protected launch still requires a package-specific local audit. No automatic updater, elevation requirement, public release upload or fabricated signing is part of Stage 3.

## Operator checks still required

After a successful non-suppressing audit and bounded tests: registration/devices → microphone calibration → final-geometry gaze calibration → protected Start → shortcut attempts → a real review warning → short and long physical camera reconnection → PIN recovery/end → local summary/PDF → restored Windows controls. Repeat emergency recovery in a separate session. Record actual interruption durations; use deterministic clocks for exact 14.9/15.0-second boundary claims. Repeat the applicable flow from the final copied distribution with a package audit. Do not run the legacy and Electron frontends against the same devices simultaneously.

## Verification record

The first native **source-runtime** recovery audit completed on 13 October 2026 at 09:54:45 UTC: **21/21 checks passed**. Its preserved local record is `artifacts/electron-protection-validation-first-pass.json`; no suppression or containment was enabled. Renderer, main and backend stalls each released at a measured 5.000 seconds since last native-confirmed progress. Observer confirmation for main/backend stalls arrived after their deliberately blocked event loops recovered (6.502 seconds), and is not substituted for the native release timestamp. Independent helper death was observed before cleanup after main death (114 ms), backend death (116 ms) and EOF (112 ms).

Trusted-content/PIN/external-focus emergency, helper suspension, helper-loop failure, replay rejection, overlapping-owner rejection, repeated cleanup and fresh hotkey registration passed. These are owned native fixtures, not human exam validation. Changes to the subsequent protected-test assertions require a new fingerprint-matching audit before Gate 3B; the first-pass file is retained as historical evidence only.

Final rc3 automated results: full Python suite in the isolated locked environment **2,058 passed in 43.12 s**; complete renderer suite **28 passed**; TypeScript suite **33 passed**; separate external-view fixture **10 passed**. The Python record is `build/electron-locked-rc3-regression.xml`. These results do not imply a validated package, physical DPI transition or human calibration accuracy.

After the containment correction and final private observer-bound adjustment,
the frozen source passed **2,087 Python tests in 46.17 s**, **34 TypeScript
tests**, **29 renderer tests**, and **10 external-view tests**. The Python record
is `build/electron-locked-rc4-regression.xml`; the preceding 2,079-test result is
preserved separately. Its fresh non-suppressing **source 3A audit passed 21/21**.
The corrected bounded source 3B run then passed **50 native checks**, with its
**2 production PIN checks explicitly NOT RUN** (52 records, so the fixture's
overall `passed` flag remains false). All **51 post-release native input probes**
passed. The new separate-process foreground test observed the exam HWND restored
after **62 ms**; this does not establish the behavior of an actual notification
when Windows refuses restoration. The human notification/refusal test remains
pending. These results do not change the failed rc3 human containment finding.
The runtime validator also rejected the actual pre-correction rc3 source audit
against the current source identity with `Machine/runtime/build changed since
audit`; the read-only check is recorded in
`artifacts/electron-rc4-stale-audit-check.json`. This is separate from the still
pending audit of the packaged executable.

The second source audit (10:04:14 UTC) also passed 21/21 checks. The subsequent
short-protection run was cancelled after its post-release `KeyA` counter failed;
Shift+Insert also lacked the expected suppression record. Native release was
reported, but the runner did not capture enough delivered-key information to
establish whether the injection/probe or ordinary input was wrong. Exact owned
process cleanup was confirmed after cancellation, and the operator confirmed
normal typing and Alt+Tab. This is a failed run, not a successful protected
workflow. Its local record is `artifacts/electron-protected-first-attempt.md`.

The isolated native external-view regression subsequently passed all **10**
checks, including remote isolation, modal/pause visibility, navigation limits,
media denial, and external-focus emergency routing. This uses a controlled
page and synthetic Electron input; it is separate from native shortcut tests.

The package inspection paths/checksums below describe completed file/build checks. Human operator and packaged native/device results remain separate and must be recorded only after those checks actually run.

The corrected unprotected input probe delivered exactly one physical `KeyA` and
one dedicated `Insert` down/up pair with all modifiers clear, hooks/hotkey absent
and suppression disabled. A prior direct-launch probe correctly refused input
when its HWND was not foreground. The final source recovery audit then passed
21/21 again, followed by **49 native protected checks** on 13 October at
10:23:20 UTC. All 13 existing-policy shortcuts passed in each of three focus
contexts (39 checks). Containment, emergency, independent maximum lease,
renderer loss, suspended helper, main/backend loss and repeated cleanup passed;
**50 ordinary post-release input probes** succeeded. Renderer loss released at
5.000 s since last native-confirmed progress. Wrong/correct production PIN
actions remain explicitly NOT RUN in this fixture, so its overall `passed`
flag intentionally remains false until separately assessed in the real workflow.
Do not reinterpret that report as a completed human test.

A subsequent real source run exposed a release-status defect: repeated normal
`RECOVERY` replies could change an already released public state to `fault` even
though native protection was disabled. The rc3 adapter correction makes matching
normal release replies idempotent while preserving genuine recovery faults; the
automated regression results above include this correction. The final matching
rc3 **source** recovery audit again passed **21/21**, and its bounded protected
fixture passed **49 checks**, with the **2 production PIN checks explicitly NOT
RUN in that fixture**. The separate human source run below covers those controls;
its containment failure prevents treating the overall protected workflow as passed.

### rc3 human source run: controls passed, containment failed

The operator confirmed wrong-PIN rejection, correct-PIN pause/resume and End,
and physical camera reconnection behavior. The durable journal records an
**11.547 s** monitoring interruption followed by automatic resume, and a
**51.906 s** interruption that remained paused until successful PIN entry.
All 82 paused observer samples kept their exam timer unchanged. After End,
209 samples over 216.528 s remained `released`, `enabled=false`, without the
previous duplicate-release status regression. The saved PDF parsed as two A4
pages. This run did not exercise emergency recovery.

The same operator reported a persistent escape by clicking a **Codex
notification**, after which other applications remained usable. That is a
confirmed containment failure despite telemetry reporting `active`. The run
does not authorize package promotion or a claim of successful protected-exam
containment. Sanitized analysis and measurement limitations are recorded in
`artifacts/electron-stage3-source-pin-recovery/ANALYSIS.md`; wrong-PIN rejection
is operator-confirmed, not inferred from state polling. The containment
correction changes the source fingerprint and requires fresh 3A,
3B and operator notification checks. Existing rc3 archives and earlier failed
attempt records remain preserved; they are not silently relabeled as passing.

The package hash bottleneck was addressed without increasing the control lease.
The backend locks the enumerated source/artifact or package files against ordinary
write/delete opens, hashes before helper preparation, and retains verified
handles until app close. Start checks the exact file set, path/handle identity
and current audit freshness rather than re-reading the whole bundle. Changes or
unavailable locks fail closed. This is local build consistency, not protection
against an administrator. On the relocated rc3 package, full capture took
**4.723 s** before helper preparation and subsequent checks **0.108–0.110 s**.
The file-only benchmark retained 793 files and 1,125 file/directory handles;
all handles were closed afterwards. These warmed-disk measurements are not a
cold-disk guarantee. The earlier rc2 result (4.531 s and 0.114–0.130 s) is retained
in `build/electron-package-rc2-benchmark.json` as historical evidence.

## rc3 inspection artifact — UNVALIDATED

- Folder: `dist/LocalProctoring-Electron-0.4.0-stage3-rc3-UNVALIDATED`
- ZIP: `dist/LocalProctoring-Electron-0.4.0-stage3-rc3-UNVALIDATED.zip`
- ZIP bytes: **331,219,065**; unpacked bytes: **807,512,153** in **796 files**.
- ZIP SHA256: `cbc51813e3af6c2e4ae68dceff76ebe3e6f13144ea756b3af26dff0e9351de9a`
- Artifact build ID: `20d5f519e289b3dadb74f2b09accc936b6a6a97830b648b3730d9a67209b940a`
- Immutable package fingerprint: `b8c2d291270d71764572849b83ca668717e3ed8121ad7b88eda522de7e0dcfde`
- Electron **44.7.0**, bundled CPython **3.11.5**, PyInstaller **6.22.3**,
  Qt/PySide6 **6.11.2**, NumPy **1.26.4**, OpenCV **4.11.0.86**,
  ONNX Runtime **1.30.0**, MediaPipe **0.10.32**, sounddevice **0.5.6**.
- Inventory hashes, ZIP CRC, explicit private-data scan and frozen entrypoint
  checks passed. **179 notice files** accompany dependency/model provenance.
- Unsigned by this project. No installer, public upload or signing bypass.

The copied test folder is outside the repository under a TEMP path containing
spaces and Cyrillic characters:

```text
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Проверка rc3 20261013-c4b791a3
```

Its public protected TOML is separate from immutable resources:

```text
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Настройки rc3 20261013-c4b791a3\protected-demo.toml
```

Inspection records are `build/electron-package-rc3-inspection.json` and
`build/electron-package-rc3-benchmark.json`. Five frozen private `--help` routes
completed successfully; missing/unknown entry modes were rejected, and the
short-protection route refused to proceed without its required recovery report.
Copying/building, resource-lock measurements and entrypoint checks are not a
packaged application, device, recovery or exam pass. **All packaged native,
device and operator checks remain pending.** The first inspection package, rc2,
their records and the old release are preserved; their audits cannot authorize
this different build or host executable path.

## rc4 inspection artifact — UNVALIDATED

Built from the final frozen Electron artifacts using `--use-built-ui`, without
rebuilding or changing those artifacts. All earlier distributions and failure
records remain intact. This is an inspection build, not a release approval.

- Folder: `dist/LocalProctoring-Electron-0.4.0-stage3-rc4-UNVALIDATED`
- ZIP: `dist/LocalProctoring-Electron-0.4.0-stage3-rc4-UNVALIDATED.zip`
- ZIP bytes: **331,227,412**; unpacked bytes: **807,521,991** in **796 files**.
- ZIP SHA256: `5b3272f048b031374bb69aba17fe5f1cd8340f717e010a0000ea811f8af43372`
- Artifact build ID: `1ecbee97442d1e52db6f66d8d6ff806f1084e706e71f24709a92bee6d3441a61`
- Immutable package fingerprint: `64c0338c68af8bd498f076b6adedc03e268b3512c9355ad7ccb8705290fafe4d`
- `resources/package-build.json` SHA256: `d4eaba44f51113afe38f6fe869b7fdb1a2d191c51ee56cf9b8380a52c90ff25e`
- `PACKAGE-INVENTORY.json` SHA256: `ea29dce7d006e76bb16cd29e95c2b8e1d89616dbdb97cdd401c304cdf13362e7`
- Frozen backend EXE SHA256: `7ed44233a017ede837ae7e91a684c5298bea9013388a64fa0b403e74bdb98e31`

The original and copied inventory hashes, ZIP CRC and private-data scan passed.
Five private frozen help routes succeeded; missing/unknown entry modes and the
protected-test invocation without a required recovery report were rejected.
The same pinned runtime versions and **179 notice files** listed for rc3 apply.
No camera, microphone, native protection or normal application window was
started during this inspection. The package is unsigned by this project.

The fresh external test copy and its separate public protected configuration are:

```text
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Проверка rc4 20261013-d8157a4c
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Настройки rc4 20261013-d8157a4c\protected-demo.toml
```

After reading the copied inventory, the file-only benchmark measured a warm
full locked hash of **1.702 s**, before native preparation, and subsequent
identity checks of **0.106–0.110 s**. All retained handles were closed afterwards.
This does not guarantee cold-disk timings. Metadata is in
`build/electron-package-rc4-inspection.json` and
`build/electron-package-rc4-benchmark.json`. The manifest SHA256 identifies the
declared file list; the runtime fingerprint also covers the actual immutable bytes.
**Package-specific native audits, device/exam tests and human notification
behavior remain pending.** No source-runtime result authorizes this copy.

### rc4 human source follow-up and shutdown defect

The notification follow-up did **not exercise a notification click**: the
operator reported that a notification arrived but did not appear for clicking.
They completed and submitted all six quiz questions; normal completion and a
one-page PDF were recorded. There was no unauthorized-foreground or containment
failure event in that session. This absence is not evidence that the patch hid
notifications or prevented escape. Details are retained in
`artifacts/electron-stage3-source-notification-rc4/ANALYSIS.md`.

A separate source session exercised **Ctrl+Shift+Alt+Q**. Its durable journal
and summary record `EMERGENCY_RELEASE` and `end_reason=emergency_shortcut` with
**4.235 s** active exam time. The operator subsequently confirmed that normal
controls were restored. The observer's last `active` snapshot preceded closure
and is not the authoritative final state; the durable journal/summary are.
The updated analysis in
`artifacts/electron-stage3-source-emergency-rc4/ANALYSIS.md` and `analysis.json`
records that confirmation, the application's self-closure and the subsequent
JavaScript dialogs. It is not a successful notification-containment test.

After the emergency closed the window, a JavaScript exception surfaced:
`ExternalExam.applyLayout: Object has been destroyed`. A scheduled external-view
tick accessed the destroyed window during shutdown. Successful native release
does not make this application-lifecycle failure acceptable. **rc4 is
non-promotable**; its files and records are preserved. A narrow shutdown-race
and bridge-promise-settlement correction, followed by fresh build/audit/operator
validation, is required before proceeding.

### rc5 correction and final source audit

The narrow shutdown correction is frozen and built. It prevents scheduled
external-view work from touching a destroyed window and settles pending bridge
requests during shutdown. Cleanup still runs when one stop operation fails;
the failure is reported without leaving an unhandled rejected stop promise.
The final corrected artifacts passed **37 TypeScript tests**, **29 renderer
tests**, and **15 owned external-view checks**. Python was unchanged by this
correction; its latest complete locked-environment result remains **2,087
passing tests**, recorded above. These automated results do not replace the
operator's emergency-exit retest.

The fresh non-suppressing rc5 **source 3A audit passed 21/21** at
**16:39:13 +05:00 on 13 October 2026** (`11:39:13 UTC`). Its source build ID is
`cd890a0f065cfb31d6c91b63398f53bebff0ef7450ecece943df5ac8bccecf28`, and its
runtime fingerprint is
`39c35f2ebbda8695533dae6b166b65583465795a9d8e6fd226d4454fe7720ea3`.
The first rc5 source 3B attempt stopped after **41 passes** because Windows
never granted the owned foreign window the foreground. The separate-process
foreground-recovery check therefore remained **NOT RUN**, not passed or a
demonstrated protection failure. Exact owned-process cleanup was confirmed.
The record is preserved as
`artifacts/electron-protected-tests-rc5-foreground-not-run.json`.

An unchanged retry restored the registered exam HWND from the owned foreign
foreground after **63 ms**, but then **FAILED the backend-loss cleanup check**:
the fixture required forced termination. Exact owned-process checks found none
remaining after exit, but eventual cleanup does not turn the failed check into
a pass. The failure is preserved in
`artifacts/electron-protected-tests-rc5-backend-cleanup-failure.json`; the matching
pre-correction source 3A audit is preserved in
`artifacts/electron-protection-validation-rc5-before-fixture-cleanup-fix.json`.
The historical failure's exact cause is **unproven**. Inspection identified
concrete dead-pipe and fixture-cleanup hazards; the narrow private-fixture
correction is built and frozen, without increasing timeouts or changing native
protection. Its **40 TypeScript tests** passed, along with typechecking/build.
The production UI and external-view behavior were unchanged from the preceding
29 renderer and 15 external-view checks.

Three actual **unarmed Electron/Python backend-crash cleanup cycles** exited
successfully in **45, 50 and 57 ms**, with exit code 0 and no forced termination.
No helper, native hook, device, calibration or exam was started in those checks.
Their record is
`artifacts/electron-stage3-audit-cleanup/unarmed-crash-cleanup.json`. These checks
exercise the corrected cleanup path; they do not establish the original failure
cause or substitute for fresh 3A/3B audits. Packaging remains held until those
audits finish. At that stage source 3B was not complete, and neither foreground
fixture result resolved the separate human notification scenario.

After that correction, the final frozen source **3A passed all 21 checks** at
**16:57:51 +05:00 on 13 October 2026**. Its build ID is
`035673e5e0808e5d4e07467cf51d84c89757bc106faabc2b34452250062ca0a2` and runtime
fingerprint is
`473b0b674eed046d8e29c09233a6d89ffa93bab072b5e6d96116fb37a3b2fa57`.
The matching source **3B passed 50 native checks** at **17:00:53.996906 +05:00**,
including backend-loss cleanup. Its **2 production PIN checks remain explicitly
NOT RUN** in the fixture (52 records; overall `passed=false` by design).
All **51 post-release ordinary-input probes** passed, and the separate-process
foreground test restored the exam window in **31 ms**. Both runners exited
successfully and an exact owned-process inspection found zero remaining.
These results authorize building the separate inspection package, not a claim
that its own audits or human workflow have already passed.

The rc5 build used the final frozen Electron artifacts with
`--use-built-ui`, following source review/regressions and fresh source native
3A/3B. The new output is
`dist/LocalProctoring-Electron-0.4.0-stage3-rc5-UNVALIDATED`; earlier packages
were preserved. Inspection checked the allowlist, local model/runtime contents,
inventory hashes, ZIP integrity and private backend entrypoints, then made a
separate copy outside the repository in a path with spaces and Cyrillic
characters. Its editable public configuration stays outside immutable resources.

The copied rc5 runtime must then pass **its own 3A and 3B tests** before the
operator performs the final packaged workflow (real devices, calibration, exam,
PIN/reconnection, saved evidence/PDF and clean exit) and a **separate emergency
recovery session**. The corrected emergency retest is planned there, avoiding
another full source onboarding pass. Source PIN/reconnection results remain
historical evidence, not packaged validation. The rc4 notification scenario was
NOT EXERCISED and remains unresolved until an actual labeled operator test;
absence of a visible notification is not a successful blocking result.

## rc5 inspection artifact — UNVALIDATED

- Folder: `dist/LocalProctoring-Electron-0.4.0-stage3-rc5-UNVALIDATED`
- ZIP: `dist/LocalProctoring-Electron-0.4.0-stage3-rc5-UNVALIDATED.zip`
- ZIP bytes: **331,228,642**; unpacked bytes: **807,530,193** in **796 files**.
- ZIP SHA256: `4ca72faf4dcb48ce88725c10df0e6a49e12748a1e646fd18fd4bfae2d5a9b146`
- Artifact build ID: `035673e5e0808e5d4e07467cf51d84c89757bc106faabc2b34452250062ca0a2`
- Immutable package fingerprint: `7f26eeb1bc02b828b195852e8089b6284f8755ae54eee233cada7b4101c5dc28`
- `resources/package-build.json` SHA256: `d4eaba44f51113afe38f6fe869b7fdb1a2d191c51ee56cf9b8380a52c90ff25e`
- `PACKAGE-INVENTORY.json` SHA256: `856ec7836c6ad5be4faa9958349ab4b82f03675135e6314f823764d0f168d093`
- Frozen backend EXE SHA256: `8a7abdd5e9e4b60ca618b488ed78ba9cea79e8217942db8aa2006a3eb155ac6b`

Original and copied inventory hashes, ZIP CRC and the explicit private-data scan
passed. The same pinned runtime versions and **179 notice files** listed for rc3
apply. Five frozen private help routes exited successfully; missing/unknown
entry modes and the protected-test invocation without its mandatory recovery
report were rejected. These entrypoint checks did not start native protection,
an application window or devices. The package is unsigned by this project.

The copied package and separate editable public configuration are:

```text
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Проверка rc5 20261013-e6793bd2
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Настройки rc5 20261013-e6793bd2\protected-demo.toml
```

That configuration resolves its validation report to `audits/electron-recovery.json`
beside the configuration, outside immutable resources. It retains the public
demonstration PIN **739261** and blank, disabled remote delivery. Its initial
inspection state contains no source or packaged passing audit.

After reading the copied inventory, a file-only benchmark captured the locked
package in **1.698 s** and checked retained identities in **0.106–0.114 s**.
It retained 793 files and 1,125 file/directory handles, then closed every handle.
These are warmed-disk timings, not a cold-disk guarantee. An exact-path process
inspection confirmed zero remaining inspection package processes. Records are
`build/electron-package-rc5-inspection.json` and
`build/electron-package-rc5-benchmark.json`. No camera, microphone, normal exam or
native audit was launched as part of this inspection. Subsequent packaged native
validation is recorded separately below. Previous distributions, failure
evidence and the legacy release remain unchanged.

### rc5 packaged recovery audit failed

The copied rc5 runtime's non-suppressing **package 3A audit failed** at
**17:08:59.814 +05:00 on 13 October 2026**: **20 checks passed**, but
`helper_loop_failure` reported **"Stalled loop cleanup was not confirmed"**.
The original report is the copied configuration's `audits/electron-recovery.json`;
a preserved workspace copy is
`artifacts/electron-package-rc5-recovery-helper-loop-failure.json`.

An exact owned-package process inspection found zero remaining after the audit.
That eventual cleanup does not establish that the stalled-loop check passed.
The initial report did not establish the cause. The later controlled measurements
below support a premature cleanup-confirmation check. **rc5 is not ready for
protected use or promotion.**
Package 3B and normal application/device/operator tests have not been run; the
failed recovery gate prevents advancing to them. The archive, hashes and failed
report remain intact. No replacement build is authorized before evidence,
correction review and a new source/artifact freeze.

### rc5 unchanged-package loop observation

Three non-suppressing observation cycles used the **unchanged rc5 package** and
retained the original helper identity. The command returned the same cleanup
error before both the original retained handle and an independent process
observer confirmed that exact helper had exited:

| Cycle | Audit error returned | Helper exit confirmed | Confirmation after error |
| --- | ---: | ---: | ---: |
| 1 | 2,511.44 ms | 2,558.26 ms | 46.82 ms |
| 2 | 2,400.51 ms | 2,448.58 ms | 48.08 ms |
| 3 | 2,324.96 ms | 2,371.06 ms | 46.10 ms |

Every helper-exit confirmation occurred **before fixture close**, so fixture
cleanup was not used to manufacture the observed release. Independent checks
matched the original PID and creation identity. All six fixture/observer
processes subsequently exited with code 0 without forced termination, and no
owned package processes remained. The record is
`artifacts/packaged-loop-observation-rc5.json`.

These measurements support correcting the audit's EOF/native-exit synchronization
rather than treating its first post-EOF sample as final proof of cleanup failure.
The frozen correction waits within the audit's **existing total six-second bound**,
requires the same verified original helper and strict fault-admission/error
checks, and leaves production recovery timeouts unchanged. It changes only
`src/proctoring/security/electron_audit.py` and its tests; no TypeScript, UI or
immutable package was modified. The full **project `.venv` Python suite** passed
**2,103 tests in 45.17 s**, including **16 new regressions** for this correction,
using `.\.venv\Scripts\python.exe -m pytest -q`. This result is recorded in the
command output, not a JUnit file. It was **not** run in the isolated packaging
environment. That environment's separate complete result remains **2,087 tests
in 46.17 s**, from before these 16 audit-only regressions, in
`build/electron-locked-rc4-regression.xml`.
The **16 new audit regressions also passed separately in the locked packaging
environment** (`tests/test_electron_audit.py`, pytest-reported **0.45 s**), with
zero failures, errors or skips. Their JUnit record is
`build/electron-package-rc6-audit-regression.xml`; the command was
`.\build\electron-package-venv\Scripts\python.exe -m pytest tests/test_electron_audit.py -q --junitxml=build/electron-package-rc6-audit-regression.xml`.
This focused run is not a rerun of the complete 2,103-test suite in that environment.
The prior 40 TypeScript, 29 renderer and 15 external-view results remain
applicable to their unchanged code. Fresh source/package gates are still
pending. The prior source audits are preserved as
`artifacts/electron-protection-validation-rc5-before-loop-observation-fix.json`
and `artifacts/electron-protected-tests-rc5-before-loop-observation-fix.json`.
The rc5 failed package audit is retained
as failed; these diagnostic observations do not retroactively make it pass.
Fresh rc6 output/copy/settings paths were reserved separately. Its final source
gates and subsequent inspection are recorded below; it is not yet authorized
for protected use.

## rc6 correction and source gates

The initial corrected-source 3A attempt could not obtain the owned foreground
for three emergency checks; its non-passing report is preserved in
`artifacts/electron-protection-validation-rc6-foreground-refused.json`.
The subsequent matching source **3A passed 21/21 checks** at
**17:28:10.474723 +05:00 on 13 October 2026**. Its runtime fingerprint is
`8650c259e5af927f9a50389588376ae7a77f0d4d24eb2333878eaceed77dc67d`.
The compiled Electron build is unchanged:
`035673e5e0808e5d4e07467cf51d84c89757bc106faabc2b34452250062ca0a2`.

The first source 3B attempt likewise refused Alt+Tab injection without the
required foreground, and remains recorded in
`artifacts/electron-protected-tests-rc6-foreground-refused.json`. In the later
operator-started run, **50 native checks passed** at **17:34:06.207224 +05:00**.
The **2 production PIN checks are explicitly NOT RUN** in that fixture, so its
overall `passed` flag remains false by design. All **51 post-release ordinary
input probes** passed. The separate-process foreground test observed restoration
from the actual foreign HWND to the exam HWND in **16 ms**. An exact source-owned
process inspection found zero remaining after cleanup. Refused input attempts
were not relabeled as successful tests; the subsequent runs supply the passing
native evidence. The separate human notification scenario remains unvalidated.

These gates cleared a fresh **UNVALIDATED rc6 inspection build** using
`--use-built-ui`, with its own output and copied settings. Source results cannot
authorize the package. Package-specific 3A/3B and the final real-device workflow,
PIN/reconnection, evidence/PDF and separate corrected emergency exit still have
to be exercised on that exact copied runtime.

## rc6 inspection artifact — UNVALIDATED

- Folder: `dist/LocalProctoring-Electron-0.4.0-stage3-rc6-UNVALIDATED`
- ZIP: `dist/LocalProctoring-Electron-0.4.0-stage3-rc6-UNVALIDATED.zip`
- ZIP bytes: **331,230,491**; unpacked bytes: **807,531,468** in **796 files**.
- ZIP SHA256: `c97634dd694eeb3a169e0dc25e7344302630630f15b145499d1c0a24ae179052`
- Artifact build ID: `035673e5e0808e5d4e07467cf51d84c89757bc106faabc2b34452250062ca0a2`
- Immutable package fingerprint: `5ad29197ad680d3e01e547cb6a0365427c6bb152995aa23c3d5fa1b97f6f7508`
- `resources/package-build.json` SHA256: `d4eaba44f51113afe38f6fe869b7fdb1a2d191c51ee56cf9b8380a52c90ff25e`
- `PACKAGE-INVENTORY.json` SHA256: `24e3a90d867c3261d81ae4e12c6f1a9c75b8f3ce201ad4f687c0faad317bbf1a`
- Frozen backend EXE SHA256: `e10b40226703b730266334917357b78c2e8ac823fbcd6fb150001a4750c72df3`

The build used `--use-built-ui` without modifying the frozen Electron artifacts.
Original and copied inventory hashes, ZIP CRC, explicit private-data scan and
the same five private help/three invalid-entry checks passed. The pinned runtime
versions are unchanged from rc3; **179 notice files** retain dependency/model
provenance. No passing audit, private config, diagnostic export, session data or
image evidence is shipped. The package remains unsigned by this project.

The separate copy and editable public protected configuration are:

```text
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Проверка rc6 20261013-f284a6c9
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Настройки rc6 20261013-f284a6c9\protected-demo.toml
```

The configuration uses the public demo PIN **739261**, blank/disabled remote
delivery and `audits/electron-recovery.json` relative to its own directory. A
file-only warm benchmark measured **1.765 s** for the full retained-resource
capture and **0.109–0.118 s** for subsequent identity checks. All 1,125 retained
handles were closed. An exact-path process check found zero remaining package
processes after inspection. These measurements do not establish cold-disk
performance or native protection behavior.

Records are `build/electron-package-rc6-inspection.json` and
`build/electron-package-rc6-benchmark.json`. Only private help/rejection processes
were used during inspection; no normal application, devices, hook or native
audit was started during inspection. Subsequent native results are separate,
below. rc5 and all earlier archives, failure reports and the legacy release
remain intact.

### rc6 copied-package native validation

The actual copied rc6 runtime's non-suppressing **package 3A audit passed all
21 checks** at **17:45:18.873152 +05:00 on 13 October 2026**. Its fingerprint
matches the inspected immutable package:
`5ad29197ad680d3e01e547cb6a0365427c6bb152995aa23c3d5fa1b97f6f7508`.
The authoritative copied-runtime report is preserved in the workspace as
`artifacts/electron-package-rc6-recovery.json`; it is not embedded in the archive.

Three read-only compatibility checks passed: the current package accepted its
matching audit; a source audit was rejected for the package; and an old source
audit was rejected for the current source. Mismatches reported
`Machine/runtime/build changed since audit`. Their record is
`artifacts/electron-package-rc6-audit-compatibility.json`.

The copied package's **3B run failed** at **17:49:36.554 +05:00 on 13 October
2026**, stopping at `helper_suspension` with **"Owned native check exceeded its
bound"**. The report contains **45 passing checks and 1 failure**; subsequent
checks were not run. The separate-process foreground check had restored the
exam HWND in **62 ms**. The failed record is preserved as
`artifacts/electron-package-rc6-protected-helper-suspension-failure.json`.

An exact owned-package process inspection found zero remaining after cleanup.
That does not turn the bounded check into a pass. The initial failed report
alone did not establish the cause; the following unchanged-package observation
identified a status-reconciliation defect. **rc6 is
non-promotable**, and its successful 3A audit does not override the 3B failure.
No normal application/device test was launched, and the prepared ordinary
startup script has not been executed. Final real-device calibration/exam,
PIN/reconnection, saved evidence/PDF and the separate corrected emergency-exit
test remain pending. No replacement package had been built at the time of this
failure. The human
notification scenario also remains unresolved.

### rc6 unchanged-package suspension observation

A separate **non-suppressing** observation retained the original helper's
process handle and creation identity. That helper was confirmed dead after
**2.41758 s**, with its exit independently corroborated by PID and creation
identity. Nevertheless, **74 samples from 2.4196 s through 10.3593 s** continued
to expose cached native `ACTIVE` and public `active` while `helper_alive=false`.
The last native snapshot was identical before and after the observed death.
The record is `artifacts/packaged-suspension-observation-rc6.json`.

This proves that the cached status was not reconciled with the retained owner's
death. It does **not** distinguish an unreconciled EOF from a late `ACTIVE`
reply; the unchanged cached snapshot supplies no evidence that a new late reply
arrived. Both observer/fixture processes later exited with code 0 without forced
termination (approximately 77/79 ms), and exact owned-process inspection found
none remaining. The observation did not enable input suppression, run a normal
exam or authorize a passing audit.

A narrow Electron-specific correction was implemented and reviewed as described
below. Fresh source/package gates are still required. The rc6 failed report and
immutable package remain unchanged and non-promotable. Fresh rc7
output/copy/settings paths were reserved separately; no rc7 package had been
built when this correction was frozen.

### rc7 retained-owner reconciliation correction

The Electron adapter now checks its original retained helper HANDLE without
waiting for pipe EOF. Existing status, controller event-drain, heartbeat and
public-state paths use a nonblocking native liveness query. Confirmed death
clears cached native activation flags, readiness and challenges, sets the
parent-observed reason `helper_exited`, and ends the reachable exam before
another monitoring/timer tick. The cached status becomes `RECOVERY`; its last
native reason is preserved rather than inventing a helper message. Repeated
reads do not generate duplicate parent recovery events or permit rearming.

A closed, changed or unreadable handle is **not** evidence of death. That state
stops renewal and admission, reports `helper_identity_unavailable`, and remains
`releasing` with an explicitly unconfirmed-release event. Existing exact-owned
cleanup is still attempted; only confirmed termination completes this pending
state. EN/RU/KK UI and summary wording make no unverified release or shortcut
availability guarantee. Buffered ACTIVE/prepared messages cannot resurrect a
terminal state, while genuine disarmed fault reports after normal release
remain visible. Pending preparation/arming acknowledgements recheck terminal
state before succeeding.

No legacy Windows adapter, helper/guardian deadlines, native release ordering,
event duration threshold or process-ownership policy was changed. Independent
read-only review found no must-fix issue. Automated checks included open-pipe
retained death through the actual controller, a real retained-handle class with
a fake native API, unknown-handle cleanup failure, late replies, concurrency,
request settlement and no rearm. These are regression checks, not new human or
packaged-runtime validation.

Both complete Python environments passed the same **2,131 tests**:

| Environment | Result | JUnit record |
| --- | --- | --- |
| Project `.venv` | 2,131 passed in 47.45 s | `build/electron-retained-death-project.xml` |
| Isolated locked packaging environment | 2,131 passed in 46.93 s | `build/electron-retained-death-locked.xml` |

The exact project command was:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=build/electron-retained-death-project.xml
```

The packaging environment has no editable source installation. Its first full
invocation therefore passed 2,128 tests but failed three subprocess CLI tests
with `ModuleNotFoundError: proctoring`. That result remains preserved in
`build/electron-retained-death-locked-import-failure.xml`. The unchanged source
then passed with a command-local source path inherited by those subprocesses;
no package or dependency installation was modified:

```powershell
$taskOriginalPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = (Resolve-Path -LiteralPath 'src').Path
    & .\build\electron-package-venv\Scripts\python.exe -m pytest -q --junitxml=build/electron-retained-death-locked.xml
} finally {
    $env:PYTHONPATH = $taskOriginalPythonPath
}
```

The small UI clarification passed **40 TypeScript tests**, **30 renderer tests**,
typecheck and build. Its frozen Electron artifact build ID is
`baf49f58593a54fecba0130c825874668890911f00aa4451edaa85585178c65a`.
Previous audits cannot authorize this changed source/artifact identity. Fresh
source gates are recorded below; a separately built and audited copied runtime
and its final operator workflow remain required. The rc6 suspension failure is
retained as a failure, and no human accuracy or protection claim is inferred
from these suites.

### rc7 source native checks

The frozen rc7 source non-suppressing **3A audit passed 21/21 checks** at
**18:21:50.956283 +05:00 on 13 October 2026**. The retained report is
`artifacts/electron-protection-validation-rc7-source.json`, with runtime
fingerprint
`ce140f2ddaaac60e8d752b82c9e22f8d68c45775a16d00905e70f417c0f54459`.
This source report does not authorize a copied package.

The first matching source 3B attempt passed **41 checks**, then stopped with
`cross_process_foreground_recovery` marked **NOT RUN**. Its report is retained
as `artifacts/electron-protected-tests-rc7-foreign-foreground-refused.json`;
later checks were not run. The actual observation was that **no foreign HWND
was sampled**. The report's diagnostic says Windows did not grant foreground,
but the observation does not prove that explanation: nominal 20 ms sampling
could miss rapid restoration or the focus/observer request timing. There is no
evidence from this attempt that production containment failed, and the case
also cannot be called passed.

An exact owned-process inspection found none remaining after cleanup, and the
operator confirmed normal typing and Alt+Tab. One repeat with the **unchanged
source and artifacts** then completed at **18:29:53.155489 +05:00 on 13 October
2026**: **50 native checks passed**, including `helper_suspension` with confirmed
original-owner death and restored ordinary input. All **51 post-release native
input probes** passed. The cross-process test actually sampled the owned foreign
HWND followed by the registered exam HWND **63 ms** later. The report is
`artifacts/electron-protected-tests-rc7-source.json` and retains the same runtime
fingerprint as the passing rc7 source 3A audit.

Its **2 production PIN checks remain explicitly NOT RUN** in this fixture
(52 records), so the report's overall `passed` flag is false by design. An exact
owned-process inspection found none remaining after the repeat. These results
do not erase the first incomplete attempt or establish human notification
containment. They clear the separate **UNVALIDATED rc7 inspection build** using
the frozen UI artifacts; the copied package must still pass its own native
gates before ordinary application/device and final operator validation.

## rc7 inspection artifact — UNVALIDATED

- Folder: `dist/LocalProctoring-Electron-0.4.0-stage3-rc7-UNVALIDATED`
- ZIP: `dist/LocalProctoring-Electron-0.4.0-stage3-rc7-UNVALIDATED.zip`
- ZIP bytes: **331,232,223**; unpacked bytes: **807,535,590** in **796 files**.
- ZIP SHA256: `cbb808190aa46c1b1dbb8d4cc8a40030ecc0d247b51b46fb562f1ca611116205`
- Artifact build ID: `baf49f58593a54fecba0130c825874668890911f00aa4451edaa85585178c65a`
- Immutable package fingerprint: `ddc4046037e04ac44897a9c5d008ae23f6dd0fe038dabf22ddaf81efba600d76`
- `resources/package-build.json` SHA256: `433c9a33814117ac2cc8347c373866e25e30ca31590a70361de3aa539d0ed99a`
- `PACKAGE-INVENTORY.json` SHA256: `c0afa9e48cfd33cfd112528ebdf2dbd9cabd5a95c802f9cd6e09ad7bf9fd920e`
- Frozen backend EXE SHA256: `8f0f70fda6ccba54cc00bc3f3b3060d39d44844e8be2a4fb8a7d86517ffb3a32`

The isolated locked builder used `--use-built-ui` and preserved the final frozen
Electron artifacts. Both original and copied inventory rows matched the actual
file sizes and SHA256 values; ZIP CRC and the explicit private-data scan passed.
The same pinned runtime versions listed for rc3 apply, with **179 notice files**.
Five private frozen help routes exited successfully; missing/unknown entry modes
and the protected-test route without its mandatory recovery report were rejected.
No passing audit, private configuration, calibration export or session evidence
is shipped. No existing package or legacy release was overwritten.

The independently copied directory and editable public protected config are:

```text
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Проверка rc7 20261013-a973d2e6
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Настройки rc7 20261013-a973d2e6\protected-demo.toml
```

The external config's SHA256 is
`6b4fa4df0527636ee56e162a3b3ffe569ef746bffcf771f23fe4c0b53bafc9e0`, identical
to the bundled public protected template. Direct TOML checks confirmed public
PIN **739261**, protection explicitly requested, blank/disabled remote delivery
and an empty external exam URL. Its local audit and evidence paths are
`audits/electron-recovery.json` and `sessions` relative to the external config,
outside immutable package files.

After verifying the copied inventory, a file-only warm benchmark captured
793 immutable files with 1,125 retained file/directory handles in **1.795 s**;
subsequent identity checks took **0.112–0.126 s**. All handles were closed.
An exact-path process inspection confirmed zero remaining original/copy package
processes. These warmed measurements are not cold-disk or protection guarantees.
Records are `build/electron-package-rc7-inspection.json` and
`build/electron-package-rc7-benchmark.json`.

Only private help/rejection subprocesses were used during this inspection;
no ordinary application window, camera, microphone, native hook or audit was
started during inspection. The project has not signed this package. Subsequent
native outcomes are recorded separately below. Source results do not authorize
that copied runtime. Earlier archives and their failed or incomplete audit
records remain preserved without relabeling.

### rc7 copied-package normal-release failure

The copied rc7 runtime's non-suppressing **3A audit passed all 21 checks** at
**18:38:00.657906 +05:00 on 13 October 2026**, with the expected immutable
fingerprint `ddc4046037e04ac44897a9c5d008ae23f6dd0fe038dabf22ddaf81efba600d76`.
The preserved report is `artifacts/electron-package-rc7-recovery.json`.

Its subsequent **3B run failed** at **18:41:29.926 +05:00** after **39 passing
checks**. `normal_release` reported that release was not consistently
acknowledged: native `armed`, `blocking_enabled`, `hook_installed`,
`hotkey_registered`, `prepared` and `control_confirmed` were all false, but
public state was `fault` with reason `normal_disable`. Later checks were not
run. The report and console trace are retained in
`artifacts/electron-package-rc7-protected-normal-release-failure.json` and
`artifacts/electron-package-rc7-protected-console.log`.
An exact owned-package process inspection found zero remaining, and the operator
confirmed normal Windows controls. Native restoration does not make the public
lifecycle mismatch acceptable: **rc7 is non-promotable**.

A deterministic in-memory reproduction exercised the actual `release` and
`_consume` methods with a mocked transport. Without a buffered earlier `ACTIVE`
reply, the matching disarmed acknowledgement left state `released`. With that
earlier reply delivered after release intent, it overwrote `releasing` with
`active`, and the same matching normal acknowledgement then produced `fault`.
This reproduces a concrete ordering defect without native input or an app
launch. The record is `build/rc7-normal-release-order-repro.json`. The historical
native run did not record the full packet order, so this reproduction is not
proof that its exact packet sequence occurred there.

A narrow correction was subsequently implemented, reviewed and tested as
recorded below. No ordinary rc7 application, devices or final exam workflow was
started. The immutable rc7 package, archive and failed reports remain intact.
Only fresh rc8 paths have been reserved: the separate dist output
`LocalProctoring-Electron-0.4.0-stage3-rc8-UNVALIDATED` and TEMP folders
`Local Proctoring Проверка rc8 20261013-e681f034` and
`Local Proctoring Настройки rc8 20261013-e681f034`. They were reserved before the
new source gates; this reservation was not protected-use authorization.

### rc8 release-intent guard and regression freeze

The reviewed correction adds a narrow six-line guard preserving `releasing`
when an earlier non-terminal status arrives after release intent. It does not
relax native release requirements or alter production recovery deadlines.
**24 new regression cases** cover this ordering; the focused suite passed
**183 tests**. Both full Python environments also passed independently:

| Environment | Result | Record |
| --- | --- | --- |
| Project `.venv` | 2,155 passed in 45.15 s | `build/electron-release-intent-project.xml` |
| Isolated locked packaging environment | 2,155 passed in 44.26 s | `build/electron-release-intent-locked.xml` |

Both JUnit files contain zero failures, errors or skips. The isolated run used
a command-local `PYTHONPATH=<repository>/src` for source/subprocess imports; no
dependency lock or development environment was changed. This is regression
evidence for the frozen source, not a packaged native or human result.

The frozen source fingerprint is
`451c29cc4fb8af2c7efd9f95de7b314d5ab944b8b9fbe6b0ba16009934010279`.
The UI artifacts are unchanged at build ID
`baf49f58593a54fecba0130c825874668890911f00aa4451edaa85585178c65a`.
Exact owned-process inspection found zero source processes before the operator
was asked to run the fresh source 3A/3B sequence. Its results are recorded below.
The rc7 native failure and its uncertain historical packet order remain
documented above.

### rc8 source native checks

The frozen rc8 source non-suppressing **3A audit passed all 21 checks** at
**19:05:00.952960 +05:00 on 13 October 2026**. The matching bounded **3B run
passed 50 native checks** at **19:07:48.193003 +05:00**, including normal release
with a stable public `released/normal_disable` state and suspended-helper
recovery with confirmed original-owner death. All **51 post-release ordinary
input probes** passed. The separate-process foreground test observed the owned
foreign HWND followed by the registered exam HWND **31 ms** later.

Both reports match source fingerprint
`451c29cc4fb8af2c7efd9f95de7b314d5ab944b8b9fbe6b0ba16009934010279` and the
unchanged UI artifact build. Preserved records are
`artifacts/electron-protection-validation-rc8-source.json` and
`artifacts/electron-protected-tests-rc8-source.json`. The protected fixture's
**2 production PIN checks are explicitly NOT RUN** (52 records); its overall
`passed` flag remains false by design. Privileged exact owned-process inspection
found none remaining after cleanup.

These results clear a separate **UNVALIDATED rc8 inspection build** using the
frozen UI. They do not authorize the copied runtime or establish a successful
human exam. Package-specific 3A/3B, actual devices/calibration/exam, production
PIN and reconnection controls, evidence/PDF, and the separate emergency run
remain pending. No earlier failed package result is reclassified as passing.

## rc8 inspection artifact — UNVALIDATED

- Folder: `dist/LocalProctoring-Electron-0.4.0-stage3-rc8-UNVALIDATED`
- ZIP: `dist/LocalProctoring-Electron-0.4.0-stage3-rc8-UNVALIDATED.zip`
- ZIP bytes: **331,233,427**; unpacked bytes: **807,535,665** in **796 files**.
- ZIP SHA256: `c0f8aa50061e56e92bb04e0c8bdfba247c4472d4665d6d9ce3540497271a7fb8`
- Artifact build ID: `baf49f58593a54fecba0130c825874668890911f00aa4451edaa85585178c65a`
- Immutable package fingerprint: `397475d7cff4340937b644b7bd1b4be328bede349d0508cf9e0487fa75c36dbb`
- `resources/package-build.json` SHA256: `433c9a33814117ac2cc8347c373866e25e30ca31590a70361de3aa539d0ed99a`
- `PACKAGE-INVENTORY.json` SHA256: `7c1bdd90b6002191595b95d80e0eba637c6dc6a29b244e2c21c12f86ec4d5457`
- Frozen backend EXE SHA256: `80c3fbc9898a3755b689879421c561e0bb25e2c8fa7be08832575508f436579c`

The isolated locked builder used `--use-built-ui`, preserving the frozen
Electron assets. Actual file sizes and SHA256 values matched both the original
and copied inventory. ZIP CRC, explicit private-data scan, five frozen private
help routes and three invalid-entry rejection checks passed. Runtime versions
remain the pinned versions listed for rc3, with **179 notice files** for runtime
dependencies and local models. The package is unsigned by this project; it
contains no private config, credentials, calibration export, session evidence
or passing audit. All earlier distributions and reports were preserved.

The fresh independent copy and editable public config are:

```text
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Проверка rc8 20261013-e681f034
C:\Users\kuten\AppData\Local\Temp\Local Proctoring Настройки rc8 20261013-e681f034\protected-demo.toml
```

The config SHA256 is
`6b4fa4df0527636ee56e162a3b3ffe569ef746bffcf771f23fe4c0b53bafc9e0`, matching
the copied package's public protected template. Direct TOML checks confirmed
public PIN **739261**, requested protection, blank/disabled remote delivery and
an empty external exam URL. `audits/electron-recovery.json` and `sessions`
resolve beside this editable config, outside immutable package resources.

A file-only warm integrity benchmark captured 793 immutable files with 1,125
retained file/directory handles in **1.903 s**; later identity checks took
**0.120–0.141 s**. All handles were closed. Privileged exact-path process
inspection found zero remaining original/copy package processes. These warmed
timings do not guarantee cold-disk performance or native protection behavior.
Records are `build/electron-package-rc8-inspection.json` and
`build/electron-package-rc8-benchmark.json`.

No ordinary application, device or native audit was launched during inspection;
only private help/rejection entrypoints were exercised. **The copied rc8
runtime's own 3A/3B audits, ordinary startup and final real-device/operator
workflow remain pending.** Source audits cannot substitute for those results.

## Source commands and legacy rollback

From the repository's `desktop` directory, after installing the locked source
dependencies and keeping the existing Python environment/models available:

```powershell
npm run build
# Safe mode; protection and remote delivery disabled in this public profile.
npm start -- --config config/default.example.toml
# Close the app before running an owned-window recovery audit.
npm start -- --validate-electron-protection --native-input --config config/electron-protected.example.toml --audit-output ..\artifacts\electron-protection-validation.json
# Only after a matching audit and operator readiness: short bounded tests.
npm start -- --validate-electron-short-protection --allow-short-protection --recovery-report ..\artifacts\electron-protection-validation.json --config config/electron-protected.example.toml --test-output ..\artifacts\electron-protected-tests.json
# Operator performs onboarding/calibration and presses Start manually.
npm start -- --config config/electron-protected.example.toml
```

The example PIN is **739261**, a public demonstration credential. Configure a
private PIN before actual deployment. Config paths in source mode resolve from
the repository root; explicit report output paths resolve from the launch
working directory. A rebuilt or edited relevant source/artifact invalidates the
earlier audit. Do not run a build while a protected app is using those resources.

The legacy frontend remains available from the repository root:

```powershell
.\.venv\Scripts\python.exe -m proctoring --config config/default.example.toml
```

Its protected mode requires its own legacy `scripts/validate_protection.py`
audit and explicitly configured legacy profile. Neither audit authorizes the
other frontend. The existing published executable and `dist/LocalProctoring`
remain unchanged. Close one frontend before opening another against the devices.

## Test machine and measurement limits

Native checks run on Windows 10 Pro 22H2 (10.0.19045), AMD Ryzen 5 9600X
(6 cores / 12 logical processors), approximately 31.1 GiB usable RAM. This is
not validation of an 8 GB machine. A clean Windows account/machine without
development tools and physical DPI transitions have not been exercised.
