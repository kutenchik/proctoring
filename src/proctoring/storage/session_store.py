"""Append-only JSONL journal and atomically replaced final summaries."""

import json
import os
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from proctoring.clock import Clock


_SECRET_KEYS = {"pin", "proctor_pin", "security_pin", "pin_hash", "pin_salt", "password", "secret",
                "telegram_bot_token", "webhook_token", "token", "access_token", "authorization", "api_key"}


def _redacted(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if str(key).lower().replace("-", "_") in _SECRET_KEYS
            else _redacted(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redacted(item) for item in value]
    return value


def _serialize(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class SessionStore:
    """Create at exam start, then persist local evidence incrementally.

    The caller owns event timestamps and supplies JSON-serializable records.
    Snapshots are deliberately absent while observations are synthetic.
    """

    def __init__(self, base_dir: Path, clock: Clock, candidate: dict | None = None, *, session_id=None):
        import re
        if session_id is not None and not re.fullmatch(r'session-[a-f0-9]{32}', session_id):
            raise ValueError('Invalid session ID')
        self.path = Path(base_dir) / (session_id or f"session-{uuid4().hex}")
        self.path.mkdir(parents=True, exist_ok=False)
        self._lock = threading.RLock()
        self._closed = False
        self._snapshots = None
        self._journal = (self.path / "events.jsonl").open("a", encoding="utf-8", newline="\n")
        try:
            metadata = {"created_at": clock.wall_time(), "session_id": self.path.name}
            if candidate is not None:
                metadata["candidate"] = dict(candidate)
            self._metadata = metadata
            self._atomic_json("session.json", metadata)
            if candidate is not None:
                self.append({"record_kind": "session_header", **metadata})
        except BaseException:
            self._journal.close()
            self._closed = True
            raise

    @classmethod
    def resume_connected(cls, base_dir, session_id, attempt_id):
        """Open only the exact original connected journal, never a new session."""
        import re
        if not re.fullmatch(r'session-[a-f0-9]{32}', session_id):
            raise ValueError('Invalid session ID')
        root = Path(base_dir).resolve()
        path = root/session_id
        if path.is_symlink() or path.resolve().parent != root:
            raise ValueError('Unsafe session directory')
        metadata = json.loads((path/'session.json').read_text(encoding='utf-8'))
        if metadata.get('session_id') != session_id or metadata.get('connected_attempt', {}).get('attempt_id') != attempt_id:
            raise ValueError('Connected session identity mismatch')
        if (path/'summary.json').exists():
            raise ValueError('Ended sessions cannot be resumed')
        # A partial final line is an uncertain record, not permission to truncate it.
        raw = (path/'events.jsonl').read_bytes()
        if raw and not raw.endswith(b'\n'):
            raise ValueError('Journal requires repair: partial record')
        for line in raw.splitlines():
            json.loads(line)
        self = cls.__new__(cls)
        self.path, self._metadata = path, metadata
        self._lock, self._closed, self._snapshots = threading.RLock(), False, None
        self._journal = (path/'events.jsonl').open('a', encoding='utf-8', newline='\n')
        self._resumed = True
        return self

    def flush_durable(self):
        with self._lock:
            if not self._closed:
                self._journal.flush()
                os.fsync(self._journal.fileno())

    @classmethod
    def inspect_ended_connected(cls, base_dir, session_id, attempt_id):
        from ..connected.sync import session_root
        root = session_root(base_dir, {'session_id': session_id, 'attempt_id': attempt_id})
        self = cls.__new__(cls)
        self.path = root
        self._metadata = json.loads((root/'session.json').read_bytes())
        self._lock, self._closed, self._snapshots = threading.RLock(), True, None
        return self

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Session store is closed")

    def _atomic_json(self, filename: str, data: dict) -> None:
        serialized = _serialize(data)
        temporary = self.path / f".{filename}.{uuid4().hex}.tmp"
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path / filename)
        finally:
            temporary.unlink(missing_ok=True)

    def append(self, record: dict) -> None:
        # Serialize first so a malformed record cannot leave a partial line.
        serialized = _serialize(record)
        with self._lock:
            self._ensure_open()
            self._journal.write(serialized + "\n")
            self._journal.flush()

    def save_config(self, config: dict) -> None:
        with self._lock:
            self._ensure_open()
            self._atomic_json("config.json", _redacted(config))

    def update_metadata(self, values: dict) -> None:
        with self._lock:
            self._ensure_open()
            self._metadata.update(values)
            self._atomic_json("session.json", self._metadata)

    def save_reference(self, jpeg_bytes: bytes, metadata: dict) -> None:
        """The vision worker encodes; this writes only an explicitly taken selfie."""
        if not jpeg_bytes.startswith(b"\xff\xd8"):
            raise ValueError("Invalid baseline JPEG")
        with self._lock:
            self._ensure_open()
            name = 'reference_face.jpg'
            if getattr(self, '_resumed', False) and (self.path/name).exists():
                name = 'reference_recovery_'+uuid4().hex+'.jpg'
            temporary = self.path / ('.'+name+'.partial')
            try:
                temporary.write_bytes(jpeg_bytes)
                os.replace(temporary, self.path / name)
            finally:
                temporary.unlink(missing_ok=True)
            self.update_metadata({"reference_face": name, "identity_reference": metadata})

    def enqueue_snapshot(self, event_id: str, frame) -> None:
        self._ensure_open()
        if self._snapshots is None:
            from .snapshots import SnapshotWriter
            self._snapshots = SnapshotWriter(self.path / "snapshots")
        self._snapshots.submit(event_id, frame)

    def finish_snapshots(self) -> tuple[dict, list]:
        if self._snapshots is None:
            return {}, []
        self._snapshots.close()
        return self._snapshots.paths, self._snapshots.errors

    def snapshot_results(self) -> list[dict]:
        return self._snapshots.drain_results() if self._snapshots is not None else []

    def append_remote_warning(self, record: dict) -> None:
        """Transport diagnostics may arrive after the exam journal is finalized."""
        serialized = _serialize(record)
        with self._lock:
            with (self.path / "remote_warnings.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized + "\n")

    def finalize(self, summary: dict) -> None:
        with self._lock:
            self._ensure_open()
            self._journal.flush()
            self._atomic_json("summary.json", summary)

    def close(self) -> None:
        if self._snapshots is not None:
            self._snapshots.close()
        with self._lock:
            if not self._closed:
                try:
                    self._journal.close()
                finally:
                    # Buffered stream close can report a final flush failure.
                    # Treat this store as terminal even then, and propagate the
                    # original error so the controller can surface lost evidence.
                    self._closed = True

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
