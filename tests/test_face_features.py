from dataclasses import FrozenInstanceError, replace
import math
import sys
from types import SimpleNamespace

import pytest

from proctoring.vision.face import FaceAnalyzer, choose_primary_face, eye_head_features, eye_head_measurement, pose_from_matrix
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import Box, EyeOverlay, HeadPose


def landmarks():
    points = [(.5, .5)] * 478
    points[0], points[2] = (.2, .15), (.8, .85)
    for first, second, upper, lower, iris, start in ((33, 133, 159, 145, 468, .3), (362, 263, 386, 374, 473, .6)):
        points[first], points[second] = (start, .4), (start + .1, .4)
        points[upper], points[lower] = (start + .05, .38), (start + .05, .42)
        points[iris] = (start + .05, .4)
    return points


def test_identity_transform_neutral_head_pose():
    pose = pose_from_matrix([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    assert pose == HeadPose()


def test_transform_yaw_and_scale():
    c, s = math.cos(math.radians(25)), math.sin(math.radians(25))
    pose = pose_from_matrix([[2*c, 0, 2*s], [0, 2, 0], [-2*s, 0, 2*c]])
    assert pose.yaw == pytest.approx(25)
    assert pose.pitch == pytest.approx(0)
    assert pose.roll == pytest.approx(0)


@pytest.mark.parametrize("matrix", [None, [], [[0]*3]*3, [[math.nan]*3]*3, [[1]]])
def test_invalid_transform_has_no_pose(matrix):
    assert pose_from_matrix(matrix) is None


def test_features_combine_iris_geometry_and_head_pose():
    features, quality = eye_head_features(landmarks(), HeadPose(yaw=12, pitch=-6))
    assert features == pytest.approx((.5, .5, .2, -.1))
    assert quality == pytest.approx(1.)


def test_features_are_invariant_to_image_resolution():
    full, _ = eye_head_features(landmarks(), HeadPose(), 1280, 720)
    small, _ = eye_head_features(landmarks(), HeadPose(), 640, 360)
    assert full == pytest.approx(small)


def test_iris_offset_changes_feature_not_a_preclassified_label():
    points = landmarks()
    points[468], points[473] = (.37, .4), (.67, .4)
    features, _ = eye_head_features(points, HeadPose())
    assert features[0] == pytest.approx(.7)
    assert isinstance(features, tuple)


def test_closed_eyes_have_no_gaze_sample():
    points = landmarks()
    points[159], points[145] = (.35, .4), (.35, .401)
    assert eye_head_features(points, HeadPose()) == (None, 0.)


def test_missing_iris_or_pose_has_no_gaze_sample():
    assert eye_head_features(landmarks()[:468], HeadPose()) == (None, 0.)
    assert eye_head_features(landmarks(), None) == (None, 0.)


def test_invalid_iris_has_no_gaze_sample():
    points = landmarks()
    points[468] = (math.nan, .4)
    assert eye_head_features(points, HeadPose()) == (None, 0.)


def test_disagreeing_eyes_have_no_gaze_sample():
    points = landmarks()
    points[468], points[473] = (.32, .4), (.68, .4)
    assert eye_head_features(points, HeadPose()) == (None, 0.)


def test_downward_iris_and_lids_do_not_cancel_each_other():
    """80 px eye; iris and both lids follow a 4 px eyes-only downward shift."""
    points = landmarks()
    for first, second, upper, lower, iris, x in (
            (33, 133, 159, 145, 468, 400), (362, 263, 386, 374, 473, 700)):
        points[first], points[second] = (x / 1280, 300 / 720), ((x + 80) / 1280, 300 / 720)
        points[upper] = ((x + 40) / 1280, 290 / 720)
        points[lower] = ((x + 40) / 1280, 310 / 720)
        points[iris] = ((x + 40) / 1280, 300 / 720)
    center, _, center_diagnostics = eye_head_measurement(points, HeadPose())
    down_points = list(points)
    for index in (159, 145, 468, 386, 374, 473):
        x, y = down_points[index]
        down_points[index] = (x, y + 4 / 720)
    down, _, down_diagnostics = eye_head_measurement(down_points, HeadPose())

    def old_vertical(source, upper, lower, iris):
        return .5 + (source[iris][1] - (source[upper][1] + source[lower][1]) / 2) * 720 / 80

    assert old_vertical(points, 159, 145, 468) == pytest.approx(.5)
    assert old_vertical(down_points, 159, 145, 468) == pytest.approx(.5)
    assert center == pytest.approx((.5, .5, 0, 0))
    assert down == pytest.approx((.5, .55, 0, 0))
    assert down_diagnostics.right_eye.opening == pytest.approx(center_diagnostics.right_eye.opening)
    assert down_diagnostics.right_eye.opening == pytest.approx(.25)
    assert down_diagnostics.right_eye.width_pixels == pytest.approx(80)


def test_lid_motion_alone_does_not_move_vertical_iris_feature():
    points = landmarks()
    baseline, _ = eye_head_features(points, HeadPose())
    for index in (159, 145, 386, 374):
        x, y = points[index]
        points[index] = (x, y + .01)
    measured, _ = eye_head_features(points, HeadPose())
    assert measured == pytest.approx(baseline)


def test_head_features_do_not_change_eye_features():
    center, _ = eye_head_features(landmarks(), HeadPose())
    head_moved, _ = eye_head_features(landmarks(), HeadPose(yaw=15, pitch=-12))
    assert head_moved[:2] == pytest.approx(center[:2])
    assert head_moved[2:] == pytest.approx((.25, -.2))


def test_eye_axes_compensate_roll_in_pixel_space():
    points = landmarks()
    points[468], points[473] = (.36, .41), (.66, .41)
    baseline, _ = eye_head_features(points, HeadPose())
    c, s = math.cos(.2), math.sin(.2)
    rotated = [((c * (x * 1280 - 640) - s * (y * 720 - 360) + 640) / 1280,
                (s * (x * 1280 - 640) + c * (y * 720 - 360) + 360) / 720)
               for x, y in points]
    measured, _ = eye_head_features(rotated, HeadPose(roll=math.degrees(.2)))
    assert measured == pytest.approx(baseline)


def test_camera_coordinates_do_not_silently_apply_preview_mirroring():
    points = landmarks()
    points[468], points[473] = (.37, .41), (.67, .41)
    measured, _, diagnostics = eye_head_measurement(points, HeadPose())
    mirrored, _, mirrored_diagnostics = eye_head_measurement([(1 - x, y) for x, y in points], HeadPose())
    assert measured[0] == pytest.approx(.7)
    assert mirrored[0] == pytest.approx(.3)
    assert mirrored[1] == pytest.approx(measured[1])
    assert diagnostics.left_eye.horizontal == pytest.approx(.7)
    assert mirrored_diagnostics.left_eye.horizontal == pytest.approx(.3)


def test_diagnostics_follow_mediapipe_eye_connection_groups():
    points = landmarks()
    points[468], points[473] = (.34, .405), (.66, .41)
    _, _, diagnostics = eye_head_measurement(points, HeadPose())
    assert diagnostics.right_eye.horizontal == pytest.approx(.4)
    assert diagnostics.left_eye.horizontal == pytest.approx(.6)
    assert diagnostics.right_eye.vertical == pytest.approx(.528125)
    assert diagnostics.left_eye.vertical == pytest.approx(.55625)


def test_narrowing_lids_does_not_amplify_vertical_feature():
    points = landmarks()
    points[468], points[473] = (.35, .406), (.65, .406)
    normal, _, _ = eye_head_measurement(points, HeadPose())
    points[159], points[145] = (.35, .389), (.35, .411)
    points[386], points[374] = (.65, .389), (.65, .411)
    narrowed, quality, diagnostics = eye_head_measurement(points, HeadPose())
    assert diagnostics.valid
    assert diagnostics.right_eye.opening == pytest.approx(.12375)
    assert quality < 1
    assert narrowed == pytest.approx(normal)


def test_blink_reports_measurements_and_reason_without_gaze_sample():
    points = landmarks()
    points[159], points[145] = (.35, .4), (.35, .401)
    features, quality, diagnostics = eye_head_measurement(points, HeadPose())
    assert features is None and quality == 0
    assert not diagnostics.valid and not diagnostics.right_eye.valid
    assert diagnostics.left_eye.valid
    assert diagnostics.right_eye.opening == pytest.approx(.005625)
    assert diagnostics.right_eye.vertical == pytest.approx(.5)
    assert diagnostics.right_eye.width_pixels == pytest.approx(128)
    assert "low eyelid aperture; iris visibility unverified" in diagnostics.reason


def test_valid_eye_measurements_are_exposed_when_head_pose_missing():
    features, quality, diagnostics = eye_head_measurement(landmarks(), None)
    assert features is None and quality == 0
    assert not diagnostics.valid
    assert diagnostics.left_eye.valid and diagnostics.right_eye.valid
    assert diagnostics.reason == "head pose unavailable or invalid"


@pytest.mark.parametrize("change,reason", [
    ({468: (math.nan, .4)}, "non-finite eye landmarks"),
    ({133: (.3001, .4)}, "eye too small"),
    ({468: (.5, .4)}, "iris outside plausible eye geometry"),
    ({159: None}, "malformed or missing eye landmarks"),
    ({159: (.35, .3), 145: (.35, .5)}, "implausible eyelid aperture"),
])
def test_invalid_geometry_keeps_other_eye_diagnostics(change, reason):
    points = landmarks()
    for index, value in change.items():
        points[index] = value
    features, quality, diagnostics = eye_head_measurement(points, HeadPose())
    assert features is None and quality == 0
    assert diagnostics.left_eye.valid
    assert diagnostics.right_eye.reason == reason


def test_eye_disagreement_reports_possible_occlusion():
    points = landmarks()
    points[468], points[473] = (.32, .4), (.68, .4)
    features, _, diagnostics = eye_head_measurement(points, HeadPose())
    assert features is None
    assert diagnostics.left_eye.valid and diagnostics.right_eye.valid
    assert "eyes disagree" in diagnostics.reason


def test_primary_face_rejects_tiny_detection():
    tiny = [(x*.05, y*.05) for x, y in landmarks()]
    assert choose_primary_face([tiny], .01) is None


def test_primary_face_prefers_large_central_face():
    small = [(x*.5, y*.5) for x, y in landmarks()]
    index, box = choose_primary_face([small, landmarks()], .01)
    assert index == 1
    assert box.area > .4


def test_primary_face_tracks_previous_nearby_face():
    small = [(x*.5, y*.5) for x, y in landmarks()]
    previous = Box(.1, .075, .4, .425)
    assert choose_primary_face([small, landmarks()], .01, previous)[0] == 0


def test_missing_local_model_fails_without_download(tmp_path):
    with pytest.raises(FileNotFoundError, match="Local Face Landmarker"):
        FaceAnalyzer(replace(VisionConfig(), face_model=tmp_path / "missing.task"))


def test_detector_keeps_face_present_when_gaze_geometry_is_unusable(monkeypatch):
    points = landmarks()
    points[159], points[145] = (.35, .4), (.35, .401)
    result = SimpleNamespace(face_landmarks=[points], facial_transformation_matrixes=[
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
    ])
    analyzer = FaceAnalyzer.__new__(FaceAnalyzer)
    analyzer.config = VisionConfig()
    analyzer._previous_box = None
    analyzer._last_timestamp_ms = -1
    analyzer._mp = SimpleNamespace(Image=lambda **kwargs: object(), ImageFormat=SimpleNamespace(SRGB=1))
    analyzer._landmarker = SimpleNamespace(detect_for_video=lambda image, timestamp: result)
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(cvtColor=lambda frame, code: frame, COLOR_BGR2RGB=1))
    measurement = analyzer.detect(SimpleNamespace(shape=(720, 1280, 3)), 10.)
    assert measurement.face_present
    assert measurement.features is None
    assert measurement.head_pose == HeadPose()
    assert measurement.box is not None
    assert measurement.diagnostics is not None
    assert measurement.frame_size == (1280, 720)
    assert not measurement.diagnostics.valid
    assert "low eyelid aperture; iris visibility unverified" in measurement.diagnostics.reason


def test_detector_fresh_frame_without_face_returns_absence(monkeypatch):
    result = SimpleNamespace(face_landmarks=[], facial_transformation_matrixes=[])
    analyzer = FaceAnalyzer.__new__(FaceAnalyzer)
    analyzer.config = VisionConfig()
    analyzer._previous_box = None
    analyzer._last_timestamp_ms = -1
    analyzer._mp = SimpleNamespace(Image=lambda **kwargs: object(), ImageFormat=SimpleNamespace(SRGB=1))
    analyzer._landmarker = SimpleNamespace(detect_for_video=lambda image, timestamp: result)
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(cvtColor=lambda frame, code: frame, COLOR_BGR2RGB=1))
    measurement = analyzer.detect(SimpleNamespace(shape=(720, 1280, 3)), 10.)
    assert not measurement.face_present
    assert measurement.features is None
    assert measurement.frame_size == (1280, 720)
    assert measurement.left_eye_overlay is None
    assert measurement.right_eye_overlay is None


