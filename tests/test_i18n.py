"""Presentation translations cannot change backend identifiers or Qt state."""
import json
import os
from pathlib import Path
import re
from string import Formatter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from proctoring import i18n
from proctoring.config import DEFAULT_CONFIG, UiConfig, load_config
from proctoring.domain import EventType
from proctoring.ui import i18n_widgets


CATALOGUE = {
    "exam.start": {"en": "Start exam", "ru": "Начать экзамен", "kk": "Емтиханды бастау"},
    "exam.progress": {"en": "Answered {done} / {total}", "ru": "Отвечено {done} / {total}",
                      "kk": "Жауап берілді {done} / {total}"},
    "center": {"en": "CENTER", "ru": "ЦЕНТР", "kk": "ОРТА"},
    "status": {"en": "Gaze: {direction} ({latency:.2f} ms)",
               "ru": "Взгляд: {direction} ({latency:.2f} мс)",
               "kk": "Көзқарас: {direction} ({latency:.2f} мс)"},
    "ready": {"en": "{message} · Ready to prepare", "ru": "{message} · Готово к подготовке",
              "kk": "{message} · Дайындалуға болады"},
    "fallback": {"en": "English fallback {number}"},
}


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def translator(monkeypatch):
    local = i18n.TranslationManager(CATALOGUE)
    monkeypatch.setattr(i18n, "manager", local)
    monkeypatch.setattr(i18n_widgets, "manager", local)
    return local


@pytest.mark.parametrize("locale,expected", [
    ("en", "Start exam"), ("ru", "Начать экзамен"), ("kk", "Емтиханды бастау"),
])
def test_t_resolves_all_supported_languages(translator, locale, expected):
    i18n.set_language(locale)
    assert i18n.get_language() == locale
    assert i18n.get_manager() is translator
    assert i18n.t("exam.start") == expected


def test_t_fallback_and_interpolation(translator):
    i18n.set_language("kk")
    assert i18n.t("fallback", number=12) == "English fallback 12"
    assert i18n.t("missing", default="Fallback {number}", number=3) == "Fallback 3"
    assert i18n.t("missing") == "missing"
    assert i18n.t("status", direction="CENTER", latency=12.345) == "Көзқарас: CENTER (12.35 мс)"


def test_language_signal_emitted_only_when_changed(translator):
    calls = []
    translator.language_changed.connect(calls.append)
    translator.set_language("ru")
    translator.set_language("ru")
    translator.set_language("en")
    assert calls == ["ru", "en"]
    with pytest.raises(ValueError, match="Unsupported UI language"):
        translator.set_language("es")
    assert translator.language == "en"


def test_source_templates_preserve_formatted_numbers_and_nested_labels(translator):
    translator.set_language("ru")
    assert translator.translate_text("Gaze: CENTER (12.30 ms)") == "Взгляд: ЦЕНТР (12.30 мс)"
    assert translator.translate_text("Start exam · Ready to prepare") == "Начать экзамен · Готово к подготовке"
    assert translator.translate_text("Start exam\nGaze: CENTER (12.30 ms)") == "Начать экзамен\nВзгляд: ЦЕНТР (12.30 мс)"
    assert translator.translate_text("session_id=abc · Start exam") == "session_id=abc · Начать экзамен"
    assert translator.translate_text("phone_visible") == "phone_visible"
    assert translator.translate_text("CUSTOM_BACKEND_FAILURE") == "CUSTOM_BACKEND_FAILURE"


def test_generic_value_template_never_matches_arbitrary_data():
    translator = i18n.TranslationManager({"generic": {"en": "{value}", "ru": "Изменено {value}"}}, "ru")
    assert translator.translate_text("raw_backend_code") == "raw_backend_code"


def test_punctuation_template_only_composes_known_labels():
    translator = i18n.TranslationManager({
        "event": {"en": "Phone detected", "ru": "Телефон обнаружен"},
        "row": {"en": "{event}: {count}", "ru": "{event}: {count}"},
    }, "ru")
    assert translator.translate_text("Phone detected: 2") == "Телефон обнаружен: 2"
    assert translator.translate_text("camera_read_failed: 123.45") == "camera_read_failed: 123.45"


def test_explicit_multiline_templates_still_match_without_swallowing_adjacent_lines():
    translator = i18n.TranslationManager({
        "setup": {"en": "Exam {name}\n\nReady", "ru": "Экзамен {name}\n\nГотово"},
        "ready": {"en": "Ready", "ru": "Готово"},
    }, "ru")
    assert translator.translate_text("Exam Math\n\nReady") == "Экзамен Math\n\nГотово"
    assert translator.translate_text("camera_read_failed\nReady") == "camera_read_failed\nГотово"


