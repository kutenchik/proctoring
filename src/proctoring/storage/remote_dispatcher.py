"""Best-effort remote copies of locally persisted session records.

Only this daemon worker performs HTTP or opens snapshot files. The caller must
save local evidence first; network delivery is deliberately not a prerequisite
for recording an event, running a detector, or progressing an exam.
"""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import math
from pathlib import Path
from queue import Empty, Full, Queue
import threading
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from proctoring.config import RemoteConfig


_LOG = logging.getLogger(__name__)
_KINDS = frozenset({"session_start", "violation_alert", "session_end", "session_report"})


@dataclass(frozen=True)
class _Delivery:
    kind: str
    payload: dict
    snapshot_path: Path | None
    document_path: Path | None = None


def format_telegram_message(kind: str, payload: dict) -> str:
    """Plain text only: no HTML/Markdown parsing of candidate-supplied names."""
    candidate = payload.get("candidate") or {}
    name = f"{candidate.get('first_name', '')} {candidate.get('last_name', '')}".strip()
    group = candidate.get("group_id", "")
    session_id = payload.get("session_id", "")
    if kind == "session_start":
        return (f"🎓 [Exam Started]\nCandidate: {name}\nGroup: {group}"
                f"\nSession: {session_id}")
    if kind == "violation_alert":
        return (f"⚠️ [Proctoring Alert] {str(payload.get('event_type', '')).upper()}"
                f"\nCandidate: {name} ({group})"
                f"\nDuration: {payload.get('duration_seconds', 0)}s"
                f"\nTimestamp: {payload.get('timestamp', '')}")
    if kind == "session_end":
        return (f"✅ [Exam Finished]\nCandidate: {name} ({group})"
                f"\nTotal Violations: {payload.get('total_events', 0)}"
                f"\nSession: {session_id}")
    if kind == "session_report":
        return (f"📋 [Final Exam Report]\nCandidate: {name} ({group})"
                f"\nTrust Score: {payload.get('trust_score', 0)}%"
                f"\nTotal Events: {payload.get('total_events', 0)}"
                "\nRule-based review score; not a misconduct probability.")
    raise ValueError("Unknown remote dispatch type")