def test_fractional_source_pixel_movement_survives_feature_calculation():
    points = landmarks()
    original, _, original_diagnostics = eye_head_measurement(points, HeadPose(), 640, 480)
    for index in (468, 473):
        x, y = points[index]
        points[index] = (x + .25 / 640, y + .125 / 480)
    moved, _, moved_diagnostics = eye_head_measurement(points, HeadPose(), 640, 480)
    width = original_diagnostics.left_eye.width_pixels
    assert moved[0] - original[0] == pytest.approx(.25 / width)
    assert moved[1] - original[1] == pytest.approx(.125 / width)
    assert moved_diagnostics.left_eye.horizontal != original_diagnostics.left_eye.horizontal
    assert moved_diagnostics.right_eye.vertical != original_diagnostics.right_eye.vertical


@pytest.mark.parametrize("opening, valid", [(0., False), (.03, False), (.099, False), (.101, True)])
def test_downward_landmarks_do_not_bypass_unchanged_aperture_safeguard(opening, valid):
    points = landmarks()
    # Move the iris and lids downward while holding both corner axes fixed.
    for upper, lower, iris, x in ((159, 145, 468, .35), (386, 374, 473, .65)):
        half_aperture = opening * 128 / 720 / 2
        points[upper], points[lower] = (x, .406 - half_aperture), (x, .406 + half_aperture)
        points[iris] = (x, .406)
    features, quality, diagnostics = eye_head_measurement(points, HeadPose(yaw=12, pitch=-6))
    assert diagnostics.valid is valid
    assert diagnostics.left_eye.opening == pytest.approx(opening)
    assert diagnostics.right_eye.opening == pytest.approx(opening)
    # Finite downward coordinates remain inspectable even when they are unusable.
    assert diagnostics.left_eye.vertical > .5
    assert diagnostics.right_eye.vertical > .5
    if valid:
        assert features[:2] == pytest.approx((.5, .53375))
        assert quality == pytest.approx(opening / .22)
    else:
        assert features is None and quality == 0
        assert diagnostics.left_eye.reason == "low eyelid aperture; iris visibility unverified"
        assert diagnostics.right_eye.reason == "low eyelid aperture; iris visibility unverified"


