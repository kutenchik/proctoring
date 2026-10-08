"""Real observation mapping regressions; synthetic eyes do not prove accuracy."""
from dataclasses import replace

import pytest

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.domain import EventType
from proctoring.events import EventEngine
from proctoring.vision.calibration import Calibration
from proctoring.vision.rules import build_result, to_observation
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import (
    Box, EyeDiagnostic, FaceMeasurement, GazeDiagnostics, GazeDirection, HeadPose,
)


CONFIG = replace(VisionConfig(), calibration_samples=5)
REFERENCES = {
    GazeDirection.CENTER: (.5, .5, .33),
    GazeDirection.LEFT: (.25, .5, .33),
    GazeDirection.RIGHT: (.75, .5, .33),
    GazeDirection.DOWN: (.5, .5463, .145),
}
GAZE_EVENTS = {EventType.GAZE_LEFT, EventType.GAZE_RIGHT, EventType.GAZE_DOWN}


def face(horizontal=.5, vertical=.528, opening=.16, *, right_opening=None,
         eye_valid=True, features_present=True, yaw=0.):
    right_opening = opening if right_opening is None else right_opening
    left = EyeDiagnostic(horizontal, vertical, opening, eye_valid,
                         "" if eye_valid else "iris unobservable", 33.1126)
    right = replace(left, opening=right_opening)
    return FaceMeasurement(
        True, box=Box(.35, .15, .65, .5),
        features=(horizontal, vertical, yaw / 60., 0.) if features_present else None,
        head_pose=HeadPose(yaw=yaw), quality=1.,
        diagnostics=GazeDiagnostics(left, right, eye_valid,
                                    "" if eye_valid else "iris unobservable"),
        frame_size=(640, 480),
    )


def collect(calibration, *, start=1., metadata=True):
    stamp = start
    for direction, reference in REFERENCES.items():
        measurement = face(*reference)
        for _ in range(CONFIG.calibration_samples):
            assert calibration.add_sample(
                direction, measurement.features, stamp, measurement.quality,
                noise_floor=1 / 33.1126, measurement=measurement if metadata else None,
            )
            stamp += .1


@pytest.fixture
def calibration():
    model = Calibration(CONFIG)
    collect(model)
    assert model.fit()[0]
    return model


@pytest.fixture
def event_config():
    # Pin this regression's timing contract independently of the operator's
    # editable demo thresholds. The production configuration is untouched.
    return replace(load_config(), thresholds={
        EventType.PHONE_VISIBLE: 1., EventType.SECOND_PERSON: 1.,
        EventType.PHONE_RAISED: 1.25, EventType.FACE_ABSENT: 3.,
        **{kind: 3. for kind in GAZE_EVENTS},
    }, clearing_seconds=.75)


@pytest.mark.parametrize("direction", [GazeDirection.LEFT, GazeDirection.RIGHT, GazeDirection.DOWN])
@pytest.mark.parametrize("opening,right_opening", [(.07, .07), (.11, .11), (.11, .33), (.33, .11)])
def test_build_result_applies_closure_veto_even_to_numerically_valid_direction(
        calibration, direction, opening, right_opening):
    horizontal, vertical, _ = REFERENCES[direction]
    measurement = face(horizontal, vertical, opening, right_opening=right_opening)
    # Geometry-only legacy calls demonstrate why the real path needs metadata.
    assert calibration.classify(measurement.features)[0] == direction
    result = build_result(20., [], [], measurement, calibration, CONFIG)
    assert result.gaze_direction == GazeDirection.UNKNOWN
    assert result.gaze_confidence is None
    assert result.face_present and result.monitoring_healthy
    assert to_observation(result).conditions == {}


@pytest.mark.parametrize("opening,valid,features_present", [(.07, False, False), (.11, True, True)])
def test_sustained_closure_has_no_gaze_or_absence_events_and_other_detectors_continue(
        calibration, event_config, opening, valid, features_present):
    app = event_config
    clock = FakeClock()
    engine = EventEngine(app.thresholds, app.clearing_seconds, clock)
    people = [Box(.05, .1, .45, .95, .9, 0), Box(.55, .1, .95, .95, .85, 0)]
    phones = [Box(.55, .25, .65, .45, .9, 67)]
    for step in range(81):
        timestamp = step / 10
        clock.advance(timestamp - clock.monotonic())
        result = build_result(timestamp, people, phones,
                              face(opening=opening, eye_valid=valid, features_present=features_present),
                              calibration, CONFIG)
        assert result.monitoring_healthy and result.face_present
        assert result.gaze_direction == GazeDirection.UNKNOWN
        observation = to_observation(result)
        assert not GAZE_EVENTS.intersection(observation.conditions)
        assert EventType.FACE_ABSENT not in observation.conditions
        assert {EventType.PHONE_VISIBLE, EventType.SECOND_PERSON, EventType.PHONE_RAISED}.issubset(
            observation.conditions)
        engine.observe(observation)
    assert {event["event_type"] for event in engine.events} == {
        EventType.PHONE_VISIBLE.value, EventType.SECOND_PERSON.value, EventType.PHONE_RAISED.value,
    }
    assert all(engine.states[kind] == "closed" for kind in GAZE_EVENTS | {EventType.FACE_ABSENT})


