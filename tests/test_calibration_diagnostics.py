"""Numerical observability regressions; these do not validate human gaze accuracy."""
from dataclasses import replace
import json
import math

import pytest

from proctoring.vision.calibration import Calibration, DIRECTIONS
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import EyeDiagnostic, FaceMeasurement, GazeDiagnostics, GazeDirection, HeadPose


def face(horizontal=.5, vertical=.5, *, width=32., opening=.22, valid=True):
    left = EyeDiagnostic(horizontal - .01, vertical + .002, opening, valid,
                         "" if valid else "eye closed or aperture too narrow", width)
    right = EyeDiagnostic(horizontal + .01, vertical - .002, opening, valid,
                          "" if valid else "eye closed or aperture too narrow", width + 2)
    return FaceMeasurement(True, features=(horizontal, vertical, .05, -.02) if valid else None,
                           head_pose=HeadPose(3, -1.2, .8), quality=1. if valid else 0.,
                           diagnostics=GazeDiagnostics(left, right, valid,
                                                       "" if valid else "narrow eyes"))


def samples(calibration, direction, rows, start, noise=None):
    for index, row in enumerate(rows):
        measurement = face(*row)
        assert calibration.add_sample(direction, measurement.features, start + index, 1.,
                                      noise_floor=noise, measurement=measurement, frame_size=(640, 480))


def test_per_eye_axis_and_original_frame_statistics_are_available():
    calibration = Calibration(replace(VisionConfig(), calibration_samples=3))
    samples(calibration, GazeDirection.CENTER, [(.50, .51), (.52, .53), (.54, .55)], 1, 1 / 32)
    stats = calibration.diagnostics["targets"]["CENTER"]
    assert stats["source_frame_sizes"] == [{"width": 640, "height": 480, "samples": 3}]
    assert stats["eyes"]["left"]["width_pixels"]["median"] == 32
    assert stats["eyes"]["right"]["width_pixels"]["median"] == 34
    assert stats["eyes"]["left"]["horizontal"]["median"] == pytest.approx(.51)
    assert stats["eyes"]["right"]["vertical"]["median"] == pytest.approx(.528)
    assert stats["eyes"]["left"]["horizontal"]["spread_p90"] == pytest.approx(.02)
    assert stats["eye_axes"]["horizontal"]["median"] == pytest.approx(.52)
    assert stats["eye_axes"]["vertical"]["spread_p90"] == pytest.approx(.02)
    assert stats["eye_spread_p90"] == pytest.approx(math.sqrt(2) * .02)
    assert stats["head_median_degrees"] == pytest.approx([3, -1.2])


@pytest.mark.parametrize("separation,required", [(.0466, .0910), (.0730, .1096), (.0556, .0784)])
def test_screenshot_numbers_alone_can_be_explained_by_distinct_causes(separation, required):
    """Same final gate can come from pixel or spread; screenshots cannot choose."""
    pixel = Calibration(replace(VisionConfig(), calibration_samples=4,
                                calibration_pixel_uncertainty_multiplier=3.0))
    spread = Calibration(replace(VisionConfig(), calibration_samples=4))
    for direction, vertical, start in ((GazeDirection.CENTER, .5, 1),
                                        (GazeDirection.DOWN, .5 + separation, 10)):
        samples(pixel, direction, [(.5, vertical)] * 4, start, required / 3)
        jitter = required / 2.0
        samples(spread, direction, [(.5, vertical - jitter), (.5, vertical + jitter)] * 2, start)
    p = pixel.diagnostics["pairs"]["CENTER_DOWN"]
    s = spread.diagnostics["pairs"]["CENTER_DOWN"]
    for pair in (p, s):
        assert pair["eye_separation"] == pytest.approx(separation)
        assert pair["required_eye_separation"] == pytest.approx(required)
        assert not pair["passed"]
    assert p["dominant_contributions"] == ["pixel_noise_floor"]
    assert s["dominant_contributions"] == ["spread"]
    assert p["threshold_contributions"]["constant_noise_floor"] == pytest.approx(.03)
    assert s["axes"]["vertical"]["central_80_percent_intervals_overlap"] is True


def test_unrelated_axis_can_drive_existing_radial_gate_without_being_hidden():
    calibration = Calibration(replace(VisionConfig(), calibration_samples=4))
    for direction, horizontal, start in ((GazeDirection.CENTER, .5, 1),
                                         (GazeDirection.LEFT, .573, 10)):
        samples(calibration, direction, [(horizontal, .45), (horizontal, .55)] * 2, start)
    pair = calibration.diagnostics["pairs"]["CENTER_LEFT"]
    assert pair["required_eye_separation"] == pytest.approx(.125)
    assert pair["eye_separation"] == pytest.approx(.073)
    assert pair["metric_dimensions"] == 2
    assert pair["relevant_axis"] == "horizontal"
    assert pair["unrelated_axis_spread_larger"] is True
    assert pair["axes"]["horizontal"]["metric_dimensions"] == 1
    assert pair["axes"]["horizontal"]["required_separation"] == pytest.approx(.03)
    assert pair["axes"]["horizontal"]["passed_diagnostic_comparison"] is True
    assert pair["axes"]["vertical"]["passed_diagnostic_comparison"] is False
    assert calibration.diagnostics["targets"]["CENTER"]["radial_tail_axis_energy_fraction"] == {
        "horizontal": 0., "vertical": 1.,
    }
    # Diagnostic comparisons never enable production calibration or events.
    assert not pair["passed"]
    assert not calibration.ready
    assert calibration.classify((.573, .5, 0, 0)) == (GazeDirection.UNKNOWN, None)


