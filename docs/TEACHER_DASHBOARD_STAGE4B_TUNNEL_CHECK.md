# Stage 4B — Authorized tunnel-only check

Date: 2026-10-14, Asia/Qyzylorda (UTC+5). This report covers the separately authorized single, maximum-15-minute public Quick Tunnel check. It does not authorize or claim a physical student exam.

## Scope and identity

The operator approved public HTTPS/WSS connectivity using a new isolated database and disposable accounts, and stated that a second Windows student PC and remote teacher browser are available. Camera, microphone, screen capture and real student exam start were explicitly excluded.

- Run directory: `build/stage4b/public-check-01`.
- Public origin assigned by the owned tunnel: `https://creations-prayer-don-shield.trycloudflare.com`.
- Local origin: `127.0.0.1:8034`; one authoritative Uvicorn worker and the built teacher frontend.
- New database/evidence: this run's `teacher.sqlite3` and `evidence/`. No historical database was copied or exposed.
- Cloudflared 2026.10.0, 55,365,048 bytes, SHA-256 `86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c`, matched against the official Cloudflare GitHub release asset digest.
- Tunnel PID 27268, creation `2026-10-14T09:25:11.1837670Z`, recorded owner/executable/full command. Source hashes, actual server process identities and exact isolated environment were verified and preserved in the run artifacts.
- Existing teacher website PID 10812 / port 5178 was verified before the check and was not restarted.
- Exposure budget started at epoch `1791969910.0467887` (14:25:10.047 local); deadline `1791970810.0467887` (14:40:10.047 local). An independent deadline guard was launched to call the ownership-verifying Stop script at the deadline.

## Public endpoint results

**24 automated assertions passed through the real public endpoint from the developer PC.** This is public Cloudflare-edge evidence, not proof that the initiating client was on a genuinely different network.

| Check | Actual result |
| --- | --- |
| HTTPS health and built teacher page | 200; frontend security policy present |
| Database path is not browsable | 404 |
| Unauthenticated teacher and student API | 401 |
| Foreign HTTP Origin | 403 |
| Disposable invitation acceptance | 200 |
| Teacher login and authenticated access | 200 |
| Secure / HttpOnly / SameSite=Strict cookie flags | Present |
| Mutation without CSRF | 403 |
| Disposable password reset and re-login | 200 |
| Authenticated library read and empty exam metadata creation | 200 / 201 |
| Authenticated WSS teacher snapshot | Received, 875 ms including socket establishment and initial authenticated snapshot |
| Three WSS ping/snapshot exchanges | 281, 312, 282 ms |
| Foreign WebSocket Origin | HTTP handshake rejected, 403 |
| Anonymous teacher WebSocket | `login_required` |
| Anonymous student WebSocket | `invalid_credential` |
| Logout and subsequent session access | 200, then 401 |

The 16 HTTP checks comprised ten expected 2xx responses and six expected denials. Their observed request durations were 313–1203 ms, median 554.5 ms. These are a small sequential connectivity sample, not a load test or throughput guarantee. WSS ping/snapshot timing is application-message round trip; **no capture-to-display-ACK latency was measured** because no screen frames were sent.

A separate browser on the developer PC rendered the actual public login UI with a visible Sign in button and no console errors in the bounded inspection. No screenshot was saved. This confirms the built UI loaded through the edge in that browser; it does not substitute for remote operator confirmation.

The tunnel registered using QUIC. That is the **cloudflared-to-Cloudflare connector protocol**, not direct WebRTC or application screen-relay transport. No WebRTC, screen relay frame delivery, FPS, webcam visibility, student presence transition, upload throughput or final receipt was measured in this check.

## Remote browser coordination

A disposable one-use invitation was provided privately in the operator question for `stage4b-remote@example.invalid`. The operator was asked to use a genuinely different network, accept the invitation, log in, and confirm network type, certificate-warning status and dashboard rendering without starting an exam/devices.

**PASS — remote teacher access, operator verified.** The operator explicitly confirmed a genuinely different network, successful invitation acceptance/account creation and login, dashboard rendering, no certificate warning, and logout. Network type was not specified. A read-only database check after shutdown independently found zero remaining sessions for that disposable account. No remote student or media claim follows from this result. The invitation token/password are not included in this report or numerical diagnostics.

