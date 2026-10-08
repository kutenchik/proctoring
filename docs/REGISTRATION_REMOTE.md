# Candidate registration and optional remote delivery

The application requests candidate identity before camera setup, calibration or
exam start. Remote delivery is a separate, disabled-by-default option. Camera
processing and gaze calibration still run locally, and local records remain the
primary record even when delivery is enabled.

## Registration

Configure the existing `config/default.toml` (or pass another complete TOML file
with `--config C:\path\demo.toml`):

```toml
[exam.registration]
enabled = true
require_group = true
```

Enter first name, last name and Group / Student ID, then select **Proceed to
Calibration**. Required fields must contain non-whitespace text. Names support
Unicode; input is trimmed, control characters are rejected, names are limited
to 100 characters, and the group field to 128 characters. The form follows the
**EN / RU / ҚАЗ** interface selector without clearing entered values.

Set `require_group = false` to make the group optional, or `enabled = false` to
keep the previous direct-to-setup flow. Candidate identity is fixed after the
session starts. Registration by itself does not start the camera, exam timer or
Windows restrictions.

The session stores candidate metadata using these stable keys:

```json
{"first_name": "Aida", "last_name": "Example", "group_id": "CS-101"}
```

Candidate metadata is linked to `sessions/<session_id>/session.json`, the
session header in `events.jsonl`, and the final `summary.json`. Interface locale
does not change the keys, technical event types or gaze identifiers.

`session.json` contains `created_at`, `session_id` and `candidate`. The first
journal row contains those fields plus `"record_kind": "session_header"`.
Subsequent lifecycle/review/security journal records also carry `session_id`
and `candidate`; the final summary includes candidate metadata at its top
level. When registration is disabled and no candidate was supplied, the
controller stores `"candidate": {}` rather than inventing an identity.

## Enable a destination explicitly

Edit the existing `[remote]` table; do not add a duplicate table. A complete
default table is:

```toml
[remote]
enabled = false
webhook_url = ""
webhook_token = ""
telegram_enabled = false
telegram_bot_token = ""
telegram_chat_id = ""
max_queue_size = 50
upload_timeout_seconds = 5.0
```

For **Telegram**, supply your bot token and the intended chat/channel ID, then
set both `telegram_enabled = true` and `enabled = true`. The bot must already
have permission to send to that destination. For a **webhook**, provide its
HTTP(S) URL and set `enabled = true`; `webhook_token`, when non-empty, becomes
an `Authorization: Bearer ...` header. Prefer HTTPS for a remote destination.
Both destinations can be configured together. A disabled dispatcher needs no
credentials and creates no network worker thread. Enabling delivery without
any usable configured destination fails configuration validation.

