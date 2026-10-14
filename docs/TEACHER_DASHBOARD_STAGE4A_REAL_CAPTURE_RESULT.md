# Stage 4A — isolated real Windows capture result

14 October 2026, Asia/Qyzylorda (UTC+5).

**Result: `capture_geometry_changed` reproduced during operator-confirmed window
movement. Exact failed operands: `content_x` and `content_y`, at `after_sources`.
No fix was implemented. The earlier click/scroll-without-movement symptom remains
unresolved because this run stopped before those scheduled phases.**

## Authorization and verified execution

The operator authorized one isolated UNPROTECTED real Windows monitor-capture
experiment. The prepared main/preload bundles were rebuilt in memory and compared
byte-for-byte with the existing artifacts before launch; original production
capture and geometry source hashes matched the preparation identity. Static UI
assets and the dependency list also matched. No prepared artifact was overwritten.

Main bundle SHA256:
`08124b1d513b71ffe7af2b9eda309584d1eb6550ac9893d8d3613b92af7decfe`.
Complete preflight identity: `build/stage4a-stream-fix/real-capture-run-01-preflight.json`.

The fixture had no Windows protection, keyboard blocking, global shortcut hooks,
camera/microphone use, Python, proctoring backend, account or API integration.
Device permissions and network requests were denied. It used the real Electron
desktopCapturer path, not the mock flag. Runtime observer samples confirmed
`mock=false`. A read-only observer queried numerical status only; it did not
check consent, click Start, manipulate the window or capture any screenshot.

The fixture first reported `awaiting_consent`, zero attempts and zero captures.
The operator then manually checked consent and started it. Start time was
06:36:11.261 UTC / 11:36:11.261 local. The first failure occurred at
06:36:25.489 UTC / 11:36:25.489 local, **14.228 seconds after Start**, including
the five-second countdown. There were **33 attempts: 32 completed captures and
one rejected capture**. Completed frames were cleared/released in memory; none
were displayed, transmitted or saved. This fixture has no teacher viewer, so these
counts are not delivered viewer FPS or a successful sustained-stream result.

## Actual action and exact numerical evidence

The scheduled phase still read `untouched`. After failure, the operator explicitly
answered **“moved window”** when asked what immediately preceded the interruption.
The phase label is therefore not a claim that the window was actually untouched.

Failure record: attempt 33, `capture_geometry_changed`, `after_sources`,
`failed=[content_x, content_y]`, `terminal_in_production=true`.

| Field | Before | After |
| --- | --- | --- |
| Sample time, UTC | 06:36:25.236 | 06:36:25.489 |
| Native content x | 328 | 334 (**+6**) |
| Native content y | 151 | 148 (**−3**) |
| Native content width × height | 1264 × 761 | 1264 × 761 |
| Zoom | 1 | 1 |
| Display count | 1 | 1 |
| Display ID | 3833731472 | 3833731472 |
| Display bounds | [0, 0, 1920, 1080] | [0, 0, 1920, 1080] |
| Display size | 1920 × 1080 | 1920 × 1080 |
| Display scale | 1 | 1 |
| Focused / maximized | true / false | true / false |
| Window / webContents destroyed | false / false | false / false |

The baseline-to-post-source guard interval was **253 ms**. The `before_mask`
and `after_initial_mask` probes passed at 06:36:25.236. Source selection found
one matching, nonempty **1280 × 720** thumbnail. The failure occurred immediately
after the awaited source acquisition, before the final mask query or frame encoding.

Six native `move` events were retained:

| UTC time | Content rectangle [x, y, width, height] |
| --- | --- |
| 06:36:25.472 | [328, 151, 1264, 761] |
| 06:36:25.473 | [333, 149, 1264, 761] |
| 06:36:25.474 | [333, 149, 1264, 761] |
| 06:36:25.474 | [333, 148, 1264, 761] |
| 06:36:25.475 | [333, 148, 1264, 761] |
| 06:36:25.476 | [334, 148, 1264, 761] |

Every retained move event reported zoom 1 and focused=true. No focus/blur,
maximize, zoom or destruction event accompanied this failure in the retained
event history. Initial synthetic preview geometry was one valid rectangle:
`[1049,180,180,120]` in client coordinates. No final mask measurement exists for
the rejected attempt because the native geometry guard stopped it first.

## What this demonstrates

This was a **real native content-position change while capture was pending**,
confirmed independently by before/after values, native move events and the
operator's action. It was not merely an active-window flag change. The sampled
window size, zoom, display identity/geometry and destruction flags stayed stable.
There was no missing/empty capture source or demonstrated invalid initial mask.
The unchanged coordinate scale and dimensions give no evidence of a coordinate-
system conversion mismatch for this failure.

The uncertain frame must be discarded: masking uses native window origin to
translate the client preview rectangle into monitor pixels. At this source scale
(1280/1920), the measured translation corresponds to **+4, −2 thumbnail pixels**.
Using a stale origin could mask the wrong region. Since pixels were not saved or
inspected, this report does not claim that the captured thumbnail represented the
old, new or an intermediate position; that uncertainty is why the check matters.

The production owner treats this geometry exception as terminal and revokes the
viewer lease. The isolated fixture reproduced the capture-layer exception and
stopped, but it intentionally has no lease, WebRTC or teacher transport.

This explains why moving this test window stopped capture. It does **not** show
that an ordinary click or scroll moves the original student window. The six later
interaction phases were not reached; the planned untouched interval was interrupted
by actual movement. Earlier physical run 03 lacked operand details, so its original
condition cannot be retroactively asserted to be the same position translation.

## Narrow correction proposed, not implemented

A narrowly scoped candidate for this demonstrated translation case would discard
only the uncertain frame when the failure is exclusively content x/y translation,
while window/view, display identity/geometry, dimensions and zoom remain valid.
A subsequent normal capture must obtain a fresh baseline and fresh preview-mask
coordinates and pass every production guard before any frame can be sent. It
must retain the same authorized viewer identity and existing delivery deadline;
no reconnect, lease extension or timeout increase is required.

Display loss/change, invalid masking, destroyed views, expired authorization and
intentional stop must remain fail-closed. Continuing motion must not permit an
uncertain frame or indefinitely postpone the existing delivery timeout. This is
a proposal for later review and verification, not an implemented fix or proof
that it solves the earlier click/scroll symptom.

## Preservation, cleanup and scope

The fixture stopped automatically on its first failure and refused further starts.
`first-failure.json` was written before cleanup. Its SHA256 remained unchanged
after normal closure:
`c149d63849b78ef2c872b2eee0268f80bb81e5a0900de3bc5782bf1d78d118e4`.

The operator confirmed **“closed”**. Cleanup recorded requested_close=true,
in_flight_at_close=false, fixture_window_closed=true and mock=false. The observer
exited normally. Read-only process verification found root PID 24624 absent and
no Electron process matching this fixture/run. Original teacher PID 10812 retained
its creation identity of 04:13:50.0156248 UTC. No existing service was restarted or
terminated, and no database or existing evidence was modified. Initial process
enumeration was denied in the sandbox; elevated read-only enumeration subsequently
succeeded, rather than treating the denied enumeration as evidence of absence.

Artifacts: `build/stage4a-stream-fix/real-capture-run-01/` contains the immutable
first failure and result, bounded numerical observer samples, operator observation,
cleanup receipt/verification, numerical summary and SHA256 manifest. No frames,
screenshots, recordings, application content or credentials were saved by the
fixture or observer.

No tests were rerun, no speculative fix was implemented, and no full application
exam, protection test, packaging, public deployment or Stage 4B was started.
**Stage 4A remains unready. Stop after this one experiment and report.**
