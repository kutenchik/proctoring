# Stage 4B ownership timestamp compatibility fix and fresh preparation

2026-10-14. Local verification complete. **No public tunnel launched; awaiting explicit approval for the new run.**

## Demonstrated root cause

The preserved `snapshots-01/tunnel-owner.json` was read without modification. Windows PowerShell 5.1 deserializes its ISO `created` property as String; PowerShell 7.6.5 deserializes it as DateTime. The former comparison coerced that DateTime into culture-dependent text, so identical process creation instants did not compare equal to freshly formatted ISO text.

Read-only reproduction results:

| Host | Deserialized type | Old text comparison | New exact UTC ticks |
|---|---|---|---:|
| Windows PowerShell 5.1.19041.6328 | System.String | true | 639275776956224190 |
| PowerShell 7.6.5 | System.DateTime | false | 639275776956224190 |

This fixes the demonstrated launcher mismatch. It makes no claim about historical admission or chunk-upload transport failures.

## Shared fix and security invariants

`scripts/stage4b-process-identity.ps1` supplies process identity capture, strict record reading, normalization, validation and owned termination. `stage4b-demo.ps1` uses it for Tunnel capture, Pin, Start, Restart, and Stop. Prepare creates only empty configuration; Invite/Reset do not terminate processes. The exposure wrapper uses the same capture function for guard ownership. Both the independent Python deadline guard and the synthetic harness's cleanup continue through the same production Stop entry point.

Creation timestamps are compared as exact signed 64-bit .NET UTC ticks (100 ns). New records serialize UTC as invariant `yyyy-MM-ddTHH:mm:ss.fffffffZ`. Existing records remain readable as explicit-offset ISO strings, DateTimeOffset or unambiguous DateTime. Explicit offsets are normalized to UTC without truncating fractions. Unspecified-kind dates, local ambiguous/invalid DST times, culture-formatted dates, absent zones, unknown offsets (`-00:00`), invalid dates and fractions beyond seven digits fail closed.

Both capture and observation use the same Win32_Process CIM CreationDate API. This Windows provider exposes microsecond precision, represented in the seven-digit format with its final zero retained; the code does not mix that value with a different process-time API or round it. One tick of difference is rejected. No tolerance, PID-only fallback, or creation-time omission was introduced.

PID must be a positive integral Int32-range value. Executable, owner and command line remain mandatory exact ordinal comparisons. Unknown, missing or duplicate JSON identity fields and repeated PID records are rejected. Access-denied process queries throw rather than masquerading as absent processes. A vanished valid process is safely treated as already stopped; a replacement identity throws.

Stop revalidates all identity fields and holds the target process handle before final validation and termination, rather than issuing a fresh PID-only Stop-Process command. Restart retains the listener-owner check and uses the same owned stop. Fixture teardown is separate from launcher termination: the deliberately unrelated fixture survives every launcher/guard operation, then the test harness releases its own harmless fixture process.

The independent guard's own accepted deadline is now capped at 900 seconds (previously its internal maximum was 1800, although the wrapper already passed 900). It still starts shutdown 60 seconds before the deadline, preserving the shutdown reserve. Ownership errors remain visible and do not authorize termination of an unrelated process.

## Focused verification

| Host | Identity checks | Lifecycle checks | Result |
|---|---:|---:|---|
| Windows PowerShell 5.1.19041.6328 | 12 | 9 | PASS |
| PowerShell 7.6.5 | 12 | 9 | PASS |

42 check executions in total, covering:

- Same live process accepted after JSON round trip, including a record produced in one shell and verified in the other.
- Seven-digit fractional round trip and equivalent explicit UTC offsets under en-US, ru-RU and kk-KZ cultures.
- Different creation instant (one tick), simulated PID reuse, PID change, executable, owner and command changes rejected.
- Missing/ambiguous/malformed fields, duplicate JSON keys and duplicate PID records rejected.
- Mismatched Stop leaves both fixtures running; valid Stop terminates only the exact recorded fixture.
- Actual Prepare and Pin actions with harmless simulated tunnel records.
- Start reaches a deliberately blocked process-launch boundary only after successful validation; changed identity rejects before that boundary.
- Restart terminates only its exact simulated server before reaching the blocked launch boundary; the simulated tunnel remains alive.
- The actual independent Python deadline guard invokes production Stop and terminates only its recorded harmless target.
- Historical timestamp reproduction is read-only with its file hash checked before/after.

Commands, from the repository root:

```powershell
powershell.exe -NoProfile -File scripts/test-stage4b-identity.ps1 -OutputDirectory "$PWD/build/stage4b/identity-tests/ps51"
pwsh.exe -NoProfile -File scripts/test-stage4b-identity.ps1 -OutputDirectory "$PWD/build/stage4b/identity-tests/ps76"
powershell.exe -NoProfile -File scripts/test-stage4b-lifecycle.ps1 -OutputDirectory "$PWD/build/stage4b/identity-tests/lifecycle51"
pwsh.exe -NoProfile -File scripts/test-stage4b-lifecycle.ps1 -OutputDirectory "$PWD/build/stage4b/identity-tests/lifecycle76"
```

