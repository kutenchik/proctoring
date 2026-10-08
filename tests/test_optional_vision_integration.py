"""Controller lifecycle/evidence wiring; camera results are synthetic, not humans."""
from collections import deque
from dataclasses import replace
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType
from proctoring.settings import (AudioConfig, IdentityConfig, RegistrationConfig, RemoteConfig,
                                  ReportingConfig, SystemChecksConfig)
from proctoring.vision.accessories import AccessoriesConfig
from proctoring.vision.rules import to_observation
from proctoring.vision.types import GazeDirection, HealthStatus, VisionResult


CANDIDATE = {"first_name": "Test", "last_name": "Candidate", "group_id": "DEMO-01"}


class OptionalMonitor:
    def __init__(self):
        self.calibration = SimpleNamespace(ready=False)
        self.started = self.stopped = self.exam_active = False
        self.identity_baseline = None
        self.identity_ready = False
        self.identity_status = "Reference face not captured"
        self.identity_config = None
        self.requested = False
        self.healthy = True
        self.queued = deque()
        self.latest_result = self.delivered_result = None

    @property
    def identity_can_capture(self): return self.started and self.healthy and not self.exam_active
    def configure_identity(self, config): self.identity_config = config
    def start(self): self.started, self.stopped = True, False
    def stop(self): self.stopped, self.exam_active = True, False
    def set_exam_active(self, active): self.exam_active = active
    def health(self, now): return HealthStatus(self.healthy and not self.stopped, "Camera unavailable")

    def request_identity_baseline(self):
        self.requested = True
        self.identity_ready = False
        self.identity_baseline = None
        return True

    def finish_baseline(self, timestamp):
        success, data = cv2.imencode(".jpg", np.full((32, 32, 3), 123, np.uint8))
        assert success
        self.identity_baseline = SimpleNamespace(jpeg_bytes=data.tobytes(),
                                                 metadata={"captured_monotonic": timestamp,
                                                           "algorithm": "test_shape_consistency"})
        self.identity_ready = True
        self.identity_status = "Reference captured; identity comparisons start with the exam"

    def publish(self, timestamp, **kwargs):
        result = VisionResult(timestamp, face_present=True, person_count=1,
                              gaze_direction=GazeDirection.UNKNOWN, **kwargs)
        self.queued.append(result)
        self.latest_result = result
        return result

    def sample(self, now):
        if not self.queued: return None
        self.delivered_result = self.queued.popleft()
        return to_observation(self.delivered_result)


@pytest.fixture
def make_controller(tmp_path):
    created = []

    def make(*, enabled=True, snapshots=False):
        config = load_config()
        config = replace(config, sessions_dir=tmp_path / "sessions", external_url="", allowed_domains=(),
                         registration=RegistrationConfig(enabled=enabled),
                         identity=IdentityConfig(selfie_verification_enabled=enabled),
                         remote=RemoteConfig(enabled=False), audio=AudioConfig(enabled=False),
                         reporting=ReportingConfig(generate_pdf_report=False), system_checks=SystemChecksConfig(),
                         vision=replace(config.vision, accessories=AccessoriesConfig(enabled)),
                         protection=replace(config.protection, enabled=False), snapshots_enabled=snapshots)
        clock, monitor = FakeClock(), OptionalMonitor()
        app = AppController(config, clock, mode="camera", monitor=monitor)
        created.append(app)
        assert app.remote is None
        return app, monitor, clock

    yield make
    for app in created:
        if app.session.started and not app.session.ended:
            app.end("test_cleanup")
        app.close_remote()


def register(app, monitor, clock):
    app.prepare_identity(CANDIDATE)
    app.capture_identity_baseline()
    assert monitor.requested
    monitor.finish_baseline(clock.monotonic())
    app.poll_optional_workers()
    assert app.identity_ready


def start(app, monitor, clock):
    if app.config.identity.selfie_verification_enabled:
        register(app, monitor, clock)
    monitor.calibration.ready = True
    app.prepare_monitoring()
    monitor.publish(clock.monotonic())
    app.start()


def advance(app, monitor, clock, duration=.1, **kwargs):
    clock.advance(duration)
    result = monitor.publish(clock.monotonic(), **kwargs)
    app.step()
    return result


