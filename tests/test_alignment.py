"""Positioning readiness must not substitute for calibrated gaze separation."""
from dataclasses import asdict, replace
import math

import pytest

from proctoring.vision.alignment import AlignmentConfig, FaceAlignment
from proctoring.vision.face import eye_head_measurement
from proctoring.vision.types import Box, EyeDiagnostic, FaceMeasurement, GazeDiagnostics, HeadPose, VisionResult


def face(**changes):
    eye = EyeDiagnostic(horizontal=.5, vertical=.5, opening=.2, valid=True, reason="", width_pixels=35.)
    measurement = FaceMeasurement(True, box=Box(.3, .2, .7, .8), features=(.5, .5, 0., 0.),
                                  head_pose=HeadPose(), quality=1.,
                                  diagnostics=GazeDiagnostics(eye, eye, True, ""), frame_size=(640, 480))
    return replace(measurement, **changes)


def result(stamp=0., measurement=None, **changes):
    changes.setdefault("face_present", True)
    return VisionResult(timestamp=stamp, face=measurement or face(), **changes)


def ready(evaluator=None):
    evaluator = evaluator or FaceAlignment()
    for stamp in (0., .375, .75):
        status = evaluator.update(result(stamp), stamp, True)
    assert status.ready
    return evaluator


def test_readiness_requires_a_stable_interval_and_unique_captures():
    evaluator = FaceAlignment()
    initial = evaluator.update(result(0.), 0., True)
    assert initial.message == "Hold still"
    assert not initial.can_collect
    assert initial.progress == 0
    middle = evaluator.update(result(.375), .375, True)
    assert not middle.ready
    assert middle.progress == pytest.approx(.5)
    status = evaluator.update(result(.75), .75, True)
    assert status.can_collect and status.ready
    assert status.message == "Face aligned"
    assert status.progress == 1
    assert status.stable_samples == 3
    assert status.stable_elapsed_seconds == .75
    assert status.guide == (.18, .08, .82, .92)


def test_numerical_diagnostics_use_source_pixels_and_degrees():
    status = ready().status
    values = asdict(status)
    assert values["frame_size"] == (640, 480)
    assert values["face_width_pixels"] == pytest.approx(256)
    assert values["face_height_pixels"] == pytest.approx(288)
    assert values["left_eye_width_pixels"] == 35.
    assert values["right_eye_width_pixels"] == 35.
    assert values["yaw_degrees"] == 0.


def test_duplicate_ui_polls_do_not_accumulate_stability():
    evaluator = FaceAlignment(AlignmentConfig(max_sample_gap_seconds=2.), max_age=2.)
    first = evaluator.update(result(0.), 0., True)
    for now in (.2, .7, 1.2):
        assert evaluator.update(result(0.), now, True) == first
    assert not evaluator.status.ready
    assert evaluator.status.stable_samples == 1


def test_duplicate_poll_may_retain_ready_only_while_result_is_fresh():
    evaluator = ready()
    assert evaluator.update(result(.75), 1., True).ready
    status = evaluator.update(result(.75), 1.5, True)
    assert not status.ready
    assert status.reason == "stale_frame"
    assert status.stable_samples == 0


def test_last_capture_becomes_stale_at_stability_gap_even_if_health_allows_longer():
    evaluator = ready(FaceAlignment(max_age=2.))
    status = evaluator.update(result(.75), 1.251, True)
    assert status.reason == "stale_frame"
    assert not status.ready


@pytest.mark.parametrize("case, reason", [
    (None, "no_frame"),
    (VisionResult(1., face=None), "no_face"),
    (result(1., face_present=False), "no_face"),
    (result(1., face(face_present=False)), "no_face"),
    (result(1., face(box=None)), "no_face"),
    (result(1., face(frame_size=None)), "source_dimensions_missing"),
    (result(1., face(frame_size=(0, 480))), "source_dimensions_missing"),
    (result(1., face(frame_size=(640, math.nan))), "source_dimensions_missing"),
    (result(1., monitoring_healthy=False), "monitoring_unavailable"),
])
def test_unavailable_geometry_immediately_clears_ready(case, reason):
    evaluator = ready()
    status = evaluator.update(case, 1., True)
    assert not status.ready
    assert status.reason == reason


