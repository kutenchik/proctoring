import threading

import numpy as np
import pytest

from proctoring.storage.snapshots import SnapshotWriter


def test_writer_saves_actual_jpeg_and_reports_success(tmp_path):
    import cv2
    writer = SnapshotWriter(tmp_path / "snapshots")
    writer.submit("test-event", np.full((32, 48, 3), 120, dtype=np.uint8))
    writer.close()
    image = cv2.imread(str(tmp_path / "snapshots/test-event.jpg"))
    assert image.shape == (32, 48, 3)
    assert writer.paths == {"test-event": "snapshots/test-event.jpg"}
    assert writer.errors == []
    assert not list(tmp_path.rglob("*.partial"))


def test_snapshot_write_failure_is_reported_without_inventing_path(tmp_path, monkeypatch):
    import cv2
    monkeypatch.setattr(cv2, "imencode", lambda *args: (False, None))
    writer = SnapshotWriter(tmp_path)
    writer.submit("event", np.zeros((4, 4, 3), dtype=np.uint8))
    writer.close()
    assert writer.paths == {}
    assert "JPEG encoding failed" in writer.errors[0]


def test_full_snapshot_queue_drops_image_without_waiting(tmp_path, monkeypatch):
    import cv2
    entered, release = threading.Event(), threading.Event()
    real_encode = cv2.imencode
    def delayed(*args):
        entered.set()
        release.wait(2)
        return real_encode(*args)
    monkeypatch.setattr(cv2, "imencode", delayed)
    writer = SnapshotWriter(tmp_path, capacity=1)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    try:
        writer.submit("first", frame)
        assert entered.wait(1)
        writer.submit("second", frame)
        with pytest.raises(RuntimeError, match="queue is full"):
            writer.submit("third", frame)
    finally:
        release.set()
        writer.close()
    assert set(writer.paths) == {"first", "second"}


def test_writer_rejects_path_traversal_and_post_shutdown_submit(tmp_path):
    writer = SnapshotWriter(tmp_path)
    try:
        with pytest.raises(ValueError, match="identifier"):
            writer.submit("../escape", np.zeros((4, 4, 3), dtype=np.uint8))
    finally:
        writer.close()
    with pytest.raises(RuntimeError, match="closed"):
        writer.submit("event", np.zeros((4, 4, 3), dtype=np.uint8))
    writer.close()
    assert writer.errors == []
