# Stage 4B live snapshot public-network preparation

Prepared 2026-10-14. **Awaiting explicit approval. No public exposure has started.**

## Prepared identity and isolation

- Fresh run: `build/stage4b/snapshots-01`; reserved loopback port 8036 (no listener at preparation check).
- Fresh database schema includes migration 005; two disposable teachers, zero attempts, zero receipts and zero event snapshot mappings. Synthetic admission/start are deliberately deferred until the approved public endpoint exists.
- Teacher credentials are in the run's DPAPI-encrypted `fixture-private.sqlite3`, not this report or logs. The remote operator will receive only the owning disposable login after approval. Use that generated login without resetting its password during the scenario: a reset invalidates the harness's authenticated owner session.
- Scenario: `scripts/stage4b_synthetic/snapshots.py`. This is a new consent-v3 snapshot fixture; the old v2 relay fixture/run remains historical and is not reused.
- Fresh frontend build plus numerical observer at `teacher-web/dist/assets/stage4b-snapshot-observer.js`. `prepared-hashes.json` seals 118 files, including server SQL migrations, connected client, current frontend build, synthetic scripts and ownership/deadline scripts. Hashes must match again before launch; any relevant change requires renewed local verification and resealing before exposure.
- Existing cloudflared binary matches its preserved verified-release SHA-256: `86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c`. No download/update was performed.

## Prepared scenario and gates

1. After approval and confirmation that the remote teacher is on another network, the existing `exposure.ps1` starts the independent deadline guard **before** requesting one new Quick Tunnel hostname. Maximum total exposure is 900 seconds; shutdown starts at 840 seconds, reserving 60 seconds for Stop.
2. Pin only the exact generated HTTPS origin using `stage4b-demo.ps1 -Action Pin`. Start only the new run's loopback API using `-Action Start`. Existing services are never restarted. HTTPS/WSS origins, cookie authentication, CSRF and ownership checks stay enabled.
3. The harness logs in both disposable teachers using production HTTP, creates the snapshot-enabled synthetic exam through the production API, admits the synthetic student exactly once, connects its production student control WebSocket, obtains consent-v3 ACK, and performs production start/confirmation. No screen viewer or capture is started. Synthetic status heartbeats keep the attempt active.
4. It writes a canonical `phone_visible` event to a synthetic session journal and invokes the production SyncWorker outbox. It then pauses at `await_remote_pending`. A generated JPEG does not yet exist.
5. Remote teacher logs in, opens this exam's live workspace/student, uses English UI, and installs the numerical observer. No “View exam monitor” click is needed or permitted for this scenario. Confirm the canonical event and “Snapshot pending” are visible, without page refresh.
6. Only after that human confirmation, write `operator-pending.json` bound to the exact attempt ID, with `separate_network`, `pending_visible`, `no_refresh` all true. The harness checks these flags and waits a further three seconds before atomically publishing a valid generated JPEG. It contains generated texture and a SYNTHETIC / NO CAMERA label, not real imagery.
7. Production SyncWorker validates and uploads the same event-associated JPEG in bounded chunks. If at least 120 seconds remain, the fixture deliberately discards one successful chunk response and reconstructs the worker with the same durable journal. This tests lost-response recovery/reconnection of subsequent HTTP requests, **not a physical network outage**. No entire-experiment retry occurs. Use `--skip-interruption` if the operator elects to omit this optional case.
8. The harness checks the server upload frontier, and independently reads its new run's database in read-only mode: file complete/bytes/hash match, no ended timestamp and zero receipts. It verifies local JPEG retention and no cleanup flag. Owner HTTP image bytes must match the JPEG hash; the second teacher must receive 404 for the same image URL.
9. It pauses at `await_remote_image`. The remote teacher must see the transition without refresh while the attempt is active, open the full image and save `stage4b-live-snapshot-metrics.json`. The observer records decoded thumbnail and full-image load states, not pixels or credentials. Paste/attach the export before authorizing finalization. Confirm no certificate warning.
10. Only after those observations, write `operator-image.json` with the same attempt ID and `available_active`, `full_image_opened`, `no_refresh`, `no_certificate_warning`, `export_saved` all true. Preserve the raw browser export separately in the run; do not substitute the harness's local HTTP result for remote observation.
11. The harness ends its synthetic lifecycle and creates generated remaining manifest material (summary, answers and PDF). The production worker finalizes the bundle. Before it can clean up, a separate read-only SQLite connection must return exactly the same committed receipt, and the production local receipt validator must pass. The local JPEG must still exist at this boundary. After production cleanup, all synthetic session evidence files must be absent and the durable receipt retained.
12. Success or critical failure triggers the existing ownership-aware Stop script, tunnel first. The independent guard is the fallback. Verify owned process exit and absence of the 8036 listener before writing `closed.json`; then verify guard exit. Retain databases, outbox, numerical results and logs. Remote teacher logs out/closes the test tab.

Operator confirmation files are evidence gates, not automated assertions. Never populate them without the corresponding human observation. If the remote user cannot observe pending, image loading, or full-image access, stop and report that result rather than advancing.

## Launch recipe — NOT EXECUTED

Only after explicit user approval, with a genuinely separate-network teacher ready:

