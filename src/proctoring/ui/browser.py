"""Optional embedded exam browser; importing this module does not start Chromium.

The guard restricts document/frame navigation, not an LMS's CSS, scripts or other
subresources. Each exam gets an off-the-record profile. QtWebEngine is loaded
only when an external exam widget is constructed; native quiz installations do
not need it. Headless tests replace ``_load_webengine`` with Qt widget doubles.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QVBoxLayout, QWidget,
)
from .i18n_widgets import QLabel, QProgressBar, QPushButton

from ..browser_policy import NavigationPolicy


NAVIGATION_BLOCKED = "Navigation outside exam domain is blocked"


def _secure_page_class(page_base):
    """Create the QWebEnginePage subclass after the optional import succeeds."""
    class SecureBrowserPage(page_base):
        def __init__(self, profile, policy, blocked, parent=None, accepted=None):
            super().__init__(profile, parent)
            self.policy = policy
            self._blocked = blocked
            self._accepted = accepted

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            # Apply the same rule to redirects, forms and child-frame documents.
            # PrettyDecoded inserts literal spaces from valid %20 path/query
            # data. Keep URL encoding intact at the parser boundary.
            if self.policy.allows(url.toString(QUrl.ComponentFormattingOption.FullyEncoded)):
                if is_main_frame and self._accepted is not None:
                    self._accepted()
                return True
            self._blocked(NAVIGATION_BLOCKED)
            return False

        def createWindow(self, window_type):
            self._blocked("Opening additional browser windows is blocked")
            return None

    return SecureBrowserPage


@dataclass(frozen=True)
class _WebEngineTypes:
    view: Any
    page: Any
    profile: Any
    settings: Any


def _load_webengine() -> _WebEngineTypes:
    # Never import WebEngine at module scope: the native quiz remains available
    # with PySide6-Essentials and CI can inject test doubles without Chromium.
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    return _WebEngineTypes(QWebEngineView, QWebEnginePage, QWebEngineProfile, QWebEngineSettings)


class SecureBrowserWidget(QWidget):
    """An exam surface that stays unloaded until ``start_exam`` is called."""

    LOAD_TIMEOUT_MS = 30_000

    def __init__(self, url: str, allowed_domains: Sequence[str] = (), parent=None):
        super().__init__(parent)
        self.policy = NavigationPolicy(url, allowed_domains)
        self.available = False
        self.unavailable_reason = ""
        self.view = None
        self.page = None
        self.profile = None
        self._started = False
        self._stopped = False
        self._shutdown = False
        self._navigation_blocked = False
        self._timed_out = False
        self._app = QApplication.instance()
        self._load_timeout = QTimer(self)
        self._load_timeout.setSingleShot(True)
        self._load_timeout.timeout.connect(self._on_timeout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.status_label = QLabel("Exam page will load when the session starts.")
        self.status_label.setWordWrap(True)
        toolbar.addWidget(self.status_label, 1)
        self.reload_button = QPushButton("Reload")
        self.reload_button.setEnabled(False)
        self.reload_button.clicked.connect(self._reload)
        toolbar.addWidget(self.reload_button)
        layout.addLayout(toolbar)
        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 100)
        self.loading_progress.setTextVisible(False)
        self.loading_progress.hide()
        layout.addWidget(self.loading_progress)

        try:
            engine = _load_webengine()
        except (ImportError, OSError) as exc:
            self.unavailable_reason = (
                "Embedded browser unavailable. Install the project's browser extra "
                '(python -m pip install -e ".[browser]") in this virtual environment. '
                f"{type(exc).__name__}: {exc}"
            )
            self.status_label.setText(self.unavailable_reason)
            return

        # A profile without a storage name is off the record: cookies and cache
        # are not persisted as a reusable university account browser profile.
        self.profile = engine.profile(self)
        self.profile.downloadRequested.connect(self._cancel_download)
        self.view = engine.view(self)
        self.page = _secure_page_class(engine.page)(
            self.profile, self.policy, self._blocked, self.view,
            accepted=self._navigation_accepted,
        )
        self.view.setPage(self.page)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        settings = self.page.settings()
        settings.setAttribute(engine.settings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(engine.settings.WebAttribute.FullScreenSupportEnabled, False)
        settings.setAttribute(engine.settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(engine.settings.WebAttribute.LocalContentCanAccessFileUrls, False)
        settings.setUnknownUrlSchemePolicy(
            engine.settings.UnknownUrlSchemePolicy.DisallowUnknownUrlSchemes,
        )
        self.view.loadStarted.connect(self._on_load_started)
        self.view.loadProgress.connect(self.loading_progress.setValue)
        self.view.loadFinished.connect(self._on_load_finished)
        self.page.renderProcessTerminated.connect(self._on_renderer_terminated)
        if hasattr(self.page, "permissionRequested"):
            self.page.permissionRequested.connect(self._deny_permission)
        else:  # Qt 6.7 compatibility; replaced by permissionRequested in Qt 6.8.
            self.page.featurePermissionRequested.connect(
                lambda origin, feature: self.page.setFeaturePermission(
                    origin, feature, engine.page.PermissionPolicy.PermissionDeniedByUser,
                ),
            )
        self.page.desktopMediaRequested.connect(self._deny_screen_capture)
        self.view.setEnabled(False)
        self.view.setMinimumHeight(360)
        layout.addWidget(self.view, 1)
        # Chromium creates its focus proxy lazily. Filtering QApplication events
        # and checking ancestry also covers renderer children created later.
        if self._app is not None:
            self._app.installEventFilter(self)
        self.available = True

    def start_exam(self) -> None:
        if not self.available:
            raise RuntimeError(self.unavailable_reason)
        if self._stopped or self._shutdown:
            raise RuntimeError("This browser session has already ended.")
        if self._started:
            return
        self._started = True
        self.view.setEnabled(True)
        self.reload_button.setEnabled(True)
        self.view.load(QUrl(self.policy.external_url))

    def _reload(self) -> None:
        if not self._started or self._stopped or self._shutdown or not self.isEnabled():
            return
        self._navigation_blocked = False
        self._timed_out = False
        current_url = self.view.url().toString(QUrl.ComponentFormattingOption.FullyEncoded)
        if self.policy.allows(current_url):
            self.view.reload()
        else:
            self.view.load(QUrl(self.policy.external_url))

    def _on_load_started(self) -> None:
        # Chromium can emit this AFTER acceptNavigationRequest rejects a URL.
        # Only an accepted main-frame navigation or explicit reload clears that
        # rejection; a delayed generic loading signal must retain its warning.
        if self._stopped or self._navigation_blocked:
            return
        self._timed_out = False
        self.status_label.setText("Loading exam page…")
        self.loading_progress.setValue(0)
        self.loading_progress.show()
        self._load_timeout.start(self.LOAD_TIMEOUT_MS)

    def _navigation_accepted(self) -> None:
        if self._stopped:
            return
        self._navigation_blocked = False
        self._on_load_started()

    def _on_load_finished(self, success: bool) -> None:
        self._load_timeout.stop()
        self.loading_progress.hide()
        if self._stopped or self._navigation_blocked or self._timed_out:
            return
        self.status_label.setText(
            "Exam page loaded." if success else
            "Exam page could not load. Check the network connection, then select Reload."
        )

    def _on_timeout(self) -> None:
        if self._stopped:
            return
        self._timed_out = True
        self.view.stop()
        self.loading_progress.hide()
        self.status_label.setText(
            "Exam page loading timed out. Check the network connection, then select Reload."
        )

    def _blocked(self, message: str) -> None:
        if self._stopped:
            return
        self._navigation_blocked = True
        self._load_timeout.stop()
        self.loading_progress.hide()
        self.status_label.setText(message)

    def _cancel_download(self, download) -> None:
        download.cancel()
        self._blocked("Downloading files from the exam browser is blocked")

    def _deny_permission(self, permission) -> None:
        # The proctoring pipeline owns the webcam. Do not grant web content
        # camera/microphone (or other device) access or create a data bridge.
        permission.deny()

    def _deny_screen_capture(self, request) -> None:
        request.cancel()

    def _on_renderer_terminated(self, status, exit_code) -> None:
        if self._stopped:
            return
        self._load_timeout.stop()
        self.loading_progress.hide()
        self.status_label.setText("Exam page stopped unexpectedly. Select Reload to try again.")

    def eventFilter(self, watched, event):
        inside_browser = (
            isinstance(watched, QWidget)
            and self.view is not None
            and (watched is self.view or self.view.isAncestorOf(watched))
        )
        if not inside_browser or self._shutdown:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.ContextMenu:
            event.accept()
            return True
        if event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            modifiers = event.modifiers()
            developer_shortcut = event.key() == Qt.Key.Key_F12 or (
                event.key() == Qt.Key.Key_I
                and bool(modifiers & Qt.KeyboardModifier.ControlModifier)
                and bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            )
            if developer_shortcut:
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def stop(self) -> None:
        """End interaction/loading without altering monitoring or exam timing."""
        if self._stopped:
            return
        self._stopped = True
        self._load_timeout.stop()
        self.loading_progress.hide()
        self.reload_button.setEnabled(False)
        if self.view is not None:
            self.view.stop()
            self.view.setEnabled(False)
        self.status_label.setText("Exam browser session ended.")

    def shutdown(self) -> None:
        """Release Chromium pages before their profile, including after app.exec."""
        if self._shutdown:
            return
        self.stop()
        self._shutdown = True
        if self._app is not None:
            self._app.removeEventFilter(self)
        # deleteLater alone is insufficient when the main event loop has already
        # ended. The page is a child of the view, and must die before the profile.
        from shiboken6 import delete, isValid
        if self.view is not None and isValid(self.view):
            delete(self.view)
        self.view = None
        self.page = None
        if self.profile is not None and isValid(self.profile):
            delete(self.profile)
        self.profile = None
