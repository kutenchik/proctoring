from dataclasses import replace
import math

import pytest

from proctoring.vision.calibration import Calibration, DIRECTIONS
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import GazeDirection


REFERENCES = {
    GazeDirection.CENTER: (.5, .5, 0., 0.),
    GazeDirection.LEFT: (.3, .5, -.15, 0.),
    GazeDirection.RIGHT: (.7, .5, .15, 0.),
    GazeDirection.DOWN: (.5, .64, 0., .2),
}


def make_calibration(config=None, references=None):
    config = config or replace(VisionConfig(), calibration_samples=5)
    calibration = Calibration(config)
    timestamp = 1.
    for direction, reference in (references or REFERENCES).items():
        for _ in range(config.calibration_samples):
            assert calibration.add_sample(direction, reference, timestamp, 1.)
            timestamp += .1
    return calibration


def test_classification_needs_current_session_calibration():
    calibration = Calibration(VisionConfig())
    assert calibration.classify(REFERENCES[GazeDirection.LEFT]) == (GazeDirection.UNKNOWN, None)
    assert not calibration.ready


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_fits_each_calibrated_direction(direction):
    calibration = make_calibration()
    assert calibration.fit()[0]
    result, confidence = calibration.classify(REFERENCES[direction])
    assert result == direction
    assert confidence == 1.


def test_labels_are_learned_from_samples_not_raw_coordinate_sign():
    references = dict(REFERENCES)
    references[GazeDirection.LEFT], references[GazeDirection.RIGHT] = references[GazeDirection.RIGHT], references[GazeDirection.LEFT]
    calibration = make_calibration(references=references)
    assert calibration.fit()[0]
    assert calibration.classify((.7, .5, .15, 0.))[0] == GazeDirection.LEFT


def test_all_direction_samples_required():
    calibration = Calibration(VisionConfig())
    assert calibration.add_sample(GazeDirection.CENTER, REFERENCES[GazeDirection.CENTER], 1., 1.)
    ok, reason = calibration.fit()
    assert not ok
    assert "LEFT" in reason
    assert not calibration.ready


def test_poorly_separated_calibration_requires_retry():
    calibration = make_calibration(references={direction: REFERENCES[GazeDirection.CENTER] for direction in DIRECTIONS})
    ok, reason = calibration.fit()
    assert not ok
    assert "not distinct" in reason
    assert not calibration.ready


def test_unsteady_samples_rejected():
    config = replace(VisionConfig(), calibration_samples=5, calibration_max_spread=.1)
    calibration = Calibration(config)
    timestamp = 1.
    for direction in DIRECTIONS:
        for i in range(5):
            row = list(REFERENCES[direction])
            row[0] += .4 if i % 2 else -.4
            calibration.add_sample(direction, tuple(row), timestamp, 1.)
            timestamp += .1
    assert not calibration.fit()[0]


@pytest.mark.parametrize("features,quality,timestamp", [
    ((.5, .5, 0, 0), .1, 1.),
    ((.5, .5, 0, 0), math.nan, 1.),
    ((.5, .5, 0, 0), 1., math.inf),
    ((math.nan, .5, 0, 0), 1., 1.),
    ((.5, .5), 1., 1.),
    (None, 1., 1.),
])
def test_bad_samples_rejected(features, quality, timestamp):
    calibration = Calibration(VisionConfig())
    assert not calibration.add_sample(GazeDirection.CENTER, features, timestamp, quality)
    assert calibration.counts[GazeDirection.CENTER] == 0


def test_duplicate_and_out_of_order_frames_cannot_fill_calibration():
    calibration = Calibration(VisionConfig())
    assert calibration.add_sample(GazeDirection.CENTER, REFERENCES[GazeDirection.CENTER], 10., 1.)
    assert not calibration.add_sample(GazeDirection.CENTER, REFERENCES[GazeDirection.CENTER], 10., 1.)
    assert not calibration.add_sample(GazeDirection.LEFT, REFERENCES[GazeDirection.LEFT], 9., 1.)
    assert calibration.counts[GazeDirection.CENTER] == 1


def test_reset_discards_session_samples_and_fit():
    calibration = make_calibration()
    assert calibration.fit()[0]
    calibration.reset()
    assert not calibration.ready
    assert all(count == 0 for count in calibration.counts.values())
    assert calibration.classify(REFERENCES[GazeDirection.LEFT])[0] == GazeDirection.UNKNOWN


def test_counts_cannot_mutate_internal_state():
    calibration = Calibration(VisionConfig())
    calibration.counts[GazeDirection.CENTER] = 999
    assert calibration.counts[GazeDirection.CENTER] == 0


def test_boundary_and_outside_training_range_are_unknown():
    calibration = make_calibration()
    assert calibration.fit()[0]
    midpoint = tuple((a + b) / 2 for a, b in zip(REFERENCES[GazeDirection.CENTER], REFERENCES[GazeDirection.LEFT]))
    assert calibration.classify(midpoint)[0] == GazeDirection.UNKNOWN
    assert calibration.classify((8, 8, 8, 8))[0] == GazeDirection.UNKNOWN


