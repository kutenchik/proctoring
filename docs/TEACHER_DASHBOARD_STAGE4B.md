# Stage 4B — Free HTTPS demo deployment

2026-10-14, Asia/Qyzylorda. **Implemented and tested locally; separately authorized public tunnel-only check PASSED (24 assertions and operator-confirmed remote teacher login/dashboard/logout). Physical cross-network student verification NOT performed.** See [bounded public-check report](TEACHER_DASHBOARD_STAGE4B_TUNNEL_CHECK.md). The owned public tunnel/API are closed. No protected validation, packaging or later stage was started.

## Acceptance record and implementation plan

The operator explicitly authorized Stage 4B with the recorded Stage 4A limitations. This supersedes the earlier administrative block on proceeding; it does **not** rewrite the physical result as full PASS. [The original physical report](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_PHYSICAL_RETEST.md) remains evidence: 812 frames / 272.0107 s, 2.9815 delivered FPS; sustained webcam-visible interaction, movement/resize/minimize/restore, teacher Stop, verified receipt and local cleanup passed. The 5–10 FPS target was not met. The separate fresh-viewer 30-second check was incomplete because the observer inherited the old viewer's safety clock. Both limitations are explicitly deferred, not resolved by this stage.

The implementation plan was: inspect existing authority/authentication; verify official tunnel guidance; add one restrictive same-origin boundary around the existing application and built frontend; provide isolated ownership-aware Windows launch commands; exercise focused synthetic/local transport tests; stop before public exposure. Existing dirty working-tree changes and old databases/evidence were preserved.

## Architecture and routing

```text
Teacher browser / Electron-owned student HTTP and WS clients
  -> exact https://<assigned>.trycloudflare.com (HTTPS/WSS)
  -> Cloudflare edge / outbound cloudflared connector
  -> http://127.0.0.1:8034
  -> DemoGateway + ONE existing FastAPI app / ONE Uvicorn worker
       / and explicitly inventoried built assets: teacher-web/dist
       /api/v1/*: existing authenticated API, control sockets and stream relay
       everything else: reject
  -> NEW isolated SQLite database and evidence directory for this demo
```

`src/proctoring_server/demo.py` adds an ASGI boundary, not a second live-state application. `create_demo_app` creates exactly one existing FastAPI service. The Stage 4B database is intentionally new and isolated; it is never a copy of historical personal data. Existing Stage 4A service/website ownership is unaffected. Vite is not exposed. No inbound firewall or router change is needed or implemented.

The frontend serves `/`/`index.html` and an explicit inventory of built assets, samples and licenses. Source maps, dotfiles, source files, database/configuration/evidence directories and directory browsing are not mounted. File containment is checked, symlink escapes are rejected, and asset reads are bounded. Teacher reports/evidence remain behind the original authenticated ownership checks under `/api/v1`, not a static evidence mount.

## Cloudflare documentation checked

Official sources checked on 2026-10-14:

