"""Candidate entry before camera setup; no network, camera, or session start."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..i18n import manager, t, translate_text
from ..registration import CandidateInfo
from .preview import CameraPreview


class RegistrationWidget(QWidget):
    submitted = Signal(dict)
    identity_open_requested = Signal(dict)
    identity_capture_requested = Signal()

    def __init__(self, require_group: bool = True, parent: QWidget | None = None,
                 *, identity_enabled: bool = False):
        super().__init__(parent)
        self.require_group = require_group
        self.identity_enabled = identity_enabled
        self._identity_ready = not identity_enabled
        self._identity_can_capture = False
        self._identity_started = False
        self._identity_message = "Open the camera and capture a reference face before calibration."
        self._error_key = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addStretch()
        pane = QFrame()
        pane.setObjectName("card")
        pane.setMaximumWidth(680)
        pane.setMinimumWidth(600)
        content = QVBoxLayout(pane)
        content.setContentsMargins(28, 26, 28, 26)
        content.setSpacing(18)
        self.eyebrow = QLabel()
        self.eyebrow.setObjectName("eyebrow")
        self.title = QLabel()
        self.title.setObjectName("title")
        self.title.setWordWrap(True)
        self.description = QLabel()
        self.description.setObjectName("subtitle")
        self.description.setWordWrap(True)
        for label in (self.eyebrow, self.title, self.description):
            label.setTextFormat(Qt.TextFormat.PlainText)
            content.addWidget(label)
        form = QFormLayout()
        form.setVerticalSpacing(14)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.first_name = QLineEdit()
        self.last_name = QLineEdit()
        self.group_id = QLineEdit()
        self.first_name_label = QLabel()
        self.last_name_label = QLabel()
        self.group_id_label = QLabel()
        for field, label, object_name, maximum in (
            (self.first_name, self.first_name_label, "candidateFirstName", 100),
            (self.last_name, self.last_name_label, "candidateLastName", 100),
            (self.group_id, self.group_id_label, "candidateGroupId", 128),
        ):
            field.setObjectName(object_name)
            field.setMaxLength(maximum)
            field.textChanged.connect(self._validate)
            field.returnPressed.connect(self._submit)
            label.setBuddy(field)
            form.addRow(label, field)
        content.addLayout(form)
        self.identity_box = QWidget()
        identity_layout = QVBoxLayout(self.identity_box)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(8)
        self.identity_note = QLabel()
        self.identity_note.setWordWrap(True)
        self.identity_note.setTextFormat(Qt.TextFormat.PlainText)
        identity_layout.addWidget(self.identity_note)
        self.identity_preview = CameraPreview()
        self.identity_preview.setFixedHeight(180)
        identity_layout.addWidget(self.identity_preview)
        self.identity_status_label = QLabel()
        self.identity_status_label.setWordWrap(True)
        self.identity_status_label.setMinimumHeight(40)
        self.identity_status_label.setTextFormat(Qt.TextFormat.PlainText)
        identity_layout.addWidget(self.identity_status_label)
        self.identity_open_button = QPushButton()
        self.identity_open_button.clicked.connect(self._open_identity)
        identity_layout.addWidget(self.identity_open_button)
        self.identity_capture_button = QPushButton()
        self.identity_capture_button.setEnabled(False)
        self.identity_capture_button.clicked.connect(self.identity_capture_requested)
        identity_layout.addWidget(self.identity_capture_button)
        self.identity_box.setMinimumHeight(380)
        self.identity_box.setVisible(identity_enabled)
        content.addWidget(self.identity_box)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setStyleSheet("color: #ab3434")
        content.addWidget(self.error_label)
        self.continue_button = QPushButton()
        self.continue_button.setObjectName("primary")
        self.continue_button.clicked.connect(self._submit)
        content.addWidget(self.continue_button)
        layout.addWidget(pane, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        manager.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self._validate()

    def candidate_info(self) -> dict[str, str]:
        """Validate using the same model as the session, returning trimmed data."""
        return CandidateInfo.from_dict({
            "first_name": self.first_name.text(),
            "last_name": self.last_name.text(),
            "group_id": self.group_id.text(),
        }, require_group=self.require_group).as_dict()

    def _validate(self, *_):
        self._error_key = ""
        self.error_label.clear()
        try:
            self.candidate_info()
        except ValueError:
            self.continue_button.setEnabled(False)
            self.identity_open_button.setEnabled(False)
        else:
            self.continue_button.setEnabled(self._identity_ready)
            self.identity_open_button.setEnabled(not self._identity_started)

    def _submit(self):
        # Return/Enter must use the same validation as the disabled button.
        try:
            info = self.candidate_info()
        except ValueError:
            self.show_submission_error()
            return
        if not self._identity_ready:
            self.show_submission_error("identity.required")
            return
        self.submitted.emit(info)

    def _open_identity(self):
        try:
            info = self.candidate_info()
        except ValueError:
            self.show_submission_error()
            return
        self.identity_open_requested.emit(info)

    def identity_started(self):
        self._identity_started = True
        for field in (self.first_name, self.last_name, self.group_id):
            field.setReadOnly(True)
        self._validate()

    def set_identity_state(self, *, ready: bool, status: str, can_capture: bool = False):
        self._identity_ready = bool(ready)
        self._identity_can_capture = bool(can_capture)
        self._identity_message = status
        self.identity_capture_button.setEnabled(self._identity_started and can_capture)
        self.identity_status_label.setText(translate_text(status))
        self._validate()

    def set_identity_preview(self, frame, result, healthy: bool, reason: str = ""):
        self.identity_preview.set_frame(frame, result, healthy, reason)

    def show_submission_error(self, key: str = "registration.invalid"):
        self._error_key = key
        self.error_label.setText(t(key))

    def retranslate_ui(self, *_):
        self.eyebrow.setText(t("registration.eyebrow"))
        self.title.setText(t("registration.title"))
        self.description.setText(t("registration.description"))
        for field, label, key in (
            (self.first_name, self.first_name_label, "registration.first_name"),
            (self.last_name, self.last_name_label, "registration.last_name"),
            (self.group_id, self.group_id_label,
             "registration.group_required" if self.require_group else "registration.group_optional"),
        ):
            text = t(key)
            label.setText(text)
            field.setAccessibleName(text)
            field.setPlaceholderText(text)
        self.continue_button.setText(t("registration.continue"))
        self.identity_note.setText(t("identity.notice"))
        self.identity_open_button.setText(t("identity.open_camera"))
        self.identity_capture_button.setText(t("identity.capture"))
        self.identity_status_label.setText(translate_text(self._identity_message))
        if self._error_key:
            self.error_label.setText(t(self._error_key))