Per-host results/reproduction JSON and lifecycle logs are in those output directories. The first lifecycle test invocation exposed PowerShell 5.1 stderr handling in the test harness; the harness was corrected to capture the intentional failure as output, and both complete test sets then passed. Production identity validation was not bypassed.

The exposure wrapper parsed successfully under both hosts. Python compile checks passed for the changed guard and sealer. No frontend/product implementation changed, so no unrelated frontend rebuild or regression suite was run. The existing frontend and observer build bytes were verified and included in the fresh seal.

No Cloudflare executable, public/local server listener, student application, real device capture, protection test, packaging or later stage was started. Hidden PowerShell sleep fixtures and simulated tunnel logs were used. Start/Restart process creation was blocked in tests. The deadline test's approval argument exercises local cleanup only; it does not launch a tunnel or grant future public authorization.

## Fresh run

- Run: `build/stage4b/snapshots-02`.
- Consent version: 3, synthetic snapshot scenario unchanged.
- Fresh database: two disposable teachers, zero attempts, zero snapshot mappings, zero receipts.
- Credentials: new DPAPI-encrypted private fixture journal; not included in reports.
- Intended loopback port: 8036; no listener at the preparation check.
- No tunnel, guard, server or started-scenario records exist yet. Genuine new ownership records will be captured only from processes actually launched after approval; no production ownership record is fabricated offline.
- Fresh seal: **121 source/build files**, including the shared helper, both focused tests, launcher, guard, wrapper, migrations, current frontend and synthetic fixture.
- SHA-256 of `prepared-hashes.json`: `ff3b92bccf4cb1ea89a644359c261f2271644f2527705be8a6bb0a16852cf750`.
- All 121 file hashes verified. See the run's `preparation-validation.json`.

`snapshots-01` remains historical evidence; it was neither retried nor resealed. Existing databases, pending journals, physical evidence and the running teacher website were not modified or restarted. Snapshot/camera/detection/streaming/synchronization implementations were not changed.

## Safe startup and shutdown — only after new approval

Retain the pending-event, delayed JPEG, active remote teacher observation, owner isolation, optional single lost-response recovery, final independent receipt and receipt-gated cleanup scenario in `TEACHER_DASHBOARD_STAGE4B_LIVE_SNAPSHOT_PREPARATION.md`, substituting **snapshots-02** everywhere. Its historical run path and seal count are superseded by this report. The teacher must be ready on a genuinely different network before starting the exposure clock.

Use an explicit shell host for operational clarity; both have now passed the focused checks. Recommended commands below use Windows PowerShell 5.1 consistently:

```powershell
$run = "$PWD/build/stage4b/snapshots-02"
powershell.exe -NoProfile -File scripts/stage4b_synthetic/exposure.ps1 -RunDirectory $run -Cloudflared "$PWD/build/stage4b-tools/2026.10.0/cloudflared.exe" -CloudflaredSha256 '86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c' -OperatorApprovedPublicExposure
# Read this run's newly assigned hostname; do not reuse an old hostname:
powershell.exe -NoProfile -File scripts/stage4b-demo.ps1 -Action Pin -RunDirectory $run -PublicOrigin '<exact new HTTPS origin>'
powershell.exe -NoProfile -File scripts/stage4b-demo.ps1 -Action Start -RunDirectory $run -OperatorApprovedPublicExposure
# Verify HTTPS/authentication/origin checks, then run the existing v3 scenario:
$env:PYTHONPATH="$PWD/src;$PWD/.venv-server/Lib/site-packages"
& build/stage4b/physical-01/student-venv/Scripts/python.exe scripts/stage4b_synthetic/snapshots.py run --run $run --operator-approved-public
# Immediate ownership-aware shutdown on completion or critical failure:
powershell.exe -NoProfile -File scripts/stage4b-demo.ps1 -Action Stop -RunDirectory $run
```

The exposure wrapper rechecks every sealed hash and starts the independent guard before tunnel launch. Maximum exposure remains 15 minutes including shutdown. Remote pending/image confirmation gates and numerical export remain mandatory. Stop immediately on critical failure, preserve its precise phase and diagnostics, and do not automatically retry or extend the deadline. Verify owned processes/listener absent before writing the closure marker; verify guard exit. Do not manually kill a PID that fails identity validation.

## Remaining gate

No local launcher blocker remains demonstrated by these focused checks. Public consent-v3 snapshot validation remains **NOT RUN**. Real-camera behavior and guaranteed snapshot latency remain unverified. New explicit approval is required for one fresh bounded public run; earlier authorization was consumed by snapshots-01. Preparation stops here.
