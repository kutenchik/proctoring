from dataclasses import replace
import math
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from proctoring.vision.face import identity_shape_points
from proctoring.vision.identity import IdentityVerifier, face_quality_reason, procrustes_distance
from proctoring.vision.types import Box, FaceMeasurement, GazeDiagnostics, HeadPose


def points(seed=7):
    return tuple(map(tuple, np.random.default_rng(seed).normal(size=(18, 3)) * 30 + [320, 240, 0]))


def face(**kwargs):
    return replace(FaceMeasurement(True, box=Box(.3, .2, .7, .8), head_pose=HeadPose(),
                                  frame_size=(640, 480), detected_face_count=1,
                                  identity_points=points()), **kwargs)


def verifier():
    value = IdentityVerifier(threshold=.4, interval_seconds=30)
    value.capture_baseline(np.full((480, 640, 3), 127, dtype=np.uint8), face(), 0.)
    return value


def test_procrustes_removes_translation_scale_and_rotation_not_shape():
    baseline = np.asarray(points())
    angle = .3
    rotation = np.array([[math.cos(angle), -math.sin(angle), 0],
                         [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
    assert procrustes_distance(baseline, baseline @ rotation * 1.8 + [30, 12, 7]) < 1e-12
    assert procrustes_distance(baseline, points(81)) > .4


@pytest.mark.parametrize("bad", [(), [(0, 0, 0)] * 18, [(float("nan"), 1, 2)] * 18,
                                  [(1, 2)] * 18, [(x, 0, 0) for x in range(18)]])
def test_procrustes_rejects_invalid_or_degenerate_landmarks(bad):
    with pytest.raises(ValueError):
        procrustes_distance(points(), bad)


def test_extracts_xyz_in_matching_pixel_units_and_never_rounds():
    landmarks = [SimpleNamespace(x=.3333, y=.4567, z=.0789) for _ in range(478)]
    extracted = identity_shape_points(landmarks, 640, 480)
    assert len(extracted) == 18
    assert extracted[0] == pytest.approx((.3333 * 640, .4567 * 480, .0789 * 640))
    assert identity_shape_points([(1, 2)] * 478, 640, 480) == ()


def test_baseline_is_local_normalized_jpeg_and_metadata_excludes_shape():
    value = verifier()
    baseline = value.baseline
    image = cv2.imdecode(np.frombuffer(baseline.jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape == (256, 256, 3)
    assert baseline.jpeg_bytes[:2] == b"\xff\xd8"
    assert baseline.metadata["source_frame_size"] == [640, 480]
    assert "points" not in baseline.metadata
    assert "not identity authentication" in baseline.metadata["purpose"]
    baseline.metadata["algorithm"] = "changed"
    assert baseline.metadata["algorithm"] == "normalized_procrustes_face_shape_v1"


@pytest.mark.parametrize("invalid", [face(face_present=False), face(detected_face_count=2),
                                      face(head_pose=HeadPose(yaw=16)), face(head_pose=HeadPose(pitch=16)),
                                      face(head_pose=HeadPose(roll=13)), face(head_pose=None),
                                      face(box=Box(0, .2, .7, .8)), face(box=Box(.3, .3, .35, .4)),
                                      face(identity_points=()), face(frame_size=None)])
def test_reference_requires_single_visible_frontal_face(invalid):
    assert face_quality_reason(invalid)
    with pytest.raises(ValueError):
        IdentityVerifier().capture_baseline(np.zeros((480, 640, 3), np.uint8), invalid, 0.)


def test_reference_rejects_wrong_source_frame():
    with pytest.raises(ValueError, match="matching source"):
        IdentityVerifier().capture_baseline(np.zeros((240, 320, 3), np.uint8), face(), 0.)


def test_four_consecutive_periodic_valid_comparisons_required():
    value = verifier()
    different = face(identity_points=points(81))
    for index, timestamp in enumerate((1., 31., 61., 91.), 1):
        result = value.observe(different, timestamp)
        assert result.checked
        assert result.distance > .4
        assert result.consecutive_mismatches == index
        assert result.suspected == (index == 4)
        waiting = value.observe(different, timestamp + .1)
        assert not waiting.checked
        assert waiting.distance is None  # No fabricated current distance/confidence.
        assert waiting.consecutive_mismatches == index
    assert not value.observe(face(), 121.).suspected


@pytest.mark.parametrize("invalid", [face(face_present=False), face(detected_face_count=2),
                                      face(identity_points=()), face(head_pose=HeadPose(yaw=18))])
def test_invalid_current_face_clears_suspicion_and_mismatch_streak(invalid):
    value = verifier()
    different = face(identity_points=points(81))
    for timestamp in (1., 31., 61., 91.):
        result = value.observe(different, timestamp)
    assert result.suspected
    result = value.observe(invalid, 91.1)
    assert not result.suspected and result.distance is None
    assert value.observe(different, 121.).consecutive_mismatches == 1


def test_unobservable_iris_is_not_automatically_missing_identity_or_missing_face():
    value = verifier()
    result = value.observe(face(features=None, quality=0., diagnostics=GazeDiagnostics(valid=False)), 1.)
    assert result.checked and result.distance < 1e-12
    assert not result.suspected


def test_duplicate_nonfinite_and_out_of_order_frames_never_count():
    value = verifier()
    different = face(identity_points=points(81))
    assert value.observe(different, 1.).consecutive_mismatches == 1
    for timestamp in (1., 0., float("nan"), float("inf")):
        result = value.observe(different, timestamp)
        assert not result.suspected and not result.checked
    assert value.observe(different, 31.).consecutive_mismatches == 2


def test_missing_baseline_never_proves_match():
    result = IdentityVerifier().observe(face(), 1.)
    assert not result.checked and result.distance is None
    assert result.status == "Reference face not captured"
