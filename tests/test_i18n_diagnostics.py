"""Language changes affect diagnostic presentation, never the labeled evidence."""
import json
import os
from copy import deepcopy
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.i18n import set_language, t, translate_text
from proctoring.ui.diagnostic_panel import DiagnosticPanel
from proctoring.vision.calibration import Calibration
from proctoring.vision.screen_region_protocol import training_specs, validation_specs
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import GazeDirection


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qt_app):
    set_language("en")
    config = replace(VisionConfig(), calibration_samples=3)
    clock = FakeClock(100.)
    widget = DiagnosticPanel(config, clock=clock.monotonic, max_age=2.,
                             preparation_seconds=2., collection_seconds=3., cue=lambda: None)
    calibration = Calibration(config)
    for target, features in (
        (GazeDirection.CENTER, (.5, .5, 0., 0.)),
        (GazeDirection.LEFT, (.49, .5, 0., 0.)),
        (GazeDirection.RIGHT, (.51, .5, 0., 0.)),
        (GazeDirection.DOWN, (.5, .51, 0., 0.)),
    ):
        for _ in range(3):
            clock.advance(.1)
            calibration.add_sample(target, features, clock.monotonic(), 1.)
    calibration.fit()
    widget.remember(calibration.export_snapshot(), "production fit rejected")
    widget.set_availability(True, False)
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    set_language("en")


@pytest.mark.parametrize("locale", ["ru", "kk"])
def test_diagnostic_controls_and_frozen_attempt_survive_language_change(panel, locale, tmp_path):
    panel.export_enabled.setChecked(True)
    source = panel.selected_attempt
    frozen = deepcopy(source)
    canonical_label = panel.attempt_selector.currentData()
    panel.begin_validation()
    panel.prepare_target()
    validation = panel.validation
    window = (panel._start, panel._end, panel._index)
    before = panel.validation_status.text()

    set_language(locale)

    assert panel.export_button.text() == t("diagnostics.export")
    assert panel.prepare_button.text() == translate_text("Prepare validation CENTER")
    assert panel.attempt_selector.currentData() == canonical_label
    assert panel.attempt_selector.currentText() != canonical_label
    assert panel.validation_status.text() != before
    assert panel.validation is validation
    assert panel.selected_attempt is source
    assert source == frozen
    assert (panel._start, panel._end, panel._index) == window
    assert "Current baseline" not in panel.attempt_identity.text()
    assert "Selected retained attempt" not in panel.attempt_identity.text()

    path = tmp_path / f"{locale}.json"
    panel.export_to_path(path)
    exported = json.loads(path.read_text(encoding="utf-8"))
    assert exported["outcome"] == "production fit rejected"
    assert exported["classification_status"] == "DEBUG / UNVALIDATED"
    assert exported["calibration"] == frozen["calibration"]
    assert exported["validation"]["source_attempt_identity"] == frozen["attempt_identity"]
    assert panel.diagnostics["retained_attempt"] == canonical_label

    set_language("en")
    assert panel.attempt_selector.currentText() == canonical_label
    assert panel.validation_status.text() == before


@pytest.mark.parametrize("locale", ["ru", "kk"])
def test_all_screen_region_operator_instructions_have_translations(locale):
    set_language(locale)
    try:
        for spec in training_specs() + validation_specs():
            assert translate_text(spec["instruction"]) != spec["instruction"]
            for phase in spec.get("phases", []):
                assert translate_text(phase["instruction"]) != phase["instruction"]
    finally:
        set_language("en")


@pytest.mark.parametrize("locale", ["ru", "kk"])
def test_nested_live_target_instruction_translates_without_changing_target_ids(panel, locale):
    panel.begin_validation()
    direction = "Look at the physical screen center, not upward or at a control in this panel."
    set_language(locale)
    assert direction not in panel.validation_status.text()
    assert "Keep your head comfortable" not in panel.validation_status.text()
    assert panel.validation.targets[0] == "CENTER"


def test_deleted_diagnostic_panel_is_not_called_on_language_change(qt_app):
    widget = DiagnosticPanel(VisionConfig(), clock=lambda: 100., max_age=2.,
                             preparation_seconds=2., collection_seconds=3., cue=lambda: None)
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    set_language("ru")
    set_language("kk")
    set_language("en")
