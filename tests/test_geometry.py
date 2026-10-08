"""Production aperture guards: synthetic geometry, not human gaze accuracy."""
from dataclasses import replace
import math

import pytest

from proctoring.vision.classifier import aperture_guard, derive_aperture_references
from proctoring.vision.types import EyeDiagnostic, FaceMeasurement, GazeDiagnostics, GazeDirection


def measurement(*, horizontal=.505, vertical=.5, relative_opening=.5,
                left_opening=None, right_opening=None, quality=1., valid=True):
    left = EyeDiagnostic(horizontal - .005, vertical,
                         .33 * relative_opening if left_opening is None else left_opening,
                         valid, "valid" if valid else "occluded", 33.)
    right = EyeDiagnostic(horizontal + .005, vertical,
                          .32 * relative_opening if right_opening is None else right_opening,
                          valid, "valid" if valid else "occluded", 34.)
    return FaceMeasurement(True, features=(horizontal, vertical, 0., 0.), quality=quality,
                           diagnostics=GazeDiagnostics(left, right, valid, "measured"))


def record(face, *, accepted=True):
    return {"accepted": accepted, "rejection_reason": None,
            "features": face.features, "quality": face.quality,
            "eyes": {"left": vars(face.diagnostics.left_eye),
                     "right": vars(face.diagnostics.right_eye)}}


def references(*, sign=1.):
    center = measurement(relative_opening=1.)
    down = measurement(horizontal=.54, vertical=.5 + sign * .0463)
    return derive_aperture_references({"CENTER": [record(center)] * 3,
                                       "DOWN": [record(down)] * 3}, required_samples=3)


def guard(face, *, refs=None, sign=1., omit_refs=False):
    centers = {"CENTER": (.505, .5, 0., 0.), "LEFT": (.3, .5, 0., 0.),
               "RIGHT": (.7, .5, 0., 0.), "DOWN": (.54, .5 + sign * .0463, 0., 0.)}
    return aperture_guard(face.features, centers, {"CENTER": .025, "DOWN": .017},
                          None if omit_refs else (refs or references(sign=sign)), face)


def test_center_openness_references_are_per_eye_and_session_local():
    refs = references()
    assert refs.left.center_opening == .33
    assert refs.right.center_opening == .32
    second = measurement(left_opening=.40, right_opening=.42)
    new_refs = derive_aperture_references({"CENTER": [record(second)]})
    assert new_refs.left.center_opening == .40
    assert new_refs.right.center_opening == .42


def test_reference_medians_exclude_rejected_and_invalid_measurements():
    good = record(measurement(relative_opening=1.))
    rejected = record(measurement(relative_opening=2.), accepted=False)
    invalid = record(measurement(relative_opening=2., valid=False))
    refs = derive_aperture_references({"CENTER": [good, rejected, invalid]})
    assert refs.left.center_opening == .33
    assert derive_aperture_references({"CENTER": [good, rejected, invalid]}, 2) is None


def test_guarded_down_requires_reduced_aperture_and_bilateral_vertical_shift():
    face = measurement(vertical=.5 + .6 * .0463)
    prediction = guard(face)
    assert prediction == (GazeDirection.DOWN, None, "guarded_aperture_and_vertical_iris_shift")


def test_guard_learns_signed_vertical_direction_from_current_session():
    assert guard(measurement(vertical=.5 - .6 * .0463), sign=-1.)[0] == GazeDirection.DOWN
    assert guard(measurement(vertical=.5 + .6 * .0463), sign=-1.) is None


@pytest.mark.parametrize("relative_opening", [.0, .20, .349])
@pytest.mark.parametrize("vertical", [.5, .5463])
def test_closure_never_becomes_center_or_down(relative_opening, vertical):
    prediction = guard(measurement(vertical=vertical, relative_opening=relative_opening))
    assert prediction[0] == GazeDirection.UNKNOWN
    assert prediction[1] is None
    assert "closure_guard" in prediction[2]


def test_relative_closure_boundary_is_strictly_below_point_35():
    assert guard(measurement(vertical=.54, relative_opening=.35))[0] == GazeDirection.DOWN


@pytest.mark.parametrize("side", ["left", "right"])
def test_one_closed_eye_vetoes_all_directions(side):
    kwargs = {f"{side}_opening": .07}
    for horizontal in (.3, .505, .7):
        prediction = guard(measurement(horizontal=horizontal, vertical=.54, **kwargs))
        assert prediction == (GazeDirection.UNKNOWN, None, "absolute_eye_closure_guard")


def test_absolute_closure_guard_remains_available_without_calibration_metadata():
    prediction = guard(measurement(left_opening=.079), omit_refs=True)
    assert prediction == (GazeDirection.UNKNOWN, None, "absolute_eye_closure_guard")


