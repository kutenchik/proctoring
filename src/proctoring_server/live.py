"""Bounded live state; SQLite commands/consent, never persistent screen pixels."""
from __future__ import annotations

import base64
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from io import BytesIO
import json
import math
import secrets
import threading
import time
from uuid import uuid4

from .service import Problem, encoded, iso, text_field
from .sync import SESSION, UUID, canonical, checksum, opaque, secret
from .stream_trace import StreamTrace

LIMITS = {"max_fps": 5, "max_frame_bytes": 262144, "max_message_bytes": 393216,
          "max_width": 1920, "max_height": 1920, "bytes_per_second": 1572864,
          "frame_queue": 1, "stale_frame_seconds": 3}
KINDS = {"warning", "pause", "resume", "end", "add_time", "monitoring_recovery", "display_recovery"}
MAX_STUDENTS, MAX_TEACHERS, MAX_VIEWERS = 256, 128, 128
RESULT_KEYS = {"state", "pause_reasons", "elapsed_seconds", "remaining_seconds", "duration_seconds",
               "old_duration_seconds", "new_duration_seconds", "delta_seconds", "code"}


def bounded_json(value, limit):
    try:
        return len(canonical(value)) <= limit
    except (ValueError, TypeError):
        return False


@dataclass
class Peer:
    role: str
    identity: str
    exam_id: str | None = None
    session_id: str | None = None
    connection_id: str = field(default_factory=lambda: uuid4().hex)
    control: deque = field(default_factory=deque)
    frame: dict | None = None
    closed: bool = False
    stop_message: dict | None = None
    last_status: float | None = None
    last_contact_at: float | None = None
    sequence: int = -1
    status: dict | None = None
    notices: OrderedDict = field(default_factory=OrderedDict)
    recent: OrderedDict = field(default_factory=OrderedDict)
    raw_session: str | None = None
    credential: str | None = None
    device_secret: str | None = None
    trace: StreamTrace | None = None

    def put(self, value):
        if self.closed:
            return False
        if len(self.control) >= 32:
            self.closed = True
            self.frame = None
            return False
        self.control.append(value)
        return True

    def pop(self):
        if self.control:
            return self.control.popleft()
        frame, self.frame = self.frame, None
        return frame


@dataclass
class Viewer:
    id: str
    teacher_id: str
    attempt_id: str
    session_id: str
    sender_token: str
    deadline: float
    expires_at: float
    student: Peer | None = None
    teacher: Peer | None = None
    last_sequence: int = -1
    last_frame: float = -100.0
    byte_window: deque = field(default_factory=deque)
    pending_teacher: deque = field(default_factory=deque)
    pending_student: deque = field(default_factory=deque)
    presented: bool = False
    transport_failures: set = field(default_factory=set)
    failure_reason: str | None = None
    last_quality: float = -100.0
    trace: StreamTrace = field(default_factory=StreamTrace)


