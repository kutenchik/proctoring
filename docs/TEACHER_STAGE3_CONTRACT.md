# Stage 3 live protocol v1

Single server process; memory-only live state/frames, SQLite durable commands,
consent and audit. Prefix `/api/v1`. HTTPS/WSS mandatory except the existing explicit
literal-loopback development exception. No bearer secrets in URL or teacher UI.

## Student control socket

`/live/student`: Authorization Bearer + X-Device-Secret headers. Expiry applies;
Stage 2 evidence-only expiry exception never authorizes live controls. First message
within 5 seconds: `{type:'hello',protocol:1,attempt_id,session_id}`. The session is
the client preselected canonical `session-<32hex>`; an already bound session must
match. Response `{type:'hello',connection_id,server_time,heartbeat_seconds:1,
stale_seconds:6}`. Replacing a connection invalidates its commands and viewers.

Before exam start send `{type:'consent',version:2,accepted:true}`. ACK:
`{type:'consent',accepted:true,version:2,session_id,recorded_at}`. Consent version 2
covers full exam-monitor viewing on teacher request, without per-request approval,
including the existing webcam preview wherever visible on the monitor. No separate
webcam stream, audio transmission or screen recording. Old version-1 masked consent
is rejected, never upgraded implicitly. Declining or missing consent blocks new
Stage 3 start; consent and start must match the same preselected session.

Send status every second (maximum 16 KiB):

```text
{type:'status',sequence:int,state:'preparation'|'running'|'paused'|'ended',
 elapsed_seconds:number,remaining_seconds:number,duration_seconds:number,
 answered:int|null,total:int|null,monitoring_healthy:bool,pause_reasons:string[],
 monitoring_outage:{outage_id:string,duration_seconds:number,healthy:bool,
                    recovery_required:bool}|null,
 display:{count:int|null,incident_id:string|null,ready:bool,
          calibration_ready:bool,approval_required:bool},screen_consent:bool}
```

No answer choices or provisional score. Student status is Python authority.
Fresh received status means online; connected before first status is reconnecting;
no status for 6 seconds or socket loss means offline. Reconnect never replays commands.
`{type:'event',sequence:int,record:object}` sends a bounded notification of an
original local journal sequence (64 KiB canonical record limit). The server projects
only event IDs/types/timestamps/durations, never arbitrary raw record keys. Durable
records still come through Stage 2. Identical notices deduplicate; conflicting
sequence payloads reject. Never create a second canonical event for notifications.

## Teacher control socket and commands

`/live/teacher`: teacher session cookie and exact configured Origin. First message
within 5 seconds `{type:'auth',csrf_token,exam_id}`. All resource ownership is checked.
Send `{type:'ping'}` at least every 5 seconds to revalidate authentication and receive
fresh snapshots. Server sends `{type:'snapshot',exam_id,students:[student...]}` and
updates `{type:'student',student}` / `{type:'event',attempt_id,event}`.

Student projection:
`{attempt_id,session_id,student:{full_name,group,student_id},presence,
last_contact_at,status:null|<status fields above>,events:[event...],
unreviewed_count,capabilities:{commands:bool,view:bool}}`.
A disconnected/stale student keeps only explicitly stale status; UI must not tick
that timer or show an old frame live. Recent notifications are bounded to 100 per
attempt. Unreviewed count is behavioral stable event identity, not message count.

`POST /attempts/{id}/commands` cookie+Origin+CSRF:
`{request_id:<32hex>,type,payload}`. Duplicate request ID returns its original command;
different content conflicts. Commands require a fresh running/paused student socket.
Offline commands are rejected, never queued for a later connection.

| Type | Payload |
|---|---|
| warning | `{text}` nonempty, max 400 characters |
| pause / resume | `{reason}` nonempty, max 1000 characters |
| end | `{reason,confirm:true}` |
| add_time | `{seconds,reason}` integer 1–3600 seconds; total limit 172800 |
| monitoring_recovery | `{outage_id,reason}` current outage, healthy, PIN gate pending |
| display_recovery | `{incident_id,reason}` current incident, exactly 1 display, calibration ready |

Response `{command}`. Teacher updates `{type:'command',command}`. History
`GET /attempts/{id}/commands` returns `{items:[command...]}`. Command projection:
`{command_id,teacher_id,exam_id,attempt_id,session_id,connection_id,command_type,
payload,created_at,expires_at,status,result:null|object}`. Status:
`sent`, `delivered`, `applied`, `rejected`, `not_delivered`, `execution_unconfirmed`.
Delivered never means read. Commands expire in 10 seconds and belong to one live
connection. Server sends student `{type:'command',...command,ttl_seconds:10}`.
Student validates binding, deadline and local lifecycle, deduplicates durable IDs,
then replies `{type:'command_ack',command_id,phase:'received'|'applied'|'rejected',
result:object,reason?:string}`. Result whitelist includes state, pause_reasons,
elapsed_seconds,remaining_seconds,duration_seconds,old_duration_seconds,
new_duration_seconds,delta_seconds,code. Never arbitrary controller state/answers.
Lost ACK or connection after send becomes execution_unconfirmed, not assumed failure.

