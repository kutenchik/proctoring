from dataclasses import replace

import pytest

from proctoring.config import DEFAULT_CONFIG, load_config
from proctoring.vision.alignment import AlignmentConfig
from proctoring.vision.collection import BoundedCollection, CollectionPositionGuard
from proctoring.vision.types import Box
from test_alignment import ready, result, face


def test_nineteen_samples_extend_until_twentieth_without_shortening_nominal():
    window = BoundedCollection(100., 3., 6., 20)
    assert window.outcome(100.001, 20) == "collect"
    assert window.outcome(102.999, 20) == "collect"
    assert window.outcome(103., 19) == "collect"
    assert window.outcome(103.1, 20) == "complete"
    assert window.deadline == 106.


def test_invalid_data_cannot_extend_absolute_deadline():
    window = BoundedCollection(100., 3., 6., 20)
    assert window.outcome(105.999, 0) == "collect"
    assert window.outcome(106., 19) == "timeout"
    assert window.outcome(1000., 19) == "timeout"
    assert window.outcome(106., 20) == "complete"


@pytest.mark.parametrize("nominal,maximum,count", [(0, 6, 20), (3, 2, 20), (3, float("inf"), 20), (3, 6, 0)])
def test_invalid_collection_policy(nominal, maximum, count):
    with pytest.raises(ValueError):
        BoundedCollection(0., nominal, maximum, count)


def test_position_reference_survives_eye_invalidity_but_never_reanchors_after_motion():
    evaluator = ready()
    guard = CollectionPositionGuard(AlignmentConfig())
    guard.anchor(result(.75))
    invalid_eyes = face(features=None, diagnostics=None)
    invalid_result = result(.85, invalid_eyes)
    status = evaluator.update(invalid_result, .85, True)
    assert not status.ready and status.positioning_stable
    assert guard.check(invalid_result, status) == "compatible"
    moved = result(.95, face(box=Box(.34, .2, .74, .8)))
    state = evaluator.update(moved, .95, True)
    assert guard.check(moved, state) == "position_changed"
    assert guard.anchor(moved)  # Does not re-anchor an established baseline.
    assert guard.check(moved, state) == "position_changed"
    returned = result(1.05)
    state = evaluator.update(returned, 1.05, True)
    assert guard.check(returned, state) == "compatible"
    assert not state.ready  # Normal positioning stability still required.


def test_missing_geometry_and_changed_camera_do_not_count_as_compatible():
    evaluator = ready()
    guard = CollectionPositionGuard(AlignmentConfig())
    guard.anchor(result(.75))
    missing = result(.85, face(box=None))
    assert guard.check(missing, evaluator.update(missing, .85, True)) == "geometry_unavailable"
    resized = result(.95, face(frame_size=(1280, 720)))
    assert guard.check(resized, evaluator.update(resized, .95, True)) == "camera_changed"
    guard.reset()
    assert guard.anchor(resized)
    assert guard.check(resized, evaluator.status) == "compatible"


def test_stale_capture_with_an_old_resolution_cannot_invalidate_entire_baseline():
    evaluator = ready()
    guard = CollectionPositionGuard(AlignmentConfig())
    guard.anchor(result(.75))
    stale = result(.1, face(frame_size=(1280, 720)))
    state = evaluator.update(stale, 1., True)
    assert not state.geometry_valid
    assert guard.check(stale, state) == "geometry_unavailable"


def test_config_defaults_and_maximum_validation(tmp_path):
    config = load_config()
    assert config.vision.calibration_collection_seconds == 3.
    assert config.vision.calibration_max_collection_seconds == 6.
    for invalid in ["2.9", "31", "nan"]:
        path = tmp_path / "config.toml"
        path.write_text(DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8").replace(
            "calibration_max_collection_seconds = 6.0", f"calibration_max_collection_seconds = {invalid}"), encoding="utf-8")
        with pytest.raises(ValueError):
            load_config(path)
