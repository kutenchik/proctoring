"""Changing presentation language must never reset camera/calibration state."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from proctoring.i18n import manager, translate_text
from proctoring.ui.calibration import CalibrationWidget
from proctoring.ui.eye_closeups import ApertureContext, EyeCloseups
from proctoring.ui.preview import CameraPreview
from proctoring.vision.calibration import Calibration
from proctoring.vision.settings import VisionConfig
from proctoring.vision.types import GazeDirection


@pytest.fixture(autouse=True)
def locale_reset():
    manager.set_language("en")
    yield
    manager.set_language("en")


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_calibration_switch_repaints_prompt_without_resetting_attempt(qt_app):
    calibration = Calibration(VisionConfig())
    calibration.add_sample(GazeDirection.CENTER, (.5, .5, 0., 0.), 1., 1.)
    panel = CalibrationWidget(calibration, 20, .75, diagnostics_enabled=True, cue=lambda: None)
    panel.preparing = True
    panel._completed_targets.add(GazeDirection.CENTER)
    counts_before = calibration.counts.copy()
    attempt_before = calibration.export_snapshot()
    original_prompt = panel.prompt.text()
    original_json = panel.diagnostics_text.toPlainText()
    try:
        manager.set_language("ru")
        assert panel.collect_button.text() == "Начать калибровку"
        assert "Смотрите на метку в физическом центре экрана" in panel.prompt.text()
        assert panel.progress.format() == "Общий ход калибровки %p%"
        assert panel.sample_progress.format() == "Пригодные измерения %v/20"
        manager.set_language("kk")
        assert panel.collect_button.text() == "Калибрлеуді бастау"
        assert "экранның физикалық ортасындағы белгіге қараңыз" in panel.prompt.text()
        assert calibration.counts == counts_before
        assert calibration.export_snapshot() == attempt_before
        assert panel.preparing is True
        assert panel._completed_targets == {GazeDirection.CENTER}
        assert panel.diagnostics_text.toPlainText() == original_json
        assert json.loads(original_json)["target"] == "CENTER"
        manager.set_language("en")
        assert panel.prompt.text() == original_prompt
    finally:
        panel.close()


def test_alignment_reason_translates_without_mutating_admission(qt_app):
    panel = CalibrationWidget(Calibration(VisionConfig()), 20, .75, cue=lambda: None)
    panel.alignment_status = replace(panel.alignment_status, message="Keep both eyes visible",
                                     reason="eyes_not_visible", ready=False)
    panel._render_alignment()
    try:
        manager.set_language("ru")
        assert panel.alignment_label.text() == "Держите оба глаза открытыми · Сбор измерений заблокирован"
        manager.set_language("kk")
        assert panel.alignment_label.text() == "Екі көзіңіз де анық көрінсін · Өлшем жинау бұғатталған"
        assert panel.alignment_status.reason == "eyes_not_visible"
        assert panel.alignment_status.message == "Keep both eyes visible"
        assert not panel.alignment_status.ready
    finally:
        panel.close()


def test_nested_fit_failure_preserves_numbers_and_translates_diagnosis():
    source = (
        "Calibration quality is insufficient: CENTER and DOWN eye measurements were not distinct enough "
        "(separation 0.0587; required 0.0906 eye widths). The assumed pixel-based uncertainty gate dominates. "
        "Vertical separation 0.0463; fit axis requirement 0.0906. Inspect the numerical diagnostics/export; "
        "this failure does not by itself establish overlapping gaze distributions. "
        "Inspect the measured contributions before retrying. Failed calibration cannot start an exam."
    )
    manager.set_language("ru")
    rendered = translate_text(source)
    assert "Качество калибровки недостаточно" in rendered
    assert "пиксельной неопределённости" in rendered
    assert "По вертикали: различие 0.0463" in rendered
    assert "0.0587" in rendered and "0.0906" in rendered
    assert "Calibration quality" not in rendered and "gate dominates" not in rendered
    manager.set_language("kk")
    rendered = translate_text(source)
    assert "Калибрлеу сапасы жеткіліксіз" in rendered
    assert "Пиксельге негізделген" in rendered
    assert "0.0587" in rendered and "0.0906" in rendered


def test_eye_status_retranslates_while_temporal_context_stays_canonical(qt_app):
    panel = EyeCloseups()
    source = ("Left eye: openness 0.149 eye widths; width 35.4 source px; "
              "rejected: low eyelid aperture; iris visibility unverified")
    panel.left.details.setText(source)
    context = ApertureContext()
    source_context = context.observe(10., .05)
    panel.left.aperture.setText(source_context)
    try:
        manager.set_language("ru")
        assert "Левый глаз: раскрытие 0.149" in panel.left.details.text()
        assert "малое раскрытие век" in panel.left.details.text()
        assert "0.00 с" in panel.left.aperture.text()
        assert context.last_text == source_context
        manager.set_language("kk")
        assert "Сол көз: ашылуы 0.149" in panel.left.details.text()
        assert "қабақ аз ашылған" in panel.left.details.text()
        manager.set_language("en")
        assert panel.left.details.text() == source
    finally:
        panel.close()


def test_preview_language_switch_preserves_overlay_and_source_message(qt_app):
    preview = CameraPreview()
    preview.set_frame(None, healthy=False, message="Waiting for healthy camera monitoring")
    # No frame/face is invented merely to localize the waiting overlay.
    preview.resize(400, 220)
    preview.show()
    try:
        for locale in ("ru", "kk", "en"):
            manager.set_language(locale)
            qt_app.processEvents()
            assert not preview.grab().isNull()
            assert preview._message == "Waiting for healthy camera monitoring"
            assert preview._image.isNull()
    finally:
        preview.close()