@pytest.mark.parametrize("widget_type", [i18n_widgets.QLabel, i18n_widgets.QPushButton,
    i18n_widgets.QCheckBox, i18n_widgets.QRadioButton])
def test_text_widgets_rerender_without_changing_source_or_selection(qt_app, translator, widget_type):
    widget = widget_type("Start exam")
    widget.setToolTip("Start exam")
    if hasattr(widget, "setChecked"):
        widget.setChecked(True)
    checked = widget.isChecked() if hasattr(widget, "isChecked") else None
    for locale, expected in [("ru", "Начать экзамен"), ("kk", "Емтиханды бастау"), ("en", "Start exam")]:
        translator.set_language(locale)
        assert widget.text() == expected
        assert widget.toolTip() == expected
        assert i18n_widgets.source_text(widget) == "Start exam"
        if checked is not None:
            assert widget.isChecked() == checked
    widget.setText("Answered 2 / 6")
    translator.set_language("ru")
    assert widget.text() == "Отвечено 2 / 6"
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    translator.set_language("kk")  # No callbacks into a deleted Qt object.


def test_cleared_labels_and_camera_images_stay_cleared_or_visible(qt_app, translator):
    label = i18n_widgets.QLabel("Start exam")
    label.clear()
    translator.set_language("ru")
    assert label.text() == ""
    assert label.source_text == ""
    image = QPixmap(16, 16)
    image.fill()
    label.setPixmap(image)
    cache_key = label.pixmap().cacheKey()
    translator.set_language("kk")
    assert label.pixmap().cacheKey() == cache_key
    label.setText("Start exam")
    assert label.text() == "Емтиханды бастау"


def test_group_and_progress_translations_preserve_values(qt_app, translator):
    group = i18n_widgets.QGroupBox("Start exam")
    progress = i18n_widgets.QProgressBar()
    progress.setValue(42)
    progress.setFormat("Answered 2 / 6")
    translator.set_language("ru")
    assert group.title() == "Начать экзамен"
    assert progress.format() == "Отвечено 2 / 6"
    assert progress.value() == 42
    assert group.source_title == "Start exam"


@pytest.mark.parametrize("locale", ["en", "ru", "kk"])
def test_ui_locale_configuration(tmp_path, locale):
    source = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    source = re.sub(r'^language\s*=.*$', f'language = "{locale}"', source, flags=re.MULTILINE)
    path = tmp_path / "config.toml"
    path.write_text(source, encoding="utf-8")
    config = load_config(path)
    assert config.ui.language == locale
    assert config.public_dict()["ui"] == {"language": locale}
    assert set(config.public_dict()["thresholds"]) == {item.value for item in config.thresholds}
    assert all(key.isascii() for key in config.public_dict()["thresholds"])
    assert EventType.PHONE_VISIBLE.value == "phone_visible"


def test_ui_default_and_bad_language(tmp_path):
    assert UiConfig().language == "en"
    source = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    source = re.sub(r"\[ui\]\n.*?(?=\n\[)", "", source, flags=re.DOTALL)
    path = tmp_path / "config.toml"
    path.write_text(source, encoding="utf-8")
    assert load_config(path).ui.language == "en"
    for bad in ("de", "EN", "", 5, None, ["ru"]):
        with pytest.raises(ValueError, match="ui.language"):
            UiConfig(language=bad)


def test_no_argument_test_configuration_is_native_and_keeps_asset_paths(isolated_default_config):
    config = load_config()
    assert config.external_url == ""
    assert not config.external_exam
    assert config.ui.language == "en"
    assert config.quiz_path.is_file()
    assert config.quiz_path.parent == DEFAULT_CONFIG.parent.parent / "assets"
    assert isolated_default_config != DEFAULT_CONFIG


def test_shipped_catalogues_have_all_locales_and_matching_placeholders():
    paths = list(Path(i18n.__file__).with_name("locales").glob("*.json"))
    assert paths, "Localized UI catalogues must be shipped with the application"
    entries = i18n._load_catalogues()
    assert entries
    formatter = Formatter()
    for key, translations in entries.items():
        assert set(translations) == {"en", "ru", "kk"}, key
        fields = None
        for locale, translation in translations.items():
            assert translation, (key, locale)
            current = {field for _literal, field, _spec, _conversion in formatter.parse(translation) if field is not None}
            if fields is None:
                fields = current
            assert current == fields, (key, locale, fields, current)