def _detect_points(monkeypatch, points):
    result = SimpleNamespace(face_landmarks=[points], facial_transformation_matrixes=[
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
    ])
    analyzer = FaceAnalyzer.__new__(FaceAnalyzer)
    analyzer.config = VisionConfig()
    analyzer._previous_box = None
    analyzer._last_timestamp_ms = -1
    analyzer._mp = SimpleNamespace(Image=lambda **kwargs: object(), ImageFormat=SimpleNamespace(SRGB=1))
    analyzer._landmarker = SimpleNamespace(detect_for_video=lambda image, timestamp: result)
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(cvtColor=lambda frame, code: frame, COLOR_BGR2RGB=1))
    return analyzer.detect(SimpleNamespace(shape=(480, 640, 3)), 10.)


def test_detector_retains_both_eyes_original_fractional_source_geometry(monkeypatch):
    points = landmarks()
    for iris, x in ((468, .35123), (473, .65123)):
        points[iris:iris + 5] = [(x, .40567), (x + .01, .40567), (x, .40567 - .01),
                                (x - .01, .40567), (x, .40567 + .01)]
    measurement = _detect_points(monkeypatch, points)
    assert measurement.frame_size == (640, 480)
    for overlay, indices in ((measurement.left_eye_overlay, ((362, 263), (386, 374), (473, 474, 475, 476, 477))),
                             (measurement.right_eye_overlay, ((33, 133), (159, 145), (468, 469, 470, 471, 472)))):
        assert isinstance(overlay, EyeOverlay)
        assert overlay.corners == tuple(points[i] for i in indices[0])
        assert overlay.lids == tuple(points[i] for i in indices[1])
        assert overlay.iris == tuple(points[i] for i in indices[2])
        assert all(isinstance(value, float) for group in (overlay.corners, overlay.lids, overlay.iris)
                   for point in group for value in point)
        with pytest.raises(FrozenInstanceError):
            overlay.iris = ()