def test_external_monitoring_health_clears_readiness():
    evaluator = ready()
    assert evaluator.update(result(1.), 1., False).reason == "monitoring_unavailable"
    assert not evaluator.status.ready


@pytest.mark.parametrize("stamp, now", [(1.1, 1.), (.1, 1.), (math.nan, 1.), (1., math.inf)])
def test_invalid_or_stale_timestamps_cannot_align(stamp, now):
    status = ready().update(result(stamp), now, True)
    assert not status.ready
    assert status.reason == "stale_frame"


def test_timestamp_regression_resets_without_accepting_replayed_history():
    evaluator = ready()
    status = evaluator.update(result(.5), .8, True)
    assert not status.ready
    assert status.reason == "timestamp_regressed"
    assert not evaluator.update(result(.75), .8, True).ready
    assert evaluator.status.stable_samples == 0
    assert not evaluator.update(result(1.), 1., True).ready
    assert evaluator.status.stable_samples == 1


@pytest.mark.parametrize("box", [Box(.17, .2, .6, .8), Box(.3, .07, .7, .8),
                                 Box(.3, .2, .83, .8), Box(.3, .2, .7, .93),
                                 Box(-.1, .2, .7, .8), Box(.3, .2, 1.1, .8),
                                 Box(.7, .2, .3, .8), Box(.3, .2, math.nan, .8)])
def test_entire_face_must_be_within_guide_and_source_frame(box):
    status = ready().update(result(1., face(box=box)), 1., True)
    assert not status.ready
    assert status.reason == "face_not_contained"
    assert status.message == "Center your face"


def test_face_touching_guide_boundary_is_contained():
    evaluator = FaceAlignment()
    status = evaluator.update(result(measurement=face(box=Box(*evaluator.config.guide))), 0., True)
    assert status.reason == "hold_still"


@pytest.mark.parametrize("measurement", [face(box=Box(.4, .2, .6, .8)),
                                          face(box=Box(.3, .4, .7, .7))])
def test_source_face_dimensions_must_be_large_enough(measurement):
    status = FaceAlignment().update(result(measurement=measurement), 0., True)
    assert not status.ready
    assert status.reason == "face_too_small"
    assert status.message == "Move closer"


def test_requested_or_preview_resolution_does_not_replace_source_resolution():
    small = face(box=Box(.3, .3, .5, .6))
    status = FaceAlignment().update(result(measurement=small, frame=type("Preview", (), {"shape": (720, 1280, 3)})()), 0., True)
    assert status.reason == "face_too_small"
    assert status.frame_size == (640, 480)
    large = replace(small, frame_size=(1280, 960))
    assert FaceAlignment().update(result(measurement=large), 0., True).reason == "hold_still"


@pytest.mark.parametrize("side", ["left_eye", "right_eye"])
def test_each_eye_must_reach_source_pixel_minimum(side):
    measurement = face()
    eye = replace(getattr(measurement.diagnostics, side), width_pixels=31.99)
    diagnostics = replace(measurement.diagnostics, **{side: eye})
    status = FaceAlignment().update(result(measurement=replace(measurement, diagnostics=diagnostics)), 0., True)
    assert status.reason == "face_too_small"
    assert not status.ready


@pytest.mark.parametrize("side", ["left_eye", "right_eye"])
def test_blink_or_narrow_eye_blocks_sample_but_preserves_fresh_stable_geometry(side):
    evaluator = ready()
    generation = evaluator.status.geometry_generation
    measurement = face()
    eye = replace(getattr(measurement.diagnostics, side), valid=False, reason="eye closed or aperture too narrow")
    diagnostics = replace(measurement.diagnostics, **{side: eye})
    status = evaluator.update(result(1., replace(measurement, diagnostics=diagnostics)), 1., True)
    assert status.reason == "eyes_not_visible"
    assert status.message == "Keep both eyes visible"
    assert not status.ready
    assert status.geometry_valid and status.positioning_stable
    assert status.geometry_generation == generation
    assert status.stable_samples == 4
    resumed = evaluator.update(result(1.1), 1.1, True)
    assert resumed.ready and resumed.stable_samples == 5
    assert resumed.geometry_generation == generation


