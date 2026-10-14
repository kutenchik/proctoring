# Stage 4B — Synthetic relay and synchronization preparation

2026-10-14. **Prepared locally; public execution NOT authorized or performed in this continuation. Stage 4B remains unaccepted.**

## 1. Evidence and correction

Read alongside `TEACHER_DASHBOARD_STAGE4B.md`, `TEACHER_DASHBOARD_STAGE4B_PHYSICAL_TEST.md`, `TEACHER_DASHBOARD_STAGE4B_RELAY_SYNC_UI_FIX.md`, and the Stage 2 synchronization / Stage 3 live contracts.

The previous remote teacher saw eight frames over 9.1808 seconds, approximately 0.87 FPS, using WSS relay. The original sender failure was `frame_delivery_unavailable`; browser ACK latency was unavailable. Only the session artifact completed upload; no complete receipt existed. Cloudflare logged repeated `context canceled` during upload, but the original request phase was not established.

**Operator correction:** a real second person was sitting in the camera corner. `People: 2` / `Second person detected` are not evidence of a false positive. Section 6 and the conclusion of the previous investigation report now explicitly withdraw that interpretation. No detector, NMS, person-count, gaze, event-threshold, protection or recovery algorithms were changed in this continuation.

The historical encrypted journal and evidence were opened read-only. All six sizes and SHA256 values still match the frozen manifest: session 2,015; events 480,546; summary 13,181; answers 243; PDF 46,862; reference 14,062 bytes. Zero receipts, cleanup false. Evidence: `build/stage4b/synthetic-02/preparation-verification.json`. No historical credential, origin, journal or evidence was migrated.

## 2. Preserved fixes and warning stability

The production sender retains actually enqueued timestamps through the existing 12-second delivery window, bounded at 64 entries. Recognized delayed ACKs advance delivery; duplicates, older sequences and untracked ACKs do not extend it. No delivery timeout or frame-buffer limit was increased.

Sequence-aware journal/snapshot merging, stable episode IDs and reserved warning layout remain intact. The focused DOM test makes 100 active/clearing updates while independently varying synthetic raw gaze labels and box positions. Warning/list node identity, reserved layout and zero restarted animations remain stable; closed episodes clear, new episodes use new IDs, and unhealthy monitoring hides the valid-detection warning. Cache tests reject stale resurrection and repeated list reordering. Five authoritative event-lifecycle tests cover continuous activation, brief clearing, new episodes, reordered samples and monitoring interruption.

These tests do not establish physical visual stability of the supplied video. That requires a separately approved human test.

## 3. New preparation code and pipeline

- `scripts/stage4b_synthetic/run.py`: offline disposable setup, authenticated synthetic student control, relay orchestration and production sync-worker exercise.
- `scripts/stage4b_synthetic/sender.mjs`: bundles the actual production `LiveScreen`, policy, geometry and delivery bookkeeping. Only capture/native-window/RTC-host adapters are synthetic. No Electron runtime, desktopCapturer, camera, microphone, controller or exam application is launched. Each capture request gets a newly numbered synthetic JPEG through one bounded private pipe; live frames are never saved.
- `scripts/stage4b_synthetic/observer.mjs`: normal remote browser numerical observer. Uses the existing production teacher UI/assembler/decoder/canvas/ACK path; does not intercept frames or authentication payloads. At most 900 samples and 128 recent trace rows per snapshot. Exports owned-server diagnostics with the existing authenticated GET endpoint before shutdown. Export failure stops viewing and preserves available teacher evidence, without pretending server export succeeded.
- `scripts/stage4b_synthetic/local-viewer.mjs`: local-only headless Edge integration driver for the production viewer. Only literal loopback HTTPS accepted.
- `scripts/stage4b_synthetic/exposure.ps1`: approval-gated launch wrapper; verifies sealed source/build hashes and starts the independent deadline guard **before** the tunnel. Uses the existing identity-aware demo launcher.
- `scripts/stage4b_synthetic/seal.py`: offline identity manifest; refuses an already-exposed run.

One missing measurement was corrected in production diagnostics: server traces now distinguish validated `accepted` frames and malformed `rejected` frames. Rejected sequence operands are sanitized to a valid integer or −1. Rate/budget drops, replacements, frame/ACK sends and ACK forwarding remain separately counted. This is instrumentation only; authorization, forwarding, validation and deadlines are unchanged.

