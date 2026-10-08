"""Language changes affect presentation, never ongoing exam/event state."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from proctoring.clock import FakeClock
from proctoring.config import UiConfig, load_config
from proctoring.controller import AppController
from proctoring.domain import EVENT_LABELS, EventType
from proctoring.i18n import manager, set_language, translate_text
from proctoring.ui.window import MainWindow, PinDialog


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app, tmp_path):
    clock = FakeClock()
    config = replace(load_config(), external_url="", sessions_dir=tmp_path,
                     ui=UiConfig(language="en"))
    controller = AppController(config, clock)
    win = MainWindow(controller, enable_watchdog=False)
    win.timer.stop()
    win.show()
    qt_app.processEvents()
    yield clock, win
    if controller.session.started and not controller.session.ended:
        controller.emergency_end("test_cleanup")
    win.close()
    win.deleteLater()
    qt_app.processEvents()


def choose(win, code):
    win.language_selector.setCurrentIndex(win.language_selector.findData(code))


def test_switcher_updates_open_widgets_and_preserves_answer_timer_and_events(window, qt_app):
    clock, win = window
    win._start()
    win.options_group.button(1).click()
    win.controller.monitor.set_condition(EventType.PHONE_RAISED, True)
    clock.advance(.1)
    win._tick()
    clock.advance(win.controller.config.thresholds[EventType.PHONE_RAISED])
    win._tick()
    before = win.controller.review_events
    remaining = win.controller.session.remaining_seconds
    quiz_button = win.options_group.button(1)
    for code, end_text, phone_word in (
        ("ru", "Завершить сеанс…", "Телефон"),
        ("kk", "Сеансты аяқтау…", "Телефон"),
        ("en", "End session…", "Phone"),
    ):
        choose(win, code)
        qt_app.processEvents()
        assert manager.language == code
        assert win.controller.config.ui.language == code
        assert win.end_button.text() == end_text
        assert phone_word in win.event_table.item(0, 1).text()
        assert win.controller.review_events == before
        assert win.controller.session.remaining_seconds == remaining
        assert win.controller.session.running
        assert win.options_group.button(1) is quiz_button
        assert quiz_button.isChecked()
        assert win.controller.quiz.answers == {0: 1}


def test_existing_pin_dialog_translates_without_clearing_pin(window):
    _, win = window
    dialog = PinDialog(win.controller.pin, "End session", win)
    dialog.pin_edit.setText("2468")
    set_language("kk")
    assert dialog.windowTitle() == "Прокторды растау"
    assert dialog.pin_edit.placeholderText() == "Проктордың PIN коды"
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "Болдырмау"
    assert dialog.pin_edit.text() == "2468"
    dialog.deleteLater()


def test_localized_event_ui_never_translates_json_evidence(window):
    clock, win = window
    choose(win, "kk")
    win._start()
    win.controller.monitor.set_condition(EventType.GAZE_DOWN, True)
    clock.advance(.1)
    win._tick()
    # Keep observations fresh throughout the configured duration. A single
    # three-second clock jump correctly represents monitoring unavailability.
    until = clock.monotonic() + win.controller.config.thresholds[EventType.GAZE_DOWN]
    while clock.monotonic() < until:
        clock.advance(min(.25, until - clock.monotonic()))
        win._tick()
    choose(win, "ru")
    win._emergency()
    directory = win.controller.store.path
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["events"][0]["event_type"] == "gaze_down"
    assert summary["events"][0]["label"] == EVENT_LABELS[EventType.GAZE_DOWN]
    assert summary["end_reason"] == "emergency_shortcut"
    assert any(event.get("event_type") == "gaze_down" for event in events)
    assert "Длительный взгляд вниз" in win.summary_events.text()
    original = (directory / "summary.json").read_bytes()
    choose(win, "kk")
    assert (directory / "summary.json").read_bytes() == original
    assert "Ұзақ уақыт төмен қарау" in win.summary_events.text()


@pytest.mark.parametrize("code,title", [("ru", "Локальный прокторинг"), ("kk", "Жергілікті прокторинг")])
def test_configured_language_applies_at_window_construction(qt_app, tmp_path, code, title):
    config = replace(load_config(), external_url="", sessions_dir=tmp_path, ui=UiConfig(code))
    win = MainWindow(AppController(config, FakeClock()), enable_watchdog=False)
    win.timer.stop()
    try:
        assert win.language_selector.currentData() == code
        assert title in win.windowTitle()
        assert win.start_button.text() == translate_text("Start demo exam")
    finally:
        win.close()
        win.deleteLater()
        qt_app.processEvents()