def test_supplement_uses_existing_three_second_activation_and_point_seven_five_clearing(calibration, event_config):
    app = event_config
    clock = FakeClock()
    engine = EventEngine(app.thresholds, app.clearing_seconds, clock)
    borderline = face()
    assert calibration.classify(borderline.features)[0] == GazeDirection.UNKNOWN

    def observe(timestamp, measurement):
        clock.advance(timestamp - clock.monotonic())
        result = build_result(timestamp, [], [], measurement, calibration, CONFIG)
        return result, engine.observe(to_observation(result))

    for timestamp in (0., .5, 1., 1.5, 2., 2.5, 2.999):
        result, changes = observe(timestamp, borderline)
        assert result.gaze_direction == GazeDirection.DOWN
        assert result.gaze_confidence is None  # No fabricated probability.
        assert not changes and not engine.events
    _, changes = observe(3., borderline)
    assert [row["action"] for row in changes] == ["activated"]
    assert changes[0]["duration_seconds"] == 3.
    assert engine.states[EventType.GAZE_DOWN] == "active"
    _, changes = observe(3.25, face(opening=.07))
    assert [row["action"] for row in changes] == ["clearing"]
    _, changes = observe(3.999, face(opening=.07))
    assert not changes
    assert engine.states[EventType.GAZE_DOWN] == "clearing"
    _, changes = observe(4., face(opening=.07))
    assert [row["action"] for row in changes] == ["closed"]
    assert engine.states[EventType.GAZE_DOWN] == "closed"
    assert len(engine.events) == 1


def test_supplement_cannot_bypass_head_pose_veto(calibration):
    result = build_result(20., [], [], face(yaw=35.), calibration, CONFIG)
    assert result.gaze_direction == GazeDirection.UNKNOWN
    assert result.head_pose == HeadPose(yaw=35.)
    assert to_observation(result).conditions == {}


def test_reset_does_not_reuse_aperture_metadata_in_a_new_numerical_only_fit(calibration):
    assert build_result(20., [], [], face(), calibration, CONFIG).gaze_direction == GazeDirection.DOWN
    calibration.reset()
    assert build_result(21., [], [], face(), calibration, CONFIG).gaze_direction == GazeDirection.UNKNOWN
    collect(calibration, start=30., metadata=False)
    assert calibration.fit()[0]
    assert build_result(40., [], [], face(), calibration, CONFIG).gaze_direction == GazeDirection.UNKNOWN


def test_discarded_down_target_cannot_reuse_old_down_aperture_metadata(calibration):
    calibration.discard_target(GazeDirection.DOWN)
    assert build_result(20., [], [], face(), calibration, CONFIG).gaze_direction == GazeDirection.UNKNOWN
    reference = face(*REFERENCES[GazeDirection.DOWN])
    for step in range(CONFIG.calibration_samples):
        assert calibration.add_sample(GazeDirection.DOWN, reference.features, 30. + step,
                                      1., noise_floor=1 / 33.1126)
    assert calibration.fit()[0]
    assert build_result(40., [], [], face(), calibration, CONFIG).gaze_direction == GazeDirection.UNKNOWN


def test_failed_refit_keeps_guarded_down_unavailable(calibration):
    calibration.discard_target(GazeDirection.DOWN)
    overlap = face(.5, .5, .145)
    for step in range(CONFIG.calibration_samples):
        assert calibration.add_sample(GazeDirection.DOWN, overlap.features, 30. + step,
                                      1., noise_floor=1 / 33.1126, measurement=overlap)
    assert not calibration.fit()[0]
    assert not calibration.ready
    assert build_result(40., [], [], face(), calibration, CONFIG).gaze_direction == GazeDirection.UNKNOWN
