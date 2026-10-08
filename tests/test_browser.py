"""Browser contracts tested with real Qt widgets but no Chromium initialization."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QContextMenuEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from proctoring.ui import browser


class FakeSettings:
    WebAttribute = SimpleNamespace(
        JavascriptCanOpenWindows="popups", FullScreenSupportEnabled="fullscreen",
        LocalContentCanAccessRemoteUrls="local_remote", LocalContentCanAccessFileUrls="local_file",
    )
    UnknownUrlSchemePolicy = SimpleNamespace(DisallowUnknownUrlSchemes="disallow")

    def __init__(self):
        self.attributes = {}
        self.scheme_policy = None

    def setAttribute(self, attribute, enabled):
        self.attributes[attribute] = enabled

    def setUnknownUrlSchemePolicy(self, policy):
        self.scheme_policy = policy


class FakeProfile(QObject):
    downloadRequested = Signal(object)


class FakePage(QObject):
    renderProcessTerminated = Signal(object, int)
    permissionRequested = Signal(object)
    desktopMediaRequested = Signal(object)

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self._settings = FakeSettings()

    def settings(self):
        return self._settings


class FakeView(QWidget):
    loadStarted = Signal()
    loadProgress = Signal(int)
    loadFinished = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loads = []
        self.reload_count = 0
        self.stop_count = 0
        self._url = QUrl()

    def setPage(self, page):
        self.page = page

    def load(self, url):
        self.loads.append(url.toString())
        self._url = url
        self.loadStarted.emit()

    def url(self):
        return self._url

    def reload(self):
        self.reload_count += 1
        self.loadStarted.emit()

    def stop(self):
        self.stop_count += 1
        self.loadFinished.emit(False)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browser_widget(qt_app, monkeypatch):
    monkeypatch.setattr(browser, "_load_webengine", lambda: browser._WebEngineTypes(
        FakeView, FakePage, FakeProfile, FakeSettings,
    ))
    widget = browser.SecureBrowserWidget("https://exam.university.test/quiz")
    widget.show()
    qt_app.processEvents()
    yield widget
    widget.shutdown()
    widget.close()


def test_does_not_load_before_exam_and_start_is_idempotent(browser_widget):
    widget = browser_widget
    assert widget.available
    assert widget.view.loads == []
    assert not widget.reload_button.isEnabled()
    widget._reload()
    assert widget.view.loads == []
    widget.start_exam()
    widget.start_exam()
    assert widget.view.loads == ["https://exam.university.test/quiz"]
    assert widget.reload_button.isEnabled()
    assert widget._load_timeout.isActive()
    widget.view.loadFinished.emit(True)
    assert widget.status_label.text() == "Exam page loaded."
    assert not widget._load_timeout.isActive()


@pytest.mark.parametrize("main_frame", [True, False])
@pytest.mark.parametrize("destination,allowed", [
    ("https://exam.university.test/quiz/2?attempt=1", True),
    ("https://exam.university.test/quiz%20one?answer=hello%20world#part%201", True),
    ("https://exam.university.test/quiz?next=https%3A%2F%2Fgoogle.com%2F#question-2", True),
    ("https://google.com/", False),
    ("https://chatgpt.com/", False),
    ("https://exam.university.test.attacker.test/", False),
    ("file:///C:/exam.html", False),
    ("mailto:student@university.test", False),
])
def test_page_navigation_checks_main_and_child_frames(browser_widget, main_frame, destination, allowed):
    assert browser_widget.page.acceptNavigationRequest(QUrl(destination), None, main_frame) is allowed
    if not allowed:
        browser_widget.view.loadFinished.emit(False)
        assert browser_widget.status_label.text() == browser.NAVIGATION_BLOCKED


def test_popups_context_menus_and_page_capabilities_disabled(browser_widget):
    widget = browser_widget
    assert widget.page.createWindow(None) is None
    assert "additional browser windows" in widget.status_label.text()
    assert widget.view.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu
    assert widget.page.settings().attributes == {
        "popups": False, "fullscreen": False, "local_remote": False, "local_file": False,
    }
    assert widget.page.settings().scheme_policy == "disallow"


def test_rejection_survives_late_loading_signal_until_next_allowed_navigation(browser_widget):
    widget = browser_widget
    widget.start_exam()
    widget.view.loadFinished.emit(True)
    assert not widget.page.acceptNavigationRequest(QUrl("https://google.com/"), None, True)
    # Actual Chromium ordering: rejection callback may precede loadStarted.
    widget.view.loadStarted.emit()
    widget.view.loadFinished.emit(False)
    assert widget.status_label.text() == browser.NAVIGATION_BLOCKED
    assert not widget._load_timeout.isActive()
    assert widget.loading_progress.isHidden()
    # An unrelated allowed child-frame load must not clear the warning.
    assert widget.page.acceptNavigationRequest(QUrl("https://exam.university.test/frame"), None, False)
    assert widget.status_label.text() == browser.NAVIGATION_BLOCKED
    # The next real allowed main-frame navigation resets the rejection even if
    # its generic loadStarted happened before acceptNavigationRequest.
    widget.view.loadStarted.emit()
    assert widget.page.acceptNavigationRequest(QUrl("https://exam.university.test/next"), None, True)
    assert widget.status_label.text() == "Loading exam page…"
    assert widget._load_timeout.isActive()
    widget.view.loadFinished.emit(True)
    assert widget.status_label.text() == "Exam page loaded."


def test_explicit_reload_clears_rejection_and_reports_real_network_failure(browser_widget):
    widget = browser_widget
    widget.start_exam()
    assert not widget.page.acceptNavigationRequest(QUrl("https://google.com/"), None, True)
    widget._reload()
    assert widget.status_label.text() == "Loading exam page…"
    widget.view.loadFinished.emit(False)
    assert "could not load" in widget.status_label.text()


@pytest.mark.parametrize("event_type", [QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress])
@pytest.mark.parametrize("key,modifiers,blocked", [
    (Qt.Key.Key_F12, Qt.KeyboardModifier.NoModifier, True),
    (Qt.Key.Key_I, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, True),
    (Qt.Key.Key_I, Qt.KeyboardModifier.NoModifier, False),
    (Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
     | Qt.KeyboardModifier.AltModifier, False),
])
def test_scoped_filter_covers_late_renderer_child_and_preserves_emergency(
    browser_widget, event_type, key, modifiers, blocked,
):
    renderer = QWidget(browser_widget.view)
    event = QKeyEvent(event_type, key, modifiers)
    assert browser_widget.eventFilter(renderer, event) is blocked
    # The browser never swallows shortcuts in proctor dialogs or other widgets.
    unrelated = QWidget()
    assert not browser_widget.eventFilter(unrelated, event)
    unrelated.close()


def test_renderer_context_menu_event_blocked(browser_widget):
    renderer = QWidget(browser_widget.view)
    position = renderer.rect().center()
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, position, renderer.mapToGlobal(position))
    assert browser_widget.eventFilter(renderer, event)


def test_failed_page_can_reload_and_timeout_is_visible(browser_widget):
    widget = browser_widget
    widget.start_exam()
    widget.view.loadFinished.emit(False)
    assert "could not load" in widget.status_label.text()
    widget._reload()
    assert widget.view.reload_count == 1
    widget._on_timeout()
    assert widget.view.stop_count == 1
    assert "timed out" in widget.status_label.text()
    widget.view.loadFinished.emit(False)
    assert "timed out" in widget.status_label.text()
    widget._reload()
    widget.view.loadFinished.emit(True)
    assert widget.status_label.text() == "Exam page loaded."


def test_reload_is_disabled_during_exam_pause(browser_widget):
    widget = browser_widget
    widget.start_exam()
    widget.setEnabled(False)
    widget._reload()
    assert widget.view.reload_count == 0
    widget.setEnabled(True)
    widget._reload()
    assert widget.view.reload_count == 1


def test_reload_retains_encoded_path_query_and_fragment(browser_widget):
    widget = browser_widget
    widget.start_exam()
    url = QUrl("https://exam.university.test/quiz%20two?answer=hello%20world#part%201")
    widget.view._url = url
    # QUrl's default formatting decodes spaces; the guard uses FullyEncoded.
    assert " " in url.toString()
    widget._reload()
    assert widget.view.reload_count == 1
    assert widget.view.loads == ["https://exam.university.test/quiz"]


def test_download_and_webcam_microphone_screen_requests_are_denied(browser_widget):
    calls = []
    download = SimpleNamespace(cancel=lambda: calls.append("download_cancelled"))
    permission = SimpleNamespace(deny=lambda: calls.append("permission_denied"))
    screen = SimpleNamespace(cancel=lambda: calls.append("screen_cancelled"))
    browser_widget.profile.downloadRequested.emit(download)
    browser_widget.page.permissionRequested.emit(permission)
    browser_widget.page.desktopMediaRequested.emit(screen)
    assert calls == ["download_cancelled", "permission_denied", "screen_cancelled"]


def test_renderer_failure_reported_with_reload(browser_widget):
    browser_widget.start_exam()
    browser_widget.page.renderProcessTerminated.emit("crashed", 1)
    assert "stopped unexpectedly" in browser_widget.status_label.text()
    assert browser_widget.reload_button.isEnabled()


def test_stop_and_shutdown_are_idempotent_and_late_signals_do_not_reenable(browser_widget):
    widget = browser_widget
    widget.start_exam()
    view, page, profile = widget.view, widget.page, widget.profile
    widget.stop()
    widget.stop()
    assert view.stop_count == 1
    view.loadStarted.emit()
    view.loadFinished.emit(True)
    page.renderProcessTerminated.emit("crashed", 1)
    assert widget.status_label.text() == "Exam browser session ended."
    assert not widget.reload_button.isEnabled()
    assert not view.isEnabled()
    assert not widget._load_timeout.isActive()
    with pytest.raises(RuntimeError, match="already ended"):
        widget.start_exam()
    widget.shutdown()
    widget.shutdown()
    assert not isValid(view)
    assert not isValid(page)
    assert not isValid(profile)


def test_missing_webengine_is_actionable_and_never_silently_starts(qt_app, monkeypatch):
    def unavailable():
        raise ModuleNotFoundError("No module named 'PySide6.QtWebEngineWidgets'")
    monkeypatch.setattr(browser, "_load_webengine", unavailable)
    widget = browser.SecureBrowserWidget("https://exam.university.test/quiz")
    assert not widget.available
    assert "browser extra" in widget.status_label.text()
    assert "QtWebEngineWidgets" in widget.unavailable_reason
    with pytest.raises(RuntimeError, match="Embedded browser unavailable"):
        widget.start_exam()
    widget.shutdown()
    widget.close()