@pytest.mark.parametrize("gap", [0., .001, .01])
def test_detector_retains_eye_inspection_geometry_when_aperture_rejects_gaze(monkeypatch, gap):
    points = landmarks()
    for upper, lower, iris, x in ((159, 145, 468, .35), (386, 374, 473, .65)):
        points[upper], points[lower], points[iris] = (x, .406), (x, .406 + gap), (x, .406)
    measurement = _detect_points(monkeypatch, points)
    assert measurement.face_present
    assert measurement.features is None
    assert measurement.quality == 0
    assert measurement.head_pose == HeadPose()
    assert not measurement.diagnostics.valid
    assert measurement.left_eye_overlay is not None
    assert measurement.right_eye_overlay is not None
    assert measurement.left_eye_overlay.iris[0] == points[473]
    assert measurement.right_eye_overlay.lids == (points[159], points[145])


@pytest.mark.parametrize("bad_point", [(math.nan, .4), (.4, math.inf), None])
def test_bad_inspection_ring_point_does_not_change_gaze_admission(monkeypatch, bad_point):
    points = landmarks()
    points[469] = bad_point
    measurement = _detect_points(monkeypatch, points)
    assert measurement.right_eye_overlay is None
    assert measurement.left_eye_overlay is not None
    # The production feature calculation does not use ring points. Rendering
    # missing inspection geometry must not introduce a new admission gate.
    assert measurement.diagnostics.valid
    assert measurement.features is not None


def test_missing_iris_geometry_does_not_invent_an_overlay(monkeypatch):
    measurement = _detect_points(monkeypatch, landmarks()[:468])
    assert measurement.face_present
    assert measurement.features is None
    assert measurement.left_eye_overlay is None
    assert measurement.right_eye_overlay is None
