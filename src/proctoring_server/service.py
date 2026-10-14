"""Transactional teacher, exam and admission operations; no desktop side effects."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import secrets
import sqlite3
import time
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from proctoring.browser_policy import NavigationPolicy

from .database import Database
from .imports import normalized
from .security import digest, email_address, hash_password, token, verify_password
from .settings import Settings


class Problem(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def text_field(data: dict, key: str, limit: int = 200) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Problem("invalid_input", f"{key} must be nonempty text of at most {limit} characters")
    if any(ord(character) < 32 for character in value):
        raise Problem("invalid_input", f"{key} must not contain control characters")
    return value.strip()


def iso(value: float | None):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def instant(value: object) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.timestamp()
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise Problem("invalid_time", "Admission timestamps must include an explicit UTC offset") from None


def identifier() -> str:
    return uuid4().hex


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class Service:
    def __init__(self, settings: Settings, clock=time.time):
        self.settings, self.clock = settings, clock
        self.database = Database(settings.database)
        self.database.migrate()
        self._dummy_password_hash = hash_password("not-a-real-account-password")

    @staticmethod
    def audit(connection, teacher_id, action, resource, now, reason=None, details=None):
        connection.execute("INSERT INTO audit_log VALUES (?,?,?,?,?,?,?)",
                           (identifier(), teacher_id, action, resource, reason, encoded(details or {}), now))

    def issue_account_token(self, kind: str, email: str) -> str:
        if kind not in ("invite", "reset"):
            raise ValueError("Unsupported account token kind")
        email = email_address(email)
        raw, now = token(), self.clock()
        with self.database.connect(write=True) as connection:
            account = connection.execute("SELECT id FROM teachers WHERE email=?", (email,)).fetchone()
            if kind == "invite" and account:
                raise Problem("account_exists", "This teacher already has an account")
            if kind == "reset" and not account:
                raise Problem("account_missing", "No teacher has this email address")
            # Generating a replacement invalidates previous outstanding links.
            connection.execute("UPDATE account_tokens SET consumed_at=? WHERE kind=? AND email=? AND consumed_at IS NULL",
                               (now, kind, email))
            connection.execute("INSERT INTO account_tokens VALUES (?,?,?,?,NULL,?)",
                               (digest(raw), kind, email, now + self.settings.token_seconds, now))
        return raw

    def consume_account_token(self, kind: str, data: dict) -> dict:
        raw = text_field(data, "token", 256)
        token_hash = digest(raw)
        # Unknown/expired/used links must not trigger expensive password work.
        # Hash outside a write transaction, then recheck under the consume lock.
        with self.database.connect() as connection:
            entry = connection.execute("SELECT expires_at,consumed_at FROM account_tokens WHERE token_hash=? AND kind=?",
                                       (token_hash, kind)).fetchone()
        if not entry or entry["consumed_at"] is not None or entry["expires_at"] <= self.clock():
            raise Problem("invalid_token", "This link is invalid, expired or already used", 400)
        name = text_field(data, "name") if kind == "invite" else None
        password_hash = hash_password(data.get("password"))
        with self.database.connect(write=True) as connection:
            now = self.clock()
            entry = connection.execute("SELECT * FROM account_tokens WHERE token_hash=? AND kind=?",
                                       (token_hash, kind)).fetchone()
            if not entry or entry["consumed_at"] is not None or entry["expires_at"] <= now:
                raise Problem("invalid_token", "This link is invalid, expired or already used", 400)
            if kind == "invite":
                teacher_id = identifier()
                try:
                    connection.execute("INSERT INTO teachers VALUES (?,?,?,?,?)",
                                       (teacher_id, entry["email"], name, password_hash, now))
                except sqlite3.IntegrityError:
                    raise Problem("invalid_token", "An account already exists for this link") from None
                result = {"id": teacher_id, "email": entry["email"], "name": name}
            else:
                teacher = connection.execute("SELECT * FROM teachers WHERE email=?", (entry["email"],)).fetchone()
                if not teacher:
                    raise Problem("invalid_token", "This reset link no longer has an account")
                teacher_id = teacher["id"]
                connection.execute("UPDATE teachers SET password_hash=? WHERE id=?", (password_hash, teacher_id))
                connection.execute("DELETE FROM sessions WHERE teacher_id=?", (teacher_id,))
                result = {"id": teacher_id, "email": teacher["email"], "name": teacher["name"]}
            connection.execute("UPDATE account_tokens SET consumed_at=? WHERE token_hash=?", (now, token_hash))
            self.audit(connection, teacher_id, kind + "_accepted", teacher_id, now)
        return {"teacher": result}

    @staticmethod
    def csrf(raw_session: str) -> str:
        return digest("csrf:" + raw_session)

    def login(self, data: dict, client_ip: str) -> tuple[str, dict]:
        email = email_address(text_field(data, "email", 254))
        password = data.get("password")
        if not isinstance(password, str) or not 1 <= len(password) <= 256:
            raise Problem("invalid_credentials", "Email or password is incorrect", 401)
        now = self.clock()
        # Persistent per-account and per-peer budgets, without trusting proxy
        # forwarded headers. CLI/reset access remains available after lockout.
        buckets = [("email:" + digest(email), 10), ("ip:" + digest(client_ip), 50)]
        with self.database.connect(write=True) as connection:
            for bucket, limit in buckets:
                entry = connection.execute("SELECT * FROM login_throttle WHERE bucket=?", (bucket,)).fetchone()
                if entry and entry["blocked_until"] > now:
                    raise Problem("login_throttled", "Too many login attempts; retry in 15 minutes", 429)
                count = entry["failures"] if entry and now - entry["window_start"] < 900 else 0
                start = entry["window_start"] if count else now
                count += 1
                connection.execute("INSERT OR REPLACE INTO login_throttle VALUES (?,?,?,?)",
                                   (bucket, start, count, now + 900 if count >= limit else 0))
            teacher = connection.execute("SELECT * FROM teachers WHERE email=?", (email,)).fetchone()
        if not verify_password(password, teacher["password_hash"] if teacher else self._dummy_password_hash) or not teacher:
            raise Problem("invalid_credentials", "Email or password is incorrect", 401)
        raw = token()
        with self.database.connect(write=True) as connection:
            # A concurrent password reset must not resurrect a session based on
            # credentials checked before that reset.
            current = connection.execute("SELECT password_hash FROM teachers WHERE id=?", (teacher["id"],)).fetchone()
            if current["password_hash"] != teacher["password_hash"]:
                raise Problem("invalid_credentials", "Email or password is incorrect", 401)
            connection.execute("INSERT INTO sessions VALUES (?,?,?,?,?)",
                               (digest(raw), teacher["id"], digest(self.csrf(raw)), now, now + self.settings.session_seconds))
            connection.execute("DELETE FROM login_throttle WHERE bucket=?", (buckets[0][0],))
            connection.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
        return raw, {"teacher": {key: teacher[key] for key in ("id", "email", "name")}, "csrf_token": self.csrf(raw)}

    def authenticate(self, raw: str | None, csrf: str | None = None, mutate=False) -> dict:
        if not raw or len(raw) > 256:
            raise Problem("login_required", "Please sign in", 401)
        with self.database.connect() as connection:
            row = connection.execute("SELECT s.*,t.name,t.email FROM sessions s JOIN teachers t ON t.id=s.teacher_id WHERE token_hash=?",
                                     (digest(raw),)).fetchone()
        if not row or row["expires_at"] <= self.clock():
            raise Problem("login_required", "Session expired; please sign in again", 401)
        if mutate:
            import hmac
            if not csrf or not hmac.compare_digest(digest(csrf), row["csrf_hash"]):
                raise Problem("csrf_rejected", "Refresh the page and retry this action", 403)
        return {"teacher": {"id": row["teacher_id"], "email": row["email"], "name": row["name"]},
                "csrf_token": self.csrf(raw)}

    def logout(self, raw: str):
        with self.database.connect(write=True) as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash=?", (digest(raw),))

    def save_library(self, owner: str, data: dict):
        document = normalized(data)
        library_id, now = identifier(), self.clock()
        with self.database.connect(write=True) as connection:
            connection.execute("INSERT INTO libraries VALUES (?,?,?,?,?)",
                               (library_id, owner, document["title"], encoded(document), now))
        return {**document, "id": library_id, "created_at": iso(now)}

    def libraries(self, owner: str):
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM libraries WHERE teacher_id=? ORDER BY created_at DESC,id", (owner,)).fetchall()
        return {"items": [{"id": row["id"], "title": row["title"], "created_at": iso(row["created_at"]),
                            "question_count": len(json.loads(row["document"])["questions"])} for row in rows]}

    def library(self, owner: str, library_id: str):
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM libraries WHERE id=? AND teacher_id=?", (library_id, owner)).fetchone()
        if not row:
            raise Problem("not_found", "Question set not found", 404)
        return {**json.loads(row["document"]), "id": row["id"], "created_at": iso(row["created_at"])}

    def create_exam(self, owner: str, data: dict):
        title, exam_type = text_field(data, "title"), text_field(data, "exam_type")
        if exam_type not in ("native", "external"):
            raise Problem("invalid_exam", "Exam type must be native or external")
        zone = text_field(data, "timezone", 100)
        try:
            ZoneInfo(zone)
        except (ValueError, ZoneInfoNotFoundError):
            raise Problem("invalid_timezone", "Choose a valid IANA timezone") from None
        start, close = instant(data.get("admission_start")), instant(data.get("admission_close"))
        if not start < close:
            raise Problem("invalid_window", "Admission close must follow admission start")
        duration = data.get("duration_seconds")
        if type(duration) is not int or not 30 <= duration <= 86400:
            raise Problem("invalid_duration", "Duration must be a whole number of seconds from 30 to 86400")
        policy = {}
        for key in ("shuffle_questions", "shuffle_options", "audio_monitoring", "save_snapshots"):
            value = data.get(key, False)
            if type(value) is not bool:
                raise Problem("invalid_policy", f"{key} must be true or false")
            policy[key] = value
        policy["protection_mode"] = data.get("protection_mode", "unprotected")
        if policy["protection_mode"] not in ("protected", "unprotected"):
            raise Problem("invalid_policy", "Protection mode must be protected or unprotected")
        external = ""
        if exam_type == "external":
            external = text_field(data, "external_url", 2048)
            try:
                external = NavigationPolicy(external).external_url
            except ValueError as error:
                raise Problem("invalid_url", str(error)) from None
            if not external.startswith("https://"):
                raise Problem("invalid_url", "External exam URL must use HTTPS without embedded credentials")
        exam_id, now = identifier(), self.clock()
        with self.database.connect(write=True) as connection:
            quiz = None
            if exam_type == "native":
                row = connection.execute("SELECT document FROM libraries WHERE id=? AND teacher_id=?",
                                         (text_field(data, "library_id"), owner)).fetchone()
                if not row:
                    raise Problem("not_found", "Question set not found", 404)
                quiz = row["document"]
            for _ in range(10):
                code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
                if not connection.execute("SELECT 1 FROM exams WHERE code=?", (code,)).fetchone():
                    break
            else:
                raise Problem("code_unavailable", "Could not allocate an exam code; retry", 503)
            connection.execute("INSERT INTO exams(id,teacher_id,code,title,exam_type,admission_start,admission_close,duration_seconds,timezone,external_url,quiz_snapshot,policy_snapshot,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (exam_id, owner, code, title, exam_type, start, close, duration, zone, external, quiz,
                                encoded(policy), now))
            self.audit(connection, owner, "exam_created", exam_id, now)
        return self.exam(owner, exam_id)

    def exam_document(self, row, connection, detail=False):
        now = self.clock()
        result = {key: row[key] for key in ("id", "code", "title", "exam_type", "duration_seconds", "timezone", "external_url")}
        result.update({key: iso(row[key]) for key in ("admission_start", "admission_close", "created_at")})
        result["policy"] = json.loads(row["policy_snapshot"])
        result.update(result["policy"])
        admission_open = row["admissions_closed_at"] is None and row["admission_start"] <= now < row["admission_close"]
        result["admissions_closed_at"] = iso(row["admissions_closed_at"])
        unfinished = connection.execute("SELECT 1 FROM attempts a WHERE exam_id=? AND finished_at IS NULL AND (started_at IS NOT NULL OR preparation_deadline>? OR EXISTS(SELECT 1 FROM sync_attempts s WHERE s.attempt_id=a.id AND s.start_key IS NOT NULL)) LIMIT 1",
                                        (row["id"], now)).fetchone()
        result["admission_open"] = admission_open
        result["phase_basis"] = "server_admission_and_recorded_attempts"
        result["phase"] = ("upcoming" if now < row["admission_start"] else "active" if admission_open or unfinished else "completed")
        counts = connection.execute("SELECT COUNT(*) AS attempts,COUNT(DISTINCT student_id) AS participants FROM attempts WHERE exam_id=?", (row["id"],)).fetchone()
        result.update(attempt_count=counts["attempts"], participant_count=counts["participants"])
        if detail:
            result["quiz"] = json.loads(row["quiz_snapshot"]) if row["quiz_snapshot"] else None
        return result

    def exams(self, owner):
        with self.database.connect() as connection:
            return {"items": [self.exam_document(row, connection) for row in connection.execute("SELECT * FROM exams WHERE teacher_id=? ORDER BY created_at DESC,id", (owner,)).fetchall()]}

    @staticmethod
    def owned_exam(connection, owner, exam_id):
        row = connection.execute("SELECT * FROM exams WHERE id=? AND teacher_id=?", (exam_id, owner)).fetchone()
        if not row:
            raise Problem("not_found", "Exam not found", 404)
        return row

    def exam(self, owner, exam_id):
        with self.database.connect() as connection:
            return self.exam_document(self.owned_exam(connection, owner, exam_id), connection, True)

    def attempt_document(self, row, connection):
        result = {key: row[key] for key in ("id", "exam_id", "student_id", "sequence", "full_name", "score", "total", "end_reason")}
        result.update({key: iso(row[key]) for key in ("admitted_at", "preparation_deadline", "started_at", "finished_at")})
        result["group"] = row["student_group"]
        result["status"] = ("finished" if row["finished_at"] is not None else "started" if row["started_at"] is not None
                            else "preparation_expired" if self.clock() >= row["preparation_deadline"] else "admitted")
        result["result_source"] = "client_reported" if row["finished_at"] is not None else None
        state = connection.execute("SELECT lifecycle,deleted_at,deletion_pending FROM sync_attempts WHERE attempt_id=?", (row["id"],)).fetchone()
        if state:
            result["lifecycle"] = "deleted" if state["deleted_at"] is not None or state["deletion_pending"] else state["lifecycle"]
        result["repeat_authorized"] = bool(connection.execute("SELECT 1 FROM repeat_grants WHERE source_attempt_id=? AND consumed_at IS NULL", (row["id"],)).fetchone())
        return result

    def attempts(self, owner, exam_id):
        with self.database.connect() as connection:
            self.owned_exam(connection, owner, exam_id)
            rows = connection.execute("SELECT * FROM attempts WHERE exam_id=? ORDER BY admitted_at,id", (exam_id,)).fetchall()
            return {"items": [self.attempt_document(row, connection) for row in rows]}

    @staticmethod
    def owned_attempt(connection, owner, attempt_id):
        row = connection.execute("SELECT a.* FROM attempts a JOIN exams e ON a.exam_id=e.id WHERE a.id=? AND e.teacher_id=?", (attempt_id, owner)).fetchone()
        if not row:
            raise Problem("not_found", "Attempt not found", 404)
        return row

    def extend(self, owner, attempt_id, data):
        reason = text_field(data, "reason", 1000)
        with self.database.connect(write=True) as connection:
            now = self.clock()
            row = self.owned_attempt(connection, owner, attempt_id)
            if connection.execute("SELECT 1 FROM sync_attempts WHERE attempt_id=? AND start_key IS NOT NULL", (attempt_id,)).fetchone():
                raise Problem("attempt_started", "A start authorization already exists; reconcile or recover that attempt", 409)
            if row["started_at"] is not None or row["finished_at"] is not None:
                raise Problem("attempt_started", "Preparation can only be extended before starting", 409)
            if connection.execute("SELECT 1 FROM attempts WHERE exam_id=? AND student_id=? AND sequence>?", (row["exam_id"], row["student_id"], row["sequence"])).fetchone():
                raise Problem("attempt_superseded", "A newer attempt already exists", 409)
            if connection.execute("SELECT 1 FROM repeat_grants WHERE source_attempt_id=? AND consumed_at IS NULL", (attempt_id,)).fetchone():
                raise Problem("repeat_authorized", "A repeat has already been authorized for this attempt", 409)
            deadline = max(row["preparation_deadline"], now) + 300
            connection.execute("UPDATE attempts SET preparation_deadline=?,credential_expires_at=MAX(credential_expires_at,?) WHERE id=?",
                               (deadline, deadline + self.settings.attempt_retention_seconds, attempt_id))
            self.audit(connection, owner, "preparation_extended", attempt_id, now, reason,
                       {"old_deadline": iso(row["preparation_deadline"]), "new_deadline": iso(deadline), "seconds": 300})
            return self.attempt_document(self.owned_attempt(connection, owner, attempt_id), connection)

    def allow_repeat(self, owner, attempt_id, data):
        reason, grant_id = text_field(data, "reason", 1000), identifier()
        with self.database.connect(write=True) as connection:
            now = self.clock()
            row = self.owned_attempt(connection, owner, attempt_id)
            if row["finished_at"] is None and connection.execute("SELECT 1 FROM sync_attempts WHERE attempt_id=? AND start_key IS NOT NULL", (attempt_id,)).fetchone():
                raise Problem("attempt_live", "A start authorization is pending reconciliation; use same-attempt recovery", 409)
            if row["finished_at"] is None and (row["started_at"] is not None or row["preparation_deadline"] > now):
                raise Problem("attempt_live", "Finish the current attempt or wait until its preparation expires", 409)
            if connection.execute("SELECT 1 FROM attempts WHERE exam_id=? AND student_id=? AND sequence>?", (row["exam_id"], row["student_id"], row["sequence"])).fetchone():
                raise Problem("attempt_superseded", "Only the most recent attempt can receive repeat authorization", 409)
            try:
                connection.execute("INSERT INTO repeat_grants VALUES (?,?,?,?,?,?,?,NULL,NULL)",
                                   (grant_id, row["exam_id"], row["student_id"], attempt_id, owner, reason, now))
            except sqlite3.IntegrityError:
                raise Problem("repeat_exists", "An unused repeat authorization already exists", 409) from None
            self.audit(connection, owner, "repeat_authorized", attempt_id, now, reason, {"grant_id": grant_id})
        return {"attempt_id": attempt_id, "grant_id": grant_id, "reason": reason}

    def admit(self, data):
        code = text_field(data, "exam_code", 32).upper()
        full_name = text_field(data, "full_name")
        group, student_id = (text_field(data, key, 128) for key in ("group", "student_id"))
        from .sync import SyncService
        binding = SyncService.admission_fields(data, {"exam_code": code, "full_name": full_name, "group": group, "student_id": student_id})
        raw, attempt_id = binding["credential"] if binding else token(), identifier()
        with self.database.connect(write=True) as connection:
            now = self.clock()
            if binding:
                old = connection.execute("SELECT * FROM sync_attempts WHERE admission_id=?", (binding["admission_id"],)).fetchone()
                if old:
                    if old["admission_hash"] != binding["admission_hash"]:
                        raise Problem("admission_conflict", "Admission retry differs from its original durable request", 409)
                    row = self.credential_attempt(connection, raw)
                    if old["deleted_at"] or old["deletion_pending"]:
                        raise Problem("materials_deleted", "Attempt materials were deleted", 410)
                    exam = connection.execute("SELECT * FROM exams WHERE id=?", (row["exam_id"],)).fetchone()
                    return {**self.admission_document(row, exam, connection), "credential": raw}
            exam = connection.execute("SELECT * FROM exams WHERE code=?", (code,)).fetchone()
            if not exam:
                raise Problem("exam_not_found", "Exam code not found", 404)
            if exam["admissions_closed_at"] is not None or not exam["admission_start"] <= now < exam["admission_close"]:
                raise Problem("admission_closed", "Admission is not open according to server time", 409)
            previous = connection.execute("SELECT * FROM attempts WHERE exam_id=? AND student_id=? ORDER BY sequence DESC LIMIT 1", (exam["id"], student_id)).fetchone()
            grant = None
            if previous:
                grant = connection.execute("SELECT * FROM repeat_grants WHERE exam_id=? AND student_id=? AND consumed_at IS NULL AND source_attempt_id=?", (exam["id"], student_id, previous["id"])).fetchone()
                if not grant:
                    raise Problem("attempt_exists", "An attempt already exists for this Student ID; teacher authorization is required for a repeat", 409)
            quiz = json.loads(exam["quiz_snapshot"]) if exam["quiz_snapshot"] else None
            policy = json.loads(exam["policy_snapshot"])
            if quiz:
                quiz = deepcopy(quiz)
                random = secrets.SystemRandom()
                if policy["shuffle_questions"]:
                    random.shuffle(quiz["questions"])
                if policy["shuffle_options"]:
                    for question in quiz["questions"]:
                        random.shuffle(question["options"])
            deadline = now + 300
            connection.execute("INSERT INTO attempts (id,exam_id,student_id,sequence,full_name,student_group,credential_hash,credential_expires_at,admitted_at,preparation_deadline,quiz_snapshot,policy_snapshot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (attempt_id, exam["id"], student_id, previous["sequence"] + 1 if previous else 1,
                                full_name, group, digest(raw), deadline + self.settings.attempt_retention_seconds,
                                now, deadline, encoded(quiz) if quiz else None, exam["policy_snapshot"]))
            if grant:
                connection.execute("UPDATE repeat_grants SET consumed_at=?,new_attempt_id=? WHERE id=?", (now, attempt_id, grant["id"]))
            if binding:
                connection.execute("INSERT INTO sync_attempts(attempt_id,admission_id,admission_hash,device_id,device_hash) VALUES (?,?,?,?,?)", (attempt_id, binding["admission_id"], binding["admission_hash"], binding["device_id"], binding["device_hash"]))
            self.audit(connection, None, "student_admitted", attempt_id, now, details={"exam_id": exam["id"], "repeat_grant_id": grant["id"] if grant else None})
            row = connection.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            return {**self.admission_document(row, exam, connection), "credential": raw}

    def credential_attempt(self, connection, credential, *, allow_superseded=False, allow_expired=False):
        if not credential or not isinstance(credential, str) or len(credential) > 256:
            raise Problem("invalid_credential", "Attempt credential is required", 401)
        row = connection.execute("SELECT * FROM attempts WHERE credential_hash=?", (digest(credential),)).fetchone()
        if not row or (not allow_expired and row["credential_expires_at"] <= self.clock()):
            raise Problem("invalid_credential", "Attempt credential is invalid or expired", 401)
        if not allow_superseded and connection.execute("SELECT 1 FROM attempts WHERE exam_id=? AND student_id=? AND sequence>?", (row["exam_id"], row["student_id"], row["sequence"])).fetchone():
            raise Problem("attempt_superseded", "This attempt was replaced by an authorized repeat", 409)
        return row

    def admission_document(self, attempt, exam, connection):
        document = self.attempt_document(attempt, connection)
        public_exam = self.exam_document(exam, connection)
        # Other students' counts and records are not admission information.
        public_exam.pop("participant_count", None)
        public_exam.pop("attempt_count", None)
        public_exam["policy"] = json.loads(attempt["policy_snapshot"])
        return {"attempt_id": attempt["id"], "status": document["status"], "server_time": iso(self.clock()),
                "preparation_deadline": document["preparation_deadline"], "started_at": document["started_at"],
                "finished_at": document["finished_at"], "exam": public_exam,
                "quiz": json.loads(attempt["quiz_snapshot"]) if attempt["quiz_snapshot"] else None}

    def student_attempt(self, credential):
        with self.database.connect() as connection:
            row = self.credential_attempt(connection, credential)
            exam = connection.execute("SELECT * FROM exams WHERE id=?", (row["exam_id"],)).fetchone()
            return self.admission_document(row, exam, connection)

    def start(self, credential):
        with self.database.connect(write=True) as connection:
            row = self.credential_attempt(connection, credential)
            now = self.clock()
            if row["finished_at"] is not None:
                raise Problem("attempt_finished", "This attempt is already finished", 409)
            if row["started_at"] is None:
                if now >= row["preparation_deadline"]:
                    raise Problem("preparation_expired", "Preparation time expired; ask the teacher for a five-minute extension", 409)
                if connection.execute("SELECT 1 FROM repeat_grants WHERE source_attempt_id=? AND consumed_at IS NULL", (row["id"],)).fetchone():
                    raise Problem("repeat_authorized", "A replacement attempt has been authorized", 409)
                connection.execute("UPDATE attempts SET started_at=? WHERE id=?", (now, row["id"]))
                self.audit(connection, None, "student_started", row["id"], now)
                row = connection.execute("SELECT * FROM attempts WHERE id=?", (row["id"],)).fetchone()
            exam = connection.execute("SELECT * FROM exams WHERE id=?", (row["exam_id"],)).fetchone()
            return self.admission_document(row, exam, connection)

    def finish(self, credential, data):
        reason = text_field(data, "end_reason", 100)
        score, total = data.get("score"), data.get("total")
        if (score is None) != (total is None) or (score is not None and
                (type(score) is not int or type(total) is not int or not 0 <= score <= total <= 500 or total < 1)):
            raise Problem("invalid_result", "Score and total must be null or valid whole numbers")
        with self.database.connect(write=True) as connection:
            row = self.credential_attempt(connection, credential)
            if row["started_at"] is None:
                raise Problem("attempt_not_started", "This attempt has not started", 409)
            if row["quiz_snapshot"] is None and (score is not None or total is not None):
                raise Problem("invalid_result", "External exams have no local quiz score; send null score and total")
            if row["quiz_snapshot"] and total is not None and total != len(json.loads(row["quiz_snapshot"])["questions"]):
                raise Problem("invalid_result", "Result total does not match the frozen question set")
            if row["finished_at"] is None:
                now = self.clock()
                connection.execute("UPDATE attempts SET finished_at=?,score=?,total=?,end_reason=? WHERE id=?", (now, score, total, reason, row["id"]))
                self.audit(connection, None, "client_reported_finish", row["id"], now)
                row = connection.execute("SELECT * FROM attempts WHERE id=?", (row["id"],)).fetchone()
            exam = connection.execute("SELECT * FROM exams WHERE id=?", (row["exam_id"],)).fetchone()
            return self.admission_document(row, exam, connection)