```powershell
$run = "$PWD/build/stage4b/snapshots-01"
& scripts/stage4b_synthetic/exposure.ps1 -RunDirectory $run -Cloudflared "$PWD/build/stage4b-tools/2026.10.0/cloudflared.exe" -CloudflaredSha256 '86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c' -OperatorApprovedPublicExposure
# Read the assigned hostname from this run's log, then use that exact value:
& scripts/stage4b-demo.ps1 -Action Pin -RunDirectory $run -PublicOrigin '<exact assigned HTTPS origin>'
& scripts/stage4b-demo.ps1 -Action Start -RunDirectory $run -OperatorApprovedPublicExposure
$env:PYTHONPATH="$PWD/src;$PWD/.venv-server/Lib/site-packages"
& build/stage4b/physical-01/student-venv/Scripts/python.exe scripts/stage4b_synthetic/snapshots.py run --run $run --operator-approved-public
```

Before starting the scenario, verify HTTPS page access and the standard unauthenticated/foreign-Origin rejections. Do not bypass a certificate warning. After `snapshot-progress.json` supplies the attempt ID, the remote browser console observer command is:

```javascript
(await import('/assets/stage4b-snapshot-observer.js')).start('<exact attempt ID>', /* deadline.json deadline minus 60, in milliseconds */)
```

Close Developer Tools afterwards. The browser's save button does not end the attempt. Preserve its export and human confirmations before the image gate. If setup or login cannot finish within the remaining budget, stop; do not extend the deadline or open another tunnel. Emergency/manual shutdown is `scripts/stage4b-demo.ps1 -Action Stop -RunDirectory $run`, which verifies ownership before terminating anything.

## Targeted local preparation results

Read the live snapshot implementation report, previous public synthetic report and current Stage 2/3 contracts. The preparation checks used temporary data and an owned ephemeral loopback HTTP/WebSocket server only.

```powershell
$env:PYTHONPATH="$PWD/src;$PWD/.venv-server/Lib/site-packages"
& build/stage4b/physical-01/student-venv/Scripts/python.exe -m pytest tests/teacher_server/test_snapshot_preparation.py --confcutdir=tests/teacher_server -q
# 3 passed, latest run 5.53 seconds
node --test --test-isolation=none scripts/stage4b_synthetic/snapshot-observer.test.mjs
# 1 passed
# From teacher-web:
node --test tests/snapshot-observer.dom.test.mjs
# 1 passed; isolated headless Edge, synthetic DOM/images, network blocked
npm run build
# TypeScript and Vite passed, 1926 modules
```

The end-to-end harness test exercised production admission, v3 consent/start, durable late JPEG upload, active pending/available server projections, one injected lost successful response, owner access, second-teacher 404, independent complete receipt and gated cleanup. A separate test injected admission transport failure and verified the recorded phase is admission with no snapshot execution. Another verifies incomplete/wrong-attempt operator confirmation is rejected. Reusing a started run is rejected before touching its original results.

Observer tests verify pending/decoded-thumbnail/full-image detection, numerical export without pixel data, and same-clock timing. These local checks do not establish remote browser behavior through Cloudflare. No full regression suites, protected-mode tests, packaging, devices or later stages ran. The browser test needed subprocess permission; the first invocation used the wrong working directory and was corrected, then passed.

## Admission failure handling and preservation

The historical `synthetic-02` admission failure remains unchanged: request-phase connection_failed, 468 ms, no HTTP status/response bytes, before upload. It is distinct from the older chunk-upload context-canceled failures. No historical database, pending attempt or evidence file was migrated, repaired or deleted.

The new harness preserves `first_failure.phase`, safe exception type and the ConnectedClient's bounded transport diagnostics in `snapshot-results.json`, including when failure occurs at admission. On an admission failure it never creates synthetic session evidence or claims snapshot validation. No automatic admission or full experiment retry, timeout increase, alternate hostname, or root-cause assumption is allowed. Preserve the safe record and close owned ingress immediately.

## Timing and final result template

All public result fields currently remain **NOT RUN**:

| Check | Required evidence after authorization |
|---|---|
| Synthetic admission | Actual public API acknowledgement and safe diagnostic |
| Live event notification | Remote event visible while active; observer pending state |
| Pending-to-available | Remote decoded thumbnail transition, no page refresh |
| Remote authenticated access | Human full-image inspection plus observer full-image loaded |
| Cross-teacher rejection | Second authenticated teacher receives 404 for the exact item |
| Upload/retry | Stable item/hash/frontier; distinguish optional injected loss from genuine failure |
| Final matching receipt | Production validation plus independent committed-receipt equality before deletion |
| Local cleanup | Expected synthetic evidence gone only after that receipt boundary |
| Observed availability delay | Browser pending-to-decoded-thumbnail interval and separate publisher-to-upload-ACK interval |

Browser timing uses one monotonic browser clock and 250 ms sampling. It includes operator waiting and the intentional publication delay, so it is not one-way network latency or exact JPEG-publication-to-display time. Publisher-to-ACK uses one local monotonic clock; remote and local wall-clock subtraction is not used to claim accuracy. Report the two observed durations with these qualifications, not a guaranteed few-second latency. Neither success nor failure establishes real-camera behavior.

## Approval requested

Approve **one** fresh Quick Tunnel run using this preparation, maximum **15 minutes**, synthetic events/JPEGs only, with a teacher on a genuinely different network and the bounded scenario above. The prior tunnel authorization has already been consumed and does not authorize this run. Stop here until the user explicitly approves.