def test_relative_closure_guard_survives_missing_down_reference():
    refs = derive_aperture_references({"CENTER": [record(measurement(relative_opening=1.))]})
    prediction = guard(measurement(relative_opening=.349), refs=refs)
    assert prediction == (GazeDirection.UNKNOWN, None, "relative_eye_closure_guard")
    assert guard(measurement(), refs=refs)[2] == "calibration_down_aperture_reference_missing"


def test_absolute_point_08_is_not_closure_but_still_fails_unchanged_backend_admission():
    # A .20 CENTER baseline makes .08 exactly .40 relative. The supplement must
    # still reject it through the existing .10 validity guard rather than DOWN.
    refs = references()
    refs = replace(refs, left=replace(refs.left, center_opening=.20),
                   right=replace(refs.right, center_opening=.20))
    prediction = guard(measurement(vertical=.54, left_opening=.08, right_opening=.08), refs=refs)
    assert prediction == (GazeDirection.UNKNOWN, None, "left_eye_unobservable")


@pytest.mark.parametrize("relative_opening", [.4, .5, .7])
def test_reduced_aperture_with_calibrated_center_iris_support_is_center(relative_opening):
    assert guard(measurement(relative_opening=relative_opening))[0] == GazeDirection.CENTER


@pytest.mark.parametrize("relative_opening", [.70, .8, 1.])
def test_open_eyes_do_not_activate_aperture_supplement(relative_opening):
    assert guard(measurement(vertical=.54, relative_opening=relative_opening)) is None


def test_exact_soft_vertical_boundary_prefers_down_when_aperture_supports_it():
    refs = references()
    soft = refs.left.center_vertical + .35 * (refs.left.down_vertical - refs.left.center_vertical)
    assert guard(measurement(vertical=soft))[0] == GazeDirection.DOWN


@pytest.mark.parametrize("horizontal,vertical", [(.3, .5), (.7, .5), (.505, .40), (.505, .70),
                                               (.3, .54), (.7, .54)])
def test_aperture_does_not_invent_labels_outside_finite_iris_support(horizontal, vertical):
    assert guard(measurement(horizontal=horizontal, vertical=vertical)) is None


def test_mean_vertical_shift_does_not_hide_one_eye_without_downward_support():
    face = measurement(vertical=.54)
    left = replace(face.diagnostics.left_eye, vertical=.5)
    right = replace(face.diagnostics.right_eye, vertical=.58)
    face = replace(face, diagnostics=GazeDiagnostics(left, right, True))
    assert guard(face) is None


@pytest.mark.parametrize("value", [None, math.nan, math.inf])
def test_missing_or_nonfinite_eye_values_are_unknown(value):
    face = measurement(vertical=.54)
    face = replace(face, diagnostics=replace(face.diagnostics,
                                            left_eye=replace(face.diagnostics.left_eye, vertical=value)))
    assert guard(face)[0] == GazeDirection.UNKNOWN


def test_invalid_iris_cannot_be_rescued_by_aperture_or_nominal_landmarks():
    assert guard(measurement(vertical=.54, valid=False))[0] == GazeDirection.UNKNOWN
    assert guard(measurement(vertical=.54, quality=.2))[0] == GazeDirection.UNKNOWN
    assert guard(replace(measurement(vertical=.54), features=None))[0] == GazeDirection.UNKNOWN
    assert guard(replace(measurement(vertical=.54), diagnostics=None))[0] == GazeDirection.UNKNOWN


def test_feature_eye_metadata_mismatch_is_unknown():
    assert guard(replace(measurement(vertical=.54), features=(.505, .5, 0., 0.)))[2] == "feature_metadata_mismatch"


def test_no_center_reference_does_not_invent_a_baseline():
    assert guard(measurement(vertical=.54), omit_refs=True)[2] == "calibration_aperture_reference_missing"


def test_no_face_is_unknown():
    assert guard(replace(measurement(), face_present=False))[0] == GazeDirection.UNKNOWN


@pytest.mark.parametrize("degrees", [-20., 0., 14., 20.])
def test_x_rotation_matrix_preserves_signed_pitch_for_downward_pose_rule(degrees):
    from proctoring.vision.face import pose_from_matrix

    angle = math.radians(degrees)
    # Synthetic positive X rotation: establishes numerical convention, not a
    # validation of the webcam/camera-placement interpretation for a person.
    matrix = [[1., 0., 0., 0.],
              [0., math.cos(angle), -math.sin(angle), 0.],
              [0., math.sin(angle), math.cos(angle), 0.],
              [0., 0., 0., 1.]]
    pose = pose_from_matrix(matrix)
    assert pose.pitch == pytest.approx(degrees)
    assert pose.yaw == pytest.approx(0.)
    assert pose.roll == pytest.approx(0.)


def test_positive_pitch_does_not_make_closed_iris_measurements_valid():
    from proctoring.vision.types import HeadPose

    closed = replace(measurement(relative_opening=.2, valid=False),
                     head_pose=HeadPose(pitch=20.), features=None)
    assert guard(closed)[0] == GazeDirection.UNKNOWN
