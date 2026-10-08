"""Separate head-down review evidence from uncertain iris measurements.

These are deterministic signal/mapping regressions, not webcam accuracy tests.
"""
from collections import deque
from dataclasses import replace
import math

import pytest

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType
from proctoring.events import EventEngine
from proctoring.vision.calibration import Calibration
from proctoring.vision.rules import build_result, head_is_down, to_observation
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import (
    Box, EyeDiagnostic, FaceMeasurement, GazeDiagnostics, GazeDirection,
    HeadPose, HealthStatus, VisionResult,
)


def face(*, pitch=0., yaw=0., roll=0., horizontal=.5, vertical=.5,
         opening=.32, eye_valid=True):
    eye = EyeDiagnostic(horizontal, vertical, opening, eye_valid,
                        "" if eye_valid else "iris occluded", 34.)
    return FaceMeasurement(
        True, box=Box(.3, .2, .6, .6),
        features=(horizontal, vertical, yaw / 60., pitch / 60.) if eye_valid else None,
        head_pose=HeadPose(yaw=yaw, pitch=pitch, roll=roll),
        quality=1. if eye_valid else 0.,
        diagnostics=GazeDiagnostics(eye, eye, eye_valid,
                                   "" if eye_valid else "iris occluded"),
    )


@pytest.fixture
def fitted():
    config = replace(VisionConfig(), calibration_samples=3)
    calibration = Calibration(config)
    references = {
        GazeDirection.CENTER: face(),
        GazeDirection.LEFT: face(horizontal=.3),
        GazeDirection.RIGHT: face(horizontal=.7),
        GazeDirection.DOWN: face(vertical=.64, opening=.18),
    }
    timestamp = 1.
    for direction, measurement in references.items():
        for _ in range(config.calibration_samples):
            assert calibration.add_sample(direction, measurement.features, timestamp,
                                          measurement.quality, measurement=measurement)
            timestamp += .1
    ok, reason = calibration.fit()
    assert ok, reason
    return config, calibration


@pytest.mark.parametrize("pitch,expected", [
    (-35., False), (-5., False), (0., False), (10., False), (14., False),
    (14.001, True), (15., True), (20., True), (89.9, True),
    (90., False), (120., False),
])
def test_head_down_uses_strict_signed_pitch_boundary(pitch, expected):
    assert head_is_down(face(pitch=pitch), VisionConfig()) is expected


@pytest.mark.parametrize("eye_valid", [False, True])
@pytest.mark.parametrize("pitch", [15., 20.])
def test_downward_pose_survives_occluded_eyes_and_eye_pose_veto(fitted, eye_valid, pitch):
    config, calibration = fitted
    result = build_result(1., [], [], face(pitch=pitch, vertical=.64,
                                          opening=.07 if not eye_valid else .18,
                                          eye_valid=eye_valid), calibration, config)
    assert result.head_down
    # The eye-only backend does not claim it measured obscured/out-of-coverage
    # irises; the distinct posture cue supplies review evidence instead.
    assert result.gaze_direction == GazeDirection.UNKNOWN
    assert result.gaze_confidence is None
    assert result.face_present and result.monitoring_healthy
    assert to_observation(result).conditions == {EventType.GAZE_DOWN: None}


@pytest.mark.parametrize("pitch", [-5., 0., 9.9, 14.])
@pytest.mark.parametrize("opening,eye_valid", [(.0, False), (.07, False), (.16, True), (.32, True)])
def test_frontal_blinks_closure_and_squint_never_create_down(fitted, pitch, opening, eye_valid):
    config, calibration = fitted
    result = build_result(1., [], [], face(pitch=pitch, opening=opening,
                                          eye_valid=eye_valid), calibration, config)
    assert not result.head_down
    assert result.gaze_direction in (GazeDirection.CENTER, GazeDirection.UNKNOWN)
    assert to_observation(result).conditions == {}


@pytest.mark.parametrize("yaw,roll,expected", [
    (15., 12., True), (-15., -12., True),
    (15.001, 0., False), (-15.001, 0., False),
    (0., 12.001, False), (0., -12.001, False),
])
def test_lateral_and_roll_guards_remain_independent(yaw, roll, expected):
    assert head_is_down(face(pitch=20., yaw=yaw, roll=roll), VisionConfig()) is expected


@pytest.mark.parametrize("axis", ["pitch", "yaw", "roll"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, None, True, "20"])
def test_invalid_pose_never_becomes_head_down(axis, value):
    measurement = face(pitch=20.)
    measurement = replace(measurement, head_pose=replace(measurement.head_pose, **{axis: value}))
    assert not head_is_down(measurement, VisionConfig())


def test_missing_or_absent_face_never_supplies_head_down():
    assert not head_is_down(replace(face(pitch=20.), head_pose=None), VisionConfig())
    assert not head_is_down(replace(face(pitch=20.), face_present=False), VisionConfig())


def test_configured_pose_limits_are_used():
    config = replace(VisionConfig(), head_down_pitch_degrees=18.,
                     head_down_max_yaw_degrees=10., head_down_max_roll_degrees=8.)
    assert not head_is_down(face(pitch=18.), config)
    assert head_is_down(face(pitch=19., yaw=10., roll=8.), config)
    assert not head_is_down(face(pitch=19., yaw=10.1), config)
    assert not head_is_down(face(pitch=19., roll=8.1), config)