For an existing environment, install the pinned official HTTP client
dependencies before enabling delivery:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-remote.lock
```

The verified client is `requests==2.34.2`; the package requirement is
`requests>=2.32,<3`. This dependency setup needs network access unless the
packages have already been prepared locally; exam delivery remains optional.

Start with the usual command:

```powershell
.\.venv\Scripts\python.exe -m proctoring
```

Keep credentials in a private configuration file, outside commits or shared
screenshots. Saved public session configuration excludes bot credentials,
webhook tokens and the webhook URL; it records only delivery settings and the
webhook hostname. Network warnings omit request URLs, response bodies and
exception text, because those can contain credentials.

## Delivery contract

The dispatcher copies these three categories after the controller writes local
session/event records:

| Remote `type` | Content | Telegram request |
| --- | --- | --- |
| `session_start` | Candidate, group and session ID | `sendMessage`, headed `🎓 [Exam Started]` |
| `violation_alert` | Technical event type, candidate, duration, timestamp and available snapshot | `sendPhoto` with caption, or `sendMessage` without a usable snapshot |
| `session_end` | Candidate, session ID and total review-event count | `sendMessage`, headed `✅ [Exam Finished]` |

The requested `violation_alert` wire name describes a proctoring **review
event**, not a proven violation. The final count is a count of recorded review
events. Technical event names retain their ASCII values; Telegram displays
the alert type in uppercase. Candidate names are sent as plain text without
Telegram Markdown/HTML parsing. Telegram text is bounded to 4096 characters;
photo captions are bounded to 1024.

Webhook delivery uses a JSON object containing the controller's metadata plus
`"type": "session_start"`, `"violation_alert"` or `"session_end"`. When an
existing JPEG snapshot is available, the request instead uses
`multipart/form-data` with:

- `payload`: the same object serialized as a JSON string;
- `photo`: the JPEG file with MIME type `image/jpeg`.

All three payloads contain `session_id`, `candidate` and an ISO wall-clock
`timestamp`. A computer-vision alert adds `event_id`, `event_type`,
`description`, `duration_seconds`, `confidence` and `start_timestamp`.
Security alerts use the same alert category with zero duration and null
confidence; they do not include `start_timestamp`. The end payload adds
`total_events`, `end_reason`, `elapsed_seconds` and `event_counts`.

Example alert JSON (illustrative values, no credentials):

```json
{
  "type": "violation_alert",
  "session_id": "session-example",
  "candidate": {"first_name": "Aida", "last_name": "Example", "group_id": "CS-101"},
  "timestamp": "2026-10-07T08:00:01+00:00",
  "event_id": "example-event",
  "event_type": "phone_visible",
  "description": "Phone detected",
  "duration_seconds": 1.0,
  "confidence": 0.86,
  "start_timestamp": "2026-10-07T08:00:00+00:00"
}
```

Alerts are queued once on activation, after snapshot completion when applicable;
sustained event updates do not repeatedly send the same alert. The final local
summary remains the source for completed event durations and details.

The receiver should support both forms. If a snapshot is absent, unreadable or
not a JPEG, delivery falls back to text/JSON and records a local warning when
a supplied snapshot cannot be opened. A failed network photo upload is dropped;
it does not trigger a second text request. No new images are captured solely
for remote delivery. Existing snapshot settings continue to control capture.

## Offline and shutdown behavior

One daemon thread performs all HTTP requests and remote snapshot reads. The UI
and vision workers enqueue small metadata with a non-blocking bounded queue.
Telegram is attempted first and the webhook second; a Telegram failure does not
prevent the webhook attempt. Every request passes the configured socket timeout.
HTTP redirects are rejected rather than forwarding identity or credentials to
another destination.

The queue holds at most `max_queue_size` pending items. A full queue drops the
new remote copy. Network errors, timeouts, unsuccessful HTTP responses or
Telegram API rejection are caught and reported locally. None pauses the exam,
changes monitoring health, blocks local persistence, or modifies event timing.

There are **no automatic retries and no durable remote outbox**. Going back
online does not replay missed alerts. Local JSON/JSONL and existing snapshots
remain available for review. Local warnings use codes such as `queue_full`,
`network_timeout`, `network_error`, `http_error`, `telegram_rejected` and
`snapshot_unavailable`; warning metadata does not include credentials.

Warnings are written separately to `sessions/<session_id>/remote_warnings.jsonl`,
including warnings arriving after summary finalization. They are not review
events and do not increase the exam's event count. Before a session directory
exists, sanitized warnings use the local application logger.

Application shutdown accepts no new remote work and waits at most two seconds
for the worker. Remaining queued copies are then dropped. An HTTP call already
in progress cannot be cancelled by `requests`; its configured timeout still
applies, and the daemon thread does not keep the process alive. This is
best-effort delivery, including the final summary, not guaranteed receipt.

## Data disclosure and verification

With `remote.enabled = false`, this dispatcher sends nothing. Enabling it
explicitly sends candidate names, group/student IDs, session metadata, review
events and any existing event snapshots to the configured recipients. Telegram
delivery also sends these data through Telegram's service. Local files retain
their normal contents; remote delivery does not provide encryption at rest or
recipient retention controls. Inform the candidate and choose the intended
university/proctor destination before enabling it.

Automated tests mock HTTP and must not send to a real chat or webhook. First
check registration, session records and disabled mode locally. For an
intentional delivery check, use a destination you control, register a test
identity, start a synthetic session, trigger one test review event, and end it.
Inspect destination receipt and the local record separately. Remove network
access and repeat to verify that the application stays responsive and still
saves its local summary. Synthetic mode has no webcam snapshot; checking a
photo upload additionally requires an explicitly enabled existing snapshot in
a camera session. Actual destination delivery requires this separate operator
test; mocked tests do not establish it.