@pytest.mark.parametrize("changes", [dict(features=None), dict(diagnostics=None),
                                     dict(quality=.4), dict(features=(.5, math.nan, 0., 0.))])
def test_invalid_eye_data_does_not_erase_observable_face_geometry(changes):
    evaluator = ready()
    before = evaluator.status
    status = evaluator.update(result(1., face(**changes)), 1., True)
    assert not status.ready
    assert status.geometry_valid and status.positioning_stable
    assert status.geometry_generation == before.geometry_generation
    assert status.stable_samples == before.stable_samples + 1
    assert evaluator.update(result(1.1), 1.1, True).ready


def test_eye_invalid_geometry_can_earn_stability_but_never_admit_gaze():
    evaluator = FaceAlignment()
    invalid = face(features=None, quality=0., diagnostics=None)
    for stamp in (0., .375, .75):
        status = evaluator.update(result(stamp, invalid), stamp, True)
        assert not status.ready
    assert status.positioning_stable and status.geometry_valid
    assert evaluator.update(result(.9), .9, True).ready


def test_small_or_unknown_eye_width_still_blocks_sample_without_erasing_face_geometry():
    for width in (31., None):
        evaluator = ready()
        measurement = face()
        diagnostics = replace(measurement.diagnostics,
                              left_eye=replace(measurement.diagnostics.left_eye, width_pixels=width))
        status = evaluator.update(result(1., replace(measurement, diagnostics=diagnostics)), 1., True)
        assert not status.ready
        assert status.geometry_valid and status.positioning_stable
        assert status.geometry_generation == 0
        assert evaluator.update(result(1.1), 1.1, True).ready


def test_movement_during_eye_invalidity_invalidates_geometry_generation():
    evaluator = ready()
    before = evaluator.status.geometry_generation
    status = evaluator.update(result(1., face(box=Box(.33, .2, .73, .8), features=None)), 1., True)
    assert not status.ready and not status.positioning_stable
    assert status.geometry_valid
    assert status.geometry_generation == before + 1
    assert status.geometry_reset_reason == "face_moved"
    assert status.stable_samples == 1


@pytest.mark.parametrize("measurement, reason", [(face(box=None), "no_face"),
                                                (face(head_pose=None, diagnostics=None), "head_pose_unavailable"),
                                                (face(frame_size=None), "source_dimensions_missing"),
                                                (face(box=Box(.1, .2, .5, .8)), "face_not_contained")])
def test_missing_or_incompatible_geometry_invalidates_once_until_reacquired(measurement, reason):
    evaluator = ready()
    before = evaluator.status.geometry_generation
    status = evaluator.update(result(1., measurement), 1., True)
    assert not status.geometry_valid and not status.positioning_stable
    assert status.geometry_generation == before + 1
    assert status.geometry_reset_reason == reason
    repeated = evaluator.update(result(1.1, measurement), 1.1, True)
    assert repeated.geometry_generation == status.geometry_generation
    resumed = evaluator.update(result(1.2), 1.2, True)
    assert resumed.geometry_valid and not resumed.positioning_stable
    assert resumed.stable_samples == 1


def test_eye_invalid_capture_after_excessive_gap_cannot_preserve_stability():
    evaluator = ready()
    before = evaluator.status.geometry_generation
    status = evaluator.update(result(1.3, face(features=None)), 1.3, True)
    assert not status.ready and not status.positioning_stable
    assert status.geometry_generation == before + 1
    assert status.geometry_reset_reason == "capture_gap"


