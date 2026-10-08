from __future__ import annotations

import math
import os
import threading
from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal, QSignalBlocker
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog,
    QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLayout, QLineEdit, QMainWindow,
    QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..controller import AppController
from ..domain import EventType
from ..i18n import manager, set_language, translate_text, t
from .i18n_widgets import (QLabel, QPushButton, QCheckBox, QGroupBox,
                           QProgressBar, QRadioButton, source_text)
from ..security import HeartbeatWatchdog, PinVerifier
from .calibration import CalibrationWidget
from .audio_check import AudioCheckWidget
from .preview import CameraPreview
from .registration import RegistrationWidget
from .screen_target import ScreenTarget, position_metadata


STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 14px; color: #182b3a; }
QMainWindow, QStackedWidget { background: #edf2f6; }
QLabel { background: transparent; }
QLabel#title { font-size: 24px; font-weight: 700; }
QLabel#subtitle { color: #5c7081; }
QLabel#eyebrow { color: #167265; font-size: 12px; font-weight: 700; }
QLabel#timer { font-size: 32px; font-weight: 700; color: #155e55; }
QLabel#banner { background: #fff2ce; color: #71530b; padding: 10px; border-radius: 7px; }
QFrame#card, QGroupBox { background: white; border: 1px solid #d8e1e8; border-radius: 10px; }
QGroupBox { padding: 18px 12px 10px; margin-top: 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 4px; }
QLabel#preview { background: #162e3e; color: #d2e6ec; border-radius: 8px; padding: 22px; font-size: 16px; }
QPushButton { background: #fff; border: 1px solid #b9c9d4; border-radius: 6px; padding: 9px 16px; }
QPushButton:hover { background: #e6f2f0; border-color: #478b80; }
QPushButton#primary { background: #13776a; color: white; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #0d6257; }
QPushButton:disabled { background: #e9eef2; color: #8d9ba7; border-color: #dce4ea; }
QPushButton#primary:disabled { background: #e9eef2; color: #8d9ba7; border-color: #dce4ea; }
QRadioButton { padding: 13px; background: #f4f7fa; border: 1px solid #dce5eb; border-radius: 6px; }
QRadioButton:checked { background: #e5f3ef; border-color: #288c7c; }
QRadioButton:disabled { color: #8896a0; }
QCheckBox { font-weight: 400; padding: 4px 0; }
QTableWidget { background: white; border: 1px solid #d8e1e8; gridline-color: #edf1f4; border-radius: 5px; }
QHeaderView::section { background: #edf3f7; padding: 8px; border: none; font-weight: 600; }
QLineEdit { background: white; padding: 10px; border: 1px solid #b9c9d4; border-radius: 5px; }
QProgressBar { border: none; background: #e6edef; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #158171; border-radius: 3px; }
"""


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(14)
    return frame, layout


class PinDialog(QDialog):
    def __init__(self, verifier: PinVerifier, action: str, parent=None):
        super().__init__(parent)
        self.verifier = verifier
        self.setMinimumWidth(350)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(label(action, "title", True))
        layout.addWidget(label("Enter the proctor PIN to continue.", "subtitle"))
        self.pin_edit = QLineEdit()
        self.pin_edit.setObjectName("proctorPin")
        self.pin_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_edit.setMaxLength(64)
        self.pin_edit.setPlaceholderText("Proctor PIN")
        layout.addWidget(self.pin_edit)
        self.error_label = label("")
        self.error_label.setStyleSheet("color: #ab3434")
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._check)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        # Qt modal windows suppress shortcuts owned by the parent window.
        # Give this dialog the same local recovery path; this installs no OS hook.
        if parent is not None and hasattr(parent, "_emergency"):
            self.recovery_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Alt+Q"), self)
            self.recovery_shortcut.activated.connect(parent._emergency)
        self.pin_edit.setFocus()
        manager.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def retranslate_ui(self, *_):
        self.setWindowTitle(translate_text("Proctor authorization"))
        self.pin_edit.setPlaceholderText(translate_text("Proctor PIN"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("common.ok"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("common.cancel"))

    def _check(self) -> None:
        if self.verifier.verify(self.pin_edit.text()):
            self.accept()
        else:
            self.error_label.setText("Incorrect PIN. Try again.")
            self.pin_edit.clear()
            self.pin_edit.setFocus()


class MainWindow(QMainWindow):
    watchdog_expired = Signal()

    def __init__(self, controller: AppController, enable_watchdog: bool = True):
        super().__init__()
        self.controller = controller
        set_language(controller.config.ui.language)
        self.camera_mode = getattr(controller, "mode", "synthetic") == "camera"
        self.external_exam = bool(controller.config.external_url)
        self.browser = None
        self.question_index = 0
        self._diagnostic_reading = False
        self._diagnostic_question_index = None
        self._diagnostic_target_name = ""
        self._diagnostic_target_position = None
        self._diagnostic_region_geometry = None
        self._diagnostic_banner_limits = None
        self._guided_geometry = None
        self._guided_target_name = ""
        self.active_pin_dialog: PinDialog | None = None
        self._contained = False
        self._windowed_geometry = None
        self._restoring_window = False
        self._report_close_pending = False
        self._watchdog_stop = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        self.setWindowTitle("Local Proctoring · Camera Demo" if self.camera_mode else "Local Proctoring · Synthetic Demo")
        self.resize(1240, 900)
        self.setMinimumSize(1040, 760)
        self.setStyleSheet(STYLE)
        self.stack = QStackedWidget()
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        language_header = QHBoxLayout()
        language_header.setContentsMargins(28, 8, 28, 0)
        language_header.addStretch()
        language_header.addWidget(label("Language"))
        self.language_selector = QComboBox()
        self.language_selector.setObjectName("languageSelector")
        for name, code in (("EN", "en"), ("RU", "ru"), ("ҚАЗ", "kk")):
            self.language_selector.addItem(name, code)
        self.language_selector.setCurrentIndex(self.language_selector.findData(manager.language))
        self.language_selector.currentIndexChanged.connect(self._select_language)
        language_header.addWidget(self.language_selector)
        central_layout.addLayout(language_header)
        central_layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.registration_widget = None
        self.registration_page = None
        self.audio_check_widget = None
        if not controller.registration_complete or (controller.config.identity.selfie_verification_enabled
                                                    and not controller.identity_ready):
            self._build_registration()
        self._build_setup()
        self._build_exam()
        self._build_summary()
        self.preflight_label = label("", "banner", True)
        central_layout.insertWidget(1, self.preflight_label)
        self.optional_status_label = label("", "subtitle", True)
        self.optional_status_label.setStyleSheet("padding: 0 28px 6px 28px; color: #5c7081;")
        central_layout.insertWidget(2, self.optional_status_label)
        self.setup_page.setEnabled(controller.registration_complete)
        if self.registration_page is not None:
            self.stack.setCurrentWidget(self.registration_page)
            self.registration_widget.first_name.setFocus()
        self.screen_target = ScreenTarget(self.stack)
        if self.camera_mode:
            self.calibration_widget.diagnostic_workflow.target_metadata_provider = self._diagnostic_target_metadata
        self.shortcut = QShortcut(QKeySequence("Ctrl+Shift+Alt+Q"), self)
        self.shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut.activated.connect(self._emergency)
        self.watchdog = HeartbeatWatchdog(controller.protection, 5.0, controller.clock)
        self.watchdog_expired.connect(self._watchdog_recovery)
        # The real adapter has an independent process. This legacy watchdog is
        # only for safe mode, and must not compete with the helper's deadline.
        if enable_watchdog and not controller.protection.blocking_enabled:
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True,
                                                      name="protection-recovery")
            self._watchdog_thread.start()
        self.timer = QTimer(self)
        self.timer.setInterval(controller.config.synthetic_interval_ms)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        controller.protection.configure_window(int(self.winId()), os.getpid())
        self._refresh()
        manager.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def _select_language(self, index: int) -> None:
        code = self.language_selector.itemData(index)
        if code:
            set_language(code)

    def retranslate_ui(self, *_):
        """Render cached presentation text only; never advance calibration/timers."""
        with QSignalBlocker(self.language_selector):
            self.language_selector.setCurrentIndex(self.language_selector.findData(manager.language))
        self.controller.config = replace(self.controller.config,
                                         ui=replace(self.controller.config.ui, language=manager.language))
        self.setWindowTitle(translate_text("Local Proctoring · Camera Demo" if self.camera_mode else
                                          "Local Proctoring · Synthetic Demo"))
        self.language_selector.setAccessibleName(translate_text("Language"))
        self.language_selector.setToolTip(translate_text("Language"))
        self.timer_label.setAccessibleName(translate_text("Time remaining"))
        self.timer_label.setToolTip(translate_text("Time remaining"))
        self.event_table.setHorizontalHeaderLabels([translate_text(value) for value in
            ("Started (UTC)", "Review event", "State", "Duration", "Confidence")])
        # Translated headings and status words need more room than English.
        for column in (0, 2, 3, 4):
            self.event_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for row in range(self.event_table.rowCount()):
            for column in range(self.event_table.columnCount()):
                item = self.event_table.item(row, column)
                if item is not None:
                    original = item.data(Qt.ItemDataRole.UserRole)
                    if original is not None:
                        item.setText(translate_text(original))
                        item.setToolTip(translate_text(original))

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(.25):
            if self.watchdog.check():
                # check() releases first, independently of the Qt UI thread.
                self.watchdog_expired.emit()

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        self.stack.addWidget(page)
        return page, layout

    def _build_registration(self) -> None:
        self.registration_widget = RegistrationWidget(
            require_group=self.controller.config.registration.require_group,
            identity_enabled=self.controller.config.identity.selfie_verification_enabled)
        self.registration_widget.submitted.connect(self._submit_registration)
        self.registration_widget.identity_open_requested.connect(self._prepare_identity)
        self.registration_widget.identity_capture_requested.connect(self._capture_identity)
        self.registration_widget.layout().addWidget(label(self._data_description(), "subtitle", True))
        self.registration_page = self.registration_widget
        if self.controller.config.identity.selfie_verification_enabled:
            # The selfie preview adds vertical content. Honor the preview and
            # form minimum sizes, keeping controls reachable on laptop screens.
            self.registration_widget.layout().setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            self.registration_page = QScrollArea()
            self.registration_page.setWidgetResizable(True)
            self.registration_page.setFrameShape(QFrame.Shape.NoFrame)
            self.registration_page.setWidget(self.registration_widget)
        self.stack.addWidget(self.registration_page)

    def _prepare_identity(self, info: dict) -> None:
        try:
            self.controller.prepare_identity(info)
        except (ValueError, RuntimeError, OSError) as error:
            self.registration_widget.set_identity_state(ready=False, status=str(error))
            return
        self.registration_widget.identity_started()
        self._refresh_optional()

    def _capture_identity(self) -> None:
        try:
            self.controller.capture_identity_baseline()
        except (ValueError, RuntimeError, OSError) as error:
            self.registration_widget.set_identity_state(ready=False, status=str(error))
            return
        self._refresh_optional()

    def _submit_registration(self, info: dict[str, str]) -> None:
        if self.controller.config.identity.selfie_verification_enabled and not self.controller.identity_ready:
            self.registration_widget.show_submission_error("identity.required")
            return
        try:
            self.controller.register_candidate(info)
        except (ValueError, RuntimeError):
            self.registration_widget.show_submission_error()
            return
        self.registration_widget.setEnabled(False)
        self.setup_page.setEnabled(True)
        self.stack.setCurrentWidget(self.setup_page)
        self._refresh_optional()
        if self.camera_mode:
            self.open_camera_button.setFocus()
        else:
            self.start_button.setFocus()

    def _require_registration(self) -> bool:
        identity_required = (self.controller.config.identity.selfie_verification_enabled
                             and not self.controller.identity_ready)
        if self.controller.registration_complete and not identity_required:
            return True
        if self.registration_widget is not None:
            self.registration_widget.show_submission_error("identity.required" if identity_required else "registration.required")
            self.stack.setCurrentWidget(self.registration_page)
        return False

    def _build_setup(self) -> None:
        if self.camera_mode:
            self._build_camera_setup()
            return
        self.setup_page, layout = self._page()
        layout.addStretch()
        pane, content = card()
        content.addWidget(label("LOCAL PROCTORING / DEVELOPMENT DEMO", "eyebrow"))
        content.addWidget(label("A complete exam flow, ready to test.", "title"))
        content.addWidget(label("Stage 1–2 • Synthetic monitoring • Local evidence", "subtitle"))
        content.addWidget(label(
            "This build uses synthetic observations. No webcam is opened, no gaze calibration is performed, "
            "and Windows keyboard/window blocking is disabled.", "banner", True))
        content.addWidget(label(
            f"{self._exam_description()} · "
            f"{self.controller.config.duration_seconds / 60:g} minutes\n\n"
            "Exercise the event thresholds using the monitoring controls. Review warnings never pause the exam. "
            "Monitoring failure pauses the quiz and timer; prolonged interruptions require the proctor PIN.", wrap=True))
        content.addWidget(label(
            "Launch without --synthetic to use webcam monitoring and session calibration. "
            "Snapshots are configured but unavailable with synthetic observations.", "subtitle", True))
        if self.controller.config.audio.enabled:
            self.audio_check_widget = AudioCheckWidget(self.controller.audio, self.controller.config.audio)
            content.addWidget(self.audio_check_widget)
        self.start_button = QPushButton("Start demo exam")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start)
        content.addWidget(self.start_button)
        self.setup_error = label("", wrap=True)
        self.setup_error.setStyleSheet("color: #ab3434")
        content.addWidget(self.setup_error)
        layout.addWidget(pane)
        layout.addStretch()
        layout.addWidget(label(self._data_description(), "subtitle", True))
        if self.audio_check_widget is not None:
            layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            body = self.setup_page
            self.stack.removeWidget(body)
            self.setup_page = QScrollArea()
            self.setup_page.setWidgetResizable(True)
            self.setup_page.setFrameShape(QFrame.Shape.NoFrame)
            self.setup_page.setWidget(body)
            self.stack.insertWidget(0, self.setup_page)

    def _exam_description(self) -> str:
        return ("External web exam" if self.external_exam else
                f"{self.controller.quiz.total} multiple-choice questions")

    def _data_description(self) -> str:
        if self.controller.config.remote.enabled:
            description = (
                "Session records are saved locally. Candidate details, proctoring alerts and available event snapshots "
                "are also sent to configured proctor destinations.")
            if self.external_exam:
                description += "\nThe external exam website receives its own form submissions and network requests."
            return description
        return ("Proctoring data stays local. The external exam website receives its own form submissions and network requests."
                if self.external_exam else "All session data stays on this computer.")

    def _build_camera_setup(self) -> None:
        self.setup_page, layout = self._page()
        layout.addWidget(label("LOCAL PROCTORING / CAMERA DEMO", "eyebrow"))
        layout.addWidget(label("Prepare your camera and calibrate your gaze", "title"))
        protection_note = ("Windows protection will activate when the calibrated exam starts."
                           if self.controller.protection.blocking_enabled else "Windows protection is disabled in safe mode.")
        layout.addWidget(label(f"{self._data_description()} {protection_note}",
                               "banner", True))
        columns = QHBoxLayout()
        instructions, content = card()
        content.addWidget(label(
            f"{self._exam_description()} · "
            f"{self.controller.config.duration_seconds / 60:g} minutes", "eyebrow"))
        content.addWidget(label(
            "Open the camera, sit comfortably with your face and eyes visible, then collect four gaze directions. "
            "Keep the camera and your seating position fixed after calibration.", wrap=True))
        self.open_camera_button = QPushButton("Open camera")
        self.open_camera_button.clicked.connect(self._retry_camera)
        content.addWidget(self.open_camera_button)
        self.setup_health = label("Camera not started", "subtitle", True)
        content.addWidget(self.setup_health)
        self.calibration_widget = CalibrationWidget(
            self.controller.monitor.calibration, self.controller.config.vision.calibration_samples,
            self.controller.config.vision.result_stale_seconds,
            clock=self.controller.clock.monotonic,
            preparation_seconds=self.controller.config.vision.calibration_preparation_seconds,
            collection_seconds=self.controller.config.vision.calibration_collection_seconds,
            max_collection_seconds=self.controller.config.vision.calibration_max_collection_seconds,
            diagnostics_enabled=self.controller.config.vision.calibration_debug,
            event_thresholds=self.controller.config.thresholds,
            clearing_seconds=self.controller.config.clearing_seconds)
        self.calibration_widget.changed.connect(self._refresh_camera)
        self.calibration_widget.validation_active_changed.connect(self._diagnostic_validation_state)
        self.calibration_widget.validation_target_changed.connect(self._diagnostic_validation_target)
        self.calibration_widget.guided_active_changed.connect(self._guided_calibration_state)
        self.calibration_widget.guided_target_changed.connect(self._guided_calibration_target)
        content.addWidget(self.calibration_widget)
        content.addWidget(label(
            "Eye gaze is an approximate estimate from iris landmarks and this session's samples. Head pose is shown separately. "
            "Poor calibration must be retried before starting.", "subtitle", True))
        self.start_button = QPushButton("Start exam")
        self.start_button.setObjectName("primary")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._start)
        content.addWidget(self.start_button)
        self.setup_error = label("", wrap=True)
        self.setup_error.setStyleSheet("color: #ab3434")
        content.addWidget(self.setup_error)
        columns.addWidget(instructions, 1)
        camera, preview_layout = card()
        preview_layout.addWidget(label("CAMERA CHECK", "eyebrow"))
        self.setup_preview = CameraPreview()
        preview_layout.addWidget(self.setup_preview, 1)
        self.setup_metrics = label("Waiting for monitoring", "subtitle", True)
        preview_layout.addWidget(self.setup_metrics)
        if self.controller.config.audio.enabled:
            self.audio_check_widget = AudioCheckWidget(self.controller.audio, self.controller.config.audio)
            preview_layout.addWidget(self.audio_check_widget)
        columns.addWidget(camera, 1)
        layout.addLayout(columns, 1)
        layout.addWidget(label("Person = green · Phone = amber · Primary face = dotted blue", "subtitle"))
        # Positioning feedback and expanded diagnostics must remain reachable
        # on laptop screens; never squeeze their controls to zero height.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        body = self.setup_page
        self.stack.removeWidget(body)
        self.setup_page = QScrollArea()
        self.setup_page.setWidgetResizable(True)
        self.setup_page.setFrameShape(QFrame.Shape.NoFrame)
        self.setup_page.setWidget(body)
        self.stack.insertWidget(0, self.setup_page)

    def _build_exam(self) -> None:
        self.exam_page, layout = self._page()
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("LOCAL PROCTORING", "eyebrow"))
        titles.addWidget(label("Demo examination", "title"))
        header.addLayout(titles)
        header.addStretch()
        self.timer_label = label("10:00", "timer")
        header.addWidget(self.timer_label)
        self.pause_button = QPushButton("Proctor pause…")
        self.pause_button.clicked.connect(self._pause_or_resume)
        header.addWidget(self.pause_button)
        self.end_button = QPushButton("End session…")
        self.end_button.clicked.connect(self._end_with_pin)
        header.addWidget(self.end_button)
        layout.addLayout(header)
        self.session_banner = label("", "banner", True)
        layout.addWidget(self.session_banner)
        self.collection_controls = QWidget()
        collection_controls_layout = QHBoxLayout(self.collection_controls)
        collection_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.collection_pause = QPushButton("Pause calibration")
        self.collection_retry = QPushButton("Retry this target")
        self.collection_cancel = QPushButton("Cancel calibration")
        self.collection_pause.clicked.connect(self._pause_diagnostic_collection)
        self.collection_retry.clicked.connect(self._retry_diagnostic_collection)
        self.collection_cancel.clicked.connect(self._cancel_diagnostic_collection)
        for button in (self.collection_pause, self.collection_retry, self.collection_cancel):
            collection_controls_layout.addWidget(button)
        self.collection_controls.hide()
        layout.addWidget(self.collection_controls)
        columns = QHBoxLayout()
        columns.setSpacing(18)
        self.quiz_card, quiz_layout = card()
        self.question_count = label("", "eyebrow")
        quiz_layout.addWidget(self.question_count)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximum(self.controller.quiz.total)
        quiz_layout.addWidget(self.progress)
        self.question_label = label("", "title", True)
        quiz_layout.addWidget(self.question_label)
        self.options_host = QWidget()
        self.options_layout = QVBoxLayout(self.options_host)
        self.options_layout.setContentsMargins(0, 6, 0, 6)
        self.options_layout.setSpacing(10)
        quiz_layout.addWidget(self.options_host)
        self.options_group = QButtonGroup(self)
        self.options_group.idClicked.connect(self._answer)
        quiz_layout.addStretch()
        nav = QHBoxLayout()
        self.previous_button = QPushButton("← Previous")
        self.previous_button.clicked.connect(lambda: self._navigate(-1))
        self.next_button = QPushButton("Next →")
        self.next_button.clicked.connect(lambda: self._navigate(1))
        nav.addWidget(self.previous_button)
        nav.addStretch()
        nav.addWidget(self.next_button)
        quiz_layout.addLayout(nav)
        self.answers_label = label("", "subtitle")
        quiz_layout.addWidget(self.answers_label)
        # Keep the native quiz for its existing calibration reading targets.
        # No browser is even constructed in native mode, including headless CI.
        self.exam_content = QStackedWidget()
        self.exam_content.addWidget(self.quiz_card)
        if self.external_exam:
            from .browser import SecureBrowserWidget
            self.browser = SecureBrowserWidget(
                self.controller.config.external_url, self.controller.config.allowed_domains)
            self.exam_content.addWidget(self.browser)
        columns.addWidget(self.exam_content, 1)

        monitor_card, monitor_layout = card()
        monitor_layout.setSpacing(10)
        monitor_layout.addWidget(label("LIVE MONITORING" if self.camera_mode else "MONITORING / SYNTHETIC INPUT", "eyebrow"))
        if self.camera_mode:
            self.preview = CameraPreview()
            self.preview.setMinimumHeight(230)
        else:
            self.preview = label("No webcam connected\nSynthetic observations only", "preview", True)
            self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview.setMinimumHeight(90)
        monitor_layout.addWidget(self.preview)
        self.monitor_label = label("", wrap=True)
        monitor_layout.addWidget(self.monitor_label)
        self.protection_label = label("Protection: INACTIVE", "subtitle")
        monitor_layout.addWidget(self.protection_label)
        monitor_layout.addWidget(label(
            "No continuous video recording" if self.camera_mode else
            "No video or snapshots captured", "subtitle", True))
        if self.camera_mode:
            self.gaze_label = label("Gaze: UNKNOWN", wrap=True)
            self.metrics_label = label("", "subtitle", True)
            monitor_layout.addWidget(self.gaze_label)
            monitor_layout.addWidget(self.metrics_label)
            self.retry_camera_button = QPushButton("Retry camera / monitoring")
            self.retry_camera_button.clicked.connect(self._retry_camera)
            monitor_layout.addWidget(self.retry_camera_button)
            self.monitor_error = label("", wrap=True)
            self.monitor_error.setStyleSheet("color: #ab3434")
            monitor_layout.addWidget(self.monitor_error)
        self.synthetic_group = QGroupBox("Synthetic event controls")
        self.synthetic_group.setMinimumHeight(176)
        inputs = QGridLayout(self.synthetic_group)
        inputs.setVerticalSpacing(4)
        names = {
            EventType.PHONE_VISIBLE: "Phone visible", EventType.SECOND_PERSON: "Second person",
            EventType.PHONE_RAISED: "Phone raised", EventType.FACE_ABSENT: "Face absent",
            EventType.GAZE_DOWN: "Gaze down", EventType.GAZE_LEFT: "Gaze left", EventType.GAZE_RIGHT: "Gaze right",
        }
        self.condition_boxes = {}
        for i, (kind, name) in enumerate(names.items()):
            box = QCheckBox(f"{name} ({self.controller.config.thresholds[kind]:g}s)")
            box.setMinimumHeight(26)
            box.setObjectName(kind.value)
            box.toggled.connect(lambda checked, kind=kind: self.controller.monitor.set_condition(kind, checked))
            self.condition_boxes[kind] = box
            inputs.addWidget(box, i // 2, i % 2)
        monitor_layout.addWidget(self.synthetic_group)
        self.synthetic_group.setVisible(not self.camera_mode)
        faults = QHBoxLayout()
        self.failure_box = QCheckBox("Monitoring failure")
        self.failure_box.setObjectName("monitoringFailure")
        self.failure_box.toggled.connect(self._set_failure)
        faults.addWidget(self.failure_box)
        self.stall_box = QCheckBox("Stop new observations")
        self.stall_box.toggled.connect(self._set_stall)
        faults.addWidget(self.stall_box)
        self.failure_box.setVisible(not self.camera_mode)
        self.stall_box.setVisible(not self.camera_mode)
        monitor_layout.addLayout(faults)
        self.event_hint = label("", "subtitle", True)
        monitor_layout.addWidget(self.event_hint)
        columns.addWidget(monitor_card, 1)
        layout.addLayout(columns, 1)
        events_heading = QHBoxLayout()
        self.event_title = label("EVENT REVIEW · 0 events", "eyebrow")
        events_heading.addWidget(self.event_title)
        events_heading.addStretch()
        events_heading.addWidget(label("One row per sustained event · Detection quality" if self.camera_mode else
                                       "One row per sustained event · Synthetic confidence", "subtitle"))
        layout.addLayout(events_heading)
        self.event_table = QTableWidget(0, 5)
        self.event_table.setHorizontalHeaderLabels(["Started (UTC)", "Review event", "State", "Duration", "Confidence"])
        self.event_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.event_table.setColumnWidth(0, 120)
        self.event_table.setColumnWidth(2, 90)
        self.event_table.setColumnWidth(3, 90)
        self.event_table.setColumnWidth(4, 110)
        self.event_table.verticalHeader().hide()
        self.event_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.event_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.event_table.setMinimumHeight(145)
        self.event_table.setMaximumHeight(190)
        layout.addWidget(self.event_table)
        self.storage_label = label("", "subtitle", True)
        self.storage_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.storage_label)
        self._show_question()
        # Keep all controls reachable on smaller/lower-resolution demo screens.
        content = self.exam_page
        self.stack.removeWidget(content)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self.exam_page = scroll
        self.stack.addWidget(scroll)

    def _build_summary(self) -> None:
        self.summary_page, layout = self._page()
        layout.addStretch()
        pane, content = card()
        content.addWidget(label("SESSION COMPLETE", "eyebrow"))
        content.addWidget(label("Exam & monitoring summary", "title"))
        self.summary_text = label("", wrap=True)
        self.summary_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.addWidget(self.summary_text)
        self.summary_events = label("", wrap=True)
        content.addWidget(self.summary_events)
        self.summary_path = label("", "subtitle", True)
        self.summary_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.addWidget(self.summary_path)
        close = QPushButton("Close application")
        close.setObjectName("primary")
        close.clicked.connect(self.close)
        content.addWidget(close)
        layout.addWidget(pane)
        layout.addStretch()

    def _start(self) -> None:
        if not self._require_registration():
            return
        preflight = self.controller.preflight_status()
        if not preflight["ready"]:
            self.setup_error.setText(preflight["reason"])
            return
        if (self.camera_mode and self.calibration_widget.diagnostic_workflow.screen_region_enabled.isChecked()):
            self.setup_error.setText("Screen-region experiment cannot start an exam. Leave experimental mode to use normal calibration.")
            return
        if (self.camera_mode and self.calibration_widget.validation_active):
            self.setup_error.setText("Finish or cancel the diagnostic validation pass before starting an exam.")
            return
        if self.browser is not None and not self.browser.available:
            self.setup_error.setText(self.browser.unavailable_reason)
            return
        try:
            self.controller.start()
        except (OSError, ValueError, RuntimeError) as error:
            self.setup_error.setText(f"Could not start: {error}")
            return
        self.watchdog.heartbeat()
        if self.browser is not None:
            self.exam_content.setCurrentWidget(self.browser)
            try:
                self.browser.start_exam()
            except (OSError, ValueError, RuntimeError) as error:
                self.controller.end("browser_start_failed")
                self._refresh()
                self.summary_text.setText(source_text(self.summary_text) + f"\nBrowser error: {error}")
                return
        self.stack.setCurrentWidget(self.exam_page)
        self._refresh()

    def _guided_calibration_state(self, active: bool) -> None:
        if active:
            if self._guided_geometry is None:
                self._guided_geometry = (self.saveGeometry(), self.isMaximized())
                self.showMaximized()
            self.start_button.setEnabled(False)
        else:
            self._guided_calibration_target("")
            if self._guided_geometry is not None:
                geometry, was_maximized = self._guided_geometry
                self._guided_geometry = None
                if not was_maximized:
                    self.showNormal()
                    self.restoreGeometry(geometry)

    def _guided_calibration_target(self, target: str) -> None:
        self._guided_target_name = target
        # Only CENTER is on-screen in the four-target protocol. The other
        # directions refer to the physical screen edges, with no fake marker.
        point = self.stack.mapFromGlobal(self.screen().geometry().center()) if target == "CENTER" else None
        self.screen_target.set_point(point)

    def _pause_diagnostic_collection(self):
        self.calibration_widget.diagnostic_workflow.pause_collection()

    def _retry_diagnostic_collection(self):
        self.calibration_widget.diagnostic_workflow.retry_target()

    def _cancel_diagnostic_collection(self):
        self.calibration_widget.diagnostic_workflow.cancel_validation()

    def _diagnostic_validation_state(self, active: bool) -> None:
        if active:
            self.start_button.setEnabled(False)
            if self.calibration_widget.diagnostic_workflow.screen_region_active:
                self._diagnostic_region_geometry = (self.saveGeometry(), self.isMaximized())
                self._diagnostic_banner_limits = (self.session_banner.minimumHeight(), self.session_banner.maximumHeight())
                self.session_banner.setFixedHeight(112)
                self.showMaximized()
        else:
            self._diagnostic_validation_target("")
            if self._diagnostic_region_geometry is not None:
                geometry, was_maximized = self._diagnostic_region_geometry
                self._diagnostic_region_geometry = None
                if not was_maximized:
                    self.showNormal()
                    self.restoreGeometry(geometry)
            if self._diagnostic_banner_limits is not None:
                minimum, maximum = self._diagnostic_banner_limits
                self._diagnostic_banner_limits = None
                self.session_banner.setMinimumHeight(minimum)
                self.session_banner.setMaximumHeight(maximum)
            self.collection_controls.hide()

    def _diagnostic_validation_target(self, target: str) -> None:
        """Show actual quiz text at its exam position, without starting a session.

        The diagnostic collector still receives fresh face measurements while
        its setup page is hidden. No answer, timer, event or evidence method is
        called; all quiz controls remain disabled until a real session starts.
        """
        panel = self.calibration_widget.diagnostic_workflow
        is_region = bool(target and panel.screen_region_active)
        if target == "READING" or is_region:
            if (self.controller.session.started or self.controller.protection.blocking_enabled
                    or not self.controller.config.vision.calibration_debug):
                return
            if not self._diagnostic_reading:
                self._diagnostic_question_index = self.question_index
                self.question_index = min(1, self.controller.quiz.total - 1)
                self._show_question()
            self._diagnostic_reading = True
            self.exam_content.setCurrentWidget(self.quiz_card)
            self.collection_controls.setVisible(is_region)
            self._diagnostic_target_name = target
            self.quiz_card.setEnabled(False)
            self.end_button.setEnabled(False)
            self.session_banner.setText(
                "DEBUG / UNVALIDATED · Read the question and options naturally until the completion beep. "
                "No exam is running; these predictions do not create review events.")
            self.stack.setCurrentWidget(self.exam_page)
            self.exam_page.verticalScrollBar().setValue(0)
            QApplication.processEvents()
            self._position_diagnostic_target()
        elif self._diagnostic_reading:
            self._diagnostic_reading = False
            self._diagnostic_target_name = ""
            self._diagnostic_target_position = None
            self.screen_target.set_point(None)
            self.question_index = self._diagnostic_question_index or 0
            self._diagnostic_question_index = None
            self._show_question()
            self.end_button.setEnabled(True)
            self.stack.setCurrentWidget(self.setup_page)
            self.collection_controls.hide()

    def _diagnostic_layout_widgets(self):
        return {"quiz": self.question_label, "options": self.options_host,
                "controls": self.end_button, "monitor": self.preview}

    def _position_diagnostic_target(self):
        panel = self.calibration_widget.diagnostic_workflow
        spec = panel.current_target_spec if panel.screen_region_active else {}
        requested = spec.get("requested_position") or {}
        position = ((requested.get("x_normalized"), requested.get("y_normalized"))
                    if requested else spec.get("widget_anchor"))
        point = None
        if isinstance(position, (tuple, list)) and len(position) == 2:
            # Center is physically on the screen; boundary targets use the
            # actual visible client area, whose coordinates are exported.
            if tuple(position) == (.5, .5):
                point = self.stack.mapFromGlobal(self.screen().geometry().center())
            else:
                point = QPoint(round(position[0] * self.stack.width()),
                               round(position[1] * self.stack.height()))
        elif position in self._diagnostic_layout_widgets():
            target_widget = self._diagnostic_layout_widgets()[position]
            point = self.stack.mapFromGlobal(target_widget.mapToGlobal(target_widget.rect().center()))
        self._diagnostic_target_position = point
        self.screen_target.set_point(point)

    def _diagnostic_target_metadata(self):
        """Numerical target/layout provenance only; no screenshots are saved."""
        self._position_diagnostic_target()
        data = position_metadata(self.stack, self._diagnostic_target_position)
        data["visible_layout_regions"] = {
            name: position_metadata(widget, widget.rect().center())
            for name, widget in self._diagnostic_layout_widgets().items()
        }
        if self._diagnostic_target_position is not None:
            desktop = self.stack.mapToGlobal(self._diagnostic_target_position)
            data["target_visible_inside_client"] = (self.stack.rect().contains(self._diagnostic_target_position)
                                                     and self.screen().geometry().contains(desktop))
        else:
            data["physical_target"] = "operator-known off-screen target or natural reading/challenge; no inferred coordinate"
        return data

    def _open_camera(self) -> None:
        if not self._require_registration():
            return
        self.setup_error.clear()
        self.monitor_error.clear()
        try:
            self.controller.prepare_monitoring()
            self.open_camera_button.setText("Retry camera / monitoring")
        except (OSError, ValueError, RuntimeError) as error:
            self.setup_error.setText(f"Could not open monitoring: {error}")
            self.monitor_error.setText(f"Could not restart monitoring: {error}")
        self._refresh_camera()

    def _retry_camera(self) -> None:
        if not self._require_registration():
            return
        # The controller observes the outage before a restarted worker can
        # publish results, preserving the existing recovery/timer behavior.
        self.controller.monitor.stop()
        self.controller.step()
        if not self.controller.session.started:
            self.calibration_widget.reset()
        self._open_camera()

    def _refresh_camera(self) -> None:
        if not self.camera_mode:
            return
        monitor = self.controller.monitor
        now = self.controller.clock.monotonic()
        health = monitor.health(now)
        result = monitor.latest_result
        metrics = monitor.metrics
        if not isinstance(metrics, dict):
            metrics = vars(metrics)
        def metric(name):
            value = metrics.get(name, 0)
            return float(value) if isinstance(value, (int, float)) else 0.0
        measurement = (
            f"Capture {metric('capture_fps'):.1f} FPS · Monitoring {metric('monitoring_fps'):.1f} FPS\n"
            f"YOLO {metric('yolo_latency_ms'):.0f} ms · Face landmarks {metric('face_latency_ms'):.0f} ms"
        )
        provider = metrics.get("provider")
        if provider:
            measurement += f" · {provider}"
        if metrics.get("input_size"):
            measurement += f"\nYOLO input: {metrics['input_size']}"
        size = metrics.get("source_frame_size")
        if size is not None:
            requested = self.controller.config.vision
            measurement += (f"\nSource: {size[0]}×{size[1]} px "
                            f"(requested {requested.capture_width}×{requested.capture_height})")
        self.setup_metrics.setText(measurement)
        self.metrics_label.setText(measurement)
        status = "Monitoring healthy" if health.healthy else f"Monitoring unavailable · {health.reason}"
        self.setup_health.setText(status)
        self.monitor_label.setText(status)
        self.monitor_label.setStyleSheet("color: #13776a" if health.healthy else "color: #ab3434")
        if health.healthy:
            self.monitor_error.clear()
        frame = monitor.latest_frame
        current_preview = self.preview if (self.controller.session.started or self._diagnostic_reading) else self.setup_preview
        if not self.controller.session.started:
            calibration_result = getattr(monitor, "latest_calibration_result", result)
            self.calibration_widget.feed_result(calibration_result, now, health.healthy)
            current_preview.set_alignment(self.calibration_widget.alignment_status)
            self.start_button.setEnabled(self.controller.registration_complete and health.healthy and monitor.calibration.ready
                                         and self.controller.preflight_status()["ready"]
                                         and (not self.controller.config.identity.selfie_verification_enabled or self.controller.identity_ready)
                                         and not self.calibration_widget.guided_active
                                         and not self.calibration_widget.validation_active
                                         and not self.calibration_widget.diagnostic_workflow.screen_region_enabled.isChecked())
            if self._guided_target_name:
                self._guided_calibration_target(self._guided_target_name)
        else:
            self.setup_preview.set_alignment(None)
            self.preview.set_alignment(None)
            self.calibration_widget.eye_closeups.feed_result(None, now, False)
        current_preview.set_frame(frame, result, health.healthy, health.reason)
        gaze = "UNKNOWN" if result is None or not health.healthy else result.gaze_direction.value
        text = f"Eye-gaze estimate: {gaze}"
        workflow = self.calibration_widget.diagnostic_workflow
        if workflow.screen_region_active and workflow.validation.screen_region_phase == "validation":
            prediction = workflow.validation.latest_region_prediction
            if prediction is not None and health.healthy and 0 <= now - prediction["timestamp"] < workflow.max_age:
                gaze = prediction["region_predicted_label"]
                text = (f"DEBUG / UNVALIDATED · Region: {prediction['region_predicted_label']}"
                        f" · Point baseline: {prediction['predicted_label']}"
                        f"\n{prediction['region_prediction_reason']}")
            else:
                text = "DEBUG / UNVALIDATED · Region: UNKNOWN · waiting for a fresh validation measurement"
        if result is not None and health.healthy:
            text += f" · People: {result.person_count} · Face: {'present' if result.face_present else 'absent'}"
            if gaze == "UNKNOWN" and result.face_present:
                eyes = getattr(getattr(result, "face", None), "diagnostics", None)
                reason = getattr(eyes, "reason", "")
                text += f"\nGaze availability reduced · {reason or 'no reliable calibrated eye-gaze estimate'}"
            if result.head_pose is not None:
                pose = result.head_pose
                text += f"\nHead pose · yaw {pose.yaw:.0f}° · pitch {pose.pitch:.0f}° · roll {pose.roll:.0f}°"
            if result.head_down:
                text += "\nHead-down posture detected · contributes to DOWN review; eye gaze is separate"
        self.gaze_label.setText(text)
        self.retry_camera_button.setVisible(not health.healthy and not self.controller.session.ended)
        if self._diagnostic_reading and workflow.screen_region_active:
            self.session_banner.setText(source_text(workflow.validation_status))
            self.collection_pause.setText(source_text(workflow.pause_button))
            self.collection_pause.setEnabled(workflow.pause_button.isEnabled())
            self.collection_retry.setEnabled(workflow.retry_target_button.isEnabled())

    def _show_question(self) -> None:
        quiz = self.controller.quiz
        question = quiz.questions[self.question_index]
        self.question_count.setText(f"QUESTION {self.question_index + 1:02} / {quiz.total:02}")
        self.question_label.setText(question.prompt)
        for button in self.options_group.buttons():
            self.options_group.removeButton(button)
            self.options_layout.removeWidget(button)
            button.deleteLater()
        for i, option in enumerate(question.options):
            button = QRadioButton(f"{chr(65 + i)}.  {option}")
            button.setObjectName(f"answer_{i}")
            self.options_group.addButton(button, i)
            self.options_layout.addWidget(button)
            button.setChecked(quiz.answers.get(self.question_index) == i)
        self.previous_button.setEnabled(self.question_index > 0)
        self.next_button.setEnabled(self.question_index < quiz.total - 1)

    def _navigate(self, delta: int) -> None:
        self.question_index = max(0, min(self.controller.quiz.total - 1, self.question_index + delta))
        self._show_question()

    def _answer(self, option: int) -> None:
        if not self.controller.answer(self.question_index, option):
            self._show_question()
        self._refresh()

    def _authorize(self, title: str) -> str | None:
        dialog = PinDialog(self.controller.pin, title, self)
        self.active_pin_dialog = dialog
        result = dialog.exec()
        self.active_pin_dialog = None
        pin = dialog.pin_edit.text() if result == QDialog.DialogCode.Accepted else None
        dialog.pin_edit.clear()
        dialog.deleteLater()
        return pin

    def _pause_or_resume(self) -> None:
        session = self.controller.session
        needs_resume = "proctor" in session.pause_reasons or session.recovery_pin_required
        pin = self._authorize("Resume exam" if needs_resume else "Pause exam")
        if pin is not None:
            if needs_resume:
                self.controller.resume(pin)
            else:
                self.controller.pause(pin)
        self._refresh()

    def _end_with_pin(self) -> None:
        pin = self._authorize("End session")
        if pin is not None:
            self.controller.end_with_pin(pin)
        self._refresh()

    def _set_failure(self, checked: bool) -> None:
        self.controller.monitor.available = not checked
        self._tick()

    def _set_stall(self, checked: bool) -> None:
        self.controller.monitor.stalled = checked
        self._tick()

    def _tick(self) -> None:
        # Only UI progress feeds the independent helper. CV/background threads
        # must not keep restrictions alive after the Qt event loop stalls.
        self.controller.protection.heartbeat()
        self.watchdog.heartbeat()
        self.controller.poll_optional_workers()
        self.controller.step()
        self._refresh()

    def _refresh_optional(self) -> None:
        if self.audio_check_widget is not None:
            started = self.controller.session.started
            self.audio_check_widget.set_exam_active(started)
            if (not started and self.controller.registration_complete
                    and self.stack.currentWidget() is self.setup_page):
                self.controller.prepare_audio_check()
        status = self.controller.preflight_status()
        self.preflight_label.setText(status.get("reason", ""))
        self.preflight_label.setVisible(bool(status.get("reason")))
        if not self.camera_mode and not self.controller.session.started:
            self.start_button.setEnabled(self.controller.registration_complete and status["ready"]
                                         and (not self.controller.config.identity.selfie_verification_enabled
                                              or self.controller.identity_ready))
        if self.registration_widget is not None and self.controller.config.identity.selfie_verification_enabled:
            self.registration_widget.set_identity_state(
                ready=self.controller.identity_ready, status=self.controller.identity_status,
                can_capture=self.controller.identity_can_capture)
            monitor = self.controller.monitor
            result = getattr(monitor, "latest_result", None)
            healthy = self.camera_mode and monitor.health(self.controller.clock.monotonic()).healthy
            # Same result/frame as the worker; no second webcam or image recording.
            frame = getattr(result, "frame", None) if result is not None else None
            self.registration_widget.set_identity_preview(frame, result, healthy)
        messages = []
        if (self.controller.config.identity.selfie_verification_enabled and self.controller.session.started
                and not self.controller.session.ended):
            messages.append(self.controller.identity_status)
        if (self.controller.config.vision.accessories.earphone_detection_enabled
                and self.controller.session.started and not self.controller.session.ended):
            result = getattr(self.controller.monitor, "latest_result", None)
            message = getattr(result, "earphone_status", "") if result is not None else ""
            if message:
                messages.append(message)
        if self.controller.config.audio.enabled and self.controller.session.started:
            message = getattr(self.controller, "audio_status", "")
            if message:
                messages.append(message)
        if self.controller.config.reporting.generate_pdf_report:
            report = getattr(self.controller, "report_status", "disabled")
            key = "report.closing" if self._report_close_pending else f"report.{report}"
            if report != "disabled":
                messages.append(t(key))
        self.optional_status_label.setText("\n".join(messages))
        self.optional_status_label.setVisible(bool(messages))

    def _sync_protection_window(self) -> None:
        protected = (self.controller.protection.blocking_enabled
                     and self.controller.protection.armed
                     and self.controller.session.started and not self.controller.session.ended)
        if protected and not self._contained:
            self._windowed_geometry = self.saveGeometry()
            self._contained = True
            self.showFullScreen()
        elif not protected and self._contained:
            self._contained = False
            self.showNormal()
            if self._windowed_geometry is not None:
                self.restoreGeometry(self._windowed_geometry)

    def _restore_contained_window(self) -> None:
        if not self._contained or not self.controller.protection.armed:
            return
        self._restoring_window = True
        try:
            self.showFullScreen()
            self.raise_()
            if self.active_pin_dialog is not None:
                self.active_pin_dialog.raise_()
                self.active_pin_dialog.activateWindow()
            else:
                self.activateWindow()
        finally:
            self._restoring_window = False

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (event.type() == QEvent.Type.WindowStateChange and getattr(self, "_contained", False)
                and not self._restoring_window and (self.isMinimized() or not self.isFullScreen())):
            self.controller.record_security_event(
                "WINDOW_MINIMIZE_ATTEMPT" if self.isMinimized() else "WINDOW_RESTORE_ATTEMPT",
                "Attempt to leave the fullscreen exam window",
                {"action": "minimize" if self.isMinimized() else "restore"})
            QTimer.singleShot(0, self._restore_contained_window)

    def _refresh(self) -> None:
        controller, session = self.controller, self.controller.session
        self._refresh_optional()
        self._sync_protection_window()
        self.protection_label.setText(f"Protection: {controller.protection.status}")
        self.protection_label.setStyleSheet(
            "color: #13776a" if controller.protection.status == "ACTIVE" else
            "color: #ab3434" if controller.protection.status == "RECOVERY" else "color: #5c7081")
        remaining = math.ceil(session.remaining_seconds)
        self.timer_label.setText(f"{remaining // 60:02}:{remaining % 60:02}")
        self.progress.setValue(controller.quiz.answered_count)
        self.answers_label.setText(f"{controller.quiz.answered_count} of {controller.quiz.total} questions answered · Answers saved in memory")
        self.quiz_card.setEnabled(session.running)
        if self.browser is not None:
            self.browser.setEnabled(session.running)
            if session.ended:
                self.browser.stop()
                self.browser.shutdown()
        reasons = session.pause_reasons
        if "monitoring" in reasons:
            message = "PAUSED · Monitoring unavailable. The exam timer is stopped."
        elif "proctor" in reasons:
            message = "PAUSED · Proctor pause. A valid PIN is required to resume."
        elif session.recovery_pin_required:
            message = "PAUSED · Monitoring recovered after a prolonged interruption. Proctor PIN required."
        else:
            message = "EXAM RUNNING · Review warnings do not pause the timer."
            if not controller.protection.blocking_enabled:
                message += " Windows blocking is disabled."
        if session.recovery_pin_required and "monitoring" in reasons:
            message += " Restore monitoring, then enter the proctor PIN."
        if self._diagnostic_reading:
            panel = self.calibration_widget.diagnostic_workflow
            message = (source_text(panel.validation_status) if panel.screen_region_active else
                       "DEBUG / UNVALIDATED · Read the question and options naturally until the completion beep. "
                       "No exam is running; these predictions do not create review events.")
        self.session_banner.setText(message)
        self.pause_button.setText("Resume with PIN…" if reasons & {"proctor", "recovery_pin"} else "Proctor pause…")
        needs_resume = bool(reasons & {"proctor", "recovery_pin"})
        self.pause_button.setEnabled(session.started and not session.ended
                                     and (not needs_resume or session.monitoring_healthy))
        if self.camera_mode:
            self._refresh_camera()
        else:
            self.monitor_label.setText("Healthy synthetic monitoring" if session.monitoring_healthy else "Monitoring unavailable — exam paused")
            self.monitor_label.setStyleSheet("color: #13776a" if session.monitoring_healthy else "color: #ab3434")
        events = controller.review_events
        active = [e for e in events if e["state"] in ("active", "clearing")]
        if self.camera_mode:
            self.event_hint.setText("\n".join(e["label"] for e in active[:3]) or
                                    "No active review events. Gaze uses this session's calibration.")
        else:
            self.preview.setText("\n".join(e["label"] for e in active[:3]) or "No webcam connected\nSynthetic observations only")
            self.event_hint.setText(
                f"{len(active)} active review event(s). Clearing hysteresis: {controller.config.clearing_seconds:g}s. "
                "Gaze controls simulate derived classifications; no landmark model is running.")
        self.event_title.setText(f"EVENT REVIEW · {len(events)} event(s)")
        self.event_table.setRowCount(len(events))
        for row, event in enumerate(events):
            confidence = event.get("confidence")
            security_event = event.get("record_kind") == "security_event"
            values = [event["start_timestamp"][11:19], event["label"],
                      "Recorded" if security_event else event["state"].capitalize(),
                      "—" if security_event else f'{event["duration_seconds"]:.2f}s', "N/A" if confidence is None else
                      f"{confidence:.0%}" + ("" if self.camera_mode else " (mock)")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(translate_text(value))
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setToolTip(translate_text(str(value)))
                if event["state"] != "closed":
                    item.setBackground(QColor("#fff6de"))
                self.event_table.setItem(row, column, item)
        if controller.storage_error:
            self.storage_label.setText(f"Evidence write error: {controller.storage_error}")
            self.storage_label.setStyleSheet("color: #ab3434")
        elif controller.store:
            self.storage_label.setText(f"Local evidence: {controller.store.path}")
        if session.ended and controller.summary is not None:
            if self.active_pin_dialog:
                self.active_pin_dialog.reject()
            summary = controller.summary
            recovery_text = ("Monitoring stopped. Protection released. Normal Windows interaction is restored."
                             if summary["blocking_enabled"] else
                             "Monitoring stopped. Protection interface released. No Windows restrictions were installed.")
            result_text = ("External web exam · Submission and score are managed by the exam website.\n"
                           if self.external_exam else
                           f"Score: {summary['score']} / {summary['total_questions']}\n"
                           f"Answered: {summary['answered']} questions   •   ")
            self.summary_text.setText(
                result_text + f"Active exam time: {summary['elapsed_seconds']:.1f}s\n"
                f"Review events: {summary['event_count']}   •   End reason: {summary['end_reason']}\n\n"
                f"{recovery_text}")
            self.summary_events.setText("\n".join(
                f"{next(event['label'] for event in summary['events'] if event['event_type'] == kind)}: {count}"
                for kind, count in summary["event_counts"].items()
            ) or "No review events recorded.")
            path_text = f"Saved locally: {controller.store.path}\nsummary.json · events.jsonl · config.json"
            if controller.storage_error:
                path_text = f"Evidence save error: {controller.storage_error}\nCheck files in {controller.store.path}"
            if controller.report_status == "complete":
                path_text += "\n" + controller.config.reporting.report_filename
            if self.camera_mode:
                path_text += "\nCamera session · No continuous video recorded."
            else:
                path_text += "\nSynthetic session: no images or video were captured."
            self.summary_path.setText(path_text)
            self.stack.setCurrentWidget(self.summary_page)

    def _emergency(self) -> None:
        if not self.controller.session.started and self.controller.audio is not None:
            # Setup now owns a microphone resource before any exam exists.
            # Release it as well; ordinary setup refresh never restarts stopped input.
            self.controller.audio.stop()
        if self.controller.session.started and not self.controller.session.ended:
            self.controller.emergency_end()
            self._refresh()
        elif self.camera_mode:
            self.controller.protection.release("emergency_shortcut")
            self.controller.monitor.stop()
            self.calibration_widget.reset()
            self.setup_error.setText("Emergency recovery: camera monitoring stopped. Reopen the camera to continue.")
            self._refresh_camera()

    def _watchdog_recovery(self) -> None:
        if self.controller.session.started and not self.controller.session.ended:
            self.controller.emergency_end("heartbeat_timeout")
            self._refresh()

    def closeEvent(self, event) -> None:
        if self.controller.session.started and not self.controller.session.ended:
            if self._contained:
                self.controller.record_security_event("WINDOW_CLOSE_ATTEMPT", "Exam window close requested",
                                                      {"action": "close"})
            if self.active_pin_dialog is not None:
                self.active_pin_dialog.raise_()
                self.active_pin_dialog.activateWindow()
                event.ignore()
                return
            self._end_with_pin()
            if not self.controller.session.ended:
                event.ignore()
                return
        if getattr(self.controller, "report_status", "disabled") == "running":
            # Qt font/layout objects used by the PDF worker require the GUI
            # application to remain alive. Restrictions are released first;
            # this timer keeps the UI responsive until the report completes.
            self.controller.protection.release("report_finishing")
            self.controller.monitor.stop()
            event.ignore()
            if not self._report_close_pending:
                self._report_close_pending = True
                QTimer.singleShot(100, self._retry_report_close)
            self._refresh_optional()
            return
        self.shutdown_ui()
        event.accept()

    def _retry_report_close(self):
        self._report_close_pending = False
        self.controller.poll_optional_workers()
        self.close()

    def shutdown_ui(self) -> None:
        """Idempotent cleanup also used when Qt exits without closeEvent."""
        self.timer.stop()
        if self.audio_check_widget is not None:
            self.audio_check_widget.timer.stop()
        self._watchdog_stop.set()
        # Release immediately, before even the safe-mode watchdog thread join.
        self.controller.protection.release("window_closed")
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=1)
        self.controller.monitor.stop()
        self.controller.protection.close()
        if self.browser is not None:
            self.browser.shutdown()
        self.controller.close_optional_workers()
        self.controller.close_remote(timeout=2.0)