Pipeline to be tested publicly:

Numbered synthetic generator → production LiveScreen → authenticated WSS → existing FastAPI relay → actual remote teacher assembler/decode/canvas → presentation ACK → server → production sender ACK validation.

The native RTC adapter deliberately never completes direct negotiation. Thus the **production timeout-to-relay path** runs, but this fixture does not test real ICE/NAT negotiation. Delivery FPS is informational; fresh usable presentation and continuity take priority. The observer measures duration between actual first and last presentation timestamps, not between Start clicks. Numbered content and monotonically increasing presentation sequences distinguish fresh frames from an open but idle WebSocket.

## 4. Multi-chunk synchronization fixture

A separate disposable attempt uses production HTTPS admission, start authorization and start confirmation. Its valid synthetic bundle contains session, events, summary, native answers, generated PDF and an artificial reference JPEG; snapshots are explicitly disabled. No captured camera image is used.

The event journal has 1,400 synthetic lifecycle records and exceeds three 256 KiB chunks. The production worker sends record batches, manifest, chunk requests, status/frontier requests and final completion. After the first successful events chunk, the fixture repeats the identical request, verifies its idempotent response, then deliberately discards that success response once. On the next worker iteration the real server frontier determines the next offset. This is labeled **injected response loss**, not a simulated Cloudflare diagnosis.

Bounded observations contain operation class, status, offset, JSON request bytes, response bytes, elapsed duration, failure phase/code and aggregate server progress. There are no request bodies or evidence bytes in diagnostics. Before the worker can clean up, the complete response is validated with the production receipt verifier and compared independently with the server's committed receipt. The worker then independently enforces manifest/identity/hash verification before deletion.

The final local run uploaded events at offsets 0, 262144, 524288 and 786432; offset 0 was deliberately repeated. Six files / 1,400 records were verified, independent receipt comparison passed before cleanup, and zero synthetic files remained. No receipt was fabricated. A real transport error stops this diagnostic run and retains pending evidence; it does not retry indefinitely or change origin.

## 5. Exact local verification

PowerShell setup for Python commands, process-local only:

```powershell
$env:PYTHONPATH="$((Resolve-Path src).Path);$((Resolve-Path .venv-server/Lib/site-packages).Path)"
$stage4bPython='build/stage4b/physical-01/student-venv/Scripts/python.exe'
```

| Command (repository root unless specified) | Final result |
| --- | --- |
| `& $stage4bPython -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_stage4b_synthetic.py tests/teacher_server/test_stage4b_deadline.py tests/teacher_server/test_live.py::test_relay_trace_is_bounded_owned_and_survives_stop tests/teacher_server/test_live.py::test_relay_rejection_trace_never_copies_invalid_frame_payload -q --tb=short` | **9 passed**, 12.54 s |
| `& $stage4bPython -m pytest --confcutdir=tests/teacher_server tests/teacher_server/test_live.py tests/teacher_server/test_demo_loopback.py tests/teacher_server/test_sync.py -q --tb=short` | **79 passed**, 18.73 s; ran before the additive counter test above |
| `& $stage4bPython -m pytest tests/test_stage4b_request_diagnostics.py tests/test_events.py::test_brief_instability_keeps_same_event_and_peak_confidence tests/test_events.py::test_positive_after_expired_hysteresis_starts_new_candidate tests/test_events.py::test_sustained_detection_activates_once_and_returns_copies tests/test_events.py::test_duplicate_and_reordered_observations_do_not_advance_or_clear tests/test_events.py::test_interrupt_closes_active_resets_candidate_and_drops_queued_samples -q --tb=short` | **12 passed**, 0.17 s |
| In `desktop`: `node --import tsx --test --test-isolation=none tests/live-screen-owner.test.ts tests/review-event-cache.test.ts tests/review-warning.dom.test.mjs` | **25 passed** |
| In `teacher-web`: `node --import tsx --test --test-isolation=none tests/viewer-recovery.test.ts` | **12 passed** |
| `node --test scripts/stage4b_synthetic/observer.test.mjs` | **1 passed** |
| In `desktop`: `npm run typecheck` | Passed |
| In `teacher-web`: `npm run build` | Typecheck and source build passed |
| `node -e "require('./teacher-web/node_modules/esbuild').buildSync({entryPoints:['scripts/stage4b_synthetic/observer.mjs'],bundle:true,format:'esm',outfile:'teacher-web/dist/assets/stage4b-synthetic-observer.js'})"` | Passed |
| PowerShell AST parse of `exposure.ps1`; `node --check scripts/stage4b_synthetic/sender.mjs` | Passed |
| `run.py relay --run build/stage4b/synthetic-02` **without** approval flag | Rejected before admission/network, expected exit 1 |