def test_source_resolution_change_invalidates_even_when_eyes_unavailable():
    evaluator = ready()
    before = evaluator.status.geometry_generation
    status = evaluator.update(result(1., face(frame_size=(1280, 720), diagnostics=None)), 1., True)
    assert not status.ready and not status.positioning_stable
    assert status.geometry_generation == before + 1
    assert status.geometry_reset_reason == "source_dimensions_changed"


def test_equivalent_source_size_list_does_not_trigger_geometry_reset():
    evaluator = ready()
    before = evaluator.status.geometry_generation
    status = evaluator.update(result(1., face(frame_size=[640, 480])), 1., True)
    assert status.ready
    assert status.geometry_generation == before
    assert status.frame_size == (640, 480)


@pytest.mark.parametrize("changes, reason", [(dict(features=None), "eye_measurements_invalid"),
                                            (dict(features=(.5, .5)), "eye_measurements_invalid"),
                                            (dict(features=(.5, math.nan, 0., 0.)), "eye_measurements_invalid"),
                                            (dict(quality=.449), "eye_quality_low"),
                                            (dict(quality=math.nan), "eye_quality_low"),
                                            (dict(diagnostics=None), "eyes_not_visible")])
def test_invalid_eye_features_cannot_collect(changes, reason):
    status = FaceAlignment().update(result(measurement=face(**changes)), 0., True)
    assert status.reason == reason
    assert not status.ready


@pytest.mark.parametrize("pose", [HeadPose(yaw=15.01), HeadPose(yaw=-15.01),
                                  HeadPose(pitch=15.01), HeadPose(pitch=-15.01),
                                  HeadPose(roll=12.01), HeadPose(roll=-12.01)])
def test_head_must_be_approximately_frontal(pose):
    status = ready().update(result(1., face(head_pose=pose)), 1., True)
    assert status.reason == "head_not_frontal"
    assert status.message == "Face the screen naturally"
    assert not status.ready


@pytest.mark.parametrize("pose", [None, HeadPose(yaw=math.nan)])
def test_missing_pose_is_not_assumed_frontal(pose):
    status = FaceAlignment().update(result(measurement=face(head_pose=pose)), 0., True)
    assert status.reason == "head_pose_unavailable"


def feature_landmarks():
    points = [(.5, .5)] * 478
    for first, second, upper, lower, iris, start in ((33, 133, 159, 145, 468, .3), (362, 263, 386, 374, 473, .6)):
        points[first], points[second] = (start, .4), (start + .1, .4)
        points[upper], points[lower] = (start + .05, .38), (start + .05, .42)
        points[iris] = (start + .05, .4)
    return points


@pytest.mark.parametrize("pose", [None, HeadPose(pitch=math.nan)])
def test_real_feature_extractor_missing_pose_has_pose_feedback_with_visible_eyes(pose):
    features, quality, diagnostics = eye_head_measurement(feature_landmarks(), pose, 640, 480)
    assert features is None and not diagnostics.valid
    assert diagnostics.left_eye.valid and diagnostics.right_eye.valid
    measurement = face(features=features, quality=quality, diagnostics=diagnostics, head_pose=pose)
    status = FaceAlignment().update(result(measurement=measurement), 0., True)
    assert status.reason == "head_pose_unavailable"
    assert not status.ready


def test_real_feature_extractor_disagreement_feedback_does_not_claim_hidden_eyes():
    landmarks = feature_landmarks()
    landmarks[468], landmarks[473] = (.32, .4), (.68, .4)
    features, quality, diagnostics = eye_head_measurement(landmarks, HeadPose(), 640, 480)
    assert diagnostics.left_eye.valid and diagnostics.right_eye.valid
    status = FaceAlignment().update(result(measurement=face(features=features, quality=quality, diagnostics=diagnostics)), 0., True)
    assert status.reason == "eye_measurements_disagree"
    assert status.message == "Hold still — eye measurements disagree"
    assert not status.ready


def test_actual_narrow_eye_takes_precedence_over_missing_pose():
    landmarks = feature_landmarks()
    landmarks[159], landmarks[145] = (.35, .4), (.35, .401)
    features, quality, diagnostics = eye_head_measurement(landmarks, None, 640, 480)
    status = FaceAlignment().update(result(measurement=face(features=features, quality=quality, diagnostics=diagnostics, head_pose=None)), 0., True)
    assert status.reason == "eyes_not_visible"