Pause clears only with teacher resume; monitoring/display recovery clears only
its named gate. Python rechecks actual current health/calibration independently.
Add-time IDs and effective duration must be persisted in checkpoints/summary:
`time_adjustment_ids:[command_id...]`, `duration_seconds`. Server checks each ID
against its issued add_time command for this attempt/session; matching durable
local application can reconcile a lost ACK. Original exam policy remains immutable.

Existing restart authorization and five-minute preparation extension keep Stage 2
and Stage 1 routes. `POST /exams/{id}/close-admissions {reason,confirm:true}` prevents
only new admission, leaving attempts, reconnects, uploads and leases intact.

## Viewer lease and separate stream socket

`POST /attempts/{id}/view {}` creates a 30-second lease for a fresh active student
with matching consent. One selected lease per teacher account; switching stops the
old lease first. Response `{viewer_id,attempt_id,session_id,expires_at,limits}`.
`POST /live/view/stop {viewer_id}` stops it. Teacher control receives
`{type:'view.stop',viewer_id,reason}` on stop/switch/disconnect/expiry.
Student control receives `{type:'view.start',viewer_id,attempt_id,session_id,
sender_token,expires_at,lease_seconds:30,limits}`. The token is a viewer-only
short-lived sender secret, forwarded only through host-only IPC to Electron main;
never to renderer or logs. Stop is `{type:'view.stop',viewer_id,reason}`; expiry
may use `view.expired` with the same identity. Capture must stop on either.

`/live/stream` first message within 5 seconds:
- Student main: `{role:'student',viewer_id,token}` (no attempt credential).
- Teacher browser: `{role:'teacher',viewer_id,csrf_token}`, with cookie and Origin.

Each side gets `{type:'stream.ready',viewer_id,role,peer_connected,expires_at,lease_seconds:30,limits}`.
The first attached peer receives `{type:'peer.ready',viewer_id}` when the other
authenticates. Capture requires this receiver-attached state; a pending request
alone does not authorize starting capture. Valid early frames are discarded.
Teacher sends `{type:'renew'}` every 5 seconds; server revalidates auth and ownership,
extends at most 30 seconds, responds `{type:'renewed',viewer_id,expires_at,
lease_seconds:30}` and forwards that renewal to sender. Authentication/socket loss,
session end, expiration, switch or explicit stop ends capture and both transports.