class LiveService:
    def __init__(self, service, sync, *, monotonic=time.monotonic):
        self.service, self.sync = service, sync
        self.database, self.clock, self.monotonic = service.database, service.clock, monotonic
        self.lock = threading.RLock()
        self.students: dict[str, Peer] = {}
        self.teachers: list[Peer] = []
        self.viewers: dict[str, Viewer] = {}
        self.closed_traces = OrderedDict()  # Last 16 leases, numeric only, process memory.

    def diagnostics(self, owner, viewer_id):
        with self.lock:
            viewer = self.viewers.get(viewer_id)
            if viewer and viewer.teacher_id == owner:
                return {'viewer_id':viewer_id, 'trace':viewer.trace.snapshot()}
            prior = self.closed_traces.get(viewer_id)
            if prior and prior[0] == owner:
                return {'viewer_id':viewer_id, 'trace':prior[1]}
            raise Problem('not_found', 'Viewer not found', 404)

    def student_connect(self, credential, device_secret, data):
        if data.get("type") != "hello" or data.get("protocol") != 1:
            raise Problem("invalid_live_hello", "Protocol 1 hello required")
        session_id = opaque(data.get("session_id"), SESSION)
        with self.database.connect(write=True) as connection:
            attempt, state = self.sync._owned(connection, credential, device_secret)
            if data.get("attempt_id") != attempt["id"]:
                raise Problem("attempt_conflict", "Live attempt identity mismatch", 409)
            self.sync._session(state, session_id)
            old = connection.execute("SELECT * FROM live_attempts WHERE attempt_id=?", (attempt["id"],)).fetchone()
            if old and old["session_id"] != session_id:
                raise Problem("session_conflict", "Live session identity is immutable", 409)
            connection.execute("INSERT OR IGNORE INTO live_attempts(attempt_id,session_id) VALUES (?,?)", (attempt["id"], session_id))
        peer = Peer("student", attempt["id"], attempt["exam_id"], session_id,
                    credential=credential, device_secret=device_secret)
        with self.lock:
            prior = self.students.get(peer.identity)
            if prior is None and len(self.students) >= MAX_STUDENTS:
                offline = next((p for p in self.students.values() if p.closed), None)
                if offline is None:
                    raise Problem("live_capacity", "Live student connection capacity reached", 503)
                self.students.pop(offline.identity)
            if prior:
                self.disconnect(prior, "connection_replaced")
                peer.notices, peer.recent = prior.notices, prior.recent
            self.students[peer.identity] = peer
            peer.put({"type": "hello", "connection_id": peer.connection_id, "server_time": iso(self.clock()),
                      "heartbeat_seconds": 1, "stale_seconds": 6})
            self.broadcast_student(peer.identity)
        return peer

    def teacher_connect(self, raw_session, csrf, exam_id):
        owner = self.service.authenticate(raw_session, csrf, True)["teacher"]["id"]
        with self.database.connect() as connection:
            self.service.owned_exam(connection, owner, exam_id)
        peer = Peer("teacher", owner, exam_id, raw_session=raw_session)
        with self.lock:
            if len(self.teachers) >= MAX_TEACHERS:
                raise Problem("live_capacity", "Live teacher connection capacity reached", 503)
            self.teachers.append(peer)
            peer.put(self.snapshot(owner, exam_id))
        return peer

    def revalidate(self, peer):
        if peer.role == "student":
            with self.database.connect() as connection:
                self.sync._owned(connection, peer.credential, peer.device_secret)
        elif peer.role in ("teacher", "viewer_teacher"):
            teacher = self.service.authenticate(peer.raw_session)["teacher"]["id"]
            if teacher != peer.identity:
                raise Problem("login_required", "Live teacher session changed", 401)

    def consent(self, peer, data):
        if data.get("version") != 3 or type(data.get("accepted")) is not bool:
            raise Problem("invalid_consent", "Explicit screen-viewing consent version 3 (monitor and live event snapshots) is required")
        with self.database.connect(write=True) as connection:
            attempt, state = self.sync._owned(connection, peer.credential, peer.device_secret)
            prior = connection.execute("SELECT * FROM live_attempts WHERE attempt_id=? AND session_id=?", (peer.identity, peer.session_id)).fetchone()
            accepted = self.clock() if data["accepted"] else None
            if attempt["started_at"] is not None or state["start_key"]:
                if not data["accepted"] or not prior or prior["consent_version"] != 3 or prior["consent_accepted_at"] is None:
                    raise Problem("consent_locked", "Consent cannot change after start authorization", 409)
                accepted = prior["consent_accepted_at"]
            else:
                connection.execute("UPDATE live_attempts SET consent_version=?,consent_accepted_at=? WHERE attempt_id=? AND session_id=?", (3 if data["accepted"] else None, accepted, peer.identity, peer.session_id))
                self.service.audit(connection, None, "screen_viewing_consent", peer.identity, self.clock(), details={"version": 3, "accepted": data["accepted"], "session_id": peer.session_id})
        peer.put({"type": "consent", "accepted": data["accepted"], "version": 3,
                  "session_id": peer.session_id, "recorded_at": iso(accepted)})

    @staticmethod
    def number(value, maximum=172800):
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum

    def status(self, peer, data):
        keys = {"type", "sequence", "state", "elapsed_seconds", "remaining_seconds", "duration_seconds", "answered", "total", "monitoring_healthy", "pause_reasons", "monitoring_outage", "display", "screen_consent"}
        if set(data) != keys or not bounded_json(data, 16384) or type(data["sequence"]) is not int or data["sequence"] <= peer.sequence:
            raise Problem("invalid_live_status", "Status schema or sequence is invalid")
        if data["state"] not in ("preparation", "running", "paused", "ended") or any(not self.number(data[k]) for k in ("elapsed_seconds", "remaining_seconds", "duration_seconds")):
            raise Problem("invalid_live_status", "Status state/timing is invalid")
        if abs(data["elapsed_seconds"] + data["remaining_seconds"] - data["duration_seconds"]) > .2:
            raise Problem("invalid_live_status", "Status allowance/timing disagree")
        if type(data["monitoring_healthy"]) is not bool or type(data["screen_consent"]) is not bool:
            raise Problem("invalid_live_status", "Explicit monitoring and consent states required")
        reasons = data["pause_reasons"]
        if not isinstance(reasons, list) or len(reasons) > 16:
            raise Problem("invalid_live_status", "Pause reasons exceed limit")
        for reason in reasons:
            opaque(reason)
        if (data["answered"] is None) != (data["total"] is None) or (data["total"] is not None and (type(data["total"]) is not int or type(data["answered"]) is not int or not 0 <= data["answered"] <= data["total"] <= 200)):
            raise Problem("invalid_live_status", "Quiz progress must be bounded counts only")
        outage = data["monitoring_outage"]
        if outage is not None:
            if not isinstance(outage, dict) or set(outage) != {"outage_id", "duration_seconds", "healthy", "recovery_required"} or not self.number(outage["duration_seconds"], 604800) or type(outage["healthy"]) is not bool or type(outage["recovery_required"]) is not bool:
                raise Problem("invalid_live_status", "Monitoring outage schema is invalid")
            opaque(outage["outage_id"])
        display = data["display"]
        if not isinstance(display, dict) or set(display) != {"count", "incident_id", "ready", "calibration_ready", "approval_required"} or any(type(display[k]) is not bool for k in ("ready", "calibration_ready", "approval_required")) or (display["count"] is not None and (type(display["count"]) is not int or not 0 <= display["count"] <= 32)):
            raise Problem("invalid_live_status", "Display state is invalid")
        if display["incident_id"] is not None:
            opaque(display["incident_id"])
        with self.lock:
            if peer.closed or self.students.get(peer.identity) is not peer:
                raise Problem("connection_replaced", "Connection is no longer current", 409)
            peer.sequence, peer.last_status, peer.last_contact_at = data["sequence"], self.monotonic(), self.clock()
            peer.status = {key: value for key, value in data.items() if key not in ("type", "sequence")}
            if data["state"] == "ended":
                self.stop_attempt_viewers(peer.identity, "session_ended")
            self.broadcast_student(peer.identity)

    def fresh(self, peer):
        return bool(peer and not peer.closed and peer.status and peer.last_status is not None and self.monotonic() - peer.last_status < 6)

    def active(self, peer):
        return self.fresh(peer) and peer.status["state"] in ("running", "paused")

    def student_document(self, row):
        peer = self.students.get(row["id"])
        fresh = self.fresh(peer)
        projection = {"attempt_id": row["id"], "session_id": peer.session_id if peer else None,
                      "student": {"full_name": row["full_name"], "group": row["student_group"], "student_id": row["student_id"]},
                      "presence": "online" if fresh else "reconnecting" if peer and not peer.closed and peer.status is None else "offline",
                      "last_contact_at": iso(peer.last_contact_at) if peer else None,
                      "status": peer.status if peer else None,
                      "events": list(peer.recent.values()) if peer else [], "unreviewed_count": 0,
                      "capabilities": {"commands": bool(self.active(peer)), "view": bool(self.active(peer) and peer.status["screen_consent"])}}
        # Persisted review decisions override transient notification counts.
        with self.database.connect() as connection:
            saved = connection.execute("SELECT * FROM sync_attempts WHERE attempt_id=?", (row["id"],)).fetchone()
            grant = connection.execute("SELECT id,state FROM recovery_grants WHERE attempt_id=? AND interruption_id=?", (row["id"], saved["interruption_id"])).fetchone() if saved and saved["interruption_id"] else None
            projection.update({"preparation_deadline": iso(row["preparation_deadline"]), "started_at": iso(row["started_at"]),
                               "start_authorized": bool(saved and saved["start_key"]), "lifecycle": saved["lifecycle"] if saved else self.service.attempt_document(row, connection)["status"],
                               "restart_recovery": {"interruption_id": saved["interruption_id"], "grant_id": grant["id"] if grant else None,
                                                    "state": grant["state"] if grant else "pending"} if saved and saved["interruption_id"] else None})
            if saved and (saved["deleted_at"] or saved["deletion_pending"]):
                if peer:
                    peer.recent.clear(); peer.notices.clear()
                projection.update(events=[], unreviewed_count=0, capabilities={"commands": False, "view": False})
                return projection
            from .review import BEHAVIORAL
            # Aggregate in SQLite: never deserialize an entire evidence journal per heartbeat.
            placeholders = ','.join('?' for _ in BEHAVIORAL)
            persisted = "SELECT DISTINCT json_extract(payload,'$.event_id') AS event_id FROM sync_records WHERE attempt_id=? AND json_extract(payload,'$.event_type') IN ("+placeholders+") AND json_type(payload,'$.event_id')='text'"
            parameters = (row["id"], *BEHAVIORAL)
            pending = connection.execute("SELECT COUNT(*) FROM ("+persisted+") AS events WHERE COALESCE((SELECT decision FROM event_review_versions v WHERE v.attempt_id=? AND v.event_id=events.event_id ORDER BY v.version DESC LIMIT 1),'not_reviewed')='not_reviewed'", (*parameters, row["id"])).fetchone()[0]
            recent = {r["event_id"] for r in projection["events"] if r["event_type"] in BEHAVIORAL}
            if recent:
                clauses = ','.join('?' for _ in recent)
                saved = {r[0] for r in connection.execute("SELECT event_id FROM ("+persisted+") WHERE event_id IN ("+clauses+")", (*parameters, *recent))}
                decisions = {r[0]: r[1] for r in connection.execute("SELECT event_id,decision FROM event_review_versions WHERE attempt_id=? AND event_id IN ("+clauses+") ORDER BY version", (row["id"], *recent))}
                pending += sum(decisions.get(identifier, 'not_reviewed') == 'not_reviewed' for identifier in recent-saved)
            # Bounded durable event projection survives student/server disconnects.
            rows = connection.execute("SELECT sequence,payload FROM sync_records WHERE attempt_id=? AND json_extract(payload,'$.event_type') IS NOT NULL AND sequence IN (SELECT MAX(sequence) FROM sync_records WHERE attempt_id=? AND json_extract(payload,'$.event_type') IS NOT NULL GROUP BY json_extract(payload,'$.event_id')) ORDER BY sequence DESC LIMIT 100", (row["id"],row["id"])).fetchall()
            durable = {}
            raw_by_id = {}
            for record_row in reversed(rows):
                raw = json.loads(record_row["payload"])
                if not isinstance(raw.get("event_id"), str) or not isinstance(raw.get("event_type"), str) or raw.get("state") == "candidate": continue
                raw_by_id[raw["event_id"]] = raw
                durable[raw["event_id"]] = {"event_id":raw["event_id"],"event_type":str(raw["event_type"])[:96],
                    "timestamp":str(raw.get("start_timestamp") or raw.get("timestamp") or "")[:64],
                    "duration_seconds":raw.get("duration_seconds",0) if self.number(raw.get("duration_seconds",0)) else 0,"sequence":record_row["sequence"],
                    "category":"behavioral" if raw["event_type"] in BEHAVIORAL else "technical"}
            for event in projection["events"]:
                old = durable.get(event["event_id"])
                if old is None or event.get("sequence",-1) >= old.get("sequence",-1): durable[event["event_id"]] = event
            files = {f["event_id"]:f for f in connection.execute("SELECT e.event_id,f.item_id,f.complete FROM event_snapshots e JOIN sync_files f ON f.attempt_id=e.attempt_id AND f.item_id=e.item_id WHERE e.attempt_id=?", (row["id"],))}
            enabled = json.loads(row["policy_snapshot"])["save_snapshots"]
            for event in durable.values():
                raw = raw_by_id.get(event["event_id"], {})
                file = files.get(event["event_id"])
                status = "disabled" if not enabled else "available" if file and file["complete"] else "unavailable" if raw.get("snapshot_status") == "unavailable" else "pending" if raw.get("snapshot_path") or raw.get("snapshot_status") in ("pending","ready") or event["category"] == "behavioral" else "not_applicable"
                event["snapshot"] = {"status":status,"item_id":file["item_id"] if status == "available" else None,
                    "reason":raw.get("snapshot_reason") if raw.get("snapshot_reason") in ("capture_unavailable","production_failed") else None}
            # Status records advance sequence, not the canonical event's position.
            projection["events"] = sorted(durable.values(), key=lambda e:(e.get("timestamp", ""), e["event_id"]))[-100:]
            projection["unreviewed_count"] = pending
        return projection

    def snapshot(self, owner, exam_id):
        with self.lock, self.database.connect() as connection:
            self.service.owned_exam(connection, owner, exam_id)
            rows = connection.execute("SELECT * FROM attempts WHERE exam_id=? ORDER BY admitted_at DESC LIMIT 200", (exam_id,)).fetchall()
            total = connection.execute("SELECT COUNT(*) FROM attempts WHERE exam_id=?", (exam_id,)).fetchone()[0]
            students, size = [], 0
            for row in rows:
                item = self.student_document(row)
                item["events"] = item["events"][-20:]
                size += len(canonical(item))
                if size > 1800000:
                    break
                students.append(item)
        return {"type": "snapshot", "exam_id": exam_id, "students": students, "total_students": total, "truncated": len(students) < total}

    def broadcast_student(self, attempt_id):
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if row:
            self.broadcast(row["exam_id"], {"type": "student", "student": self.student_document(row)})

    def broadcast(self, exam_id, message):
        for peer in self.teachers:
            if not peer.closed and peer.exam_id == exam_id:
                peer.put(message)

    def event(self, peer, data):
        record, sequence = data.get("record"), data.get("sequence")
        if type(sequence) is not int or not 0 <= sequence < 100000 or not isinstance(record, dict) or not bounded_json(record, 65536):
            raise Problem("invalid_live_event", "Notification must identify a bounded original journal record")
        if record.get("session_id", peer.session_id) != peer.session_id:
            raise Problem("session_conflict", "Notification belongs to another session", 409)
        sha = checksum(record)
        with self.lock:
            if sequence in peer.notices:
                if peer.notices[sequence] != sha:
                    raise Problem("record_conflict", "Notification retry differs", 409)
                return
            peer.notices[sequence] = sha
            while len(peer.notices) > 1000:
                peer.notices.popitem(last=False)
            if not isinstance(record.get("event_type"), str):
                return
            event_id = opaque(record.get("event_id") or f"record-{sequence}")
            event = {"event_id": event_id, "event_type": str(record["event_type"])[:96],
                     "timestamp": str(record.get("start_timestamp") or record.get("timestamp") or "")[:64],
                     "duration_seconds": record.get("duration_seconds", 0), "sequence": sequence}
            from .review import BEHAVIORAL
            event["category"] = "behavioral" if event["event_type"] in BEHAVIORAL else "technical"
            if not self.number(event["duration_seconds"]):
                event["duration_seconds"] = 0
            peer.recent[event_id] = event
            while len(peer.recent) > 100:
                peer.recent.popitem(last=False)
            self.broadcast(peer.exam_id, {"type": "event", "attempt_id": peer.identity, "event": event})
            self.broadcast_student(peer.identity)

    @staticmethod
    def command_document(row):
        return {**{key: row[key] for key in ("teacher_id", "exam_id", "attempt_id", "session_id", "connection_id", "command_type", "status")},
                "command_id": row["id"], "payload": json.loads(row["payload"]), "created_at": iso(row["created_at"]),
                "expires_at": iso(row["expires_at"]), "result": json.loads(row["result"]) if row["result"] else None}

    def commands(self, owner, attempt_id):
        self.sweep()
        with self.database.connect() as connection:
            self.service.owned_attempt(connection, owner, attempt_id)
            return {"items": [self.command_document(row) for row in connection.execute("SELECT * FROM live_commands WHERE attempt_id=? ORDER BY created_at,id", (attempt_id,))]}

    @staticmethod
    def payload(kind, payload):
        if not isinstance(payload, dict) or kind not in KINDS:
            raise Problem("invalid_command", "Unsupported remote command")
        keys = {"warning": {"text"}, "pause": {"reason"}, "resume": {"reason"}, "end": {"reason", "confirm"},
                "add_time": {"seconds", "reason"}, "monitoring_recovery": {"outage_id", "reason"}, "display_recovery": {"incident_id", "reason"}}
        if set(payload) != keys[kind]:
            raise Problem("invalid_command", "Command payload fields are invalid")
        clean = dict(payload)
        key = "text" if kind == "warning" else "reason"
        clean[key] = text_field(payload, key, 400 if kind == "warning" else 1000)
        if kind == "end" and payload["confirm"] is not True:
            raise Problem("confirmation_required", "Explicit end confirmation is required")
        if kind == "add_time" and (type(payload["seconds"]) is not int or not 1 <= payload["seconds"] <= 3600):
            raise Problem("invalid_command", "Add-time delta must be 1–3600 whole seconds")
        for identifier in ("outage_id", "incident_id"):
            if identifier in payload:
                opaque(payload[identifier])
        return clean

    def command(self, owner, attempt_id, data):
        request_id, kind = opaque(data.get("request_id"), UUID), data.get("type")
        payload = self.payload(kind, data.get("payload"))
        with self.lock, self.database.connect(write=True) as connection:
            attempt = self.service.owned_attempt(connection, owner, attempt_id)
            old = connection.execute("SELECT * FROM live_commands WHERE teacher_id=? AND request_id=?", (owner, request_id)).fetchone()
            if old:
                if old["attempt_id"] != attempt_id or old["command_type"] != kind or json.loads(old["payload"]) != payload:
                    raise Problem("command_conflict", "Request ID was already used for another command", 409)
                return {"command": self.command_document(old)}
            peer = self.students.get(attempt_id)
            if not self.active(peer) or attempt["finished_at"] is not None:
                raise Problem("student_offline", "Commands are never queued for offline or ended attempts", 409)
            if kind == "add_time" and peer.status["duration_seconds"] + payload["seconds"] > 172800:
                raise Problem("invalid_command", "Total allowance cannot exceed 172800 seconds")
            if kind == "monitoring_recovery":
                outage = peer.status["monitoring_outage"]
                if not outage or not outage["healthy"] or not outage["recovery_required"] or outage["outage_id"] != payload["outage_id"] or outage["duration_seconds"] < 15:
                    raise Problem("recovery_unavailable", "Current healthy long-outage recovery gate is required", 409)
            if kind == "display_recovery":
                display = peer.status["display"]
                if display["count"] != 1 or not display["ready"] or not display["calibration_ready"] or not display["approval_required"] or display["incident_id"] != payload["incident_id"]:
                    raise Problem("recovery_unavailable", "Single-display revalidation/calibration and a pending incident are required", 409)
            cid, now = uuid4().hex, self.clock()
            connection.execute("INSERT INTO live_commands VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)", (cid, request_id, owner, attempt["exam_id"], attempt_id, peer.session_id, peer.connection_id, kind, encoded(payload), now, now+10, "sent"))
            row = connection.execute("SELECT * FROM live_commands WHERE id=?", (cid,)).fetchone()
            document = self.command_document(row)
            connection.execute("INSERT INTO live_command_events(command_id,phase,payload,created_at) VALUES (?,?,?,?)", (cid, "sent", "{}", now))
            self.service.audit(connection, owner, "live_command_created", attempt_id, now, details={"command_id": cid, "type": kind})
        with self.lock:
            if not peer.put({"type": "command", **document, "ttl_seconds": 10}):
                self.unconfirmed(peer.connection_id)
                document["status"] = "execution_unconfirmed"
            self.broadcast(peer.exam_id, {"type": "command", "command": document})
        return {"command": document}

    def acknowledge(self, peer, data):
        cid = opaque(data.get("command_id"), UUID)
        phase, result = data.get("phase"), data.get("result", {})
        if phase not in ("received", "applied", "rejected") or not isinstance(result, dict) or set(result) - RESULT_KEYS or not bounded_json(result, 4096):
            raise Problem("invalid_command_ack", "Invalid bounded acknowledgement")
        for key in ("elapsed_seconds", "remaining_seconds", "duration_seconds", "old_duration_seconds", "new_duration_seconds", "delta_seconds"):
            if key in result and not self.number(result[key]):
                raise Problem("invalid_command_ack", "Invalid numerical acknowledgement")
        with self.database.connect(write=True) as connection:
            row = connection.execute("SELECT * FROM live_commands WHERE id=? AND attempt_id=? AND session_id=? AND connection_id=?", (cid, peer.identity, peer.session_id, peer.connection_id)).fetchone()
            if not row:
                raise Problem("command_binding", "Acknowledgement belongs to another command/connection", 409)
            if phase == "applied" and row["command_type"] == "add_time":
                delta = json.loads(row["payload"])["seconds"]
                if any(key not in result for key in ("old_duration_seconds", "new_duration_seconds", "delta_seconds")) or result["delta_seconds"] != delta or result["new_duration_seconds"] - result["old_duration_seconds"] != delta:
                    raise Problem("invalid_command_ack", "Applied time delta must match the issued command")
            status = "delivered" if phase == "received" else phase
            if row["status"] in ("applied", "rejected"):
                if row["status"] != status or json.loads(row["result"] or "{}") != result:
                    raise Problem("command_conflict", "Terminal command result is immutable", 409)
                return
            if self.clock() >= row["expires_at"] and phase == "received":
                raise Problem("command_expired", "Expired commands cannot be delivered", 409)
            connection.execute("UPDATE live_commands SET status=?,result=? WHERE id=?", (status, encoded(result), cid))
            connection.execute("INSERT INTO live_command_events(command_id,phase,payload,created_at) VALUES (?,?,?,?)", (cid, status, encoded(result), self.clock()))
            self.service.audit(connection, row["teacher_id"], "live_command_"+status, peer.identity, self.clock(), details={"command_id": cid})
            updated = self.command_document(connection.execute("SELECT * FROM live_commands WHERE id=?", (cid,)).fetchone())
        with self.lock:
            self.broadcast(peer.exam_id, {"type": "command", "command": updated})

    def unconfirmed(self, connection_id, *, expired_only=False):
        with self.database.connect(write=True) as connection:
            rows = connection.execute("SELECT * FROM live_commands WHERE connection_id=? AND status IN ('sent','delivered')" + (" AND expires_at<=?" if expired_only else ""), (connection_id, self.clock()) if expired_only else (connection_id,)).fetchall()
            for row in rows:
                connection.execute("UPDATE live_commands SET status='execution_unconfirmed' WHERE id=?", (row["id"],))
                connection.execute("INSERT INTO live_command_events(command_id,phase,payload,created_at) VALUES (?,'execution_unconfirmed','{}',?)", (row["id"], self.clock()))
                self.broadcast(row["exam_id"], {"type": "command", "command": {**self.command_document(row), "status": "execution_unconfirmed"}})

    def sweep(self):
        with self.lock:
            now = self.monotonic()
            for viewer in list(self.viewers.values()):
                if now >= viewer.deadline or not self.active(self.students.get(viewer.attempt_id)):
                    self.stop_viewer(viewer.id, "authorization_expired" if now >= viewer.deadline else "student_offline")
            with self.database.connect() as connection:
                rows = connection.execute("SELECT DISTINCT connection_id FROM live_commands WHERE expires_at<=? AND status IN ('sent','delivered')", (self.clock(),)).fetchall()
            for row in rows:
                self.unconfirmed(row[0], expired_only=True)

    def viewer_document(self, viewer):
        return {"viewer_id": viewer.id, "attempt_id": viewer.attempt_id, "session_id": viewer.session_id,
                "expires_at": iso(viewer.expires_at), "lease_seconds": 30, "limits": LIMITS}

    def start_viewer(self, owner, attempt_id):
        with self.lock, self.database.connect() as connection:
            attempt = self.service.owned_attempt(connection, owner, attempt_id)
            peer = self.students.get(attempt_id)
            consent = connection.execute("SELECT * FROM live_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if not self.active(peer) or attempt["finished_at"] is not None:
                raise Problem("student_offline", "A fresh active attempt is required", 409)
            if not consent or consent["consent_version"] != 3 or consent["consent_accepted_at"] is None or consent["session_id"] != peer.session_id or not peer.status["screen_consent"]:
                raise Problem("consent_required", "Current session has no screen-viewing consent", 409)
            for old in list(self.viewers.values()):
                if old.teacher_id == owner:
                    self.stop_viewer(old.id, "viewer_switched")
            if len(self.viewers) >= MAX_VIEWERS:
                raise Problem("live_capacity", "Viewer capacity reached", 503)
            viewer = Viewer(uuid4().hex, owner, attempt_id, peer.session_id, secrets.token_urlsafe(32), self.monotonic()+30, self.clock()+30)
            self.viewers[viewer.id] = viewer
            peer.put({"type": "view.start", **self.viewer_document(viewer), "sender_token": viewer.sender_token})
            with self.database.connect(write=True) as audit:
                self.service.audit(audit, owner, "screen_view_requested", attempt_id, self.clock(), details={"viewer_id": viewer.id})
            return self.viewer_document(viewer)

    def stop_attempt_viewers(self, attempt_id, reason):
        for viewer in list(self.viewers.values()):
            if viewer.attempt_id == attempt_id:
                self.stop_viewer(viewer.id, reason)

    def stop_viewer(self, viewer_id, reason, owner=None):
        with self.lock:
            viewer = self.viewers.get(viewer_id)
            if not viewer:
                return {"stopped": True}
            if owner is not None and viewer.teacher_id != owner:
                raise Problem("not_found", "Viewer not found", 404)
            self.viewers.pop(viewer_id)
            viewer.trace.record('closed')
            self.closed_traces[viewer.id] = (viewer.teacher_id, viewer.trace.snapshot())
            while len(self.closed_traces) > 16:
                self.closed_traces.popitem(last=False)
            reason = viewer.failure_reason or reason
            message = {"type": "view.stop", "viewer_id": viewer.id, "reason": reason}
            student = self.students.get(viewer.attempt_id)
            if student:
                student.put(message)
            for teacher in self.teachers:
                if teacher.identity == viewer.teacher_id:
                    teacher.put(message)
            for peer in (viewer.student, viewer.teacher):
                if peer:
                    peer.frame = None
                    peer.stop_message = message
                    peer.closed = True
            with self.database.connect(write=True) as connection:
                self.service.audit(connection, viewer.teacher_id, "screen_view_stopped", viewer.attempt_id, self.clock(), reason, {"viewer_id": viewer.id})
            return {"stopped": True}

    def stream_connect(self, data, raw_session=None):
        viewer_id, role = opaque(data.get("viewer_id"), UUID), data.get("role")
        with self.lock:
            self.sweep()
            viewer = self.viewers.get(viewer_id)
            if not viewer:
                raise Problem("viewer_expired", "Viewer lease is unavailable", 403)
            if role == "teacher":
                owner = self.service.authenticate(raw_session, data.get("csrf_token"), True)["teacher"]["id"]
                if owner != viewer.teacher_id or viewer.teacher:
                    raise Problem("not_found", "Viewer unavailable", 404)
                peer = Peer("viewer_teacher", owner, session_id=viewer_id, raw_session=raw_session)
                viewer.teacher = peer
            elif role == "student":
                import hmac
                if viewer.student or not hmac.compare_digest(secret(data.get("token")), viewer.sender_token):
                    raise Problem("viewer_forbidden", "Invalid or consumed sender authorization", 403)
                peer = Peer("viewer_student", viewer.attempt_id, session_id=viewer_id)
                viewer.student = peer
            else:
                raise Problem("invalid_viewer", "Unknown stream role")
            counterpart = viewer.student if role == "teacher" else viewer.teacher
            peer.trace = viewer.trace
            peer.put({"type": "stream.ready", "role": role, "peer_connected": counterpart is not None, **self.viewer_document(viewer)})
            if counterpart:
                counterpart.put({"type": "peer.ready", "viewer_id": viewer.id})
            pending = viewer.pending_teacher if role == "teacher" else viewer.pending_student
            while pending:
                peer.put(pending.popleft())
            return peer

    def stream(self, peer, data):
        with self.lock:
            self.sweep()
            viewer = self.viewers.get(peer.session_id)
            if not viewer or peer.closed:
                raise Problem("viewer_expired", "Viewer authorization ended", 403)
            if data.get("viewer_id", viewer.id) != viewer.id:
                raise Problem("viewer_forbidden", "Viewer identity mismatch", 403)
            target = viewer.student if peer.role == "viewer_teacher" else viewer.teacher
            kind = data.get("type")
            if kind == "view.stop" and peer.role == "viewer_teacher":
                if set(data) != {"type", "viewer_id"}:
                    raise Problem("invalid_viewer", "Invalid stop message")
                self.revalidate(peer)
                self.stop_viewer(viewer.id, "teacher_stopped", peer.identity)
            elif kind == "renew" and peer.role == "viewer_teacher":
                self.revalidate(peer)
                viewer.deadline, viewer.expires_at = self.monotonic()+30, self.clock()+30
                message = {"type": "renewed", "viewer_id": viewer.id, "expires_at": iso(viewer.expires_at), "lease_seconds": 30}
                peer.put(message)
                if target:
                    target.put(message)
            elif kind == "signal":
                signal = data.get("signal")
                if not bounded_json(data, 65536) or not isinstance(signal, dict) or signal.get("type") not in ("offer", "answer", "ice"):
                    raise Problem("invalid_signal", "Unsupported or oversized signaling message")
                if signal["type"] in ("offer", "answer") and (set(signal) != {"type", "sdp"} or not isinstance(signal["sdp"], str)):
                    raise Problem("invalid_signal", "SDP schema is invalid")
                if signal["type"] == "ice" and (set(signal) != {"type", "candidate"} or signal["candidate"] is not None and not isinstance(signal["candidate"], dict)):
                    raise Problem("invalid_signal", "ICE schema is invalid")
                if target:
                    target.put({"type": "signal", "viewer_id": viewer.id, "signal": signal})
                else:
                    pending = viewer.pending_student if peer.role == "viewer_teacher" else viewer.pending_teacher
                    if len(pending) >= 16:
                        raise Problem("signal_limit", "Pending signaling limit exceeded")
                    pending.append({"type": "signal", "viewer_id": viewer.id, "signal": signal})
            elif kind == "transport":
                if data.get("transport") not in ("direct", "relay", "unavailable") or not isinstance(data.get("reason", ""), str) or len(data.get("reason", "")) > 200:
                    raise Problem("invalid_transport", "Unsupported transport")
                if data['transport'] == 'unavailable' and peer.role == 'viewer_student':
                    from proctoring.connected.screen_diagnostic import safe_code
                    viewer.failure_reason = viewer.failure_reason or safe_code(data.get('reason'))
                if target:
                    target.put({"type": "transport", "viewer_id": viewer.id, "transport": data["transport"], "reason": data.get("reason", "")})
                if peer.role == "viewer_teacher" and data["transport"] == "direct" and data.get("reason") == "frame_presented":
                    self.view_presented(viewer, "direct")
                if data["transport"] == "unavailable" and peer.role not in viewer.transport_failures:
                    viewer.transport_failures.add(peer.role)
                    with self.database.connect(write=True) as connection:
                        self.service.audit(connection, viewer.teacher_id, "screen_transport_unavailable", viewer.attempt_id, self.clock(), details={"viewer_id": viewer.id, "reporter": peer.role, "code": viewer.failure_reason})
            elif kind == "capture.recovering" and peer.role == "viewer_student":
                if (set(data) != {"type", "viewer_id", "through_sequence"} or
                        type(data["through_sequence"]) is not int or not 0 <= data["through_sequence"] < 2**53):
                    raise Problem("invalid_stream_message", "Invalid capture recovery barrier")
                if target:
                    target.put(dict(data))
            elif kind == "frame" and peer.role == "viewer_student":
                try:
                    self.frame(viewer, data)
                except Problem:
                    sequence = data.get('sequence')
                    viewer.trace.record('rejected', sequence if type(sequence) is int and 0 <= sequence < 2**53 else -1)
                    raise
            elif kind == "quality" and peer.role == "viewer_student":
                if set(data) != {"type", "viewer_id", "ack_roundtrip_ms", "send_fps", "width", "jpeg_quality", "degraded"} or (data["ack_roundtrip_ms"] is not None and not self.number(data["ack_roundtrip_ms"], 60000)) or not self.number(data["send_fps"], 10) or type(data["width"]) is not int or not 1 <= data["width"] <= 1920 or not self.number(data["jpeg_quality"], 100) or type(data["degraded"]) is not bool:
                    raise Problem("invalid_quality", "Invalid bounded transport quality report")
                now = self.monotonic()
                if now - viewer.last_quality >= 1:
                    viewer.last_quality = now
                    if target:
                        target.put(dict(data))
            elif kind == "frame_ack" and peer.role == "viewer_teacher":
                if type(data.get("sequence")) is not int or not 0 <= data["sequence"] < 2**53:
                    raise Problem("invalid_frame_ack", "Invalid frame acknowledgement")
                viewer.trace.record('ack_received', data['sequence'])
                if target and target.put({"type": "frame_ack", "sequence": data["sequence"]}):
                    viewer.trace.record('ack_forwarded', data['sequence'])
                if 0 <= data["sequence"] <= viewer.last_sequence:
                    self.view_presented(viewer, "relay")
            else:
                raise Problem("invalid_stream_message", "Unsupported stream operation")

    def frame(self, viewer, data):
        if set(data) != {"type", "viewer_id", "sequence", "captured_at", "width", "height", "jpeg_base64"}:
            raise Problem("invalid_frame", "Invalid frame schema")
        if type(data["sequence"]) is not int or not viewer.last_sequence < data["sequence"] < 2**53 or not self.number(data["captured_at"], 10**15):
            raise Problem("invalid_frame", "Invalid frame sequence/timestamp")
        if any(type(data[key]) is not int or not 1 <= data[key] <= 1920 for key in ("width", "height")) or not isinstance(data["jpeg_base64"], str) or len(data["jpeg_base64"]) > 349528:
            raise Problem("frame_limit", "Frame exceeds declared dimensions or byte limit")
        if not viewer.teacher:
            return  # Sender may attach first; never retain frames without a receiver.
        viewer.trace.record('received', data['sequence'], len(data['jpeg_base64']))
        now = self.monotonic()
        if now-viewer.last_frame < .19:
            viewer.trace.record('rate_dropped', data['sequence'])
            return  # Bounded latest stream; excessive-rate frames are dropped.
        from PIL import Image
        try:
            pixels = base64.b64decode(data["jpeg_base64"], validate=True)
            if len(pixels) > 262144:
                raise ValueError("large")
            with Image.open(BytesIO(pixels)) as picture:
                if picture.format != "JPEG" or picture.size != (data["width"], data["height"]):
                    raise ValueError("dimensions")
                picture.verify()
        except (ValueError, OSError, Image.DecompressionBombError):
            raise Problem("invalid_frame", "Frame is not a valid matching JPEG") from None
        while viewer.byte_window and viewer.byte_window[0][0] <= now-1:
            viewer.byte_window.popleft()
        if sum(size for _, size in viewer.byte_window)+len(pixels) > LIMITS["bytes_per_second"]:
            viewer.trace.record('budget_dropped', data['sequence'])
            return
        viewer.byte_window.append((now, len(pixels)))
        viewer.trace.record('accepted', data['sequence'], len(pixels))
        viewer.last_frame, viewer.last_sequence = now, data["sequence"]
        if viewer.teacher.frame:
            viewer.trace.record('replaced', viewer.teacher.frame['sequence'])
        viewer.teacher.frame = {**data, "server_received_at": self.clock()*1000}

    def view_presented(self, viewer, transport):
        if not viewer.presented:
            viewer.presented = True
            with self.database.connect(write=True) as connection:
                self.service.audit(connection, viewer.teacher_id, "screen_view_presented", viewer.attempt_id, self.clock(), details={"viewer_id": viewer.id, "transport": transport})

    def disconnect(self, peer, reason="disconnected"):
        with self.lock:
            peer.closed, peer.frame = True, None
            if peer.role == "student":
                self.unconfirmed(peer.connection_id)
                if self.students.get(peer.identity) is peer:
                    self.stop_attempt_viewers(peer.identity, reason)
                    self.broadcast_student(peer.identity)
            elif peer.role == "teacher":
                self.teachers = [p for p in self.teachers if p is not peer]
                for viewer in list(self.viewers.values()):
                    if viewer.teacher_id == peer.identity:
                        self.stop_viewer(viewer.id, reason)
            elif peer.role in ("viewer_student", "viewer_teacher"):
                self.stop_viewer(peer.session_id, reason)

    def close_admissions(self, owner, exam_id, data):
        if data.get("confirm") is not True:
            raise Problem("confirmation_required", "Explicit close-admission confirmation is required")
        reason = text_field(data, "reason", 1000)
        with self.database.connect(write=True) as connection:
            exam = self.service.owned_exam(connection, owner, exam_id)
            if exam["admissions_closed_at"] is None:
                connection.execute("UPDATE exams SET admissions_closed_at=? WHERE id=?", (self.clock(), exam_id))
                self.service.audit(connection, owner, "admissions_closed_early", exam_id, self.clock(), reason)
        return self.service.exam(owner, exam_id)


def effective_allowance(connection, attempt, data, now):
    """Verify durable applied add-time IDs, including application with lost ACK."""
    original = connection.execute("SELECT duration_seconds FROM exams WHERE id=?", (attempt["exam_id"],)).fetchone()[0]
    ids = data.get("time_adjustment_ids", [])
    if not isinstance(ids, list) or len(ids) > 2048 or any(not isinstance(cid, str) for cid in ids) or len(ids) != len(set(ids)):
        raise Problem("invalid_allowance", "Time adjustment IDs must be unique and bounded")
    allowance = original
    state = connection.execute("SELECT session_id FROM sync_attempts WHERE attempt_id=?", (attempt["id"],)).fetchone()
    applied = {r[0] for r in connection.execute("SELECT id FROM live_commands WHERE attempt_id=? AND command_type='add_time' AND status='applied'", (attempt["id"],))}
    if not applied <= set(ids):
        raise Problem("invalid_allowance", "Previously applied time adjustments cannot be omitted", 409)
    adjustments = []
    for cid in ids:
        opaque(cid, UUID)
        row = connection.execute("SELECT * FROM live_commands WHERE id=? AND attempt_id=? AND command_type='add_time'", (cid, attempt["id"])).fetchone()
        if not row or not state or row["session_id"] != state["session_id"] or row["status"] in ("rejected", "not_delivered"):
            raise Problem("invalid_allowance", "Time allowance includes an unauthorized/rejected command", 409)
        old, delta = allowance, json.loads(row["payload"])["seconds"]
        allowance += delta
        adjustments.append((row, {"code": "reconciled_from_durable_local_application", "old_duration_seconds": old, "new_duration_seconds": allowance, "delta_seconds": delta}))
    if allowance > 172800 or data.get("duration_seconds", original) != allowance:
        raise Problem("invalid_allowance", "Effective allowance does not match issued, durably applied command IDs", 409)
    for row, result in adjustments:
        if row["status"] != "applied":
            connection.execute("UPDATE live_commands SET status='applied',result=? WHERE id=?", (encoded(result), row["id"]))
            connection.execute("INSERT INTO live_command_events(command_id,phase,payload,created_at) VALUES (?,'applied',?,?)", (row["id"], encoded({**result, "source": "durable_evidence"}), now))
    return allowance
