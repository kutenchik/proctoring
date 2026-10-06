from dataclasses import replace
import math

import pytest

from proctoring.domain import EventType
from proctoring.vision.calibration import Calibration
from proctoring.vision.rules import build_result, filter_persons, filter_phones, phone_is_raised, to_observation
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import Box, FaceMeasurement, GazeDirection, VisionResult


CONFIG = VisionConfig()
PERSON = Box(.1, .1, .9, .95, .8, 0)
FACE = FaceMeasurement(True, Box(.4, .15, .6, .4))
RAISED = Box(.64, .2, .71, .4, .85, 67)
LOW_PHONE = Box(.64, .75, .71, .9, .85, 67)


def test_phone_near_face_is_raised():
    assert phone_is_raised([RAISED], [], FACE, CONFIG)


def test_phone_upper_person_can_be_raised_with_occluded_face():
    assert phone_is_raised([RAISED], [PERSON], FaceMeasurement(False), CONFIG)


def test_phone_low_in_frame_is_not_raised():
    assert not phone_is_raised([LOW_PHONE], [PERSON], FACE, CONFIG)


def test_phone_without_face_or_person_reference_is_not_raised():
    assert not phone_is_raised([RAISED], [], FaceMeasurement(False), CONFIG)


def test_unrelated_phone_far_side_is_not_raised():
    narrow_face = FaceMeasurement(True, Box(.15, .2, .25, .35))
    narrow_person = Box(.05, .1, .35, .9, .9, 0)
    assert not phone_is_raised([RAISED], [narrow_person], narrow_face, CONFIG)


def test_person_fallback_does_not_use_lower_half_of_frame():
    low_person = Box(.2, .7, .8, 1, .9, 0)
    assert not phone_is_raised([LOW_PHONE], [low_person], FaceMeasurement(False), CONFIG)


@pytest.mark.parametrize("bad", [
    Box(.1, .1, .11, .11, .99, 0),
    Box(.1, .1, .4, .19, .99, 0),
    Box(.1, .1, .5, .8, .2, 0),
    Box(.1, .1, .5, .8, math.nan, 0),
    Box(.1, .1, .5, .8, .9, 67),
    Box(-.1, .1, .5, .8, .9, 0),
])
def test_person_noise_is_filtered(bad):
    assert filter_persons([PERSON, bad], CONFIG) == (PERSON,)


@pytest.mark.parametrize("bad", [
    Box(.1, .1, .105, .105, .99, 67),
    Box(.1, .1, .2, .3, .1, 67),
    Box(.1, .1, .2, .3, .9, 0),
    Box(.1, .1, math.inf, .3, .9, 67),
])
def test_phone_noise_is_filtered(bad):
    assert filter_phones([RAISED, bad], CONFIG) == (RAISED,)


@pytest.mark.parametrize("count,expected", [(0, False), (1, False), (2, True), (3, True)])
def test_second_person_count_uses_yolo_people(count, expected):
    people = [PERSON] * count
    result = build_result(10., people, [], FACE, Calibration(CONFIG), CONFIG)
    observation = to_observation(result)
    assert (EventType.SECOND_PERSON in observation.conditions) == expected


def test_fresh_frame_without_face_is_suspicious_but_healthy():
    result = build_result(10., [], [], FaceMeasurement(False), Calibration(CONFIG), CONFIG)
    assert result.monitoring_healthy
    assert result.gaze_direction == GazeDirection.UNKNOWN
    assert to_observation(result).conditions == {EventType.FACE_ABSENT: None}


def test_face_present_with_closed_eyes_does_not_create_absence_or_gaze():
    result = build_result(10., [], [], FaceMeasurement(True, features=None), Calibration(CONFIG), CONFIG)
    assert to_observation(result).conditions == {}


def test_unhealthy_result_cannot_clear_events_or_generate_absence():
    with pytest.raises(ValueError, match="monitoring health"):
        to_observation(VisionResult(10., monitoring_healthy=False))


@pytest.mark.parametrize("direction,event", [
    (GazeDirection.LEFT, EventType.GAZE_LEFT),
    (GazeDirection.RIGHT, EventType.GAZE_RIGHT),
    (GazeDirection.DOWN, EventType.GAZE_DOWN),
])
def test_direction_maps_to_existing_engine(direction, event):
    result = VisionResult(10., face_present=True, gaze_direction=direction, gaze_confidence=.7)
    observation = to_observation(result)
    assert observation.source == "vision"
    assert observation.timestamp == 10.
    assert observation.conditions == {event: .7}


def test_no_gaze_event_when_face_absent_even_if_bad_input_claims_direction():
    result = VisionResult(10., face_present=False, gaze_direction=GazeDirection.DOWN)
    assert to_observation(result).conditions == {EventType.FACE_ABSENT: None}


def test_phone_detection_and_raised_are_separate_engine_conditions():
    result = build_result(10., [PERSON], [RAISED], FACE, Calibration(CONFIG), CONFIG)
    assert to_observation(result).conditions == {
        EventType.PHONE_VISIBLE: .85,
        EventType.PHONE_RAISED: .85,
    }


def test_raised_phone_cannot_exist_without_phone_visible():
    assert EventType.PHONE_RAISED not in to_observation(VisionResult(10., phone_raised=True)).conditions


def test_thresholds_are_configurable():
    strict = replace(CONFIG, person_confidence=.95, phone_confidence=.95)
    assert filter_persons([PERSON], strict) == ()
    assert filter_phones([RAISED], strict) == ()