def test_per_axis_and_per_eye_signed_differences_and_interval_overlap():
    calibration = Calibration(VisionConfig())
    samples(calibration, GazeDirection.CENTER, [(.49, .49), (.5, .5), (.51, .51)], 1)
    samples(calibration, GazeDirection.DOWN, [(.49, .54), (.5, .55), (.51, .56)], 10)
    pair = calibration.diagnostics["pairs"]["CENTER_DOWN"]
    assert pair["relevant_axis"] == "vertical"
    assert pair["axes"]["vertical"]["signed_second_minus_first"] == pytest.approx(.05)
    assert pair["axes"]["horizontal"]["central_80_percent_intervals_overlap"]
    assert not pair["axes"]["vertical"]["central_80_percent_intervals_overlap"]
    for side in ("left", "right"):
        assert pair["axes"]["vertical"]["eyes"][side]["signed_second_minus_first"] == pytest.approx(.05)
        assert pair["axes"]["vertical"]["eyes"][side]["first_spread_p90"] == pytest.approx(.01)


def test_missing_metadata_is_explicit_and_eye_width_is_never_inferred():
    calibration = Calibration(VisionConfig())
    calibration.add_sample(GazeDirection.CENTER, (.5, .5, 0, 0), 1, 1.)
    calibration.add_sample(GazeDirection.DOWN, (.5, .55, 0, 0), 2, 1.)
    stats = calibration.diagnostics["targets"]["CENTER"]
    assert stats["eyes"]["left"]["width_pixels"] is None
    assert stats["eyes"]["left"]["horizontal"] is None
    assert stats["source_frame_sizes"] == []
    assert stats["source_frame_size_missing_samples"] == 1
    assert stats["pixel_noise_floor_missing_samples"] == 1
    assert stats["supplied_pixel_noise_floor_p90"] is None
    pair = calibration.diagnostics["pairs"]["CENTER_DOWN"]
    assert pair["threshold_contributions"]["pixel_noise_floor"] is None
    assert pair["required_eye_separation"] == .03
    assert pair["dominant_contributions"] == ["constant_noise_floor"]


def test_invalid_downward_eye_geometry_remains_available_in_numerical_export():
    calibration = Calibration(VisionConfig())
    measurement = face(vertical=.55, opening=.07, valid=False)
    calibration.record_rejection(GazeDirection.DOWN, "left: eye closed or aperture too narrow",
                                 timestamp=8., measurement=measurement, frame_size=(640, 480))
    snapshot = calibration.export_snapshot()
    record = snapshot["samples"]["DOWN"][0]
    assert not record["accepted"]
    assert record["features"] is None
    assert record["eyes"]["left"]["vertical"] == pytest.approx(.552)
    assert record["eyes"]["left"]["opening"] == .07
    assert record["eyes"]["left"]["reason"] == "eye closed or aperture too narrow"
    assert record["head_pose_degrees"] == {"yaw": 3., "pitch": -1.2, "roll": .8}
    assert record["frame_size"] == [640, 480]
    assert snapshot["last_recorded_timestamp"] == 8.
    assert snapshot["last_accepted_timestamp"] is None
    assert snapshot["diagnostics"]["targets"]["DOWN"]["accepted"] == 0
    assert snapshot["diagnostics"]["targets"]["DOWN"]["all_recorded_eyes"]["left"]["vertical"] is not None
    assert snapshot["diagnostics"]["targets"]["DOWN"]["eyes"]["left"]["vertical"] is None


def test_export_is_bounded_and_deeply_detached_without_images_or_landmarks():
    calibration = Calibration(replace(VisionConfig(), calibration_max_samples=3))
    for timestamp in range(10):
        calibration.record_rejection(GazeDirection.DOWN, "invalid", timestamp=timestamp,
                                     measurement=face(valid=False), frame_size=(640, 480))
    snapshot = calibration.export_snapshot()
    assert len(snapshot["samples"]["DOWN"]) == 3
    assert snapshot["dropped_numerical_records"]["DOWN"] == 7
    assert snapshot["last_recorded_timestamp"] == 9
    assert snapshot["diagnostics"]["targets"]["DOWN"]["rejected"] == 10
    text = json.dumps(snapshot, allow_nan=False)
    assert '"landmarks":' not in text
    assert '"frame":' not in text
    snapshot["samples"]["DOWN"][0]["eyes"]["left"]["opening"] = 100
    assert calibration.export_snapshot()["samples"]["DOWN"][0]["eyes"]["left"]["opening"] == .22