class RemoteDispatcher:
    """One bounded, non-blocking queue; no retries or durable remote outbox.

    ``close`` gives queued work at most two seconds to finish, then drops any
    remaining queued copies. Requests already in progress cannot be cancelled
    by requests; their configured socket timeout still applies and their thread
    is a daemon. Repeated close calls never repeat the shutdown wait.
    """

    def __init__(self, config: "RemoteConfig"):
        self.config = config
        self._queue: Queue[_Delivery] = Queue(maxsize=config.max_queue_size)
        self._state_lock = threading.Lock()
        self._warning_lock = threading.Lock()
        self._warnings: deque[dict] = deque(maxlen=max(50, config.max_queue_size))
        self._closing = threading.Event()
        self._abort = threading.Event()
        self._accepting = bool(config.enabled)
        self._closed = False
        self._thread: threading.Thread | None = None
        if config.enabled:
            self._thread = threading.Thread(
                target=self._run, name="remote-dispatcher", daemon=True,
            )
            self._thread.start()

    def enqueue(self, kind: str, payload: dict, snapshot_path: Path | None = None,
                document_path: Path | None = None) -> bool:
        """Copy small metadata and enqueue immediately; never perform file/HTTP I/O."""
        if not self.config.enabled:
            return False
        if kind not in _KINDS or not isinstance(payload, dict):
            self._warn("invalid_payload")
            return False
        try:
            item = _Delivery(kind, deepcopy(payload), Path(snapshot_path) if snapshot_path else None,
                             Path(document_path) if document_path else None)
        except Exception:
            self._warn("invalid_payload")
            return False
        with self._state_lock:
            if not self._accepting:
                self._warn("dispatcher_closed", item=item)
                return False
            try:
                self._queue.put_nowait(item)
            except Full:
                self._warn("queue_full", item=item)
                return False
        return True

    def drain_warnings(self) -> list[dict]:
        """Return sanitized diagnostics for the controller's local session journal."""
        with self._warning_lock:
            warnings = list(self._warnings)
            self._warnings.clear()
        return warnings

    def close(self, timeout: float = 2.0) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._accepting = False
            self._closing.set()
        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return
        # Never allow a caller's timeout to defeat the application's exit bound.
        timeout = float(timeout)
        budget = min(2.0, max(0.0, timeout)) if math.isfinite(timeout) else 2.0
        thread.join(budget)
        if thread.is_alive():
            self._abort.set()
            dropped = 0
            while True:
                try:
                    self._queue.get_nowait()
                except Empty:
                    break
                else:
                    dropped += 1
                    self._queue.task_done()
            self._warn("shutdown_timeout", dropped_count=dropped)

    def _warn(self, code: str, *, item: _Delivery | None = None,
              backend: str | None = None, **details) -> None:
        # Never include str(exception), HTTP response bodies, URLs or credentials:
        # requests errors often embed the Telegram bot token in a request URL.
        warning = {"type": "remote_dispatch_warning", "code": code, **details}
        if item is not None:
            warning["dispatch_type"] = item.kind
            if isinstance(item.payload.get("session_id"), str):
                warning["session_id"] = item.payload["session_id"]
        if backend is not None:
            warning["backend"] = backend
        with self._warning_lock:
            self._warnings.append(warning)
        _LOG.warning("Remote dispatch: %s (%s)", code, backend or "queue")

    def _run(self) -> None:
        while not self._abort.is_set():
            try:
                item = self._queue.get(timeout=.05)
            except Empty:
                if self._closing.is_set():
                    return
                continue
            try:
                if self._abort.is_set():
                    self._warn("shutdown_dropped", item=item)
                    continue
                self._dispatch(item)
            except Exception:
                # A malformed remote payload or unexpected client error must not
                # kill the worker, affect local evidence, or escape into the UI.
                self._warn("worker_error", item=item)
            finally:
                self._queue.task_done()

    def _dispatch(self, item: _Delivery) -> None:
        if self.config.telegram_enabled:
            self._attempt("telegram", item, self._telegram)
        if self.config.webhook_url and not self._abort.is_set():
            self._attempt("webhook", item, self._webhook)

    def _attempt(self, backend: str, item: _Delivery, deliver) -> None:
        try:
            deliver(item)
        except requests.exceptions.Timeout:
            self._warn("network_timeout", item=item, backend=backend)
        except requests.exceptions.HTTPError as error:
            status = getattr(error.response, "status_code", None)
            detail = {"http_status": status} if isinstance(status, int) else {}
            self._warn("http_error", item=item, backend=backend, **detail)
        except requests.exceptions.RequestException:
            self._warn("network_error", item=item, backend=backend)
        except Exception:
            self._warn("delivery_error", item=item, backend=backend)

    def _post(self, url: str, **kwargs):
        response = requests.post(
            url, timeout=self.config.upload_timeout_seconds,
            allow_redirects=False, **kwargs,
        )
        try:
            response.raise_for_status()
            if 300 <= response.status_code < 400:
                # Do not forward exam metadata/credentials to redirect targets.
                raise requests.exceptions.HTTPError(response=response)
            return response
        except Exception:
            response.close()
            raise

    def _open_snapshot(self, item: _Delivery, backend: str):
        path = item.snapshot_path
        if path is None:
            return None
        try:
            if path.suffix.lower() not in {".jpg", ".jpeg"}:
                raise ValueError("Not a JPEG snapshot")
            return path.open("rb")
        except (OSError, ValueError):
            self._warn("snapshot_unavailable", item=item, backend=backend)
            return None

    def _telegram(self, item: _Delivery) -> None:
        text = format_telegram_message(item.kind, item.payload)
        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/"
        if item.kind == "session_report":
            self._telegram_report(item, url, text)
            return
        photo = self._open_snapshot(item, "telegram") if item.kind == "violation_alert" else None
        if photo is not None:
            with photo:
                response = self._post(url + "sendPhoto", data={
                    "chat_id": self.config.telegram_chat_id,
                    "caption": text[:1024],
                }, files={"photo": (Path(photo.name).name, photo, "image/jpeg")})
        else:
            response = self._post(url + "sendMessage", json={
                "chat_id": self.config.telegram_chat_id, "text": text[:4096],
            })
        try:
            result = response.json()
            if not isinstance(result, dict) or result.get("ok") is not True:
                self._warn("telegram_rejected", item=item, backend="telegram")
        finally:
            response.close()

    def _telegram_report(self, item: _Delivery, url: str, caption: str) -> None:
        # Only an explicitly queued report can upload a document. Never attach
        # the PDF to ordinary events, nor silently send another local file.
        try:
            if item.document_path is None or item.document_path.suffix.lower() != ".pdf":
                raise ValueError("Not a PDF report")
            document = item.document_path.open("rb")
        except (OSError, ValueError):
            self._warn("document_unavailable", item=item, backend="telegram")
            return
        with document:
            if document.read(5) != b"%PDF-":
                self._warn("document_invalid", item=item, backend="telegram")
                return
            document.seek(0)
            response = self._post(url + "sendDocument", data={
                "chat_id": self.config.telegram_chat_id, "caption": caption[:1024],
            }, files={"document": (item.document_path.name, document, "application/pdf")})
        try:
            result = response.json()
            if not isinstance(result, dict) or result.get("ok") is not True:
                self._warn("telegram_rejected", item=item, backend="telegram")
        finally:
            response.close()

    def _webhook(self, item: _Delivery) -> None:
        envelope = {**item.payload, "type": item.kind}
        headers = {}
        if self.config.webhook_token:
            headers["Authorization"] = f"Bearer {self.config.webhook_token}"
        # The PDF destination was authorized as Telegram. Webhooks receive only
        # report metadata; document_path is deliberately outside the envelope.
        photo = self._open_snapshot(item, "webhook") if item.kind != "session_report" else None
        if photo is not None:
            with photo:
                response = self._post(self.config.webhook_url, headers=headers,
                                      data={"payload": json.dumps(envelope, ensure_ascii=False, allow_nan=False)},
                                      files={"photo": (Path(photo.name).name, photo, "image/jpeg")})
        else:
            response = self._post(self.config.webhook_url, headers=headers, json=envelope)
        response.close()