## Isolation and observations

Actual server environment checks confirmed identical pinned HTTPS origins, the new database/evidence paths and `PROCTOR_ALLOW_LOOPBACK_HTTP=0`. There were **zero student attempts** at the verification checkpoint. The only exam record was explicitly named connectivity-only metadata; no admission, start authorization, device initialization, consent flow or capture was performed. Protection and keyboard-blocking code were not invoked.

Ten brief process samples over 9.005 seconds covered the owned launcher, console host, actual API and cloudflared. Summed RSS was 111.85 MiB; aggregate CPU-time delta was below the observed accounting resolution (0 seconds). This was a quiet interval, not streaming or load; summed RSS may double-count shared memory. Do not extrapolate capacity or streaming CPU from it.

The initial PowerShell binary download stalled. The first bounded full transfer hit its deadline, and a subsequent range transfer encountered a read timeout. Completed ranges were retained; bounded 64-KiB official HTTPS range downloads completed the file. Every range was checked for exact Content-Range/length and the final entire file matched the official SHA-256 before execution. No certificate checks were disabled and no unofficial binary was used. Only the identified owned downloader processes were stopped. These preparation delays occurred before the public-exposure timer.

The first WSS probe stopped before opening its socket because its local helper environment could not resolve the requested timezone. Public HTTP checks had already passed. The continuation created empty exam metadata through the actual running API, which accepted the IANA timezone, then completed WSS verification. This was a helper-environment failure, not a demonstrated public server timezone failure. No product security checks were weakened and no service restart was used to hide it.

## Shutdown verification

The ownership-verifying Stop completed successfully at approximately **2026-10-14T14:36:34.896+05:00**, closing public ingress before the isolated API. Elapsed time from the conservative exposure-budget start was **684.849 seconds**, below the 900-second authorization. This timestamp is the successful Stop log write, not an edge propagation measurement.

At **2026-10-14T14:37:09.313+05:00**, independent process/listener verification found all four recorded owned PIDs absent and no listener on port 8034. The original teacher website PID 10812 retained its exact creation time, executable and owner and continued listening on port 5178. The isolated database and evidence directory were preserved, with zero student attempts. The independent deadline guard exited successfully with `closed_early`; the owned browser-check tab was closed. No source changes or historical evidence deletion were performed during this connectivity check.

## Preserved evidence

Under `build/stage4b/public-check-01`:

- `preflight.json`, `build-identity-*.json`, `tunnel-owner.json`, `server-owner.json`, `server-config-verification.json`.
- `deadline.json`, `deadline_guard.py`, `shutdown-summary.json`, `cleanup.json`, `closed.json` and `stop-result.log`.
- `public-checks.json`, `check-summary.json`, `remote-operator.json`, `browser-check.json`, `resource-samples.json`, `resource-summary.json`.
- Private operational tunnel/server logs and bounded download diagnostics. No request body, credentials, stream payload, webcam image, screenshot or screen recording was added to numerical diagnostics.

The verified binary/provenance and incomplete download artifacts remain under `build/stage4b-tools/2026.10.0`. These runtime directories are not mounted publicly.

## Acceptance boundary

**PASS for this bounded tunnel-only check:** public HTTPS/WSS endpoint connectivity, the listed authentication/route checks and operator-confirmed remote teacher access. All 24 automated assertions passed; required operator checks passed. No further public or physical run is authorized by this result. Full Stage 4B cross-network integration is **not** established by them. Remote Windows student admission, normal readiness/exam start, commands during a real exam, direct-vs-relay screen transport, network interruption/recovery, durable synchronization and receipt/cleanup still need their separately approved bounded test.

Stage 4A's accepted limitations remain unchanged: approximately 2.98 physical delivered FPS was below the 5–10 target, and the separate fresh-viewer 30-second check was incomplete due to the observer safety timer. No new performance claim is made. No full regression suite, protected audit, packaging, firewall/router change, paid service, Stage 4C or Stage 4D work was performed.