def test_nonfinite_rejections_export_as_json_null_and_cannot_pollute_statistics():
    calibration = Calibration(VisionConfig())
    assert not calibration.add_sample(GazeDirection.CENTER, (math.nan, .5, 0, 0), math.inf, math.nan,
                                      noise_floor=math.nan)
    snapshot = calibration.export_snapshot()
    json.dumps(snapshot, allow_nan=False)
    record = snapshot["samples"]["CENTER"][0]
    assert record["features"][0] is None
    assert record["timestamp"] is None
    assert record["quality"] is None
    assert record["supplied_noise_floor"] is None
    assert snapshot["diagnostics"]["targets"]["CENTER"]["eye_median"] is None


@pytest.mark.parametrize("pixel_floor,spread,expected", [(None, .0, "constant"), (.04, .0, "pixel-based"), (None, .03, "eye-spread")])
def test_failure_feedback_identifies_actual_gate_without_claiming_human_cause(pixel_floor, spread, expected):
    calibration = Calibration(replace(VisionConfig(), calibration_samples=4))
    references = {GazeDirection.CENTER: (.5, .5), GazeDirection.LEFT: (.51, .5),
                  GazeDirection.RIGHT: (.8, .5), GazeDirection.DOWN: (.5, .8)}
    for index, direction in enumerate(DIRECTIONS):
        x, y = references[direction]
        samples(calibration, direction, [(x, y - spread), (x, y + spread)] * 2, index * 10, pixel_floor)
    success, message = calibration.fit()
    assert not success
    assert expected in message
    assert "dominates" in message
    assert "does not by itself establish overlapping" in message
    assert not calibration.ready


def test_missing_sample_failure_reports_counts_and_recorded_reasons():
    calibration = Calibration(replace(VisionConfig(), calibration_samples=3))
    calibration.record_rejection(GazeDirection.DOWN, "eye closed or aperture too narrow", timestamp=1)
    success, message = calibration.fit()
    assert not success
    assert "DOWN: 0/3 accepted, 1 rejected" in message
    assert "eye closed or aperture too narrow: 1" in message


def test_discard_and_reset_remove_numerical_measurements_but_discard_keeps_freshness():
    calibration = Calibration(VisionConfig())
    samples(calibration, GazeDirection.CENTER, [(.5, .5)], 10, 1 / 32)
    snapshot = calibration.export_snapshot()
    calibration.discard_target(GazeDirection.CENTER)
    assert calibration.export_snapshot()["samples"]["CENTER"] == []
    assert calibration.export_snapshot()["last_recorded_timestamp"] == 10
    assert snapshot["samples"]["CENTER"]
    calibration.reset()
    assert calibration.export_snapshot()["last_recorded_timestamp"] is None
    assert calibration.export_snapshot()["last_accepted_timestamp"] is None


@pytest.mark.parametrize("floors", [[None] * 4, [.001, .02, None, .04], [.001] * 4, [.03, .02, .025, .04]])
def test_split_threshold_terms_exactly_reproduce_configured_production_gate(floors):
    calibration = Calibration(replace(VisionConfig(), calibration_samples=4))
    timestamp = 0
    for direction, x in ((GazeDirection.CENTER, .5), (GazeDirection.LEFT, .43)):
        for index, floor in enumerate(floors):
            timestamp += 1
            calibration.add_sample(direction, (x, .5 + (-.015 if index % 2 else .015), 0, 0),
                                   timestamp, 1, noise_floor=floor)
    pair = calibration.diagnostics["pairs"]["CENTER_LEFT"]
    gate = max(3 * .01, .8 * max(value or 0 for value in floors), 2.5 * .015)
    assert pair["required_eye_separation"] == pytest.approx(gate)
    assert max(value for value in pair["threshold_contributions"].values() if value is not None) == pytest.approx(gate)


def test_down_fit_gate_uses_vertical_spread_without_unrelated_horizontal_noise():
    calibration = Calibration(replace(VisionConfig(), calibration_samples=4))
    for direction, vertical, start in ((GazeDirection.CENTER, .5, 1),
                                       (GazeDirection.DOWN, .5463, 10)):
        samples(calibration, direction, [(.45, vertical - .005), (.55, vertical + .005)] * 2,
                start, 1 / 33.11)
    pair = calibration.diagnostics["pairs"]["CENTER_DOWN"]
    assert pair["eye_separation"] == pytest.approx(.0463)
    assert pair["threshold_contributions"]["spread"] == pytest.approx(.01)
    assert pair["required_eye_separation"] == pytest.approx(.03)
    assert pair["dominant_contributions"] == ["constant_noise_floor"]
    assert pair["metric_dimensions"] == 1
    assert pair["unrelated_axis_spread_larger"]
    assert not pair["axis_comparisons_are_diagnostic_only"]
    assert pair["passed"]
    # A passing pair still cannot bypass absent LEFT/RIGHT samples.
    assert not calibration.fit()[0]
