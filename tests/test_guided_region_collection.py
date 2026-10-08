"""Collection mechanics only; these synthetic rows do not validate human gaze."""
from dataclasses import replace

import pytest

from proctoring.clock import FakeClock
from proctoring.ui.diagnostic_panel import DiagnosticPanel
from proctoring.vision.alignment import AlignmentConfig, FaceAlignment
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import Box
from test_diagnostic_ui import measurement, qt_app


@pytest.fixture
def region(qt_app):
    clock = FakeClock(9.8)
    config = replace(VisionConfig(), alignment=AlignmentConfig(stable_seconds=.01))
    alignment = FaceAlignment(config.alignment, max_age=1.)
    panel = DiagnosticPanel(config, clock=clock.monotonic, max_age=1., preparation_seconds=2.,
                            collection_seconds=3., max_collection_seconds=6., cue=lambda: None)
    panel.screen_region_enabled.setChecked(True)
    panel.target_metadata_provider = lambda: {"rendered": True, "x_normalized": .5, "y_normalized": .5}

    def feed(stamp, *, valid=True, source=None, moved=False, size=None):
        clock.advance(stamp - clock.monotonic())
        row = measurement(stamp if source is None else source, valid=valid)
        # Aperture invalidity is independent of source eye size.
        if not valid:
            eyes = row.face.diagnostics
            row = replace(row, face=replace(row.face, diagnostics=replace(eyes,
                left_eye=replace(eyes.left_eye, width_pixels=40.),
                right_eye=replace(eyes.right_eye, width_pixels=40.))))
        if moved:
            row = replace(row, face=replace(row.face, box=Box(.385, .2, .685, .65)))
        if size is not None:
            row = replace(row, face=replace(row.face, frame_size=size))
        panel.set_alignment(alignment.update(row, stamp, True))
        panel.feed_result(row, stamp, True)
        return row

    for stamp in (9.8, 9.9, 10.):
        feed(stamp)
    panel.begin_region_calibration()
    yield clock, panel, feed
    panel.close()


def preparation(region):
    clock, panel, feed = region
    start = panel._start
    assert start is not None
    while clock.monotonic() < start - .11:
        feed(round(clock.monotonic() + .1, 6))
    return start


def complete(region):
    _, panel, feed = region
    start = preparation(region)
    index = panel._index
    for i in range(1, 31):
        feed(round(start + i * .1, 6))
    assert panel._index == index + 1


def test_nineteen_samples_extend_then_auto_advance_with_fresh_interval(region):
    _, panel, feed = region
    start = preparation(region)
    baseline = panel.current_baseline["baseline_id"]
    for i in range(1, 31):
        feed(start + i * .1, valid=i <= 19)
    assert panel._index == 0
    assert panel.validation.accepted_counts["CENTER_START"] == 19
    assert panel._start == start
    assert "19/20" in panel.validation_status.text()
    feed(start + 3.1)
    assert panel._index == 1
    assert panel.validation.active_target == "SCREEN_LEFT"
    assert panel._start == pytest.approx(start + 5.1)
    assert panel.current_baseline["baseline_id"] == baseline
    old_end = panel.validation.training_snapshot()["collection_windows"]["CENTER_START"]["ends_at"]
    assert old_end == pytest.approx(start + 3.1)
    feed(start + 3.2, source=start + 3.05)  # Prior fixation still in flight.
    assert panel.validation.accepted_counts["SCREEN_LEFT"] == 0
    assert all(row["operator_target"] == "CENTER_START" and row["timestamp"] < panel._start
               for row in panel.validation.training_snapshot()["samples"]["CENTER_START"])