def test_sample_memory_is_bounded_and_fit_is_immutable_until_reset():
    config = replace(VisionConfig(), calibration_samples=5, calibration_max_samples=5)
    calibration = make_calibration(config)
    assert not calibration.add_sample(GazeDirection.CENTER, REFERENCES[GazeDirection.CENTER], 99., 1.)
    assert calibration.fit()[0]
    assert not calibration.add_sample(GazeDirection.CENTER, REFERENCES[GazeDirection.LEFT], 100., 1.)


EYES_ONLY_REFERENCES = {
    GazeDirection.CENTER: (.5, .5, 0., 0.),
    GazeDirection.LEFT: (.42, .5, 0., 0.),
    GazeDirection.RIGHT: (.58, .5, 0., 0.),
    GazeDirection.DOWN: (.5, .56, 0., 0.),
}


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_distinguishable_eyes_with_unchanged_head_fit_and_classify(direction):
    calibration = make_calibration(references=EYES_ONLY_REFERENCES)
    assert calibration.fit()[0]
    assert calibration.classify(EYES_ONLY_REFERENCES[direction])[0] == direction
    pair = calibration.diagnostics["pairs"]["CENTER_DOWN"]
    assert pair["eye_separation"] == pytest.approx(.06)
    assert pair["required_eye_separation"] == pytest.approx(.03)
    assert pair["head_separation_degrees"] == 0.


def test_head_rotation_cannot_rescue_overlapping_center_down_eyes():
    references = dict(EYES_ONLY_REFERENCES)
    references[GazeDirection.DOWN] = (.5, .5, 0., .7)
    calibration = make_calibration(references=references)
    ok, reason = calibration.fit()
    assert not ok
    assert "eye measurements were not distinct" in reason
    assert not calibration.ready
    pair = calibration.diagnostics["pairs"]["CENTER_DOWN"]
    assert pair["eye_separation"] == 0.
    assert pair["head_separation_degrees"] == pytest.approx(42.)
    assert not pair["passed"]


def test_eye_label_is_independent_of_small_head_movement():
    calibration = make_calibration(references=EYES_ONLY_REFERENCES)
    assert calibration.fit()[0]
    # A small nod must not turn a center iris reference into DOWN.
    assert calibration.classify((.5, .5, 0., .1))[0] == GazeDirection.CENTER
    assert calibration.classify((.5, .56, .1, -.1))[0] == GazeDirection.DOWN
    # Beyond head coverage, report uncertainty instead of extrapolating.
    assert calibration.classify((.5, .56, 1., 1.)) == (GazeDirection.UNKNOWN, None)


def test_down_label_is_learned_in_camera_coordinates_not_fixed_vertical_sign():
    references = dict(EYES_ONLY_REFERENCES)
    references[GazeDirection.DOWN] = (.5, .44, 0., 0.)
    calibration = make_calibration(references=references)
    assert calibration.fit()[0]
    assert calibration.classify((.5, .44, 0., 0.))[0] == GazeDirection.DOWN
    assert calibration.classify((.5, .56, 0., 0.)) == (GazeDirection.UNKNOWN, None)


@pytest.mark.parametrize("direction", (GazeDirection.LEFT, GazeDirection.RIGHT, GazeDirection.DOWN))
def test_reading_displacements_do_not_automatically_become_offscreen(direction):
    calibration = make_calibration(references=EYES_ONLY_REFERENCES)
    assert calibration.fit()[0]
    center = EYES_ONLY_REFERENCES[GazeDirection.CENTER]
    target = EYES_ONLY_REFERENCES[direction]
    for progress in (.1, .2, .4, .55, .65):
        features = tuple(a + progress * (b - a) for a, b in zip(center, target))
        assert calibration.classify(features)[0] in (GazeDirection.CENTER, GazeDirection.UNKNOWN)
    assert calibration.classify(target)[0] == direction


def test_signal_must_exceed_camera_resolution_floor():
    config = replace(VisionConfig(), calibration_samples=5)
    calibration = Calibration(config)
    timestamp = 1.
    # 40-pixel eyes: a one-pixel heuristic is .025 eye widths. The required
    # signal is .075, so the otherwise distinct .06 DOWN signal remains failed.
    for direction, reference in EYES_ONLY_REFERENCES.items():
        for _ in range(5):
            assert calibration.add_sample(direction, reference, timestamp, 1., noise_floor=1 / 40)
            timestamp += .1
    assert not calibration.fit()[0]
    pair = calibration.diagnostics["pairs"]["CENTER_DOWN"]
    assert pair["required_eye_separation"] == pytest.approx(.075)
    assert pair["eye_signal_noise"] == pytest.approx(2.4)
    assert pair["required_signal_noise"] == pytest.approx(3.)


