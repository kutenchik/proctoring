"""Screen experiment UI mechanics; no webcam or human accuracy claims."""
import json
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint

from proctoring.ui.screen_target import ScreenTarget, position_metadata
from proctoring.vision.types import EyeDiagnostic, GazeDiagnostics
from test_ui_stage3 import camera_window, qt_app, align, publish, complete_calibration


def begin(window_fixture, *, synthetic_position=False):
    clock, monitor, window = window_fixture
    window._open_camera()
    align(clock, monitor, window)
    widget = window.calibration_widget
    widget.diagnostics_panel.setChecked(True)
    panel = widget.diagnostic_workflow
    panel.screen_region_enabled.setChecked(True)
    if synthetic_position:
        panel.target_metadata_provider = lambda: {"x_normalized": .5, "y_normalized": .5, "rendered": True}
    panel.begin_region_calibration()
    return clock, monitor, window, panel


def finish_target(clock, monitor, window, panel):
    assert panel._start is not None, (panel._index, panel.active, panel.validation_status.text(), panel._target_metadata)
    index = panel._index
    limit = panel._start + panel.collection_seconds + .2
    while panel._index == index and clock.monotonic() < limit:
        publish(clock, monitor, window)
    assert panel._index == index + 1, panel.validation_status.text()


def publish_invalid(clock, monitor, window):
    clock.advance(.1)
    current = monitor.latest_result
    eye = EyeDiagnostic(.5, .5, .05, False, "low eyelid aperture; iris visibility unverified", 40.)
    face = replace(current.face, features=None, diagnostics=GazeDiagnostics(eye, eye, False, eye.reason))
    monitor.latest_result = replace(current, timestamp=clock.monotonic(), face=face)
    window._refresh_camera()


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_training_selectable_without_old_fit_and_records_layout_position(camera_window):
    clock, monitor, window, panel = begin(camera_window)
    assert not monitor.calibration.ready
    assert panel.screen_region_active
    assert not window.start_button.isEnabled()
    assert not window.controller.session.started
    panel.prepare_target()
    assert window.stack.currentWidget() is window.exam_page
    assert not window.screen_target.isHidden()
    location = panel._target_metadata
    assert location["rendered"]
    assert location["target_visible_inside_client"]
    assert location["x_normalized"] == pytest.approx(.5, abs=.003)
    assert location["y_normalized"] == pytest.approx(.5, abs=.003)
    assert set(location["visible_layout_regions"]) == {"quiz", "options", "controls", "monitor"}
    assert not window.controller.protection.blocking_enabled
    panel.cancel_validation()
    assert window.screen_target.isHidden()
    assert window.stack.currentWidget() is window.setup_page
    assert not monitor.calibration.ready


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_training_requires_alignment_but_retains_invalid_samples(camera_window):
    clock, monitor, window = camera_window
    window._open_camera()
    align(clock, monitor, window)
    window.calibration_widget.diagnostics_panel.setChecked(True)
    panel = window.calibration_widget.diagnostic_workflow
    panel.screen_region_enabled.setChecked(True)
    publish_invalid(clock, monitor, window)
    panel.begin_region_calibration()
    assert not panel.prepare_button.isEnabled()
    panel.prepare_target()
    assert panel._start is None
    align(clock, monitor, window)
    assert panel._start is not None  # Valid positioning begins preparation automatically.
    clock.advance(panel._start - clock.monotonic())
    publish_invalid(clock, monitor, window)
    assert panel.validation.accepted_counts[panel.validation.targets[0]] == 0
    assert not monitor.calibration.ready
    panel.cancel_validation()


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_prepare_rechecks_frame_age_at_click_time(camera_window):
    clock, monitor, window, panel = begin(camera_window)
    panel.pause_collection()
    clock.advance(panel.max_age + .01)
    panel.pause_collection()  # Resume also rechecks the age of the source capture.
    assert panel._start is None
    assert "fresh aligned" in panel.validation_status.text()
    assert not monitor.calibration.ready
    panel.cancel_validation()


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_training_exports_own_attempt_and_validation_uses_matching_source(camera_window, tmp_path):
    clock, monitor, window, panel = begin(camera_window, synthetic_position=True)
    # The offscreen Qt backend exposes an 800px synthetic display smaller than
    # the real app's minimum width. This test checks collection provenance; the
    # separate center/layout test exercises real widget coordinate mapping.
    for _ in panel.validation.targets:
        finish_target(clock, monitor, window, panel)
    assert not panel.active
    saved = panel.selected_attempt
    assert saved["calibration"]["protocol"] == "screen_region_training_v1"
    assert len(saved["calibration"]["target_definitions"]) == 13
    assert saved["calibration"]["diagnostics"]["ready"] is False
    assert not monitor.calibration.ready
    assert not window.controller.session.started
    assert window._diagnostic_region_geometry is None
    panel.candidate_enabled.setChecked(True)  # Must not compose the older candidate.
    panel.begin_validation()
    assert panel.validation.candidate is None
    assert len(panel.validation.targets) == 17
    panel.prepare_target()
    assert panel._end - panel._start == 6.
    panel.cancel_validation()
    panel.export_enabled.setChecked(True)
    destination = tmp_path / "region.json"
    panel.export_to_path(destination)
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["validation"]["source_attempt_identity"] == payload["attempt_identity"]
    assert payload["contains_images_or_video"] is False


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_moving_window_during_target_cancels_instead_of_mislabelling(camera_window):
    clock, monitor, window, panel = begin(camera_window)
    panel.prepare_target()
    provider = panel.target_metadata_provider
    frozen = provider()
    panel.target_metadata_provider = lambda: dict(frozen, client_geometry=[9, 9, 900, 700])
    publish(clock, monitor, window)
    assert not panel.active
    assert "layout moved" in panel.validation_status.text()
    assert not monitor.calibration.ready