def test_burst_does_not_finish_early_and_duplicate_invalid_stale_are_not_valid(region):
    _, panel, feed = region
    start = preparation(region)
    for i in range(1, 21):
        feed(start + i * .001)
    assert panel._index == 0 and panel.collecting
    feed(start + .1, source=start + .020)
    feed(start + .2, valid=False)
    assert panel.validation.accepted_counts["CENTER_START"] == 20
    assert panel.validation.target_progress("CENTER_START")["rejection_reasons"]["blink_or_narrow_eye"] == 1
    # An excessive stale delivery loses geometry continuity; it cannot be added.
    feed(start + 1.5, source=start + .02)
    assert panel.training_needs_retry
    assert panel.validation.accepted_counts["CENTER_START"] == 0
    saved = panel.selected_attempt["calibration"]["samples"]["CENTER_START"]
    assert sum(row["accepted"] for row in saved) == 20
    assert len(saved) == 21


def test_invalid_eyes_keep_stable_face_and_accepted_rows_but_hard_deadline_wins(region):
    _, panel, feed = region
    start = preparation(region)
    feed(start + .1)
    generation = panel._alignment.geometry_generation
    for i in range(2, 61):
        feed(start + i * .1, valid=False)
        if i < 60:
            assert panel.validation.accepted_counts["CENTER_START"] == 1
            assert panel._alignment.geometry_generation == generation
            assert panel._alignment.positioning_stable
    assert panel.training_needs_retry
    assert panel._start is None
    assert panel.collection_progress.value() == 0
    assert "Eye measurements" in panel.validation_status.text()
    saved = panel.selected_attempt["calibration"]["samples"]["CENTER_START"]
    assert all(row["timestamp"] < start + 6. for row in saved)
    assert sum(row["accepted"] for row in saved) == 1


def test_movement_clears_only_current_target_and_retry_requires_previous_position(region):
    clock, panel, feed = region
    complete(region)
    first = panel.validation.training_snapshot()["samples"]["CENTER_START"]
    baseline = panel.current_baseline["baseline_id"]
    start = preparation(region)
    feed(start + .1)
    feed(start + .2, moved=True)
    assert panel.training_needs_retry
    assert panel.validation.accepted_counts["SCREEN_LEFT"] == 0
    panel.retry_target()
    assert panel._start is None
    for i in range(3, 7):
        feed(start + i * .1, moved=True)
    assert panel._start is None
    assert "previous face position" in panel.validation_status.text()
    for i in range(7, 11):
        feed(start + i * .1)
    assert panel._start is not None
    complete(region)
    snapshot = panel.validation.training_snapshot()
    assert snapshot["samples"]["CENTER_START"] == first
    assert len(snapshot["samples"]["SCREEN_LEFT"]) == 29
    assert all(row["timestamp"] > start + .2 for row in snapshot["samples"]["SCREEN_LEFT"])
    assert panel.current_baseline["baseline_id"] == baseline


def test_pause_cancel_and_resume_preserve_completed_compatible_targets(region):
    clock, panel, feed = region
    complete(region)
    first = panel.validation.training_snapshot()["samples"]["CENTER_START"]
    start = preparation(region)
    feed(start + .1)
    panel.pause_collection()
    assert panel.training_paused and panel._start is None
    assert panel.validation.accepted_counts["SCREEN_LEFT"] == 0
    feed(start + .2)
    panel.pause_collection()
    assert panel._start is not None and not panel.training_paused
    panel.cancel_validation()
    assert not panel.active
    assert "Resume" in panel.region_calibration_button.text()
    feed(start + .3)
    panel.begin_region_calibration()
    assert panel.active and panel._index == 1
    assert panel.validation.training_snapshot()["samples"]["CENTER_START"] == first
    assert panel._start > clock.monotonic()


def test_camera_dimensions_change_requires_new_baseline(region):
    _, panel, feed = region
    complete(region)
    baseline = panel.current_baseline["baseline_id"]
    start = preparation(region)
    feed(start + .1, size=(1280, 720))
    assert not panel.active
    assert panel.current_baseline["baseline_id"] != baseline
    assert panel._suspended_training is None
    assert "Camera dimensions changed" in panel.validation_status.text()


