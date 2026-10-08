from dataclasses import replace

import numpy as np
import pytest

from proctoring.vision.accessories import AccessoriesConfig, EarphoneHeuristicDetector, patch_anomaly
from proctoring.vision.face import ear_adjacent_regions
from proctoring.vision.types import Box, FaceMeasurement, HeadPose


def frame():
    image = np.full((120, 120, 3), (70, 110, 160), np.uint8)
    image[18:30, 18:30] = 255
    return image


def face(**kwargs):
    return replace(FaceMeasurement(True, head_pose=HeadPose(yaw=20), detected_face_count=1,
                                  frame_size=(120, 120), ear_regions=(Box(.1, .1, .3, .3), Box(.7, .1, .9, .3))), **kwargs)


def detector():
    return EarphoneHeuristicDetector(AccessoriesConfig(True, 12.))


def test_patch_anomaly_is_only_contrast_appearance_not_object_recognition():
    assert patch_anomaly(frame()[12:36, 12:36])
    for patch in (np.full((24, 24, 3), 255, np.uint8), np.zeros((24, 24, 3), np.uint8),
                  np.zeros((2, 2, 3), np.uint8), np.full((24, 24, 3), float("nan")), None):
        assert not patch_anomaly(patch)


def test_five_fresh_consecutive_frames_required():
    value = detector()
    for index in range(1, 6):
        result = value.observe(frame(), face(), index / 10)
        assert result.suspected == (index == 5)
        assert result.consecutive_anomalies == index
    assert "unvalidated" in result.status


@pytest.mark.parametrize("invalid", [face(face_present=False), face(detected_face_count=2),
                                      face(head_pose=HeadPose(yaw=12)), face(head_pose=HeadPose(yaw=36)),
                                      face(head_pose=HeadPose(yaw=20, pitch=21)), face(ear_regions=()),
                                      face(frame_size=(240, 240)), face(head_pose=None),
                                      face(ear_regions=(Box(-.1, .1, .2, .3), Box(.7, .1, .9, .3)))])
def test_invalid_or_neutral_pose_resets_anomaly_streak(invalid):
    value = detector()
    for index in range(5):
        value.observe(frame(), face(), index / 10)
    assert not value.observe(frame(), invalid, .6).suspected
    assert value.observe(frame(), face(), .7).consecutive_anomalies == 1


def test_disabled_has_no_flags_and_duplicate_or_large_gaps_reset_streak():
    disabled = EarphoneHeuristicDetector(AccessoriesConfig())
    assert not disabled.observe(frame(), face(), 0.).suspected
    value = detector()
    for index in range(4):
        value.observe(frame(), face(), index / 10)
    assert not value.observe(frame(), face(), .3).suspected
    assert value.observe(frame(), face(), .4).consecutive_anomalies == 1
    assert value.observe(frame(), face(), 3.).consecutive_anomalies == 1


def test_side_change_and_noisy_patch_reset_streak():
    value = detector()
    for index in range(4):
        value.observe(frame(), face(), index / 10)
    assert not value.observe(frame(), face(head_pose=HeadPose(yaw=-20)), .4).suspected
    assert value.observe(frame(), face(), .5).consecutive_anomalies == 1
    assert not value.observe(np.zeros((120, 120, 3), np.uint8), face(), .6).suspected


def test_regions_are_contour_adjacent_not_claimed_ear_landmarks():
    landmarks = [(0., 0.)] * 478
    landmarks[234], landmarks[454] = (.3, .45), (.7, .45)
    left, right = ear_adjacent_regions(landmarks, Box(.3, .2, .7, .8))
    assert left.center[0] < .3 and right.center[0] > .7
    assert left.width == pytest.approx(.4 * .24)