Counts are per invocation, overlap, and must not be summed as unique coverage. The final local relay generated nine frames, enqueued nine, received/accepted eight ACKs, and stopped with requested `teacher_stopped`. The production browser test asserts at least eight canvas presentations and relay transport. Final numeric artifacts: `local-relay-results.json` and `local-sync-results.json` in the prepared run.

The new integration uses real TLS sockets and authenticated WSS. Python and Node trust only the generated temporary test CA; headless Edge pins that certificate's SPKI for this local process. No global trust-store change or public TLS bypass. The existing gateway boundary is additionally exercised over real loopback sockets. Synthetic capture/native adapters are explicitly distinguished from real capture.

Initial fixture development exposed a test-page CSP mismatch and a synthetic summary start timestamp mismatch; both were corrected in the fixture. The production immutable-start guard was retained. OpenSSL/esbuild/Edge subprocess execution required the targeted sandbox escalation. Final invocations above passed. Existing Starlette/httpx deprecation warning remains.

Delayed (8 s), duplicate and out-of-order ACK rejection, lease expiry, stale clearing and stale-command non-replay are **local deterministic checks**. The proposed public sustained run does not inject arbitrary ACK corruption or claim those adversarial cases were exercised on a separate network. The synthetic client refuses unexpected teacher commands; it does not implement or replay them.

## 6. Disposable setup and security review

Prepared run: `build/stage4b/synthetic-02`, planned loopback API port **8035**. Its `config.json` still has no public origin. Fresh database: one disposable teacher, zero attempts, zero receipts. Password and fixture seed are in a separate DPAPI-encrypted journal; do not print them into diagnostic logs or this report. Arrange disposable account access privately with the operator after approval.

`prepared-hashes.json` seals 109 source/build files, including server/client protocol sources, sender adapters, teacher distribution, observer, launch scripts and dependency lockfiles. Exposure rejects a changed hash. Revalidate rather than silently resealing changed code after approval. Existing runtime installations are reused read-only; test-only PYTHONPATH supplies their already-installed dependencies. No shared package installation or operator configuration was modified.

Security controls retained: exact generated HTTPS origin, Secure teacher cookie/CSRF, owner-scoped viewer lease and diagnostic export, consent v2, authenticated student control, bounded relay/latest-frame storage, valid source protocol, authorization expiry and cleanup. Synthetic consent/health represent declared fixture state only, never human consent, readiness or monitoring proof. No external credentials, paid service, firewall or router change.

The existing launcher records PID, owner, executable, command and creation time. Startup refuses an occupied port; shutdown verifies identity before stopping only recorded processes. The new wrapper starts an independent **900-second maximum** guard first. Shutdown begins at deadline minus 60 seconds, leaving the final minute for the ownership-aware Stop timeout. Clients stop at the same earlier boundary. No new hostname, automatic reopening or retry after a failed exposure is permitted. Guard tests verify approval, one-shot deadline records, bounded Stop invocation and early-close behavior without launching/killing processes.

Before Pin/Start, recheck the independent guard PID/identity is alive, deadline still valid, assigned origin unique in the owned tunnel log, and port ownership. If identity differs, stop and ask; never terminate the mismatched process. After early verified shutdown, write `closed.json` only after owned processes are confirmed gone so the guard can exit. Preserve all logs/databases/results.

## 7. Proposed public procedure — DO NOT EXECUTE before approval

Maximum **15 minutes**, including tunnel creation and shutdown. Have the remote teacher ready before starting the clock. One exposure, one synthetic relay viewer, one separate synthetic synchronization attempt. No real student app or physical exam.

1. Reverify sealed hashes and existing process ownership; preserve existing websites/services. Verify the cloudflared binary against `build/stage4b-tools/2026.10.0/verified-release.json` (SHA256 `86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c`). Invoke:

   ```powershell
   & scripts/stage4b_synthetic/exposure.ps1 -RunDirectory "$PWD/build/stage4b/synthetic-02" -Cloudflared "$PWD/build/stage4b-tools/2026.10.0/cloudflared.exe" -CloudflaredSha256 '86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c' -OperatorApprovedPublicExposure
   ```