def test_marker_coordinates_include_screen_origin_and_resize(qt_app):
    from PySide6.QtWidgets import QWidget
    widget = QWidget()
    widget.resize(700, 500)
    widget.show()
    overlay = ScreenTarget(widget)
    overlay.set_point(QPoint(350, 250))
    metadata = position_metadata(widget, overlay.point)
    assert metadata["client_normalized"] == [.5, .5]
    origin_x, origin_y, width, height = metadata["screen_geometry"]
    desktop_x, desktop_y = metadata["desktop_position"]
    assert metadata["x_normalized"] == (desktop_x - origin_x) / width
    assert metadata["y_normalized"] == (desktop_y - origin_y) / height
    widget.resize(800, 600)
    overlay.set_point(QPoint(400, 300))
    assert overlay.geometry() == widget.rect()
    assert position_metadata(widget, overlay.point)["client_normalized"] == [.5, .5]
    widget.close()


@pytest.mark.parametrize("camera_window", [True], indirect=True)
def test_experiment_mode_blocks_exam_even_with_previous_production_fit(camera_window):
    clock, monitor, window = camera_window
    complete_calibration(clock, monitor, window)
    assert monitor.calibration.ready
    assert window.start_button.isEnabled()
    window.calibration_widget.diagnostics_panel.setChecked(True)
    panel = window.calibration_widget.diagnostic_workflow
    panel.screen_region_enabled.setChecked(True)
    assert not window.start_button.isEnabled()
    window._start()
    assert not window.controller.session.started
    assert "cannot start an exam" in window.setup_error.text()
    align(clock, monitor, window)
    panel.target_metadata_provider = lambda: {"x_normalized": .5, "y_normalized": .5, "rendered": True}
    panel.begin_region_calibration()
    for _ in panel.validation.targets:
        finish_target(clock, monitor, window, panel)
    assert monitor.calibration.ready  # Experimental fit neither rewrites nor authorizes production.
    assert not window.start_button.isEnabled()
    window._start()
    assert not window.controller.session.started
    panel.screen_region_enabled.setChecked(False)
    publish(clock, monitor, window)
    assert window.start_button.isEnabled()