@pytest.mark.parametrize("noise_floor", (0., -.01, math.nan, math.inf))
def test_invalid_resolution_floor_is_rejected(noise_floor):
    calibration = Calibration(VisionConfig())
    assert not calibration.add_sample(GazeDirection.CENTER, REFERENCES[GazeDirection.CENTER],
                                      1., 1., noise_floor=noise_floor)
    assert calibration.diagnostics["targets"]["CENTER"]["rejection_reasons"] == {
        "invalid_measurement_noise_floor": 1,
    }


def test_mixed_ui_glances_across_entire_interval_fail():
    config = replace(VisionConfig(), calibration_samples=5)
    calibration = Calibration(config)
    timestamp = 1.
    for direction, reference in EYES_ONLY_REFERENCES.items():
        for index in range(10):
            # First five DOWN samples are good, later five look back at the UI.
            # Stopping at minimum N would have hidden this mixed distribution.
            row = EYES_ONLY_REFERENCES[GazeDirection.CENTER] if (
                direction == GazeDirection.DOWN and index >= 5) else reference
            assert calibration.add_sample(direction, row, timestamp, 1.)
            timestamp += .1
    assert calibration.counts[GazeDirection.DOWN] == 10
    assert not calibration.fit()[0]
    pair = calibration.diagnostics["pairs"]["CENTER_DOWN"]
    assert pair["eye_separation"] == pytest.approx(.03)
    assert pair["required_eye_separation"] == pytest.approx(.075)


def test_diagnostics_report_aggregate_counts_medians_spreads_and_rejection_reasons():
    calibration = make_calibration(references=EYES_ONLY_REFERENCES)
    calibration.record_rejection(GazeDirection.DOWN, "blink_or_occlusion")
    assert not calibration.add_sample(GazeDirection.DOWN, EYES_ONLY_REFERENCES[GazeDirection.DOWN], 1., 1.)
    snapshot = calibration.diagnostics
    down = snapshot["targets"]["DOWN"]
    assert down["accepted"] == 5
    assert down["rejected"] == 2
    assert down["rejection_reasons"] == {"blink_or_occlusion": 1, "reused_or_out_of_order_measurement": 1}
    assert down["eye_median"] == [.5, .56]
    assert down["eye_spread_p90"] == 0.
    assert down["head_median_degrees"] == [0., 0.]
    assert "samples" not in snapshot
    import json
    json.dumps(snapshot, allow_nan=False)
    down["eye_median"][0] = 999
    down["rejection_reasons"]["blink_or_occlusion"] = 999
    assert calibration.diagnostics["targets"]["DOWN"]["eye_median"] == [.5, .56]
    assert calibration.diagnostics["targets"]["DOWN"]["rejected"] == 2


def test_retry_target_pair_refreshes_baseline_and_keeps_freshness_barrier():
    calibration = make_calibration(references=EYES_ONLY_REFERENCES)
    assert calibration.fit()[0]
    directions = calibration.retry_targets((GazeDirection.DOWN,))
    assert directions == (GazeDirection.CENTER, GazeDirection.DOWN)
    assert not calibration.ready
    assert calibration.counts[GazeDirection.CENTER] == 0
    assert calibration.counts[GazeDirection.DOWN] == 0
    assert calibration.counts[GazeDirection.LEFT] == 5
    assert not calibration.add_sample(GazeDirection.CENTER, REFERENCES[GazeDirection.CENTER], 1., 1.)
    assert not calibration.fit()[0]


def test_retry_checks_new_baseline_against_preserved_targets():
    calibration = make_calibration(references=EYES_ONLY_REFERENCES)
    assert calibration.fit()[0]
    calibration.retry_targets((GazeDirection.DOWN,))
    for index in range(5):
        # The camera/student moved: the new CENTER overlaps the old LEFT.
        assert calibration.add_sample(GazeDirection.CENTER, EYES_ONLY_REFERENCES[GazeDirection.LEFT],
                                      100. + index, 1.)
    for index in range(5):
        assert calibration.add_sample(GazeDirection.DOWN, EYES_ONLY_REFERENCES[GazeDirection.DOWN],
                                      110. + index, 1.)
    assert not calibration.fit()[0]
    assert calibration.diagnostics["failed_targets"] == ["CENTER", "LEFT"]


def test_discard_interrupted_target_preserves_other_samples_but_invalidates_fit():
    calibration = make_calibration()
    assert calibration.fit()[0]
    calibration.discard_target(GazeDirection.DOWN)
    assert calibration.counts[GazeDirection.DOWN] == 0
    assert calibration.counts[GazeDirection.CENTER] == 5
    assert not calibration.ready


def test_legacy_mixed_separation_setting_cannot_bypass_eye_noise_requirement():
    references = dict(EYES_ONLY_REFERENCES)
    references[GazeDirection.DOWN] = (.5, .505, 0., .4)
    calibration = make_calibration(
        replace(VisionConfig(), calibration_samples=5, calibration_min_separation=0.), references)
    assert not calibration.fit()[0]