def test_registration_photo_persists_before_calibration_and_reuses_session_directory(make_controller):
    app, monitor, clock = make_controller()
    with pytest.raises(RuntimeError, match="registration"):
        app.prepare_monitoring()
    with pytest.raises(RuntimeError, match="registration"):
        app.start()
    assert app.store is None
    register(app, monitor, clock)
    assert app.registration_complete and not app.session.started
    original_path = app.store.path
    metadata = json.loads((original_path / "session.json").read_text("utf-8"))
    assert metadata["candidate"] == CANDIDATE
    assert metadata["reference_face"] == "reference_face.jpg"
    assert (original_path / "reference_face.jpg").read_bytes() == monitor.identity_baseline.jpeg_bytes
    journal = [json.loads(line) for line in (original_path / "events.jsonl").read_text("utf-8").splitlines()]
    assert journal[0]["record_kind"] == "session_header" and journal[0]["candidate"] == CANDIDATE
    with pytest.raises(RuntimeError, match="gaze calibration"):
        app.start()
    with pytest.raises(RuntimeError, match="fixed"):
        app.register_candidate({**CANDIDATE, "first_name": "Another"})
    monitor.calibration.ready = True
    monitor.publish(clock.monotonic())
    app.start()
    assert app.session.running and monitor.exam_active
    assert app.store.path == original_path
    app.end()
    summary = json.loads((original_path / "summary.json").read_text("utf-8"))
    assert summary["session_id"] == original_path.name
    assert summary["candidate"] == CANDIDATE
    assert summary["reference_face"] == "reference_face.jpg"
    assert not monitor.exam_active


def test_enabled_optional_observations_create_one_event_and_jpeg_each_without_pause(make_controller):
    app, monitor, clock = make_controller(snapshots=True)
    start(app, monitor, clock)
    frame = np.full((64, 64, 3), 180, np.uint8)
    flags = {"identity_suspected": True, "identity_distance": .6,
             "earphone_suspected": True, "frame": frame}
    for _ in range(8):
        advance(app, monitor, clock, **flags)
    assert app.session.running and app.session.monitoring_healthy
    assert app.session.elapsed_seconds == pytest.approx(.8)
    assert len(app.review_events) == 2
    identity, earphone = (next(event for event in app.review_events if event["event_type"] == kind.value)
                         for kind in (EventType.IMPERSONATION_SUSPECTED, EventType.EARPHONE_SUSPECTED))
    assert identity["severity"] == "high" and earphone["severity"] == "review"
    assert identity["confidence"] is None  # Shape distance is not an accuracy probability.
    app.end()
    assert app.summary["event_count"] == 2
    snapshots = list((app.store.path / "snapshots").glob("*.jpg"))
    assert len(snapshots) == 2
    for event in app.summary["events"]:
        assert (app.store.path / event["snapshot_path"]).is_file()
    records = [json.loads(line) for line in (app.store.path / "events.jsonl").read_text("utf-8").splitlines()]
    assert len([record for record in records if record.get("action") == "activated"]) == 2


def test_disabled_optional_detectors_ignore_unexpected_flags_without_network_or_pause(make_controller):
    app, monitor, clock = make_controller(enabled=False)
    start(app, monitor, clock)
    assert monitor.identity_config is None
    for _ in range(10):
        advance(app, monitor, clock, identity_suspected=True, earphone_suspected=True)
    assert app.session.running and app.session.monitoring_healthy
    assert app.review_events == []
    assert not (app.store.path / "reference_face.jpg").exists()
    assert app.remote is None


def test_failed_reference_save_blocks_exam_even_with_calibration_ready(make_controller, monkeypatch):
    from proctoring.storage import SessionStore
    app, monitor, clock = make_controller()
    app.prepare_identity(CANDIDATE)
    app.capture_identity_baseline()
    monitor.finish_baseline(0.)
    monitor.calibration.ready = True
    monkeypatch.setattr(SessionStore, "save_reference", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    app.poll_optional_workers()
    assert not app.identity_ready
    assert "could not be saved" in app.identity_status
    with pytest.raises(RuntimeError, match="registration"):
        app.start()
    assert not app.session.started


def test_failed_reference_retake_must_not_pair_new_embedding_with_old_saved_selfie(make_controller, monkeypatch):
    app, monitor, clock = make_controller()
    register(app, monitor, clock)
    previous = monitor.identity_baseline
    app.capture_identity_baseline()
    monitor.finish_baseline(1.)
    assert monitor.identity_baseline is not previous
    monkeypatch.setattr(app.store, "save_reference", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    app.poll_optional_workers()
    assert not app.identity_ready
    monitor.calibration.ready = True
    with pytest.raises(RuntimeError, match="registration"):
        app.start()
