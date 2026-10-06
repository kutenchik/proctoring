"""Protection lifecycle integration with fake helpers; no Windows hooks installed."""
import json
import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from proctoring.clock import FakeClock
from proctoring.config import load_config
from proctoring.controller import AppController
from proctoring.domain import EventType, Observation
from proctoring.ui.window import MainWindow
from proctoring.vision.calibration import Calibration
from proctoring.vision.types import GazeDirection, HealthStatus


class FakeProtection:
    blocking_enabled = True

    def __init__(self):
        self.armed = False
        self.status = "INACTIVE"
        self.release_reason = None
        self.arm_count = 0
        self.heartbeat_count = 0
        self.pending = []
        self.window = None
        self.closed = False

    def configure_window(self, hwnd, pid):
        self.window = hwnd, pid

    def arm(self):
        self.arm_count += 1
        self.armed = True
        self.status = "ACTIVE"
        self.release_reason = None

    def release(self, reason):
        if self.armed or self.release_reason is None:
            self.release_reason = reason
        self.armed = False
        if self.status != "RECOVERY":
            self.status = "INACTIVE"

    def heartbeat(self):
        self.heartbeat_count += 1

    def drain_events(self):
        events, self.pending = self.pending, []
        return events

    def close(self):
        self.release("closed")
        self.closed = True

    def recover(self, reason="heartbeat_timeout"):
        self.release(reason)
        self.status = "RECOVERY"
        self.pending.append({"event_type": "PROTECTION_RECOVERY",
                             "description": "Independent protection recovery",
                             "details": {"reason": reason}})


