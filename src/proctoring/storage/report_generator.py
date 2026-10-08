"""Local, atomic Qt PDF audits; no widgets, network, or new image evidence.

The rule-based score summarizes recorded review events, not human guilt or a
validated probability. Image overlays are drawn onto in-memory copies only.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from html import escape
import json
import math
import os
from pathlib import Path
import threading
from typing import Callable, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from proctoring.settings import ReportingConfig


def _unique_events(events: list[dict]) -> list[dict]:
    """Keep the final state of each recorded event, never count frame updates."""
    selected: dict[str, dict] = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict) or not event.get("event_type"):
            continue
        if event.get("state") == "candidate":
            continue
        key = str(event.get("event_id") or f"unidentified-{index}")
        selected[key] = {**selected.get(key, {}), **event}
    return list(selected.values())


def calculate_trust_score(events: list[dict]) -> int:
    """Apply the requested fixed weights once per distinct recorded event ID."""
    penalty = 0
    for event in _unique_events(events):
        kind = str(event["event_type"]).lower()
        if kind in {"phone_visible", "phone_raised"}:
            penalty += 30
        elif kind == "voice_detected":
            penalty += 15
        elif kind in {"gaze_down", "gaze_left", "gaze_right", "gaze_deviation", "head_down"}:
            penalty += 10
        elif kind == "impersonation_suspected":
            penalty += 50
    return max(0, 100 - penalty)


def collect_report_events(session_dir: Path, summary: dict) -> list[dict]:
    """Prefer the last persisted journal state, retaining summary-only evidence.

    ``summary.json`` holds completed snapshot paths and optional box metadata;
    these supplement the journal without inventing images or detections.
    """
    base = _unique_events([*summary.get("events", []), *summary.get("security_events", [])])
    events = {str(event.get("event_id")): event for event in base if event.get("event_id")}
    journal = Path(session_dir) / "events.jsonl"
    if journal.exists():
        with journal.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if (not isinstance(record, dict) or not record.get("event_id")
                        or not record.get("event_type")):
                    continue
                if (record.get("record_kind") != "security_event"
                        and record.get("action") not in {"activated", "updated", "clearing", "closed"}):
                    continue
                key = str(record["event_id"])
                prior = events.get(key, {})
                merged = {**prior, **record}
                # A missing activation JPEG is resolved by the finalized summary.
                if not merged.get("snapshot_path") and prior.get("snapshot_path"):
                    merged["snapshot_path"] = prior["snapshot_path"]
                events[key] = merged
    return sorted(events.values(), key=lambda e: (str(e.get("start_timestamp") or e.get("timestamp") or ""),
                                                   str(e["event_id"])))


def _local_image(session_dir: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    try:
        value = Path(relative)
        root = session_dir.resolve()
        path = (root / value).resolve()
        if (value.is_absolute() or ".." in value.parts or not path.is_relative_to(root)
                or path.suffix.lower() not in {".jpg", ".jpeg", ".png"} or not path.is_file()
                or path.stat().st_size > 25 * 1024 * 1024):
            return None
        return path
    except (OSError, ValueError):
        return None


def _number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def _severity(event: dict) -> str:
    value = event.get("severity")
    if value:
        return str(value)
    if str(event.get("event_type", "")).lower() in {"impersonation_suspected", "phone_visible", "phone_raised"}:
        return "High review priority"
    return "Review required"


def _timeline_time(value: object) -> str:
    """Keep the recorded offset, omitting the date and fractional seconds.

    Do not convert according to the report worker machine's timezone. The full
    unmodified timestamps remain available in the session journal and summary.
    """
    if not isinstance(value, str) or "T" not in value:
        return "Not recorded"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except ValueError:
        return "Not recorded"


def _report_font_family() -> str:
    """Require real glyph data, including Windows' fontless offscreen plugin.

    That plugin otherwise renders every character as a square path and still
    returns a syntactically valid PDF. Load an installed system font explicitly;
    no download or bundled/unlicensed font copy is involved. QFontDatabase's
    static functions are thread-safe, so this also works in the report worker.
    """
    from PySide6.QtGui import QFontDatabase

    families = QFontDatabase.families()
    if not families:
        candidates = ([Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"]
                      if os.name == "nt" else [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")])
        for path in candidates:
            if path.is_file() and QFontDatabase.addApplicationFont(str(path)) >= 0:
                families = QFontDatabase.families()
                if families:
                    break
    if not families:
        raise RuntimeError("No usable local font is available for PDF text")
    return next((name for name in ("Segoe UI", "DejaVu Sans", "Arial") if name in families), families[0])


def build_report_document(session_dir: Path, summary: dict, events: list[dict]):
    """Create worker-owned QTextDocument using only vetted QImage resources."""
    from PySide6.QtCore import QRectF, Qt, QUrl
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QTextDocument

    class LocalDocument(QTextDocument):
        def loadResource(self, resource_type, name):
            # Do not allow Qt's default local/remote URL loader to fetch anything.
            return None

        def paginate_timeline(self):
            """Move a split row and its following rows to a new table/page.

            Qt paginates individual cell paragraphs, so a tall image can move
            independently of its event label. Measure at the PDF paint device's
            actual dimensions and split tables at those row boundaries instead.
            Headers repeat; no rows/images are truncated to meet a page budget.
            """
            starts = set()
            page_height = self.pageSize().height()
            while rows and page_height > 0:
                self.documentLayout().documentSize()  # complete lazy layout
                offset, split_at = 0, None
                for table in self.rootFrame().childFrames():
                    if not hasattr(table, "columns") or table.columns() != 5:
                        continue
                    for row in range(1, table.rows()):
                        bounds = [self.documentLayout().blockBoundingRect(
                            table.cellAt(row, column).firstCursorPosition().block())
                            for column in range(table.columns())]
                        top = min(rect.top() for rect in bounds)
                        bottom = max(rect.bottom() for rect in bounds)
                        boundary = offset + row - 1
                        if (int(top // page_height) != int((bottom - .1) // page_height)
                                and boundary not in starts):
                            split_at = boundary
                            break
                    if split_at is not None:
                        break
                    offset += table.rows() - 1
                if split_at is None:
                    break
                starts.add(split_at)
                boundaries = sorted(starts | {0, len(rows)})
                tables = []
                for start, end in zip(boundaries, boundaries[1:]):
                    opening = table_open.replace('<table ', '<table style="page-break-before:always" ', 1) \
                        if start in starts else table_open
                    tables.append(opening + ''.join(rows[start:end]) + '</table>')
                # addResource images are cached by QTextDocument across setHtml.
                self.setHtml(prefix + ''.join(tables))

    document = LocalDocument()
    font_family = _report_font_family()
    document.setDefaultFont(QFont(font_family, 10))
    document.setDocumentMargin(0)
    document.setDefaultStyleSheet("""
        body { color: #173042; font-size: 10pt; }
        h1 { font-size: 23pt; color: #12364a; margin-bottom: 8px; }
        h2 { font-size: 14pt; color: #126d72; margin-top: 20px; margin-bottom: 8px; }
        p { margin-top: 5px; margin-bottom: 8px; }
        th { color: white; background-color: #173e52; text-align: left; }
        td { vertical-align: top; }
        .muted { color: #576c77; font-size: 9pt; }
        .small { font-size: 8pt; }
    """)
    image_counter = 0
    image_hashes = {}
    image_resources = {}

    def image_html(relative: object, width: int, height: int, boxes=(), *, thumbnail=False) -> str:
        nonlocal image_counter
        missing = ('<span style="color:#8c959f">No capture</span>' if thumbnail
                   else '<span class="muted">No saved image</span>')
        path = _local_image(session_dir, relative)
        if path is None:
            return missing
        # Compare actual file content, never timestamps alone: simultaneous
        # event IDs can have distinct paths containing the same source frame.
        # Retain only digests and small rendered resources, not full-size frames.
        data = None
        try:
            if path not in image_hashes:
                data = path.read_bytes()
                image_hashes[path] = sha256(data).digest()
        except OSError:
            return missing
        rectangles = set()
        for item in boxes:
            coords = ([item.get(key) for key in ("x1", "y1", "x2", "y2")]
                      if isinstance(item, dict) and "x1" in item
                      else item.get("box") if isinstance(item, dict) else item)
            if not isinstance(coords, (list, tuple)) or len(coords) != 4:
                continue
            numbers = tuple(_number(value, float("nan")) for value in coords)
            if (all(math.isfinite(value) and 0 <= value <= 1 for value in numbers)
                    and numbers[2] > numbers[0] and numbers[3] > numbers[1]):
                rectangles.add(numbers)
        # Distinct overlays remain distinct evidence; labels are not painted.
        key = (image_hashes[path], width, height, tuple(sorted(rectangles)), thumbnail)
        if key in image_resources:
            return image_resources[key]
        try:
            image = QImage.fromData(data if data is not None else path.read_bytes())
        except OSError:
            return missing
        if image.isNull():
            return missing
        if rectangles or thumbnail:
            image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        if rectangles:
            painter = QPainter(image)
            try:
                painter.setPen(QPen(QColor("#ffe251"), max(2, image.width() / 240)))
                for x1, y1, x2, y2 in rectangles:
                    painter.drawRect(QRectF(x1 * image.width(), y1 * image.height(),
                                            (x2 - x1) * image.width(), (y2 - y1) * image.height()))
            finally:
                painter.end()
        image = image.scaled(width * 2, height * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if thumbnail:
            # QTextDocument implements only a subset of CSS. Paint the subtle
            # one-display-pixel rounded border into the 2x resource for reliable
            # PDF rendering; the saved snapshot is never modified.
            painter = QPainter(image)
            try:
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(QPen(QColor("#d0d7de"), 2))
                painter.drawRoundedRect(QRectF(1, 1, image.width() - 2, image.height() - 2), 6, 6)
            finally:
                painter.end()
        image_counter += 1
        name = QUrl(f"snapshot://resource/{image_counter}" if thumbnail else f"report-image:{image_counter}")
        document.addResource(QTextDocument.ImageResource, name, image)
        html = f'<img src="{name.toString()}" width="{image.width() / 2:.0f}" height="{image.height() / 2:.0f}">'
        image_resources[key] = html
        return html

    def text(value: object) -> str:
        return escape(str(value if value is not None else "Not recorded"), quote=True)

    candidate = summary.get("candidate") or {}
    score = calculate_trust_score(events)
    color, band = (("#18735b", "Low Risk") if score >= 90 else
                   ("#9a6715", "Moderate Risk") if score >= 70 else ("#ab3546", "High Risk"))
    parts = ['<p class="muted">LOCAL PROCTORING / SESSION AUDIT</p>',
             '<h1>Exam Proctoring Integrity Report</h1>',
             '<p class="muted">Recorded review events and available evidence. Human review is required.</p>',
             '<table width="100%" cellspacing="0" cellpadding="8"><tr><td width="73%">',
             f'<b>Candidate:</b> {text(candidate.get("first_name", ""))} {text(candidate.get("last_name", ""))}<br>',
             f'<b>Group / Student ID:</b> {text(candidate.get("group_id", ""))}<br>',
             f'<b>Session:</b> {text(summary.get("session_id", session_dir.name))}<br>',
             f'<b>Ended:</b> {text(summary.get("ended_at"))}<br>',
             f'<b>Exam duration:</b> {_number(summary.get("elapsed_seconds")):.1f} seconds<br>',
             f'<b>Mode:</b> {text(summary.get("mode", "Not recorded"))}</td><td width="27%">',
             image_html("reference_face.jpg", 130, 115), '</td></tr></table>',
             f'<table width="100%" cellpadding="12" cellspacing="0" bgcolor="#eef4f5"><tr><td>',
             f'<span style="color:{color};font-size:20pt"><b>Trust Score: {score}%</b></span><br>',
             f'<b>{band}</b> (rule-based band) / {len(events)} recorded review events<br>',
             '<span class="muted">A configurable-demo scoring rule, not a validated misconduct probability. '
             'No detected events does not prove compliant behavior.</span></td></tr></table>',
             '<p class="small">Fixed weights per event: phone 30; voice/noise 15; gaze 10; identity inconsistency 50. '
             'Minimum score: 0. Other review events are listed without a score deduction.</p>',
             '<h2>System and device context</h2>']
    for key, label in (("system_info", "System"), ("device_info", "Devices"), ("system_checks", "Pre-flight checks")):
        value = summary.get(key, summary.get("system", "Not recorded") if key == "system_info" else "Not recorded")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        parts.append(f'<p class="small"><b>{label}:</b> {text(value)}</p>')
    parts.append('<h2>Review-event timeline</h2>')
    parts.append('<p class="small muted">Times use the recorded UTC offset; full timestamps remain in events.jsonl. '
                 'Thumbnails retain recorded boxes; original captures are unchanged.</p>')
    prefix = ''.join(parts)
    table_open = ('<table width="100%" border="0" cellspacing="0" cellpadding="4">'
                 '<thead><tr><th width="18%">Time</th><th width="24%">Event type</th>'
                 '<th width="14%">Duration (s)</th><th width="18%">Severity / Review</th>'
                 '<th width="26%">Snapshot</th></tr></thead>')
    rows = []
    for index, event in enumerate(events):
        thumbnail = image_html(event.get("snapshot_path"), 80, 60,
                               event.get("snapshot_boxes") or (), thumbnail=True)
        timestamp = _timeline_time(event.get("start_timestamp") or event.get("timestamp"))
        rows.append(f'<tr bgcolor="{"#f0f5f7" if index % 2 == 0 else "#ffffff"}">'
                     f'<td class="small" style="white-space:nowrap">{text(timestamp)}</td>'
                     f'<td class="small">{text(event.get("event_type"))}</td>'
                     f'<td>{_number(event.get("duration_seconds")):.2f}</td>'
                     f'<td class="small">{text(_severity(event))}</td><td>{thumbnail}</td></tr>')
    if not events:
        rows.append('<tr><td colspan="5">No review events were recorded.</td></tr>')
    document.setHtml(prefix + table_open + ''.join(rows) + '</table>')
    return document


def generate_report(session_dir: Path, summary: dict,
                    filename: str = "exam_integrity_report.pdf") -> Path:
    """Write a PDF atomically after local summary completion, with page numbers."""
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
    from PySide6.QtGui import QFont, QGuiApplication, QPageLayout, QPageSize, QPainter, QPdfWriter

    root = Path(session_dir).resolve()
    # Reject traversal, alternate streams, platform device names and non-PDFs.
    if (not isinstance(filename, str) or not filename or Path(filename).name != filename
            or any(character in filename for character in '/\\:<>"|?*\x00')
            or filename.endswith((" ", ".")) or Path(filename).suffix.lower() != ".pdf"
            or Path(filename).stem.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                                               *[f"LPT{i}" for i in range(1, 10)]}):
        raise ValueError("Report filename must be a safe PDF basename")
    if not (root / "summary.json").is_file():
        raise RuntimeError("A saved session summary is required before PDF generation")
    if QGuiApplication.instance() is None:
        raise RuntimeError("PDF generation requires an existing Qt GUI application")
    events = collect_report_events(root, summary)
    document = build_report_document(root, summary, events)
    destination = root / filename
    temporary = root / f".{filename}.{uuid4().hex}.partial"
    try:
        writer = QPdfWriter(str(temporary))
        writer.setCreator("Local Proctoring")
        writer.setTitle("Exam Proctoring Integrity Report")
        writer.setResolution(144)
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setPageMargins(QMarginsF(15, 14, 15, 14), QPageLayout.Millimeter)
        width, height = writer.width(), writer.height()
        footer = 45
        page_height = height - footer
        document.documentLayout().setPaintDevice(writer)
        document.setPageSize(QSizeF(width, page_height))
        document.paginate_timeline()
        painter = QPainter(writer)
        if not painter.isActive():
            raise OSError("Could not open PDF writer")
        try:
            pages = max(1, document.pageCount())
            for page in range(pages):
                if page and not writer.newPage():
                    raise OSError("Could not create PDF page")
                # Explicit paper white also renders predictably in transparent
                # PDF preview surfaces; PDF viewers normally supply it for us.
                painter.fillRect(QRectF(-100, -100, width + 200, height + 200), Qt.white)
                painter.save()
                painter.setClipRect(QRectF(0, 0, width, page_height))
                painter.translate(0, -page * page_height)
                document.drawContents(painter, QRectF(0, page * page_height, width, page_height))
                painter.restore()
                painter.setPen(Qt.darkGray)
                painter.setFont(QFont(document.defaultFont().family(), 8))
                painter.drawText(QRectF(0, height - 30, width, 25), Qt.AlignRight,
                                 f"Local session audit | Page {page + 1} of {pages}")
        finally:
            painter.end()
        del writer  # release Windows file handle before atomic replacement
        with temporary.open("rb") as stream:
            if stream.read(5) != b"%PDF-" or temporary.stat().st_size < 100:
                raise OSError("PDF writer did not produce a valid document")
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ReportResult:
    path: Path | None = None
    trust_score: int | None = None
    error: str | None = None


class ReportJob:
    """One fail-soft report worker. Caller polls status or uses a worker callback."""
    def __init__(self, session_dir: Path, summary: dict, config: "ReportingConfig",
                 on_complete: Callable[[ReportResult], None] | None = None):
        self._lock = threading.Lock()
        self._result = ReportResult()
        self._status = "running" if config.generate_pdf_report else "disabled"
        self._thread = None
        if config.generate_pdf_report:
            self._thread = threading.Thread(target=self._run,
                                            args=(Path(session_dir), deepcopy(summary), config.report_filename, on_complete),
                                            name="session-pdf-report", daemon=True)
            self._thread.start()

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def result(self) -> ReportResult:
        with self._lock:
            return self._result

    def _run(self, session_dir, summary, filename, on_complete):
        try:
            path = generate_report(session_dir, summary, filename)
            result = ReportResult(path, calculate_trust_score(collect_report_events(session_dir, summary)))
        except Exception as error:
            # Paths/candidate data do not belong in operational error strings.
            result = ReportResult(error=f"PDF generation failed ({type(error).__name__})")
        with self._lock:
            self._result = result
            self._status = "failed" if result.error else "complete"
        if on_complete is not None:
            try:
                on_complete(result)
            except Exception:
                # The local PDF is still complete if remote enqueue fails.
                pass

    def close(self, timeout: float = 2.0) -> bool:
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        budget = _number(timeout, 2.0)
        thread.join(min(2.0, max(0.0, budget)))
        return not thread.is_alive()
