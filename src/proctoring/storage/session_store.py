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

    def __init__(self, base_dir: Path, clock: Clock, candidate: dict | None = None):
        self.path = Path(base_dir) / f"session-{uuid4().hex}"
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
            temporary = self.path / ".reference_face.jpg.partial"
            try:
                temporary.write_bytes(jpeg_bytes)
                os.replace(temporary, self.path / "reference_face.jpg")
            finally:
                temporary.unlink(missing_ok=True)
            self.update_metadata({"reference_face": "reference_face.jpg", "identity_reference": metadata})

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