def test_natural_pose_and_eye_movements_are_allowed_without_target_classification():
    evaluator = FaceAlignment()
    for stamp, features in ((0., (.35, .5, 0., 0.)), (.375, (.65, .5, 0., 0.)), (.75, (.5, .65, 0., 0.))):
        status = evaluator.update(result(stamp, face(features=features, head_pose=HeadPose(yaw=15., pitch=-15., roll=12.))), stamp, True)
    assert status.ready


def test_drift_compares_with_original_anchor_so_slow_motion_cannot_accumulate():
    evaluator = FaceAlignment()
    evaluator.update(result(0.), 0., True)
    evaluator.update(result(.375, face(box=Box(.315, .2, .715, .8))), .375, True)
    status = evaluator.update(result(.75, face(box=Box(.325, .2, .725, .8))), .75, True)
    assert not status.ready
    assert status.stable_samples == 1
    assert status.progress == 0


def test_small_center_jitter_does_not_reset_stability():
    evaluator = FaceAlignment()
    for stamp, delta in ((0., 0.), (.375, .01), (.75, -.01)):
        status = evaluator.update(result(stamp, face(box=Box(.3 + delta, .2, .7 + delta, .8))), stamp, True)
    assert status.ready


def test_exact_drift_and_scale_limits_are_inclusive_despite_float_rounding():
    evaluator = FaceAlignment()
    evaluator.update(result(0.), 0., True)
    evaluator.update(result(.375, face(box=Box(.32, .2, .72, .8))), .375, True)
    status = evaluator.update(result(.75, face(box=Box(.30, .2, .74, .8))), .75, True)
    assert status.ready


@pytest.mark.parametrize("box", [Box(.27, .2, .73, .8), Box(.3, .165, .7, .835)])
def test_width_or_height_scale_change_resets_stability(box):
    status = ready().update(result(1., face(box=box)), 1., True)
    assert not status.ready
    assert status.stable_samples == 1


def test_long_capture_gap_cannot_count_as_stillness():
    evaluator = FaceAlignment(max_age=2.)
    evaluator.update(result(0.), 0., True)
    evaluator.update(result(.4), .4, True)
    status = evaluator.update(result(1.), 1., True)
    assert not status.ready
    assert status.stable_samples == 1


def test_two_frames_cannot_qualify_even_when_duration_is_sufficient():
    evaluator = FaceAlignment(AlignmentConfig(max_sample_gap_seconds=1.))
    evaluator.update(result(0.), 0., True)
    status = evaluator.update(result(.75), .75, True)
    assert not status.ready
    assert status.progress == pytest.approx(2 / 3)


def test_resolution_change_restarts_stability():
    status = ready().update(result(1., face(frame_size=(1280, 720))), 1., True)
    assert not status.ready
    assert status.stable_samples == 1


def test_public_reset_for_new_target_discards_previous_stability():
    evaluator = ready()
    assert not evaluator.reset().ready
    assert evaluator.update(result(2.), 2., True).stable_samples == 1


@pytest.mark.parametrize("kwargs", [dict(guide=(0, 0, 2, 1)), dict(min_eye_width_pixels=0),
                                   dict(stable_seconds=math.nan), dict(min_stable_samples=2),
                                   dict(min_quality=1.1), dict(min_quality=True),
                                   dict(min_eye_width_pixels=True), dict(guide=None),
                                   dict(guide=(.1, .1)), dict(guide=(0, 0, True, 1)),
                                   dict(max_scale_change=".1")])
def test_bad_alignment_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        AlignmentConfig(**kwargs)


@pytest.mark.parametrize("max_age", [0., -1., math.nan, True, "1"])
def test_bad_maximum_frame_age_rejected(max_age):
    with pytest.raises(ValueError):
        FaceAlignment(max_age=max_age)
