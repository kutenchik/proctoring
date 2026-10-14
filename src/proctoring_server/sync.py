"""Device-bound reconciliation and durable immutable attempt evidence."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from uuid import uuid4

from .security import digest
from .service import Problem, encoded, instant, iso, text_field

ID = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
UUID = re.compile(r"[a-f0-9]{32}\Z")
SESSION = re.compile(r"session-[a-f0-9]{32}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
KINDS = {"session", "events", "summary", "answers", "original_pdf", "reference", "snapshot"}
FORBIDDEN = {"password", "pin", "proctor_pin", "credential", "device_secret", "token", "access_token", "authorization", "api_key", "webhook_token", "telegram_bot_token", "correct_option_ids", "correct_index"}


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def checksum(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def opaque(value, pattern=ID):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise Problem("invalid_identity", "Invalid opaque identifier")
    return value


def secret(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value):
        raise Problem("invalid_credential", "A random 256-bit device/attempt credential is required", 401)
    return value


def safe_document(value, depth=0):
    if depth > 30:
        raise Problem("invalid_evidence", "Evidence nesting exceeds the supported limit")
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower().replace("-", "_") in FORBIDDEN:
                raise Problem("private_material", "Credentials, PINs, answer keys and private configuration are not evidence")
            safe_document(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            safe_document(child, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise Problem("invalid_evidence", "Non-finite evidence values are not supported")


class SyncService:
    def __init__(self, service):
        self.service = service
        self.database, self.clock = service.database, service.clock
        self.root = service.settings.evidence_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def admission_fields(data, identity):
        if not any(key in data for key in ("admission_id", "device_id", "device_secret", "credential")):
            return None
        result = {"admission_id": opaque(data.get("admission_id"), UUID),
                  "device_id": opaque(data.get("device_id"), UUID),
                  "device_hash": digest(secret(data.get("device_secret"))),
                  "credential": secret(data.get("credential"))}
        result["admission_hash"] = checksum({**identity, "device_id": result["device_id"],
                                             "device_hash": result["device_hash"], "credential_hash": digest(result["credential"])})
        return result

    def bound(self, credential):
        with self.database.connect() as connection:
            row = self.service.credential_attempt(connection, credential, allow_superseded=True)
            return bool(connection.execute("SELECT 1 FROM sync_attempts WHERE attempt_id=?", (row["id"],)).fetchone())

    def _owned(self, connection, credential, device_secret, *, allow_deleted=False, evidence_only=False):
        attempt = self.service.credential_attempt(connection, credential, allow_superseded=True, allow_expired=evidence_only)
        state = connection.execute("SELECT * FROM sync_attempts WHERE attempt_id=?", (attempt["id"],)).fetchone()
        if not state or not hmac.compare_digest(digest(secret(device_secret)), state["device_hash"]):
            raise Problem("wrong_device", "This attempt is bound to its original protected device credential", 403)
        if evidence_only and (not state["start_key"] or not state["session_id"]):
            raise Problem("session_required", "Evidence upload requires an existing authorized canonical session", 409)
        if state["ended_at"] is None and connection.execute("SELECT 1 FROM attempts WHERE exam_id=? AND student_id=? AND sequence>?", (attempt["exam_id"], attempt["student_id"], attempt["sequence"])).fetchone():
            raise Problem("attempt_superseded", "Only ended evidence may synchronize after a replacement attempt", 409)
        if (state["deleted_at"] is not None or state["deletion_pending"]) and not allow_deleted:
            raise Problem("materials_deleted", "Completed attempt materials were deleted", 410)
        return attempt, state

    @staticmethod
    def _session(state, value):
        opaque(value, SESSION)
        if state["session_id"] and state["session_id"] != value:
            raise Problem("session_conflict", "The local session does not match the admitted attempt", 409)

    def _response(self, connection, attempt_id):
        attempt = connection.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        exam = connection.execute("SELECT * FROM exams WHERE id=?", (attempt["exam_id"],)).fetchone()
        return {**self.service.admission_document(attempt, exam, connection), **self.state(connection, attempt_id)}

    def state(self, connection, attempt_id):
        row = connection.execute("SELECT * FROM sync_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if not row:
            return {}
        grant = connection.execute("SELECT * FROM recovery_grants WHERE attempt_id=? AND interruption_id=?", (attempt_id, row["interruption_id"])).fetchone()
        return {"lifecycle": row["lifecycle"], "start_key": row["start_key"], "session_id": row["session_id"],
                "sync_status": "fully_synchronized" if row["lifecycle"] == "synchronized" else "pending",
                "recovery": {"interruption_id": row["interruption_id"], "grant_id": grant["id"] if grant else None,
                             "state": grant["state"] if grant else "pending" if row["interruption_id"] else "none",
                             "checkpoint": json.loads(row["checkpoint"]) if row["checkpoint"] else None}}

    def attempt(self, credential, device_secret):
        with self.database.connect() as connection:
            attempt, _ = self._owned(connection, credential, device_secret)
            return self._response(connection, attempt["id"])

    def authorize_start(self, credential, device_secret, data):
        start_key, session_id = opaque(data.get("start_key"), UUID), opaque(data.get("session_id"), SESSION)
        with self.database.connect(write=True) as connection:
            attempt, state = self._owned(connection, credential, device_secret)
            self._session(state, session_id)
            live = connection.execute("SELECT * FROM live_attempts WHERE attempt_id=?", (attempt["id"],)).fetchone()
            if live and (live["session_id"] != session_id or live["consent_version"] != 3 or live["consent_accepted_at"] is None):
                raise Problem("consent_required", "Explicit full exam-monitor viewing consent is required before start", 409)
            if state["ended_at"] is not None or state["lifecycle"] in ("interrupted", "recovery_authorized"):
                raise Problem("start_blocked", "Attempt is ended or requires teacher-authorized recovery", 409)
            if state["start_key"]:
                if state["start_key"] != start_key:
                    raise Problem("start_conflict", "A different start operation already exists", 409)
            else:
                if self.clock() >= attempt["preparation_deadline"]:
                    raise Problem("preparation_expired", "Preparation deadline has expired", 409)
                if connection.execute("SELECT 1 FROM repeat_grants WHERE source_attempt_id=? AND consumed_at IS NULL", (attempt["id"],)).fetchone():
                    raise Problem("repeat_authorized", "A replacement attempt has already been authorized", 409)
                connection.execute("UPDATE sync_attempts SET lifecycle='start_authorized',start_key=?,session_id=? WHERE attempt_id=?", (start_key, session_id, attempt["id"]))
                self.service.audit(connection, None, "start_authorized", attempt["id"], self.clock())
            return self._response(connection, attempt["id"])

    def confirm_start(self, credential, device_secret, data):
        started_at = instant(data.get("started_at"))
        with self.database.connect(write=True) as connection:
            attempt, state = self._owned(connection, credential, device_secret)
            self._session(state, data.get("session_id"))
            if state["start_key"] != data.get("start_key") or not state["start_key"]:
                raise Problem("start_conflict", "No matching start authorization", 409)
            if state["lifecycle"] not in ("start_authorized", "started"):
                raise Problem("start_blocked", "This start cannot be confirmed", 409)
            if state["local_started_at"] is None:
                if not attempt["admitted_at"] - 300 <= started_at <= self.clock() + 300:
                    raise Problem("invalid_time", "Local start timestamp is outside the admitted time range")
                connection.execute("UPDATE sync_attempts SET lifecycle='started',local_started_at=? WHERE attempt_id=?", (started_at, attempt["id"]))
                connection.execute("UPDATE attempts SET started_at=? WHERE id=?", (started_at, attempt["id"]))
                self.service.audit(connection, None, "local_start_confirmed", attempt["id"], self.clock())
            elif state["local_started_at"] != started_at:
                raise Problem("start_conflict", "Confirmed local start is immutable", 409)
            return self._response(connection, attempt["id"])

    def interrupted(self, credential, device_secret, data):
        interruption_id = opaque(data.get("interruption_id"), UUID)
        reason = text_field(data, "reason", 1000)
        checkpoint = data.get("checkpoint")
        required = {"elapsed_seconds", "remaining_seconds", "answers", "pause_reasons"}
        if not isinstance(checkpoint, dict) or not required <= set(checkpoint) or set(checkpoint) - required - {"duration_seconds", "time_adjustment_ids"}:
            raise Problem("invalid_checkpoint", "A complete timing/answers/pause checkpoint is required")
        safe_document(checkpoint)
        elapsed, remaining = checkpoint["elapsed_seconds"], checkpoint["remaining_seconds"]
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (elapsed, remaining)):
            raise Problem("invalid_checkpoint", "Checkpoint timing is invalid")
        if not isinstance(checkpoint["answers"], dict) or not isinstance(checkpoint["pause_reasons"], list) or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", value) for value in checkpoint["pause_reasons"]):
            raise Problem("invalid_checkpoint", "Checkpoint answers or pause reasons are invalid")
        with self.database.connect(write=True) as connection:
            attempt, state = self._owned(connection, credential, device_secret)
            self._session(state, data.get("session_id"))
            if state["ended_at"] is not None or attempt["finished_at"] is not None:
                raise Problem("attempt_finished", "Terminal completion, including emergency exit, cannot be recovered", 409)
            from .live import effective_allowance
            duration = effective_allowance(connection, attempt, checkpoint, self.clock())
            if abs(elapsed + remaining - duration) > .1:
                raise Problem("invalid_checkpoint", "Checkpoint cannot change exam duration")
            if state["checkpoint"] and elapsed < json.loads(state["checkpoint"])["elapsed_seconds"]:
                raise Problem("invalid_checkpoint", "Recovery cannot reset previously recorded elapsed time")
            if state["interruption_id"] == interruption_id:
                if state["checkpoint"] != encoded(checkpoint):
                    raise Problem("checkpoint_conflict", "An interruption checkpoint is immutable", 409)
            else:
                if state["lifecycle"] not in ("started", "start_authorized", "recovery_authorized"):
                    raise Problem("interruption_conflict", "An interruption is already awaiting recovery", 409)
                connection.execute("UPDATE sync_attempts SET lifecycle='interrupted',interruption_id=?,checkpoint=? WHERE attempt_id=?", (interruption_id, encoded(checkpoint), attempt["id"]))
                self.service.audit(connection, None, "unexpected_interruption", attempt["id"], self.clock(), reason)
            return self._response(connection, attempt["id"])

    def authorize_recovery(self, owner, attempt_id, data):
        reason, interruption_id = text_field(data, "reason", 1000), opaque(data.get("interruption_id"), UUID)
        with self.database.connect(write=True) as connection:
            self.service.owned_attempt(connection, owner, attempt_id)
            state = connection.execute("SELECT * FROM sync_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if not state or state["lifecycle"] != "interrupted" or state["interruption_id"] != interruption_id or state["ended_at"] is not None:
                raise Problem("recovery_unavailable", "Only the current unexpected interruption can receive approval", 409)
            grant = connection.execute("SELECT * FROM recovery_grants WHERE interruption_id=?", (interruption_id,)).fetchone()
            if not grant:
                grant_id = uuid4().hex
                connection.execute("INSERT INTO recovery_grants VALUES (?,?,?,?,?,'granted',?)", (grant_id, attempt_id, interruption_id, owner, reason, self.clock()))
                self.service.audit(connection, owner, "recovery_authorized", attempt_id, self.clock(), reason, {"grant_id": grant_id, "interruption_id": interruption_id})
            return self.state(connection, attempt_id)["recovery"]

    def recovery(self, credential, device_secret, data, confirm=False):
        with self.database.connect(write=True) as connection:
            attempt, state = self._owned(connection, credential, device_secret)
            self._session(state, data.get("session_id"))
            grant = connection.execute("SELECT * FROM recovery_grants WHERE id=? AND attempt_id=? AND interruption_id=?", (data.get("grant_id"), attempt["id"], state["interruption_id"])).fetchone()
            if not grant or state["ended_at"] is not None or state["lifecycle"] not in ("interrupted", "recovery_authorized", "started"):
                raise Problem("recovery_unavailable", "A matching teacher recovery grant is required", 409)
            if confirm and grant["state"] not in ("consumed", "confirmed"):
                raise Problem("recovery_unavailable", "Consume recovery authorization before confirming the local resume", 409)
            if confirm and state["local_started_at"] is None:
                started = instant(data.get("started_at"))
                if not attempt["admitted_at"] - 300 <= started <= self.clock() + 300:
                    raise Problem("invalid_time", "Original local start timestamp is required for recovery confirmation")
                connection.execute("UPDATE sync_attempts SET local_started_at=? WHERE attempt_id=?", (started, attempt["id"]))
                connection.execute("UPDATE attempts SET started_at=? WHERE id=?", (started, attempt["id"]))
            if grant["state"] != "confirmed":
                lifecycle, grant_state = ("started", "confirmed") if confirm else ("recovery_authorized", "consumed")
                connection.execute("UPDATE recovery_grants SET state=? WHERE id=?", (grant_state, grant["id"]))
                connection.execute("UPDATE sync_attempts SET lifecycle=? WHERE attempt_id=?", (lifecycle, attempt["id"]))
                self.service.audit(connection, None, "recovery_" + grant_state, attempt["id"], self.clock())
            return self._response(connection, attempt["id"])

    def records_upload(self, credential, device_secret, data):
        records = data.get("records")
        if not isinstance(records, list) or not 1 <= len(records) <= 100 or len(canonical(records)) > 512 * 1024:
            raise Problem("batch_limit", "Upload 1–100 records within 512 KiB")
        with self.database.connect(write=True) as connection:
            attempt, state = self._owned(connection, credential, device_secret, evidence_only=True)
            self._session(state, data.get("session_id"))
            if not state["session_id"]:
                raise Problem("session_required", "Start authorization must bind the canonical local session", 409)
            for entry in records:
                if not isinstance(entry, dict) or type(entry.get("sequence")) is not int or not 0 <= entry["sequence"] < 100000 or not isinstance(entry.get("record"), dict):
                    raise Problem("invalid_record", "Each record requires a bounded sequence and object payload")
                record = entry["record"]
                if record.get("session_id", state["session_id"]) != state["session_id"]:
                    raise Problem("session_conflict", "Journal record belongs to a different session", 409)
                safe_document(record)
                if len(canonical(record)) > 64 * 1024:
                    raise Problem("record_limit", "Individual record exceeds 64 KiB")
                sha = checksum(record)
                old = connection.execute("SELECT sha256 FROM sync_records WHERE attempt_id=? AND sequence=?", (attempt["id"], entry["sequence"])).fetchone()
                if old and old["sha256"] != sha:
                    raise Problem("record_conflict", "Previously received raw detection records are immutable", 409)
                if not old:
                    if state["lifecycle"] == "synchronized":
                        raise Problem("bundle_frozen", "Complete receipt freezes raw evidence", 409)
                    connection.execute("INSERT INTO sync_records VALUES (?,?,?,?,?)", (attempt["id"], entry["sequence"], encoded(record), sha, self.clock()))
            return {"accepted_sequences": [entry["sequence"] for entry in records]}

    def snapshot_declare(self, credential, device_secret, data):
        """Provisional file declaration; never ends an attempt or issues a receipt."""
        event_id = opaque(data.get("event_id"))
        item_id = "event_" + hashlib.sha256(event_id.encode()).hexdigest()
        path = "snapshots/" + event_id + ".jpg"
        size, sha = data.get("size"), data.get("sha256")
        if type(size) is not int or not 0 < size <= 8*1024*1024 or not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise Problem("invalid_snapshot", "Snapshot requires bounded size and SHA-256")
        with self.database.connect(write=True) as connection:
            attempt, state = self._owned(connection, credential, device_secret, evidence_only=True)
            self._session(state, data.get("session_id"))
            if not json.loads(attempt["policy_snapshot"])["save_snapshots"]:
                raise Problem("policy_conflict", "Event snapshots are disabled", 409)
            consent = connection.execute("SELECT * FROM live_attempts WHERE attempt_id=?", (attempt["id"],)).fetchone()
            if not consent or consent["session_id"] != state["session_id"] or consent["consent_version"] != 3 or consent["consent_accepted_at"] is None:
                raise Problem("snapshot_consent_required", "Early camera evidence requires consent version 3", 403)
            records = connection.execute("SELECT payload FROM sync_records WHERE attempt_id=? AND json_extract(payload,'$.event_id')=? ORDER BY sequence", (attempt["id"], event_id))
            associated = any((r := json.loads(row[0])).get("snapshot_path") == path and r.get("event_type") and r.get("state") != "candidate" for row in records)
            if not associated:
                raise Problem("snapshot_event_required", "Persist the original associated event first", 409)
            old = connection.execute("SELECT * FROM sync_files WHERE attempt_id=? AND item_id=?", (attempt["id"], item_id)).fetchone()
            if old:
                if old["size"] != size or old["sha256"] != sha or old["relative_path"] != path or old["kind"] != "snapshot":
                    raise Problem("file_conflict", "Accepted snapshot identity/content is immutable", 409)
            else:
                if state["current_manifest"] or state["lifecycle"] == "synchronized":
                    raise Problem("bundle_frozen", "Use final manifest for finalized evidence", 409)
                count, total = connection.execute("SELECT COUNT(*),COALESCE(SUM(size),0) FROM sync_files WHERE attempt_id=?", (attempt["id"],)).fetchone()
                if count >= 1900 or total+size > 240*1024*1024:
                    raise Problem("bundle_limit", "Provisional evidence limit reached", 409)
                connection.execute("INSERT INTO sync_files(attempt_id,item_id,kind,relative_path,size,sha256) VALUES (?,?,?,?,?,?)", (attempt["id"],item_id,"snapshot",path,size,sha))
                connection.execute("INSERT INTO event_snapshots VALUES (?,?,?)", (attempt["id"],event_id,item_id))
            row = connection.execute("SELECT received_bytes,complete FROM sync_files WHERE attempt_id=? AND item_id=?", (attempt["id"],item_id)).fetchone()
            return {"item_id":item_id,"received_bytes":row[0],"complete":bool(row[1])}

    def _manifest(self, attempt, state, manifest):
        if not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("attempt_id") != attempt["id"]:
            raise Problem("invalid_manifest", "Manifest identity/version is invalid")
        self._session(state, manifest.get("session_id"))
        if not state["session_id"]:
            raise Problem("session_required", "Manifest must belong to an authorized local session", 409)
        safe_document(manifest)
        ended = instant(manifest.get("ended_at"))
        if not attempt["admitted_at"] - 300 <= ended <= self.clock() + 300:
            raise Problem("invalid_time", "Actual completion timestamp is outside the admitted time range")
        text_field(manifest, "end_reason", 100)
        if type(manifest.get("record_count")) is not int or not 0 <= manifest["record_count"] <= 100000 or type(manifest.get("identity_required")) is not bool:
            raise Problem("invalid_manifest", "Record count and identity requirement must be explicit")
        items = manifest.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 2000 or len(canonical(manifest)) > 512 * 1024:
            raise Problem("manifest_limit", "Manifest item count/size exceeds the supported limit")
        seen, paths, kinds, total = set(), set(), {}, 0
        for item in items:
            if not isinstance(item, dict) or set(item) != {"id", "kind", "relative_path", "required", "status", "size", "sha256", "error"}:
                raise Problem("invalid_manifest", "Each item must use the complete documented item schema")
            opaque(item.get("id"))
            if item["id"] in seen or not isinstance(item["kind"], str) or item["kind"] not in KINDS or type(item["required"]) is not bool:
                raise Problem("invalid_manifest", "Item IDs/kinds/requirements are invalid")
            seen.add(item["id"])
            path = item["relative_path"]
            if not isinstance(path, str) or len(path) > 200 or "\\" in path or ":" in path or path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")):
                raise Problem("invalid_path", "Evidence requires a safe relative filename")
            if path in paths:
                raise Problem("invalid_manifest", "Two items cannot claim the same local file")
            paths.add(path)
            kinds.setdefault(item["kind"], []).append(item)
            extensions = {"session": ".json", "summary": ".json", "answers": ".json", "events": ".jsonl", "original_pdf": ".pdf", "reference": ".jpg", "snapshot": ".jpg"}
            if PurePosixPath(path).suffix.lower() != extensions[item["kind"]] or path.lower().endswith("config.json"):
                raise Problem("invalid_file_type", "File extension does not match an allowed evidence kind")
            if item["status"] not in ("present", "missing_error", "disabled", "optional_absent"):
                raise Problem("invalid_manifest", "Unknown item availability status")
            if item["error"] is not None and (not isinstance(item["error"], str) or len(item["error"]) > 1000):
                raise Problem("invalid_manifest", "Error metadata must be a bounded description")
            if item["status"] == "missing_error" and not item["error"]:
                raise Problem("invalid_manifest", "Missing material must identify its production error")
            if item["status"] == "present":
                if type(item["size"]) is not int or not 0 < item["size"] <= 64 * 1024 * 1024 or not isinstance(item["sha256"], str) or not SHA.fullmatch(item["sha256"]):
                    raise Problem("invalid_manifest", "Present files require a bounded size and SHA-256")
                total += item["size"]
            elif item["size"] is not None or item["sha256"] is not None:
                raise Problem("invalid_manifest", "Absent files must not claim a size or checksum")
        if total > 256 * 1024 * 1024:
            raise Problem("bundle_limit", "Attempt evidence exceeds 256 MiB")
        required = {"session", "events", "summary", "original_pdf"}
        if attempt["quiz_snapshot"]:
            required.add("answers")
        if manifest["identity_required"]:
            required.add("reference")
        for kind in required:
            entries = kinds.get(kind, [])
            if not entries or not any(item["required"] for item in entries) or (kind != "reference" and len(entries) != 1):
                raise Problem("missing_required_kind", f"Manifest must declare required {kind} material")
        for kind in KINDS - {"snapshot", "reference"}:
            if len(kinds.get(kind, [])) > 1:
                raise Problem("invalid_manifest", "Singleton evidence kind declared more than once")
        policy = json.loads(attempt["policy_snapshot"])
        if not policy["save_snapshots"]:
            if len(kinds.get("snapshot", [])) != 1 or kinds["snapshot"][0]["status"] != "disabled":
                raise Problem("policy_conflict", "Disabled snapshots require an explicit disabled marker")
        elif any(item["status"] == "disabled" for item in kinds.get("snapshot", [])):
            raise Problem("policy_conflict", "Enabled snapshot evidence cannot be declared disabled")
        return ended

    def manifest_upload(self, credential, device_secret, data):
        manifest = data.get("manifest")
        with self.database.connect(write=True) as connection:
            attempt, state = self._owned(connection, credential, device_secret, evidence_only=True)
            ended = self._manifest(attempt, state, manifest)
            sha = checksum(manifest)
            if state["current_manifest"] == sha:
                return {"manifest_sha256": sha}
            if state["lifecycle"] == "synchronized":
                raise Problem("bundle_frozen", "Verified receipt forbids changing the manifest", 409)
            if state["ended_at"] is not None and (state["ended_at"] != ended or state["end_reason"] != manifest["end_reason"]):
                raise Problem("completion_conflict", "Actual completion identity is immutable", 409)
            if state["current_manifest"]:
                previous = json.loads(connection.execute("SELECT payload FROM sync_manifests WHERE attempt_id=? AND sha256=?", (attempt["id"], state["current_manifest"])).fetchone()[0])
                current = {item["id"]: item for item in manifest["items"]}
                for item in previous["items"]:
                    if item["status"] == "present" and current.get(item["id"]) != item:
                        raise Problem("file_conflict", "Previously declared present files are immutable", 409)
                if manifest["record_count"] != previous["record_count"] or manifest["identity_required"] != previous["identity_required"]:
                    raise Problem("manifest_conflict", "Manifest repair cannot weaken required evidence", 409)
            current_items = {i["id"]: i for i in manifest["items"]}
            for early in connection.execute("SELECT f.* FROM sync_files f JOIN event_snapshots e ON e.attempt_id=f.attempt_id AND e.item_id=f.item_id WHERE f.attempt_id=?", (attempt["id"],)):
                final = current_items.get(early["item_id"], {})
                if final.get("status") != "present" or any(final.get(k) != early[k] for k in ("kind","relative_path","size","sha256")):
                    raise Problem("file_conflict", "Final manifest must retain every provisional snapshot unchanged", 409)
            connection.execute("INSERT OR IGNORE INTO sync_manifests VALUES (?,?,?,?)", (attempt["id"], sha, encoded(manifest), self.clock()))
            for item in manifest["items"]:
                if item["status"] == "present":
                    connection.execute("INSERT OR IGNORE INTO sync_files(attempt_id,item_id,kind,relative_path,size,sha256) VALUES (?,?,?,?,?,?)", (attempt["id"], item["id"], item["kind"], item["relative_path"], item["size"], item["sha256"]))
            connection.execute("UPDATE sync_attempts SET lifecycle='upload_pending',current_manifest=?,ended_at=?,end_reason=? WHERE attempt_id=?", (sha, ended, manifest["end_reason"], attempt["id"]))
            connection.execute("UPDATE attempts SET finished_at=COALESCE(finished_at,?),end_reason=COALESCE(end_reason,?) WHERE id=?", (ended, manifest["end_reason"], attempt["id"]))
            return {"manifest_sha256": sha}

    def directory(self, attempt_id):
        opaque(attempt_id, UUID)
        target = self.root / attempt_id
        if target.is_symlink() or not target.resolve().is_relative_to(self.root):
            raise Problem("unsafe_storage", "Evidence storage path is not a private owned directory", 500)
        return target

    def _path(self, attempt_id, item_id, partial=False):
        opaque(item_id)
        directory = self.directory(attempt_id)
        path = directory / (item_id + (".part" if partial else ".blob"))
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise Problem("unsafe_storage", "Unsafe evidence file path", 500)
        return path

    @staticmethod
    def _verify_file(path, item):
        try:
            if path.stat().st_size != item["size"]:
                return False
            with path.open("rb") as source:
                hasher = hashlib.sha256()
                while chunk := source.read(256 * 1024):
                    hasher.update(chunk)
            return hmac.compare_digest(hasher.hexdigest(), item["sha256"])
        except OSError:
            return False

    @staticmethod
    def _file_type(path, kind):
        with path.open("rb") as source:
            prefix = source.read(8)
        if kind in ("reference", "snapshot") and not prefix.startswith(b"\xff\xd8\xff"):
            raise Problem("invalid_file_type", "Image evidence must be a JPEG")
        if kind == "original_pdf" and not prefix.startswith(b"%PDF-"):
            raise Problem("invalid_file_type", "Original report must be a PDF")
        if kind in ("reference", "snapshot"):
            from PIL import Image, UnidentifiedImageError
            try:
                with Image.open(path) as picture:
                    if picture.format != "JPEG" or picture.width * picture.height > 16_000_000:
                        raise ValueError("Unsupported image")
                    picture.verify()
                with Image.open(path) as picture:
                    picture.load()
            except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                raise Problem("invalid_file_type", "Image evidence must contain a valid bounded JPEG") from None
        if kind == "original_pdf":
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError
            try:
                with path.open("rb") as source:
                    report = PdfReader(source, strict=True)
                    if report.is_encrypted or not 1 <= len(report.pages) <= 2000:
                        raise ValueError("Unsupported PDF")
            except (OSError, ValueError, PdfReadError):
                raise Problem("invalid_file_type", "Original report must contain a readable, unencrypted PDF") from None
        if kind in ("session", "summary", "answers"):
            try:
                content = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                raise Problem("invalid_file_type", "Structured evidence must be UTF-8 JSON") from None
            if not isinstance(content, dict):
                raise Problem("invalid_file_type", "Structured evidence must be a JSON object")
            safe_document(content)

    def chunk(self, credential, device_secret, item_id, data, *, provisional=False):
        opaque(item_id)
        if type(data.get("offset")) is not int or data["offset"] < 0 or not isinstance(data.get("data_base64"), str) or len(data["data_base64"]) > 350000:
            raise Problem("invalid_chunk", "Chunk offset/data is invalid")
        try:
            chunk = base64.b64decode(data["data_base64"], validate=True)
        except (ValueError, binascii.Error):
            raise Problem("invalid_chunk", "Invalid base64 chunk") from None
        if not 0 < len(chunk) <= 256 * 1024:
            raise Problem("chunk_limit", "Chunk must contain 1–262144 bytes")
        with self.database.connect(write=True) as connection:
            attempt, state = self._owned(connection, credential, device_secret, evidence_only=True)
            if provisional:
                self._session(state, data.get("session_id"))
                early = connection.execute("SELECT 1 FROM event_snapshots WHERE attempt_id=? AND item_id=?", (attempt["id"], item_id)).fetchone()
                if not early or state["current_manifest"]:
                    raise Problem("bundle_frozen", "Provisional upload is not available", 409)
            elif not state["current_manifest"] or state["current_manifest"] != data.get("manifest_sha256"):
                raise Problem("manifest_conflict", "Upload must name the current manifest", 409)
            item = connection.execute("SELECT * FROM sync_files WHERE attempt_id=? AND item_id=?", (attempt["id"], item_id)).fetchone()
            if not item or data["offset"] + len(chunk) > item["size"]:
                raise Problem("invalid_chunk", "Chunk is outside a declared evidence file")
            target, partial = self._path(attempt["id"], item_id), self._path(attempt["id"], item_id, True)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and self._verify_file(target, item):
                with target.open("rb") as source:
                    source.seek(data["offset"])
                    if source.read(len(chunk)) != chunk:
                        raise Problem("chunk_conflict", "Retry differs from persisted evidence", 409)
                connection.execute("UPDATE sync_files SET received_bytes=size,complete=1 WHERE attempt_id=? AND item_id=?", (attempt["id"], item_id))
                return {"item_id": item_id, "received_bytes": item["size"], "complete": True}
            if item["complete"]:
                raise Problem("file_corrupt", "Previously verified evidence is missing or corrupt", 409)
            frontier = item["received_bytes"]
            with partial.open("r+b" if partial.exists() else "w+b") as output:
                output.seek(0, os.SEEK_END)
                if output.tell() < frontier:
                    raise Problem("file_corrupt", "Stored byte frontier is missing", 409)
                if output.tell() > frontier:
                    output.truncate(frontier)
                offset = data["offset"]
                if offset < frontier:
                    if offset + len(chunk) > frontier:
                        raise Problem("chunk_conflict", "Retry crosses the stored byte frontier", 409)
                    output.seek(offset)
                    if output.read(len(chunk)) != chunk:
                        raise Problem("chunk_conflict", "Retry differs from persisted bytes", 409)
                elif offset == frontier:
                    output.seek(frontier)
                    output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                    frontier += len(chunk)
                else:
                    raise Problem("chunk_gap", "Upload the next persisted byte offset", 409)
            complete = frontier == item["size"]
            if complete:
                if not self._verify_file(partial, item):
                    # Uncommitted bytes are retried from the last committed
                    # frontier; do not turn a corrupt upload into an ACK.
                    raise Problem("checksum_mismatch", "File SHA-256 does not match its manifest", 409)
                self._file_type(partial, item["kind"])
                os.replace(partial, target)
            connection.execute("UPDATE sync_files SET received_bytes=?,complete=? WHERE attempt_id=? AND item_id=?", (frontier, int(complete), attempt["id"], item_id))
            return {"item_id": item_id, "received_bytes": frontier, "complete": complete}

    def _missing(self, connection, state, manifest):
        missing = []
        for item in manifest["items"]:
            if item["status"] != "present":
                if item["required"]:
                    missing.append(item["id"] + ":" + item["status"])
                continue
            row = connection.execute("SELECT * FROM sync_files WHERE attempt_id=? AND item_id=?", (state["attempt_id"], item["id"])).fetchone()
            if not row or not row["complete"] or not self._verify_file(self._path(state["attempt_id"], item["id"]), row):
                missing.append(item["id"] + ":not_verified")
        return missing

    def status(self, credential, device_secret):
        with self.database.connect() as connection:
            attempt, state = self._owned(connection, credential, device_secret, allow_deleted=True, evidence_only=True)
            manifest = self._current_manifest(connection, state)
            receipt = connection.execute("SELECT payload FROM sync_receipts WHERE attempt_id=?", (attempt["id"],)).fetchone()
            deleted = state["deleted_at"] is not None or state["deletion_pending"]
            missing = self._missing(connection, state, manifest) if manifest and not deleted else ["manifest"] if not manifest else []
            verified = bool(receipt and not deleted and not missing)
            files = [dict(row) for row in connection.execute("SELECT item_id AS id,received_bytes,complete FROM sync_files WHERE attempt_id=? ORDER BY item_id", (attempt["id"],))]
            return {"status": "deleted" if deleted else "fully_synchronized" if verified else "pending",
                    "manifest_sha256": state["current_manifest"], "files": files,
                    "record_sequences": [row[0] for row in connection.execute("SELECT sequence FROM sync_records WHERE attempt_id=? ORDER BY sequence", (attempt["id"],))],
                    "receipt": json.loads(receipt[0]) if verified else None,
                    "missing": missing, "server_time": iso(self.clock())}

    @staticmethod
    def _current_manifest(connection, state):
        if not state["current_manifest"]:
            return None
        row = connection.execute("SELECT payload FROM sync_manifests WHERE attempt_id=? AND sha256=?", (state["attempt_id"], state["current_manifest"])).fetchone()
        return json.loads(row[0]) if row else None

    def _load_kind(self, manifest, kind):
        item = next((item for item in manifest["items"] if item["kind"] == kind and item["status"] == "present"), None)
        if not item:
            return None
        return json.loads(self._path(manifest["attempt_id"], item["id"]).read_text(encoding="utf-8"))

    def _validate_bundle(self, connection, attempt, state, manifest):
        session = self._load_kind(manifest, "session")
        summary = self._load_kind(manifest, "summary")
        for document in (session, summary):
            if document.get("session_id") != state["session_id"]:
                raise Problem("session_conflict", "Structured evidence has a different canonical session", 409)
            connected = document.get("connected_attempt")
            if not isinstance(connected, dict) or connected.get("attempt_id") != attempt["id"]:
                raise Problem("attempt_conflict", "Evidence belongs to a different server attempt", 409)
        if instant(summary.get("ended_at")) != state["ended_at"] or summary.get("end_reason") != state["end_reason"]:
            raise Problem("completion_conflict", "Final summary and manifest disagree on completion", 409)
        starts = [entry.get("timestamp") for entry in summary.get("lifecycle", []) if isinstance(entry, dict) and entry.get("event_type") == "session_started"]
        if summary.get("started_at"):
            starts.append(summary["started_at"])
        if not starts:
            raise Problem("start_evidence_missing", "Final evidence requires the original local session_started timestamp", 409)
        timestamps = {instant(value) for value in starts}
        if len(timestamps) != 1:
            raise Problem("start_conflict", "Final evidence must preserve one original local start", 409)
        original_start = timestamps.pop()
        if not attempt["admitted_at"] - 300 <= original_start <= state["ended_at"] or (state["local_started_at"] is not None and original_start != state["local_started_at"]):
            raise Problem("start_conflict", "Final evidence disagrees with the original admitted/confirmed start", 409)
        events_item = next(item for item in manifest["items"] if item["kind"] == "events")
        path = self._path(attempt["id"], events_item["id"])
        count = 0
        with path.open(encoding="utf-8") as journal:
            for sequence, line in enumerate(journal):
                try:
                    record = json.loads(line)
                except ValueError:
                    raise Problem("invalid_journal", "Journal contains invalid JSON lines", 409) from None
                safe_document(record)
                if not isinstance(record, dict) or record.get("session_id", state["session_id"]) != state["session_id"]:
                    raise Problem("invalid_journal", "Journal contains another session", 409)
                stored = connection.execute("SELECT sha256 FROM sync_records WHERE attempt_id=? AND sequence=?", (attempt["id"], sequence)).fetchone()
                if not stored or stored[0] != checksum(record):
                    raise Problem("journal_incomplete", "Uploaded journal and immutable record batches do not match", 409)
                count += 1
        stored_count = connection.execute("SELECT COUNT(*) FROM sync_records WHERE attempt_id=?", (attempt["id"],)).fetchone()[0]
        if count != manifest["record_count"] or count != stored_count:
            raise Problem("journal_incomplete", "Journal record count is not complete", 409)
        declared = {item["relative_path"]: item for item in manifest["items"]}
        def reference(path, kind):
            if not path:
                return
            item = declared.get(str(path).replace("\\", "/"))
            if not item or item["kind"] != kind or item["status"] != "present":
                raise Problem("missing_reference", f"Referenced {kind} evidence is missing", 409)
        reference(session.get("reference_face") or summary.get("reference_face"), "reference")
        for event in summary.get("events", []):
            reference(event.get("snapshot_path"), "snapshot")
        for raw in connection.execute("SELECT payload FROM sync_records WHERE attempt_id=?", (attempt["id"],)):
            reference(json.loads(raw[0]).get("snapshot_path"), "snapshot")
        if summary.get("storage_error"):
            raise Problem("production_error", "Recorded journal/storage failure requires explicit recovery before complete receipt", 409)
        if summary.get("snapshot_errors"):
            raise Problem("production_error", "Recorded snapshot failures leave evidence incomplete", 409)
        from .live import effective_allowance
        duration = effective_allowance(connection, attempt, summary, self.clock())
        elapsed, remaining = summary.get("elapsed_seconds"), summary.get("remaining_seconds")
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (elapsed, remaining)) or abs(elapsed + remaining - duration) > .1:
            raise Problem("invalid_timing", "Final timing must preserve the original exam duration", 409)
        result = {"source": "not_applicable", "score": None, "total": None, "percentage": None, "consistent": None}
        if attempt["quiz_snapshot"]:
            submitted = self._load_kind(manifest, "answers")
            if submitted.get("session_id") != state["session_id"] or submitted.get("attempt_id") != attempt["id"] or not isinstance(submitted.get("answers"), dict):
                raise Problem("invalid_answers", "Answers require canonical session and question/option ID selections")
            quiz = json.loads(attempt["quiz_snapshot"])
            selected = submitted["answers"]
            questions = {item["id"]: item for item in quiz["questions"]}
            if any(key not in questions for key in selected):
                raise Problem("invalid_answers", "Submitted answer references an unknown question")
            score = 0
            for qid, question in questions.items():
                values = selected.get(qid, [])
                valid = {option["id"] for option in question["options"]}
                if not isinstance(values, list) or any(not isinstance(value, str) or value not in valid for value in values) or len(values) != len(set(values)) or (question["type"] == "single_choice" and len(values) > 1):
                    raise Problem("invalid_answers", "Submitted selections do not match the immutable question set")
                score += set(values) == set(question["correct_option_ids"])
            total = len(questions)
            result = {"source": "server_verified_answers", "score": score, "total": total,
                      "percentage": score / total * 100, "client_score": summary.get("score"),
                      "client_total": summary.get("total_questions", summary.get("total")),
                      "consistent": summary.get("score") == score and summary.get("total_questions", summary.get("total")) == total}
        return summary, result, original_start

    def complete(self, credential, device_secret, data):
        with self.database.connect(write=True) as connection:
            attempt, state = self._owned(connection, credential, device_secret, evidence_only=True)
            if not state["current_manifest"] or state["current_manifest"] != data.get("manifest_sha256"):
                raise Problem("manifest_conflict", "Complete receipt requires the current full manifest", 409)
            existing = connection.execute("SELECT payload FROM sync_receipts WHERE attempt_id=?", (attempt["id"],)).fetchone()
            manifest = self._current_manifest(connection, state)
            missing = self._missing(connection, state, manifest)
            if missing:
                raise Problem("bundle_incomplete", "Required/present material is not verified: " + ", ".join(missing[:10]), 409)
            summary, result, original_start = self._validate_bundle(connection, attempt, state, manifest)
            if existing:
                return {"receipt": json.loads(existing[0])}
            receipt = {"version": 1, "receipt_id": uuid4().hex, "attempt_id": attempt["id"], "session_id": state["session_id"],
                       "manifest_sha256": state["current_manifest"], "verified_at": iso(self.clock()),
                       "file_count": sum(item["status"] == "present" for item in manifest["items"]), "record_count": manifest["record_count"], "complete": True}
            connection.execute("INSERT INTO sync_receipts VALUES (?,?,?,?)", (attempt["id"], encoded(receipt), state["current_manifest"], self.clock()))
            connection.execute("UPDATE sync_attempts SET lifecycle='synchronized',server_result=?,local_started_at=COALESCE(local_started_at,?) WHERE attempt_id=?", (encoded(result), original_start, attempt["id"]))
            connection.execute("UPDATE attempts SET score=?,total=?,started_at=COALESCE(started_at,?) WHERE id=?", (summary.get("score"), summary.get("total_questions", summary.get("total")), original_start, attempt["id"]))
            self.service.audit(connection, None, "complete_receipt_verified", attempt["id"], self.clock(), details={"manifest_sha256": state["current_manifest"], "receipt_id": receipt["receipt_id"]})
            return {"receipt": receipt}

    def require_complete(self, connection, attempt_id):
        state = connection.execute("SELECT s.*,r.payload AS receipt FROM sync_attempts s LEFT JOIN sync_receipts r ON r.attempt_id=s.attempt_id WHERE s.attempt_id=?", (attempt_id,)).fetchone()
        if not state or state["ended_at"] is None or not state["receipt"] or state["lifecycle"] != "synchronized" or state["deleted_at"] is not None or state["deletion_pending"]:
            raise Problem("review_not_ready", "Ended attempt and verified complete evidence receipt are required", 409)
        manifest = self._current_manifest(connection, state)
        if not manifest or self._missing(connection, state, manifest):
            raise Problem("bundle_incomplete", "Evidence persistence verification failed", 409)
        return json.loads(state["receipt"])

    def records(self, owner, attempt_id):
        with self.database.connect() as connection:
            self.service.owned_attempt(connection, owner, attempt_id)
            state = connection.execute("SELECT deleted_at,deletion_pending FROM sync_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if state and (state["deleted_at"] is not None or state["deletion_pending"]):
                raise Problem("materials_deleted", "Attempt material is deleted or being deleted", 410)
            return [json.loads(row[0]) for row in connection.execute("SELECT payload FROM sync_records WHERE attempt_id=? ORDER BY sequence", (attempt_id,))]

    def teacher_detail(self, owner, attempt_id):
        with self.database.connect() as connection:
            attempt = self.service.owned_attempt(connection, owner, attempt_id)
            exam = self.service.owned_exam(connection, owner, attempt["exam_id"])
            state = connection.execute("SELECT * FROM sync_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            receipt = connection.execute("SELECT payload FROM sync_receipts WHERE attempt_id=?", (attempt_id,)).fetchone()
            deleted = bool(state and (state["deleted_at"] is not None or state["deletion_pending"]))
            manifest = self._current_manifest(connection, state) if state and not deleted else None
            verified = bool(receipt and manifest and not deleted and not self._missing(connection, state, manifest))
            result = {"attempt": self.service.attempt_document(attempt, connection), "exam": self.service.exam_document(exam, connection),
                      "lifecycle": state["lifecycle"] if state else "legacy", "status": "deleted" if deleted else "fully_synchronized" if verified else "pending",
                      "receipt_complete": verified, "receipt": json.loads(receipt[0]) if receipt else None,
                      "manifest": manifest,
                      "files": [dict(row) for row in connection.execute("SELECT item_id AS id,kind,relative_path,size,sha256,received_bytes,complete FROM sync_files WHERE attempt_id=? ORDER BY item_id", (attempt_id,))],
                      "server_result": json.loads(state["server_result"]) if state and state["server_result"] else None,
                      "client_result": {"score": attempt["score"], "total": attempt["total"], "source": "client_reported"},
                      "deleted_at": iso(state["deleted_at"]) if state else None,
                      "deletion_pending": bool(state and state["deletion_pending"]),
                      "retention_until": iso(state["ended_at"] + 30 * 86400) if state and state["ended_at"] is not None else None,
                      "records": [{"sequence": row[0], "record": json.loads(row[1])} for row in connection.execute("SELECT sequence,payload FROM sync_records WHERE attempt_id=? ORDER BY sequence", (attempt_id,))],
                      "timing": {"started_at": iso(state["local_started_at"]) if state else iso(attempt["started_at"]), "ended_at": iso(state["ended_at"]) if state else iso(attempt["finished_at"]), "elapsed_seconds": None, "remaining_seconds": None},
                      "recovery": self.state(connection, attempt_id).get("recovery")}
            if deleted:
                result["records"], result["files"] = [], []
                result["recovery"] = None
            if state and result["manifest"] and not deleted:
                try:
                    summary = self._load_kind(result["manifest"], "summary")
                    if summary:
                        result["timing"].update({key: summary.get(key) for key in ("elapsed_seconds", "remaining_seconds")})
                except (OSError, ValueError):
                    pass
            return result

    def file_path(self, owner, attempt_id, item_id):
        with self.database.connect() as connection:
            self.service.owned_attempt(connection, owner, attempt_id)
            state = connection.execute("SELECT * FROM sync_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            item = connection.execute("SELECT * FROM sync_files WHERE attempt_id=? AND item_id=?", (attempt_id, item_id)).fetchone()
            if state and (state["deleted_at"] is not None or state["deletion_pending"]):
                raise Problem("materials_deleted", "Evidence has been deleted or is being deleted", 410)
            if not state or not item or not item["complete"]:
                raise Problem("not_found", "Evidence is unavailable", 404)
            path = self._path(attempt_id, item_id)
            if not self._verify_file(path, item):
                raise Problem("file_corrupt", "Evidence persistence check failed", 409)
            return path

    def evidence_file(self, owner, attempt_id, item_id):
        path = self.file_path(owner, attempt_id, item_id)
        with self.database.connect() as connection:
            row = connection.execute("SELECT kind,relative_path FROM sync_files WHERE attempt_id=? AND item_id=?", (attempt_id, item_id)).fetchone()
        media = "application/pdf" if row["kind"] == "original_pdf" else "image/jpeg" if row["kind"] in ("snapshot", "reference") else "application/json" if row["kind"] != "events" else "application/x-ndjson"
        return path, media, PurePosixPath(row["relative_path"]).name

    def delete_materials(self, owner, attempt_id, data, *, retention=False):
        if data.get("confirm") is not True:
            raise Problem("confirmation_required", "Explicit confirmation is required")
        reason = text_field(data, "reason", 1000)
        with self.database.connect(write=True) as connection:
            self.service.owned_attempt(connection, owner, attempt_id)
            state = connection.execute("SELECT * FROM sync_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if state and state["deleted_at"] is not None:
                return {"deleted": True, "deleted_at": iso(state["deleted_at"])}
            if not state or not state["deletion_pending"]:
                self.require_complete(connection, attempt_id)
            if retention and state["ended_at"] + 30 * 86400 > self.clock():
                raise Problem("retention_not_due", "Retention period has not elapsed", 409)
            connection.execute("UPDATE sync_attempts SET deletion_pending=1 WHERE attempt_id=?", (attempt_id,))
        # Commit the tombstone intent before deleting bytes. A crash or disk
        # error blocks all reads/writes and allows idempotent explicit retry.
        target = self.directory(attempt_id)
        if target.parent.resolve() != self.root or target.name != attempt_id:
            raise Problem("unsafe_storage", "Deletion target escaped private evidence root", 500)
        if target.exists():
            shutil.rmtree(target)
        with self.database.connect(write=True) as connection:
            now = self.clock()
            connection.execute("UPDATE sync_attempts SET deleted_at=?,checkpoint=NULL,deletion_pending=0 WHERE attempt_id=?", (now, attempt_id))
            connection.execute("DELETE FROM sync_records WHERE attempt_id=?", (attempt_id,))
            connection.execute("DELETE FROM event_snapshots WHERE attempt_id=?", (attempt_id,))
            connection.execute("DELETE FROM sync_files WHERE attempt_id=?", (attempt_id,))
            connection.execute("DELETE FROM sync_manifests WHERE attempt_id=?", (attempt_id,))
            connection.execute("UPDATE attempt_conclusions SET review_snapshot='{}',comment='',report_status='deleted',report_error=NULL WHERE attempt_id=?", (attempt_id,))
            connection.execute("DELETE FROM event_review_versions WHERE attempt_id=?", (attempt_id,))
            connection.execute("DELETE FROM manual_observation_versions WHERE attempt_id=?", (attempt_id,))
            connection.execute("UPDATE live_command_events SET payload='{}' WHERE command_id IN (SELECT id FROM live_commands WHERE attempt_id=?)", (attempt_id,))
            connection.execute("UPDATE live_commands SET payload='{}',result=NULL WHERE attempt_id=?", (attempt_id,))
            connection.execute("UPDATE audit_log SET details=? WHERE resource_id=? AND action IN ('event_reviewed','manual_observation_changed','attempt_concluded')", (encoded({"materials_deleted": True}), attempt_id))
            self.service.audit(connection, owner, "retention_deleted" if retention else "materials_deleted_early", attempt_id, now, reason)
            return {"deleted": True, "deleted_at": iso(now)}

    def retain(self):
        with self.database.connect() as connection:
            rows = connection.execute("SELECT s.attempt_id,e.teacher_id FROM sync_attempts s JOIN attempts a ON a.id=s.attempt_id JOIN exams e ON e.id=a.exam_id JOIN sync_receipts r ON r.attempt_id=s.attempt_id WHERE s.deleted_at IS NULL AND s.lifecycle='synchronized' AND s.ended_at<=?", (self.clock() - 30 * 86400,)).fetchall()
        results = []
        for row in rows:
            results.append({"attempt_id": row["attempt_id"], **self.delete_materials(row["teacher_id"], row["attempt_id"], {"confirm": True, "reason": "30-day completed evidence retention expired"}, retention=True)})
        return {"deleted": results}