class CameraMonitor:
    def __init__(self, config, clock):
        self.clock = clock
        self.calibration = Calibration(config)
        self.available = True
        self.stopped = False
        self.latest_result = self.latest_frame = self.delivered_result = None
        self.metrics = {}
        self.conditions = {}
        features = ((.5, .5, 0., 0.), (.2, .5, -.25, 0.),
                    (.8, .5, .25, 0.), (.5, .8, 0., .3))
        timestamp = 0.0
        for direction, vector in zip((GazeDirection.CENTER, GazeDirection.LEFT,
                                      GazeDirection.RIGHT, GazeDirection.DOWN), features):
            for _ in range(config.calibration_samples):
                timestamp += .1
                self.calibration.add_sample(direction, vector, timestamp, 1.)
        assert self.calibration.fit()[0]

    def health(self, now):
        return HealthStatus(self.available and not self.stopped, "Test camera disconnected")

    def sample(self, now):
        return Observation(now, self.conditions, source="camera") if self.health(now).healthy else None

    def start(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


@pytest.fixture
def protected_controller(tmp_path):
    config = replace(load_config(), sessions_dir=tmp_path, snapshots_enabled=False)
    clock = FakeClock()
    protection = FakeProtection()
    monitor = CameraMonitor(config.vision, clock)
    app = AppController(config, clock, mode="camera", monitor=monitor, protection=protection)
    yield clock, app, protection
    if app.session.started and not app.session.ended:
        app.end("test_cleanup")


def test_enabled_protection_requires_camera_mode(tmp_path):
    protection = FakeProtection()
    app = AppController(replace(load_config(), sessions_dir=tmp_path), FakeClock(), protection=protection)
    with pytest.raises(RuntimeError, match="healthy camera"):
        app.start()
    assert protection.arm_count == 0
    assert app.store is None


@pytest.mark.parametrize("missing", ["health", "calibration"])
def test_protection_is_not_armed_until_health_and_calibration_succeed(protected_controller, missing):
    _, app, protection = protected_controller
    if missing == "health":
        app.monitor.available = False
    else:
        app.monitor.calibration.reset()
    with pytest.raises(RuntimeError):
        app.start()
    assert not protection.armed
    assert protection.arm_count == 0
    assert not app.session.started


@pytest.mark.parametrize("outage,needs_pin", [(14.9, False), (15.0, True)])
def test_protection_survives_monitoring_pause_and_existing_recovery_boundary(protected_controller, outage, needs_pin):
    clock, app, protection = protected_controller
    app.start()
    clock.advance(.5)
    app.step()
    app.monitor.available = False
    app.step()
    remaining = app.session.remaining_seconds
    assert protection.armed and not app.session.running
    clock.advance(outage)
    app.monitor.available = True
    app.step()
    assert protection.armed
    assert app.session.remaining_seconds == remaining
    assert app.session.recovery_pin_required is needs_pin
    if needs_pin:
        assert not app.resume("0000")
        assert app.resume("2468")
    assert app.session.running
    assert protection.arm_count == 1


def test_review_warning_and_proctor_pause_keep_protection_active(protected_controller):
    clock, app, protection = protected_controller
    app.start()
    app.monitor.conditions = {EventType.PHONE_VISIBLE: .9}
    clock.advance(.1)
    app.step()
    clock.advance(1)
    app.step()
    assert len(app.events.events) == 1
    assert app.session.running and protection.armed
    assert app.pause("2468")
    clock.advance(1)
    app.step()
    assert protection.armed and not app.session.running
    assert app.resume("2468")
    assert protection.arm_count == 1


@pytest.mark.parametrize("finish", ["pin", "normal", "emergency", "expiry", "shutdown"])
def test_release_precedes_monitor_shutdown_and_evidence_finalization(protected_controller, monkeypatch, finish):
    clock, app, protection = protected_controller
    app.start()
    original_stop, original_finalize = app.monitor.stop, app.store.finalize
    calls = []

    def stop():
        assert not protection.armed
        calls.append("stop")
        original_stop()

    def finalize(summary):
        assert not protection.armed
        calls.append("finalize")
        original_finalize(summary)

    monkeypatch.setattr(app.monitor, "stop", stop)
    monkeypatch.setattr(app.store, "finalize", finalize)
    if finish == "pin":
        assert not app.end_with_pin("0000")
        assert protection.armed
        assert app.end_with_pin("2468")
    elif finish == "emergency":
        app.emergency_end()
    elif finish == "expiry":
        for _ in range(int(app.config.duration_seconds)):
            clock.advance(1)
            app.step()
    else:
        app.end("application_exit" if finish == "shutdown" else "completed")
    assert calls and calls[-1] == "finalize"
    assert app.summary is not None and app.session.ended


def test_security_event_is_immediate_deduplicated_and_saved_without_pausing(protected_controller):
    clock, app, protection = protected_controller
    app.start()
    event = {"event_id": "key-1", "event_type": "BLOCKED_COPY", "description": "Copy shortcut blocked",
             "details": {"action": "Ctrl+C"}}
    protection.pending.extend([event, event.copy()])
    clock.advance(.2)
    app.step()
    assert app.session.running
    assert app.session.elapsed_seconds == pytest.approx(.2)
    assert not app.events.events
    assert len(app.review_events) == 1
    saved = [json.loads(line) for line in (app.store.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    security = [record for record in saved if record.get("record_kind") == "security_event"]
    assert len(security) == 1
    assert security[0]["session_id"] == app.store.path.name
    assert security[0]["timestamp"]
    assert security[0]["details"]["action"] == "Ctrl+C"
    app.end_with_pin("2468")
    assert app.summary["event_counts"] == {"BLOCKED_COPY": 1}
    assert app.summary["security_events"] == security
    assert "2468" not in (app.store.path / "config.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("pause", [False, True])
def test_helper_recovery_ends_session_before_cv_and_never_rearms(protected_controller, monkeypatch, pause):
    _, app, protection = protected_controller
    app.start()
    if pause:
        app.pause("2468")
    protection.recover()
    monkeypatch.setattr(app.monitor, "health", lambda now: pytest.fail("CV was consulted during independent recovery"))
    app.step()
    assert app.session.ended and not protection.armed
    assert app.session.end_reason == "heartbeat_timeout"
    assert app.summary["event_counts"]["PROTECTION_RECOVERY"] == 1
    app.step()
    assert protection.arm_count == 1


def test_only_ui_ticks_send_main_application_heartbeats(protected_controller):
    clock, app, protection = protected_controller
    app.start()
    clock.advance(.1)
    app.step()
    assert protection.heartbeat_count == 0


def test_helper_emergency_event_does_not_add_duplicate_fallback_record(protected_controller):
    _, app, protection = protected_controller
    app.start()
    protection.release("emergency_shortcut")
    protection.status = "RECOVERY"
    protection.pending.append({"event_type": "EMERGENCY_RELEASE",
                               "description": "Emergency shortcut released protection",
                               "details": {"reason": "emergency_shortcut"}})
    app.step()
    assert app.session.end_reason == "emergency_shortcut"
    assert app.summary["event_counts"] == {"EMERGENCY_RELEASE": 1}
    assert len(app.summary["security_events"]) == 1


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def protected_window(protected_controller, qt_app):
    clock, app, protection = protected_controller
    window = MainWindow(app, enable_watchdog=False)
    window.timer.stop()
    window.show()
    qt_app.processEvents()
    yield clock, window, protection
    if app.session.started and not app.session.ended:
        app.emergency_end("test_cleanup")
    window.close()
    qt_app.processEvents()


def test_fullscreen_status_and_ui_heartbeat_then_recovery_restores_window(protected_window, qt_app):
    _, window, protection = protected_window
    assert protection.window == (int(window.winId()), os.getpid())
    assert window.protection_label.text() == "Protection: INACTIVE"
    window._start()
    assert window.isFullScreen()
    assert window.protection_label.text() == "Protection: ACTIVE"
    window._tick()
    assert protection.heartbeat_count == 1
    protection.recover()
    window._tick()
    qt_app.processEvents()
    assert not window.isFullScreen()
    assert window.protection_label.text() == "Protection: RECOVERY"
    assert window.stack.currentWidget() is window.summary_page
    assert "Independent protection recovery" in window.summary_events.text()


def test_security_events_appear_in_shared_table(protected_window):
    _, window, protection = protected_window
    window._start()
    protection.pending.append({"event_type": "BLOCKED_ALT_TAB", "description": "Application switch blocked"})
    window._tick()
    assert window.event_table.rowCount() == 1
    assert window.event_table.item(0, 1).text() == "Application switch blocked"
    assert window.event_table.item(0, 2).text() == "Recorded"
    assert window.controller.session.running


def test_minimize_is_restored_and_close_requires_pin(protected_window, qt_app):
    _, window, protection = protected_window
    window._start()
    window.showMinimized()
    qt_app.processEvents()
    assert window.isFullScreen() and not window.isMinimized()
    assert window.controller.security_events[-1]["event_type"] == "WINDOW_MINIMIZE_ATTEMPT"
    QTimer.singleShot(0, lambda: window.active_pin_dialog.reject())
    window.close()
    assert protection.armed and window.controller.session.running
    assert window.controller.security_events[-1]["event_type"] == "WINDOW_CLOSE_ATTEMPT"


@pytest.mark.parametrize("context", ["quiz", "pin", "monitoring_pause", "violation"])
def test_local_emergency_in_all_ui_contexts(protected_window, qt_app, context):
    _, window, protection = protected_window
    window._start()
    if context == "monitoring_pause":
        window.controller.monitor.available = False
        window._tick()
    elif context == "violation":
        protection.pending.append({"event_type": "BLOCKED_PASTE", "description": "Paste blocked"})
        window._tick()

    def emergency(target):
        target.activateWindow()
        target.setFocus()
        qt_app.processEvents()
        QTest.keyClick(target, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier)
        qt_app.processEvents()

    if context == "pin":
        def in_dialog():
            dialog = window.active_pin_dialog
            QTimer.singleShot(500, dialog.reject)
            emergency(dialog)
        QTimer.singleShot(0, in_dialog)
        window._end_with_pin()
    else:
        emergency(window)
    assert window.controller.session.end_reason == "emergency_shortcut"
    assert not protection.armed and not window.isFullScreen()
    assert window.controller.summary["event_counts"]["PROTECTION_RECOVERY"] == 1