- [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/): account/domain-free temporary hostname, development use, no uptime guarantee, 200 in-flight requests, no SSE and hostname changes after restart.
- [Email authentication announcement](https://developers.cloudflare.com/changelog/post/2026-10-02-protected-quick-tunnels/): optional `--allowed-mail` challenge. The Quick Tunnel documentation explicitly states this needs an interactive browser and does not support non-interactive clients. **Do not enable it here:** Python/Electron HTTP, upload and WS clients do not participate in that challenge. Application teacher/student authentication stays mandatory.
- [Official Windows downloads](https://developers.cloudflare.com/tunnel/downloads/) point to Cloudflare's GitHub releases; Windows binaries require manual updates. The release page resolved to [2026.10.0](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.0) at inspection.
- [WebSocket support](https://developers.cloudflare.com/network/websockets/) describes proxied WebSockets and warns that edge restarts can terminate connections. It is not a guarantee for this application's duration/performance.

At the initial local checkpoint no binary or tunnel had run. The later separately approved check downloaded and SHA-256 verified official cloudflared 2026.10.0, ran one bounded tunnel, then closed it; see the linked public-check report. Budget remains 0 KZT: no domain, account subscription, VPS, external STUN/TURN purchase or other paid resource. Existing network/data costs are outside that software budget. Cloudflare terminates public TLS; the own-server relay is authenticated but is not an application-level end-to-end encryption claim against the tunnel provider. Use disposable data for the approved demo.

## Public-origin security

- Exact lowercase HTTPS Quick Tunnel origin only, no wildcard, port, path, credential or suffix match. Frontend and API settings must be identical; public mode rejects the HTTP development exception.
- Listener binds only `127.0.0.1`. The gateway checks the actual socket peer is loopback, exactly one matching Host header, and exactly one `X-Forwarded-Proto: https`. Conflicting, missing or duplicate values fail closed. A present Origin must exactly match the pinned origin.
- Uvicorn runs with `--no-proxy-headers`. The gateway discards Forwarded, X-Forwarded-* and CF-* before dispatch. It never trusts a forwarded client IP, host or arbitrary scheme. Logical HTTPS/WSS is set from the pinned configuration after the boundary checks. The HTTPS marker is required, not blindly used to construct URLs or grant privileges.
- This is not a security boundary against another process running as a local user. Such a process can mimic loopback tunnel headers, but still needs application credentials. Application permissions and secrets remain essential.
- Teacher cookies retain Secure, HttpOnly, SameSite=Strict and `/api/v1` scope. Existing exact Origin and CSRF mutation checks, teacher ownership, attempt bearer/device-secret checks, short-lived viewer leases and consent v2 are preserved. Invitation/reset links use the configured origin and keep one-use tokens in fragments. No email challenge, public registration or debug docs endpoint is added.
- Public errors hide raw ValueError text; unexpected exceptions do not expose tracebacks through the boundary. No request body/frame logging is introduced. Local operational logs are private and are not static routes.
- Browser policy permits only same-origin scripts/fonts, required inline styles, local/blob/data images, and same-origin/the exact WSS origin; framing and base tags are denied. Responses are no-store and nosniff with no-referrer and HTTPS HSTS.
- Deployment-wide bounds: 600 HTTP/WS initiation requests per rolling minute, 30 auth mutation/admission requests per minute, 16 concurrent HTTP operations, 32 concurrent WebSockets, 30-second HTTP operation timeout. Budgets use bounded deques and actual connections, not spoofable forwarded IPs. They are small-demo limits, not capacity certification. Shared limits and existing loopback-IP login throttling can deny legitimate users under abuse; do not claim Internet-scale availability.
- Original 3 MiB raw request, 256 KiB upload chunk, stream message/frame/queue/rate/lease limits remain. Uvicorn uses max 393216-byte WS messages, queue 8, no WS compression, concurrency/backlog 64, one worker and no access logs. Relay remains latest-frame-only memory, 5 FPS and 1.5 MiB/s per sender maximum; it does not guarantee those rates.
- Server HTTP development settings now accept only literal loopback IPs, aligning with the existing student rule. `http://localhost` is rejected even with the development opt-in; use `http://127.0.0.1` for those local configurations. Remote certificate verification is unchanged and mandatory.

## Windows setup and exact commands

Run from the repository root in PowerShell. These are **instructions for later approved execution**, not a record that public commands ran. Keep the existing website/services untouched.

Prerequisites: the existing `.venv-server` with `server/requirements.lock.txt`, Node dependencies in `teacher-web`, and a freshly built frontend. If setting up a separate computer, use the existing server README venv instructions. Do not install server libraries into the desktop environment.

```powershell
Set-Location 'C:\Users\kuten\Desktop\case3_proctoring'
Push-Location teacher-web
npm run build
Pop-Location
$demoRun = Join-Path $PWD 'build\stage4b\demo-01'
.\scripts\stage4b-demo.ps1 -Action Prepare -RunDirectory $demoRun -Port 8034
```

Prepare refuses an existing directory and creates no listener/account/database/tunnel. The root must be a child of `build/stage4b`. Use a new name for a new demonstration; never point at Stage 4A data.

Download the verified official standalone Windows amd64 binary (no service installation):

```powershell
.\scripts\get-stage4b-cloudflared.ps1 -Version '2026.10.0'
$cfBinary = Join-Path $PWD 'build\stage4b-tools\2026.10.0\cloudflared.exe'
$cfRelease = Get-Content 'build\stage4b-tools\2026.10.0\verified-release.json' -Raw | ConvertFrom-Json
```

The download script queries only the official `cloudflare/cloudflared` release, requires its exact stable tag, expected asset URL and SHA-256 digest, downloads with normal TLS verification, checks the bytes, and saves provenance. If the official digest is unavailable or differs, it stops; do not bypass verification. The script passed syntax checks, but its actual PowerShell download stalled. A bounded official HTTPS range-download helper completed the binary and verified the entire official SHA-256; the stock script is not claimed to have completed successfully. Recheck the official release before a substantially later demo.

**Approval gate:** obtain explicit operator permission for the public tunnel and service exposure before the following commands. The switches are deliberate safeguards, not implied permission from this report.

```powershell
.\scripts\stage4b-demo.ps1 -Action Tunnel -RunDirectory $demoRun `
  -Cloudflared $cfBinary -CloudflaredSha256 $cfRelease.sha256 `
  -OperatorApprovedPublicExposure
Get-Content (Join-Path $demoRun 'tunnel.stderr.log')
Get-Content (Join-Path $demoRun 'tunnel.stdout.log')
```

The tunnel first targets a **closed** loopback port, so no application is exposed during hostname discovery. It is still a public tunnel and still needs permission. No `--allowed-mail` flag is used. Metrics bind to loopback. The script refuses an occupied port and preexisting user cloudflared config files instead of replacing/deleting them. It records the process PID, creation timestamp, executable, owner and full command line. This command does not download anything or start the backend.

Copy the one generated URL from those owned tunnel logs. Never substitute a hostname supplied by an unrelated message. Pin validates that the supplied origin uniquely matches that process's logs and that its recorded identity still matches:

```powershell
$demoOrigin = Read-Host 'Exact HTTPS URL printed by this tunnel'
.\scripts\stage4b-demo.ps1 -Action Pin -RunDirectory $demoRun -PublicOrigin $demoOrigin
.\scripts\stage4b-demo.ps1 -Action Start -RunDirectory $demoRun -OperatorApprovedPublicExposure
.\scripts\stage4b-demo.ps1 -Action Invite -RunDirectory $demoRun -Email 'disposable-teacher@example.edu'
# If needed, issue a new one-use reset privately:
.\scripts\stage4b-demo.ps1 -Action Reset -RunDirectory $demoRun -Email 'disposable-teacher@example.edu'
```

Use an operator-chosen disposable account address. Share the invitation privately, never in diagnostics. Start verifies tunnel identity and free port, sets both origins to the pinned value, disables the HTTP exception, uses the new isolated DB/evidence, records source/build hashes and verifies the actual listener belongs to its recorded process tree. It never starts Vite, the student app, devices or capture. Process windows are hidden. The dashboard and student server-address field use **the same `$demoOrigin`**; students also enter exam code, full name, group and institutional student ID.

After exposure is approved, confirm HTTPS login and the built UI from the intended browser before admitting a student. Do not work around a Host/proto/Origin rejection by widening the whitelist. Preserve the error and inspect the actual edge header behavior. The later bounded check passed actual edge headers, browser rendering, authentication and WSS; see the public-check report.

Normal shutdown: finish/synchronize the disposable exam and explicitly stop viewing first. Then close public ingress before the server:

```powershell
.\scripts\stage4b-demo.ps1 -Action Stop -RunDirectory $demoRun
```

Stop rechecks PID, creation time, executable, owner and full command before termination; a reused/different process fails closed. It stops only recorded tunnel/server processes, not a port owner found by guesswork. Database/evidence/logs/ownership records are retained. Confirm ports/processes afterward; do not kill unrelated services to resolve conflicts.

For a separately authorized **server-only** restart with the SAME running tunnel/URL and SAME database:

```powershell
.\scripts\stage4b-demo.ps1 -Action Restart -RunDirectory $demoRun -OperatorApprovedPublicExposure
```

Restart verifies tunnel/server identities and port ownership, preserves the old ownership record, and starts one replacement server. In-memory presence/viewers are lost, so fresh authenticated connections and a new authorized viewer are required. Durable attempts/evidence/commands stay in the same database. The full start/restart/stop launcher was exercised locally with a harmless sleeping process standing in for cloudflared, a real loopback Uvicorn server and a persistent database marker. Do not use a server restart as a way to preserve an old viewer lease.

## Student connectivity and changed tunnel URL

Existing client behavior remains authoritative: normal verifying TLS, no HTTP redirects, no inherited proxy credentials, exact server origin, only a successfully verified address remembered, and admitted attempts bound to the original device and durable server origin. Network loss affects online status/synchronization, not the local exam clock. Reconnection to the same valid origin authenticates the original attempt/device; interrupted process recovery still requires its existing teacher authorization/readiness gates.

| Event | Effect / supported response |
| --- | --- |
| Temporary network loss, same tunnel still alive | Offline/stale status; local exam continues; bounded reconnect and durable retry to the original origin. Viewing needs fresh valid authorization after disconnect. |
| Backend restart, same tunnel URL/database | Old live leases disappear; teacher/student reconnect/authenticate; durable state remains. No automatic old-lease capture. |
| Tunnel stops/restarts with a new hostname | Existing sockets break. Old browser cookie is not transferred to a new host; fresh login and new origin-specific invitation/reset links as needed. |
| Existing admitted/pending student attempt and new hostname | **Automatic migration is unsupported and deliberately blocked.** The client remains pinned to the old origin; it does not send bearer/device secrets to the new one, create a duplicate attempt or reset the timer. Pending local evidence is retained. |
| New disposable attempt after a changed URL | New explicit origin verification and admission; does not recover an old attempt. Preserve old journal/evidence, and do not delete pending attempts just to admit again. |

There is no stable server identity/certificate-pinning migration protocol in the current application. A valid HTTPS endpoint plus the public health response identifies a compatible service, not proof that a new hostname is the old operator's server. Therefore a lost Quick Tunnel can strand pending delivery until a separately designed authenticated migration or stable-host deployment exists. Finish and verify receipts before planned tunnel shutdown. Do not promise URL-change recovery or manually rewrite encrypted journals.

## Direct transport, relay and stale-view handling

No streaming implementation was replaced. Host-only ICE and no external STUN/TURN mean direct WebRTC often cannot cross NAT. The existing teacher timeout is 8 seconds; its authenticated transport notification switches to the own-server WSS relay. The loopback test explicitly simulated direct timeout and verified relay frame/ACK exchange, renewal and ordered Stop. It did not establish real NAT traversal or Cloudflare throughput.

Consent v2 and the webcam-visible monitor policy are unchanged. The webcam appears only where it is actually visible on the monitor; a covering app/minimization may hide it until restore. No second camera, audio media, separate webcam stream, recording or remote input control was added. Stale images are hidden after the existing 3-second bound. Stream frames never enter the database/outbox; latest-only buffers, deadlines, viewer identity and cleanup still apply. Losing network cannot reuse an expired cached lease.

## Targeted verification — initial local checkpoint

**77 distinct focused tests passed.** No full Python/Electron/Playwright suite ran. Initial WebSocket fixture hostname mismatch was fixed in the test. Sandbox-only Vite process-spawn and CIM access restrictions were resolved by rerunning those specific local checks with the required process access; no public action was performed. Full launcher testing also caught Windows PowerShell file-hashing compatibility and JSON array handling issues; these were corrected with .NET SHA-256 and explicit process-record array normalization. The test harness now uses files instead of inherited output pipes to avoid a Windows descendant-handle wait. The temporary test server was identity-verified and closed before rerunning successfully.

| Target | Final result |
| --- | --- |
| `tests/teacher_server/test_demo.py` | 12 passed: exact origins, Host/proto spoof rejection, static/private routes, cookies/CSRF/invite/reset, socket auth, budgets, body bound, safe errors |
| `tests/teacher_server/test_demo_loopback.py` | 1 passed: real loopback TCP/WS through new boundary, admission/consent v2, authenticated synthetic relay/ACK/renew/Stop; owned listener cleanup |
| `tests/teacher_server/test_demo_script.py` | 5 passed: isolated prepare, no implicit launch, bad path/wildcard refusal, reused identity rejection, owned fixture cleanup, full real loopback server start/restart/stop with database preservation and no actual tunnel |
| `tests/teacher_server/test_auth.py` | 21 passed, including literal-loopback exception correction |
| Selected `tests/teacher_server/test_live.py` | 8 passed, 35 deselected: cross-teacher rejection, expiry, lease renewal/reconnect, relay memory/fallback, consent v1 rejection, cookie/CSRF/owner |
| Selected connected client / Stage 2 API tests | 13 passed, 12 deselected: origin/TLS/no-redirect behavior, synthetic real-server receipt/retry/recovery continuity |
| New admitted-origin-change client test | 1 passed, 21 deselected: no credential/attempt/deadline migration or duplicate admission |
| Teacher `viewer-recovery.test.ts` | 10 passed: stale image clearing, fresh lease rules, cleanup/Stop |
| Desktop `live-screen.test.ts` | 6 passed: frame bounds, consent/lease policy, HTTPS/WSS and relay/direct assembly |
| Teacher `npm run build` | TypeScript and built frontend passed; no source maps |
| Changed server Python compile checks | Passed |
| Cloudflared download script | PowerShell parse passed; download/execution not performed |

The old desktop source/capture code was not rebuilt or changed. No camera, microphone, screen capture, human exam, protection/recovery audit, keyboard blocking, packaging, deployment, load test or Stage 4C/4D was run. Tests use temporary databases and synthetic bytes; the existing teacher website on port 5178 was preserved.

## Separate approval and network test plan

The separately approved bounded tunnel-only HTTPS/WSS check is now complete; see the linked report. The operator confirmed a remote teacher browser on another network and availability of a second Windows student PC. A Windows student PC on a genuinely separate network is needed for remote-student validation. A remote teacher browser over cellular, with student/server on one PC, is only partial remote-teacher evidence. Label localhost, LAN, remote teacher, remote student and full cross-network results separately.

After public-edge checks pass, obtain **separate physical-test approval** before any devices or monitor capture. Proposed one disposable UNPROTECTED run, maximum 15 minutes plus normal synchronization/cleanup:

1. Verify source identity, new database/evidence paths, process owners, exact pinned origin and disabled protection/restrictions. Use only disposable identities. Establish HTTPS teacher login, create a native quiz/exam code, then student public-origin verification and admission.
2. Operator manually accepts consent v2, completes devices/calibration/readiness and starts. Never bypass those gates. Confirm online status, actual monitor and visible preview.
3. Record 30 seconds idle from the first displayed frame and at least 180 seconds of clicks, navigation, scrolling, focus/movement/resize/minimize/restore. Record actual transport, not desired transport. If direct fails, observe the authenticated relay outcome separately.
4. Exercise warning, pause/resume, reasoned time extension; verify actual authoritative outcomes. Briefly disconnect the student network with operator coordination while the tunnel process stays alive; distinguish offline/stale from ended. Restore the same origin and verify reconciliation, no clock reset and fresh authenticated viewer authorization.
5. Explicit Stop, verify cleanup/reason, then at most one approved fresh viewer for a full 30 seconds. Its observer safety clock must bind to the **new actual viewer ID**, not inherit the previous Start timestamp. Preserve the first failure and stop rather than repeatedly restart.
6. End normally, wait for real complete server receipt, independently match attempt/session/manifest/file counts, verify local cleanup only after receipt, inspect original/reviewed reports and XLSX under teacher ownership. Missing receipt means retain local evidence and fail that check.
7. Close student normally, confirm controls, stop the owned tunnel first and server second, preserve numeric results and account/evidence isolation. Do not continue into protected validation or packaging.

### Measurements and honest result levels

Collect bounded per-run numeric samples (maximum 1800 samples), no HAR/body dumps, screenshots, webcam images or stream recordings. Keep credentials, cookies, tokens, participant content and URLs with secrets out of diagnostics. Existing viewer metrics provide delivered count/FPS and capture-to-display-ACK round trip; the latter is not one-way latency. Count only numeric message byte lengths for relay frame sizes/throughput; never persist frame payloads. Use request outcome/status counters, socket connection/reconnect durations, presence-transition times, selected transport, sampled CPU/memory, upload bytes/duration, receipt timestamps and safe tunnel error codes. Any additional observer must be inspected before the physical run, including the fresh-viewer timer correction.

| Evidence level | Status |
| --- | --- |
| Implemented | Single-origin boundary, isolation/start/stop/restart scripts, download verification procedure, runbook |
| Tested locally | Focused synthetic auth/security tests, real loopback relay and sync, builds, command safety |
| Tested through public tunnel | PASS: 24 bounded public HTTPS/WSS assertions; tunnel/API closed |
| Remote teacher from a different network | PASS: operator confirmed account creation, login, dashboard, no certificate warning and logout |
| Remote Windows student | NOT TESTED |
| Full cross-network physical integration | NOT TESTED |
| Remote FPS/ACK latency/upload throughput | NOT MEASURED; no frames/devices |
| Tunnel-only resource sample | 111.85 MiB summed owned-process RSS over 9.005 s; not streaming/load |
| Local physical comparison baseline | Stage 4A: 2.9815 FPS, ACK median 261.8152 ms / p95 295.1337 ms; not a remote guarantee |

## Remaining risks and later stages

Actual Cloudflare header acceptance, browser rendering and basic authenticated WSS passed the later bounded check. WSS longevity, relay throughput, broader public error behavior and remote upload durability still require separately approved tests. This stage does not establish production hardening, uptime or capacity. Rate limits bound work but cannot prevent every availability attack. TLS, provider access and new URL trust require care; pending attempts cannot silently migrate. The genuine hash-verified cloudflared launch and owned shutdown passed the bounded public check. The stock PowerShell download stalled; the verified download fallback is documented in the check report.

Before Stage 4C/4D: obtain separate scope/approval, retain exact source/policy identity, resolve the relevant acceptance criteria and run their matching safety/recovery or packaging verification. Earlier physical results cannot certify changed protected builds. No requirements for those stages are considered completed here.

**Next execution gate:** separately authorize any bounded UNPROTECTED remote-student physical test. The tunnel-only authorization has been used and its processes are closed. No full cross-network physical PASS is claimed; no additional tunnel, exam or devices will start without approval.

## Cross-network physical preparation update

See [the prepared Machine B setup, corrected observer, exact execution gate and bounded test plan](TEACHER_DASHBOARD_STAGE4B_PHYSICAL_PREPARATION.md). The new teacher observer keys its clock to each actual viewer identity and measures from the first displayed frame; historical scripts/evidence are unchanged. Proposed total public exposure is 30 minutes including setup and synchronization, superseding the earlier 15-minute-plus-cleanup proposal only if explicitly approved. No new tunnel or physical test has started.

## Authorized remote-teacher physical result

The operator revised the topology to colocated server/student and a teacher on another network. The single authorized run FAILED sustained viewing (8 relay frames over 9.1808 seconds, approximately 0.8714 FPS; sender first failure frame_delivery_unavailable) and synchronization (1/6 artifacts complete, no receipt). All six local artifacts were retained and hash-verified. Public tunnel/API closed within the 30-minute budget; no automatic restart or fix was applied. See [actual physical measurements and cleanup status](TEACHER_DASHBOARD_STAGE4B_PHYSICAL_TEST.md). Remote student connectivity and full cross-network integration remain untested. Stage 4B is not accepted.

## Follow-up relay, synchronization and warning investigation

[The focused investigation report](TEACHER_DASHBOARD_STAGE4B_RELAY_SYNC_UI_FIX.md) documents the demonstrated ACK timestamp-eviction defect, event-cache replay ordering fix, bounded numerical diagnostics and HTTP error classification correction. Targeted local checks passed. The historical physical relay interruption and public upload interruption remain incompletely explained; Stage 4B remains unaccepted. The operator now treats low FPS as informational, prioritizing sustained usable viewing, commands, evidence synchronization and stable ongoing warnings. No further public or physical run was started.
