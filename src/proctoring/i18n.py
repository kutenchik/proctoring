"""Small, presentation-only translation service.

The application continues to calculate and store canonical English identifiers.
Only widgets call this module; changing language never changes an observation,
calibration reference, event record, or an already selected quiz answer.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from string import Formatter
from typing import Mapping

from PySide6.QtCore import QObject, Signal


SUPPORTED_LANGUAGES = ("en", "ru", "kk")
_LOCALES = Path(__file__).with_name("locales")
_FORMATTER = Formatter()


def _load_catalogues() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path in sorted(_LOCALES.glob("*.json")):
        with path.open(encoding="utf-8") as stream:
            entries = json.load(stream)
        for key, translations in entries.items():
            if not isinstance(translations, dict) or not all(
                isinstance(locale, str) and isinstance(text, str)
                for locale, text in translations.items()
            ):
                raise ValueError(f"Invalid translation entry {key!r} in {path.name}")
            if key in result and result[key] != translations:
                raise ValueError(f"Duplicate translation key {key!r} in {path.name}")
            result[key] = translations
    return result


def _template_pattern(template: str):
    """Match a complete rendered source, preserving its already formatted values."""
    parts: list[str] = []
    fields: list[str] = []
    literal_size = 0
    meaningful_literal = False
    try:
        for literal, field, _spec, _conversion in _FORMATTER.parse(template):
            parts.append(re.escape(literal))
            literal_size += len(literal)
            meaningful_literal = meaningful_literal or any(char.isalpha() for char in literal)
            if field is not None:
                if not field or not field.isidentifier():
                    return None
                if field in fields:
                    parts.append(f"(?P={field})")
                else:
                    # A field owns one presentation fragment, not subsequent
                    # status lines or independent dot-separated indicators.
                    # Delimiters explicitly present in the template still match.
                    parts.append(f"(?P<{field}>(?:(?! · )[^\r\n])*?)")
                    fields.append(field)
    except ValueError:
        return None
    # An unconstrained {value} template must never translate arbitrary data.
    if not fields or not literal_size:
        return None
    return literal_size, re.compile("".join(parts)), meaningful_literal


def _render_captured(template: str, values: Mapping[str, str]) -> str:
    # A capture such as "12.30" is already formatted. Applying :.2f to the string
    # would either fail or destroy the original representation through coercion.
    return "".join(literal + (values[field] if field is not None else "")
                   for literal, field, _spec, _conversion in _FORMATTER.parse(template))


class TranslationManager(QObject):
    language_changed = Signal(str)

    def __init__(self, catalogues: Mapping[str, Mapping[str, str]] | None = None,
                 language: str = "en", parent: QObject | None = None):
        super().__init__(parent)
        self.catalogues = dict(catalogues) if catalogues is not None else _load_catalogues()
        self._language = "en"
        self._sources: dict[str, str] = {}
        self._templates: list[tuple[int, re.Pattern, str, bool]] = []
        for key, translations in self.catalogues.items():
            source = translations.get("en")
            if source is None:
                continue
            # Identical English UI labels may have several semantic keys. Their
            # exact key translations remain accessible through t().
            self._sources.setdefault(source, key)
            match = _template_pattern(source)
            if match is not None:
                size, pattern, meaningful_literal = match
                self._templates.append((size, pattern, key, meaningful_literal))
        self._templates.sort(key=lambda value: value[0], reverse=True)
        self.set_language(language)

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported UI language: {language!r}; use en, ru, or kk")
        if language != self._language:
            self._language = language
            self.language_changed.emit(language)

    def t(self, key: str, default: str | None = None, **kwargs) -> str:
        translations = self.catalogues.get(key, {})
        result = translations.get(self._language, translations.get("en", default if default is not None else key))
        return result.format(**kwargs) if kwargs else result

    def _translate_match(self, source: str, depth: int) -> str | None:
        """Translate only one complete catalog entry, without fragment fallback."""
        key = self._sources.get(source)
        if key is not None:
            return self.t(key)
        for _size, pattern, key, meaningful_literal in self._templates:
            match = pattern.fullmatch(source)
            if match is None:
                continue
            values = {name: self.translate_text(value, _depth=depth + 1)
                      for name, value in match.groupdict().items()}
            if not meaningful_literal and values == match.groupdict():
                # Punctuation-only entries such as {event}: {count} can compose
                # known labels, but must not reinterpret opaque technical data.
                continue
            try:
                return _render_captured(self.t(key), values)
            except (KeyError, ValueError):
                # A missing/malformed localized template must not break a UI or
                # cause raw observations to be replaced by a guessed value.
                return source
        return None

    def translate_text(self, source: str, *, _depth: int = 0) -> str:
        """Translate a UI source string, never inventing text for unknown values."""
        if self._language == "en" or not source or _depth >= 4:
            return source
        matched = self._translate_match(source, _depth)
        if matched is not None:
            return matched
        # Composition itself adds no semantic nesting: otherwise the fourth
        # line or final indicator could hit the recursion guard untranslated.
        fragments = re.split(r"(\r?\n)", source)
        if len(fragments) > 1:
            return "".join(part if index % 2 else self.translate_text(part, _depth=_depth)
                           for index, part in enumerate(fragments))
        fragments = source.split(" · ")
        if len(fragments) > 1:
            rendered: list[str] = []
            start = 0
            while start < len(fragments):
                # Retain compound catalog entries such as the paired YOLO/face
                # timings even when an unrelated provider follows their text.
                for end in range(len(fragments), start, -1):
                    candidate = " · ".join(fragments[start:end])
                    translated = self._translate_match(candidate, _depth)
                    if translated is not None:
                        rendered.append(translated)
                        start = end
                        break
                else:
                    rendered.append(fragments[start])
                    start += 1
            return " · ".join(rendered)
        return source


manager = TranslationManager()
language_changed = manager.language_changed


def get_manager() -> TranslationManager:
    return manager


def set_language(language: str) -> None:
    manager.set_language(language)


def get_language() -> str:
    return manager.language


def t(key: str, default: str | None = None, **kwargs) -> str:
    return manager.t(key, default, **kwargs)


def translate_text(source: str) -> str:
    return manager.translate_text(source)