2. Use existing `scripts/stage4b-demo.ps1 -Action Pin` with the **new exact assigned origin**, then `-Action Start -OperatorApprovedPublicExposure` for this run. No old hostname. Verify HTTPS and rejection of unauthenticated/foreign-origin requests; any critical authorization/security failure ends the run immediately.
3. Remote teacher signs in to the disposable account on a confirmed different network, uses English UI, then installs the same-origin observer:

   ```javascript
   (await import('/assets/stage4b-synthetic-observer.js')).start(DEADLINE_MINUS_60_SECONDS_IN_EPOCH_MILLISECONDS)
   ```

   Replace the numeric argument with the coordinator's actual independently enforced deadline, never an invented extension. Confirm observer active before starting the viewer.
4. Run `& $stage4bPython scripts/stage4b_synthetic/run.py relay --run build/stage4b/synthetic-02 --operator-approved-public`. The server creates synthetic metadata only. On coordinator signal, teacher opens **one** viewer and observes continuously for at least **120 seconds from the first actual frame**, checking numbered images continue changing. Retain viewer identity, actual FPS, ACK round-trip values, freshness gaps, fallback and lease evidence. Do not fail just for FPS below 5.
5. On success, use **Stop and save numerical diagnostics**. Confirm `teacher_stopped`, sender cleanup, and the saved JSON contains both teacher and owned-server traces. No new viewer. On any unexpected terminal failure, the harness preserves the first diagnostic and ends; save browser/server evidence before shutdown and mark failed. Do not restart. If server export fails, preserve available teacher evidence and the authenticated browser while investigating the export; do not claim complete diagnostics.
6. Only if relay/security checks permit continuing within the original deadline, run `& $stage4bPython scripts/stage4b_synthetic/run.py sync --run build/stage4b/synthetic-02 --operator-approved-public`. This is a separate synthetic admission with no device workflow. Observe multi-chunk retry/frontier and final verified receipt/cleanup. If actual `context canceled` or another transport failure recurs, preserve HTTP phase/status/offset/size/duration and owned server logs; retain evidence and stop. No timeout increases or speculative fixes during the experiment.
7. Export all owned-viewer diagnostics **before** server shutdown; confirm the remote JSON is saved. Remote teacher logs out and closes the tab. Run existing `stage4b-demo.ps1 -Action Stop` for this run only, verify process exit, record `closed.json`, preserve results and report. Never restart exposure automatically.

Public synthetic sender/sync traffic originates here and traverses Cloudflare. That is a public-endpoint test, **not a remote-student topology**. Only the confirmed remote teacher browser counts as a genuinely separate network. Successful synthetic tests cannot establish real webcam, gaze, capture, exam or protected-mode behavior.

## 8. Remaining limitations and approval request

Historical physical relay interruption and Cloudflare upload cancellation remain unresolved until the new traces identify the actual phase. The timestamp-cache defect is demonstrated locally; its correction is not yet a public stability result. Real direct WebRTC negotiation, physical warning jitter, remote student behavior and protected operation remain unverified. No public throughput or physical PASS is claimed.

Skipped: full Python/Electron/Playwright suites, live webcam/microphone/monitor capture, real exams, keyboard blocking, native protection audits, protected tests, packaging, public deployment, load tests, Stage 4C/4D.

**Approval requested:** one public Quick Tunnel exposure, maximum 15 minutes including shutdown, using this fresh isolated database/disposable account; one ≥120-second synthetic relay session to a teacher browser on a confirmed different network, plus one separate synthetic multi-chunk synchronization attempt. No physical devices or exam. Stop on first unexpected terminal/security failure, preserve diagnostics and pending evidence, no automatic restart. Wait for explicit approval before any public launch.

## 9. Authorized execution result — 2026-10-14

The operator subsequently authorized the single bounded run. Synthetic separate-network relay passed; synchronization failed at admission before upload. Exposure closed within 697.384 seconds. See [the execution report](TEACHER_DASHBOARD_STAGE4B_SYNTHETIC_PUBLIC_TEST.md). Overall Stage 4B remains incomplete. Earlier proposal and approval-request sections above are historical preparation state.

