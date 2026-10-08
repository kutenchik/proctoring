"""Opt-in Qt text widgets which retain their canonical English presentation.

These subclasses do not monkeypatch Qt. Language changes only repaint text;
they do not rerun calibration, exam, or event logic.
"""
from PySide6.QtWidgets import (
    QLabel as _QLabel, QPushButton as _QPushButton, QCheckBox as _QCheckBox,
    QGroupBox as _QGroupBox, QProgressBar as _QProgressBar,
    QRadioButton as _QRadioButton,
)

from ..i18n import manager, translate_text


class _TextMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_text = super().text()
        self.source_tooltip = super().toolTip()
        manager.language_changed.connect(self._retranslate_text)
        self._retranslate_text()

    def setText(self, text: str) -> None:
        self.source_text = text
        super().setText(translate_text(text))

    def setToolTip(self, text: str) -> None:
        self.source_tooltip = text
        super().setToolTip(translate_text(text))

    def _retranslate_text(self, _language: str = "") -> None:
        if getattr(self, "_text_translation_enabled", True):
            super().setText(translate_text(self.source_text))
        super().setToolTip(translate_text(self.source_tooltip))


class QLabel(_TextMixin, _QLabel):
    def setText(self, text: str) -> None:
        self._text_translation_enabled = True
        super().setText(text)

    def clear(self) -> None:
        self.source_text = ""
        self._text_translation_enabled = True
        super().clear()

    def setPixmap(self, pixmap) -> None:
        # Camera previews share QLabel. A locale switch must not replace their
        # current image with an earlier text placeholder.
        self.source_text = ""
        self._text_translation_enabled = False
        super().setPixmap(pixmap)


class QPushButton(_TextMixin, _QPushButton):
    pass


class QCheckBox(_TextMixin, _QCheckBox):
    pass


class QRadioButton(_TextMixin, _QRadioButton):
    pass


class QGroupBox(_QGroupBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_title = self.title()
        manager.language_changed.connect(self._retranslate_title)
        self._retranslate_title()

    def setTitle(self, title: str) -> None:
        self.source_title = title
        super().setTitle(translate_text(title))

    def _retranslate_title(self, _language: str = "") -> None:
        super().setTitle(translate_text(self.source_title))


class QProgressBar(_QProgressBar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_format = self.format()
        manager.language_changed.connect(self._retranslate_format)
        self._retranslate_format()

    def setFormat(self, value: str) -> None:
        self.source_format = value
        super().setFormat(translate_text(value))

    def _retranslate_format(self, _language: str = "") -> None:
        super().setFormat(translate_text(self.source_format))


def source_text(widget) -> str:
    """Return the English presentation text, even after a locale switch."""
    return widget.source_text if hasattr(widget, "source_text") else widget.text()