Authenticated signaling: `{type:'signal',viewer_id,signal:{type:'offer'|'answer',sdp}}
or `{type:'signal',viewer_id,signal:{type:'ice',candidate:<RTCIceCandidateInit|null>}}`.
Maximum 64 KiB. Student is offerer; direct RTCDataChannel sends the same JSON frame
packet as fallback. No microphone/webcam track. Teacher/main selects fallback on
RTC failure with `{type:'transport',viewer_id,transport:'relay',reason}`; server
forwards. `direct` or `unavailable` can also be reported; unsupported transport is
never disguised with fixture data.

Frame packet (direct data channel or student stream WS relay):
`{type:'frame',viewer_id,sequence:int,captured_at:<UTC epoch milliseconds>,width:int,height:int,
jpeg_base64:<base64 JPEG>}`. Max 256 KiB decoded JPEG, max 384 KiB message, max 1920 pixels per axis,
5 FPS, 1.5 MiB/s per sender. Server validates JPEG dimensions and uses exactly one
latest-frame slot per viewer; congestion replaces old frames instead of queuing.
Teacher replies `{type:'frame_ack',sequence}` after actual frame presentation;
the server relays bounded ACKs to the sender (direct uses the RTC channel).
Student stream may emit `{type:'quality',viewer_id,ack_roundtrip_ms:number|null,
send_fps:number,width:int,jpeg_quality:number,degraded:bool}` at most once per
second. Bounds: 0–60000 ms, 0–10 FPS, 1–1920 pixels, 0–100 quality. This is
memory-only telemetry; acknowledgement round-trip includes capture, decoding,
presentation and return ACK and is explicitly not one-way latency.
Forwarded relay packet adds `server_received_at`; this is receipt age, not proof
of capture latency or clock synchronization. UI labels latency measurements with
their basis, hides images after 3 seconds without a new frame and never stores them.
Control/signaling queues max 32; overload closes the connection rather than
silently discarding commands. No frame is written to SQLite, files, audits or outbox.

No WebSocket starts capture by itself. Capture requires an authorized unexpired
lease, explicit consent and the active original session. Protected-mode geometry
safety remains terminal; this stage does not relax native recovery/containment.

Live projections additionally expose `preparation_deadline`, `started_at`,
`start_authorized`, saved `lifecycle`, and `restart_recovery` containing only
`interruption_id`, `grant_id`, and `state` (or null). Saved lifecycle is not presence;
checkpoint answers and provisional scores never appear. Existing preparation
extension and restart-grant endpoints apply, with results visible on the next ping.

Memory caps: 256 student connection/cache entries (only closed entries can be
evicted), 128 teacher control sockets and 128 viewer leases. Capacity refuses
new connections rather than evicting active sessions. Snapshot max 200 newest
attempts, 20 recent events each, and 1.8 MB payload; `total_students` and `truncated`
make partial lists explicit. Each student's live event cache still caps at 100.

Run Uvicorn with `--ws websockets-sansio --ws-max-size 393216 --ws-max-queue 8
--ws-per-message-deflate false`. Application bounds complement the transport
limit; no production capacity claim is made. Request, first presented frame,
transport-unavailable and stop audit entries are distinct and contain no pixels.
Retention/early deletion purges command message/reason/result content while
retaining command metadata and lifecycle audit tombstones.


## Stage 4A webcam-visible monitor policy (2026-10-14)

Consent v2 supersedes v1. A preparing student must explicitly opt in to the new
localized disclosure; persisted v1 acceptance and v1 acknowledgements are not valid.
Consent remains locked after start authorization: an old active session cannot be
silently converted to unmasked sharing. Deployment requires a newly consented attempt.
The stream protocol itself remains v1; only the screen-consent policy is v2.

Capture validates one display, stable display ID/bounds/size/scale across the
viewer lease and asynchronous capture, a single matching nonempty screen source,
positive bounded thumbnail dimensions and matching aspect ratio. Native content
bounds, UI zoom and webcam DOM rectangles are not monitor coordinates and no longer
gate screen pixels. Native calibration, display incidents and readiness still use
their existing independent checks. The current monitor may show other apps or no
preview when the exam window is covered/minimized; there is no separate camera feed.

An authenticated teacher stream may send `{type:'view.stop',viewer_id}`. The server
revokes only its own viewer and sends `view.stop` with the preserved reason to both
stream sockets before closing. HTTP Stop remains supported. Earlier genuine failure
classification wins over later cleanup. A normal transport close alone is not consent
to reconnect; new authentication, consent and viewer authorization are required.

See [Stage 4A follow-up](TEACHER_DASHBOARD_STAGE4A_WEBCAM_VISIBLE_FIX.md) for tests,
remaining physical verification, synchronization and the separately gated retest.

## Stage 4B diagnostic extension (2026-10-14)

The frame and ACK wire schemas and deadlines are unchanged. Optional sender terminal `delivery_trace` contains fixed-vocabulary counters and up to 128 numerical sequence/stage/time/value rows, validated in TypeScript/Python. Teacher numerical diagnostics expose the analogous in-memory trace. No frame bodies are included.

`GET /live/view/{viewer_id}/diagnostics` requires the authenticated owning teacher and returns `{viewer_id,trace}`. The server keeps active traces plus the last 16 closed-viewer traces in process memory only. Each trace has counters and up to 128 numeric rows. Other owners receive not-found. Export before API shutdown. Enqueue/send completion does not establish presentation; ACK acceptance remains the sender's delivery evidence. Monotonic timestamps from different machines cannot establish one-way latency.

See [the investigation and verification limits](TEACHER_DASHBOARD_STAGE4B_RELAY_SYNC_UI_FIX.md). Low FPS is informational for the current Stage 4B acceptance request; sustained authorized usable viewing and complete verified synchronization remain required.
# Stage 4B active-snapshot extension (2026-10-14)

Current consent is version 3. Its localized disclosure includes event-associated
camera JPEG upload and authorized teacher review during the exam. Older consent
must not authorize a new start/viewer or early snapshot upload. This supersedes
earlier version references; it does not upgrade historical consent records
or prohibit legacy ended-attempt Stage 2 evidence synchronization.

Live events retain canonical IDs and expose optional `snapshot` metadata:
`status` (pending, available, unavailable, disabled, not_applicable), `item_id`,
and a bounded production failure `reason`. Durable upload completion triggers an
owning-teacher projection; periodic projections reconstruct state after missed
notifications/disconnects. Images use the existing authenticated evidence route.
No frame/ACK protocol or capture scope is expanded by this extension.

See [implementation, limits and focused verification](TEACHER_DASHBOARD_STAGE4B_LIVE_SNAPSHOTS.md).

