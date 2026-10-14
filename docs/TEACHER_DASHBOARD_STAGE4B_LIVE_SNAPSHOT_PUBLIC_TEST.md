# Stage 4B consent-v3 snapshot public attempt — setup stopped

2026-10-14. The operator authorized one public Quick Tunnel run, maximum 15 minutes, and confirmed a teacher browser ready on a genuinely different network. This authorization was used for `build/stage4b/snapshots-01`. **The snapshot scenario was not reached. No second exposure or experiment retry was performed.**

## Exposure and closure

All 118 prepared source/build hashes matched before launch. The independent deadline guard started before the tunnel. Exposure clock start: epoch 1791980894.8054461 (17:28:14.805 Asia/Qyzylorda). Assigned hostname: `net-create-revenues-rats.trycloudflare.com`, initially forwarding to the closed loopback port 8036.

Origin pinning stopped on `Process identity changed; stopping without termination`. The origin remained null; no server ownership record or server listener was created. The subsequent security-check command rejected the null URL locally with MissingSchema, before issuing an HTTP request. It is not a public connectivity or admission failure.

The existing ownership-aware Stop script, invoked explicitly with Windows PowerShell (`powershell.exe -NoProfile`), verified ownership and successfully stopped the tunnel. Process absence and no listener on 8036 were checked before writing `closed.json` at epoch 1791980961.558 (17:29:21.558): **66.753 seconds from exposure-clock start**, within 900 seconds. The deadline guard and its Python child subsequently exited; a successful elevated CIM query confirmed this after the sandbox denied the initial query. No unrelated service was terminated.

## Setup diagnosis

The calling shell was PowerShell 7.6.5. A read-only reproduction using the preserved ownership JSON shows that `ConvertFrom-Json` converts its `created` value to `System.DateTime`. Converting that value back to text produces `10/14/2026 12:28:15`, whereas the script's newly inspected process identity uses the ISO timestamp `2026-10-14T12:28:15.6224190Z`. The script's exact string comparison returns false. This demonstrates a shell-dependent comparison mismatch consistent with the pin failure; it does not establish actual process replacement. Stop using Windows PowerShell passed the existing ownership checks.

No script/source/build identity was changed during the experiment, and pinning was not retried. A future preparation should explicitly use one consistent Windows PowerShell host for these ownership scripts, or separately implement/test timestamp normalization while retaining all ownership fields. Any new public run needs a fresh isolated run and new approval.

## Requested results, separately

| Check | Result |
|---|---|
| Synthetic admission | NOT RUN — API server never started |
| Live event notification | NOT RUN |
| Pending-to-available snapshot transition | NOT RUN |
| Remote authenticated full-image access | NOT RUN |
| Cross-teacher access rejection | NOT RUN |
| Snapshot upload / controlled interruption / reconnection | NOT RUN |
| Final matching receipt | NOT RUN — zero receipts |
| Receipt-gated local evidence cleanup | NOT APPLICABLE — no synthetic attempt/session evidence was created |
| Actual observed snapshot availability delay | NOT MEASURED |

Read-only inspection of the new run database found zero attempts, zero event snapshot mappings and zero synchronization receipts. No real-camera conclusion is possible. Existing local automated preparation results remain valid but are not public validation.

## Evidence preserved

This run retains `prepared-hashes.json`, preparation validation, fresh database/private credential journal, `deadline.json`, tunnel/guard ownership records and logs, `closed.json`, and `setup-failure.json`. It contains no started snapshot harness marker. Historical `synthetic-02` admission diagnostics and the older pending physical attempt/evidence remain unchanged.

This was a **pre-admission ownership/setup failure**, not a recurrence of the historical admission connection_failed or chunk-upload context-canceled failure. No timeouts were changed and no root cause was assigned to Cloudflare. Work stopped after preserving the result and verifying shutdown.
