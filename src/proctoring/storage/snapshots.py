"""Bounded, local JPEG writes; no video recording and no UI encoding work."""
from pathlib import Path
from queue import Empty, Full, Queue
import re
import threading


class SnapshotWriter:
    def __init__(self, directory: Path, capacity: int = 4):
        self.directory = directory
        self._queue = Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._paths: dict[str, str] = {}
        self._errors: list[str] = []
        self._thread = threading.Thread(target=self._run, name="event-snapshots", daemon=True)
        self._thread.start()

    def submit(self, event_id: str, frame) -> None:
        if self._closing.is_set():
            raise RuntimeError("Snapshot writer is closed")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", event_id):
            raise ValueError("Invalid event identifier")
        try:
            self._queue.put_nowait((event_id, frame.copy()))
        except Full as error:
            raise RuntimeError("Snapshot queue is full; image omitted") from error

    @property
    def paths(self) -> dict[str, str]:
        with self._lock:
            return dict(self._paths)

    @property
    def errors(self) -> list[str]:
        with self._lock:
            return list(self._errors)

    def _run(self) -> None:
        while not self._closing.is_set() or not self._queue.empty():
            try:
                event_id, frame = self._queue.get(timeout=.05)
            except Empty:
                continue
            try:
                import cv2
                success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not success:
                    raise OSError("JPEG encoding failed")
                self.directory.mkdir(parents=True, exist_ok=True)
                target = self.directory / f"{event_id}.jpg"
                temporary = target.with_suffix(".jpg.partial")
                temporary.write_bytes(encoded.tobytes())
                temporary.replace(target)
                with self._lock:
                    self._paths[event_id] = f"snapshots/{target.name}"
            except Exception as error:
                with self._lock:
                    self._errors.append(f"{event_id}: {error}")
            finally:
                self._queue.task_done()

    def close(self, timeout: float = 3.0) -> None:
        if self._closing.is_set():
            return
        self._closing.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            with self._lock:
                self._errors.append("Snapshot writer did not finish before shutdown deadline")