def test_failed_or_reset_calibration_does_not_enable_pose_assistance(fitted):
    config, calibrated = fitted
    failed = Calibration(config)
    assert not failed.fit()[0]
    calibrated.reset()
    for calibration in (failed, calibrated):
        result = build_result(1., [], [], face(pitch=20., eye_valid=False), calibration, config)
        assert not result.head_down
        assert to_observation(result).conditions == {}


@pytest.mark.parametrize("direction", list(GazeDirection))
def test_head_down_has_one_down_condition_without_invented_eye_confidence(direction):
    result = VisionResult(1., face_present=True, gaze_direction=direction,
                          gaze_confidence=.8, head_down=True)
    expected = .8 if direction == GazeDirection.DOWN else None
    assert to_observation(result).conditions == {EventType.GAZE_DOWN: expected}


def test_no_face_and_unhealthy_results_cannot_use_pose_fallback():
    result = VisionResult(1., face_present=False, head_down=True)
    assert to_observation(result).conditions == {EventType.FACE_ABSENT: None}
    with pytest.raises(ValueError, match="monitoring health"):
        to_observation(replace(result, face_present=True, monitoring_healthy=False))


def test_head_down_waits_three_seconds_deduplicates_and_clears_at_point_75(fitted):
    config, calibration = fitted
    clock = FakeClock()
    engine = EventEngine({EventType.GAZE_DOWN: 3.0}, .75, clock)

    def sample(timestamp, *, down=True):
        clock.advance(timestamp - clock.monotonic())
        measurement = face(pitch=20. if down else 0., opening=.06, eye_valid=False)
        return engine.observe(to_observation(build_result(timestamp, [], [], measurement,
                                                         calibration, config)))

    for timestamp in (0., 1., 2., 2.999):
        assert sample(timestamp) == []
    assert engine.events == []
    changes = sample(3.)
    assert [item["action"] for item in changes] == ["activated"]
    assert changes[0]["duration_seconds"] == 3.
    assert changes[0]["confidence"] is None
    event_id = changes[0]["event_id"]
    for timestamp in (3.5, 4., 4.5):
        assert all(item["action"] != "activated" for item in sample(timestamp))
    assert len(engine.events) == 1
    assert sample(5., down=False)[0]["action"] == "clearing"
    assert sample(5.749, down=False) == []
    closed = sample(5.75, down=False)[0]
    assert closed["action"] == "closed" and closed["event_id"] == event_id
    assert closed["duration_seconds"] == 4.5
    assert len(engine.events) == 1


def test_current_frame_pose_does_not_reuse_a_previous_down_value(fitted):
    config, calibration = fitted
    down = build_result(1., [], [], face(pitch=20., eye_valid=False), calibration, config)
    unknown = build_result(1.1, [], [], replace(face(eye_valid=False), head_pose=None),
                           calibration, config)
    assert to_observation(down).conditions == {EventType.GAZE_DOWN: None}
    assert not unknown.head_down
    assert to_observation(unknown).conditions == {}


def test_head_down_keeps_phone_person_events_and_exam_timer_running(fitted, tmp_path):
    config, calibration = fitted

    class Monitor:
        def __init__(self):
            self.calibration = calibration
            self.queued = deque()
            self.latest_result = self.delivered_result = None

        def start(self): pass
        def stop(self): pass
        def health(self, now): return HealthStatus(True, "Healthy")

        def sample(self, now):
            if not self.queued:
                return None
            self.delivered_result = self.queued.popleft()
            return to_observation(self.delivered_result)

        def publish(self, timestamp):
            people = [Box(.05, .05, .5, .95, .9, 0), Box(.55, .05, .95, .95, .8, 0)]
            phones = [Box(.6, .25, .7, .4, .85, 67)]
            self.latest_result = build_result(timestamp, people, phones,
                                              face(pitch=20., eye_valid=False), calibration, config)
            self.queued.append(self.latest_result)

    clock = FakeClock()
    app_config = load_config()
    thresholds = {**app_config.thresholds, EventType.GAZE_DOWN: 3.}
    app_config = replace(app_config, sessions_dir=tmp_path, snapshots_enabled=False,
                         thresholds=thresholds, vision=config)
    monitor = Monitor()
    app = AppController(app_config, clock, mode="camera", monitor=monitor)
    try:
        monitor.publish(0.)
        app.start()
        for _ in range(6):
            clock.advance(.5)
            monitor.publish(clock.monotonic())
            app.step()
        assert app.session.running
        assert app.session.monitoring_healthy
        assert app.session.elapsed_seconds == 3.
        assert not app.session.pause_reasons
        types = {event["event_type"] for event in app.review_events}
        assert {"gaze_down", "phone_visible", "phone_raised", "second_person"} <= types
        assert "face_absent" not in types
        assert not app.protection.blocking_enabled
    finally:
        if app.session.started and not app.session.ended:
            app.end("test_cleanup")
        app.close_remote()