@pytest.mark.parametrize("when", ["preparation", "nominal_boundary"])
def test_camera_change_is_checked_before_preparation_or_completion(region, when):
    _, panel, feed = region
    baseline = panel.current_baseline["baseline_id"]
    start = panel._start
    if when == "nominal_boundary":
        preparation(region)
        for i in range(1, 30):
            feed(start + i * .1)
        stamp = start + 3.
    else:
        stamp = start - 1.
    feed(stamp, size=(1280, 720))
    assert not panel.active and panel._index == 0
    assert panel.current_baseline["baseline_id"] != baseline
    assert not panel.selected_attempt["calibration"]["collection_complete"]
    assert panel._suspended_training is None


def test_position_change_at_nominal_completion_cannot_finish_target(region):
    _, panel, feed = region
    start = preparation(region)
    for i in range(1, 30):
        feed(start + i * .1)
    feed(start + 3., moved=True)
    assert panel._index == 0
    assert panel.training_needs_retry
    assert panel.validation.accepted_counts["CENTER_START"] == 0


def test_monitoring_failure_does_not_offer_old_baseline_resume(region):
    clock, panel, _ = region
    complete(region)
    baseline = panel.current_baseline["baseline_id"]
    panel.feed_result(None, clock.monotonic(), False)
    assert not panel.active
    assert panel.current_baseline["baseline_id"] != baseline
    assert panel._suspended_training is None
    assert "Monitoring interrupted" in panel.validation_status.text()


def test_all_training_targets_progress_without_prepare_clicks(region):
    _, panel, _ = region
    sequence = panel.validation
    for _ in sequence.targets:
        complete(region)
    assert not panel.active
    assert panel.selected_attempt["calibration"]["collection_complete"]
    assert not panel.selected_attempt["calibration"]["diagnostics"]["ready"]
    assert panel.selected_attempt["validation"] is None
    windows = panel.selected_attempt["calibration"]["collection_windows"]
    previous_end = sequence.training_cutoff
    for target in sequence.targets:
        window = windows[target]
        assert window["starts_at"] > previous_end
        assert window["ends_at"] - window["starts_at"] == pytest.approx(3.)
        rows = panel.selected_attempt["calibration"]["samples"][target]
        assert all(row["operator_target"] == target and
                   window["starts_at"] <= row["timestamp"] < window["ends_at"] for row in rows)
        previous_end = window["ends_at"]


def test_native_layout_timer_reentry_schedules_only_one_next_window(region, monkeypatch):
    clock, panel, feed = region
    calls, shown = [], []
    original_start = panel.validation.start_target

    def start_once(label, starts_at, ends_at):
        calls.append((label, starts_at, ends_at))
        return original_start(label, starts_at, ends_at)

    def layout_timer_delivery(target):
        shown.append((target, clock.monotonic()))
        # Mirrors the timer firing while MainWindow settles the new Qt layout.
        feed(clock.monotonic() + .001)

    monkeypatch.setattr(panel.validation, "start_target", start_once)
    panel.target_changed.connect(layout_timer_delivery)
    complete(region)
    assert len(calls) == 1
    assert calls[0][0] == "SCREEN_LEFT"
    assert all(target == "SCREEN_LEFT" for target, _ in shown)
    assert calls[0][1] == pytest.approx(clock.monotonic() + panel.preparation_seconds)
    assert panel.validation.active_target == "SCREEN_LEFT"
    assert panel.validation.accepted_counts["SCREEN_LEFT"] == 0
    assert not panel._scheduling_target


def test_monitoring_loss_during_native_target_layout_still_invalidates_baseline(region):
    clock, panel, _ = region
    baseline = panel.current_baseline["baseline_id"]
    panel.target_changed.connect(lambda target: panel.feed_result(None, clock.monotonic(), False) if target else None)
    complete(region)
    assert not panel.active
    assert panel._suspended_training is None
    assert panel.current_baseline["baseline_id"] != baseline
    assert "Monitoring interrupted" in panel.validation_status.text()
