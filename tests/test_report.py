import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import QMarginsF, QSizeF, Qt, QUrl
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument, QTextTable
try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # Optional dev inspection; report runtime needs Essentials only.
    QPdfDocument = None
from PySide6.QtWidgets import QApplication

from proctoring.storage.report_generator import (
    ReportJob, _report_font_family, build_report_document, calculate_trust_score, collect_report_events, generate_report,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def audit(tmp_path):
    summary = dict(session_id="session-synthetic", candidate={"first_name": "Amina", "last_name": "Abai",
                   "group_id": "CS-101"}, ended_at="2026-10-07T12:30:00Z", elapsed_seconds=180,
                   mode="synthetic", system_info={"OS": "Windows 11"}, device_info={"camera": "640x480"},
                   events=[dict(event_id="one", event_type="phone_visible", state="closed", duration_seconds=2.5,
                                start_timestamp="2026-10-07T12:29:00Z", snapshot_path="snapshots/one.jpg")])
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (tmp_path / "snapshots").mkdir()
    image = QImage(640, 480, QImage.Format_RGB32)
    image.fill(Qt.lightGray)
    image.save(str(tmp_path / "snapshots/one.jpg"))
    image.save(str(tmp_path / "reference_face.jpg"))
    return tmp_path, summary


def timeline(document):
    """Inspect the actual Qt table that will be painted, not a duplicate template."""
    for frame in document.rootFrame().childFrames():
        if isinstance(frame, QTextTable):
            cursor = frame.cellAt(0, 0).firstCursorPosition()
            if cursor.block().text() == "Time":
                return frame
    raise AssertionError("No review-event timeline table")


def cell_text(cell):
    cursor = cell.firstCursorPosition()
    cursor.setPosition(cell.lastCursorPosition().position(), cursor.MoveMode.KeepAnchor)
    return cursor.selectedText()


def cell_images(cell):
    block = cell.firstCursorPosition().block()
    end = cell.lastCursorPosition().position()
    images = []
    while block.isValid() and block.position() <= end:
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                images.append(fragment.charFormat().toImageFormat())
            iterator += 1
        block = block.next()
    return images


@pytest.mark.parametrize("source_size", [(640, 480), (1280, 720), (480, 640)])
def test_timeline_embeds_vetted_thumbnail_resources_with_aspect_ratio(qt_app, audit, source_size):
    root, summary = audit
    source = QImage(*source_size, QImage.Format_RGB32)
    source.fill(Qt.lightGray)
    assert source.save(str(root / "snapshots/one.jpg"))
    document = build_report_document(root, summary, summary["events"])
    table = timeline(document)
    assert [length.rawValue() for length in table.format().columnWidthConstraints()] == [18, 24, 14, 18, 26]
    images = cell_images(table.cellAt(1, 4))
    assert len(images) == 1
    image = images[0]
    assert image.name().startswith("snapshot://")
    assert 0 < image.width() <= 96 and 0 < image.height() <= 60
    assert image.width() / image.height() == pytest.approx(source_size[0] / source_size[1], abs=.04)
    resource = document.resource(QTextDocument.ImageResource, QUrl(image.name()))
    assert isinstance(resource, QImage) and not resource.isNull()
    assert image.name() in document.toHtml()
    assert "Saved evidence gallery" not in document.toPlainText()
    assert "Image 1" not in cell_text(table.cellAt(1, 4))


@pytest.mark.parametrize("snapshot", [None, "snapshots/missing.jpg", "snapshots/corrupt.jpg",
                                     "../outside.jpg", "https://remote.example/leak.jpg"])
def test_unavailable_snapshot_is_neutral_badge_without_image(qt_app, audit, snapshot):
    root, summary = audit
    (root / "snapshots/corrupt.jpg").write_bytes(b"not an image")
    summary["events"][0]["snapshot_path"] = snapshot
    document = build_report_document(root, summary, summary["events"])
    cell = timeline(document).cellAt(1, 4)
    assert not cell_images(cell)
    assert cell_text(cell) == "No capture"


@pytest.mark.parametrize(("timestamp", "expected"), [
    ("2026-10-07T15:48:12.495239+00:00", "15:48:12"),
    ("2026-10-07T20:48:12.495239+05:00", "20:48:12"),
    ("2026-10-07T15:48:12Z", "15:48:12"),
    (None, "Not recorded"), ("broken-timestamp", "Not recorded")])
def test_timeline_timestamp_is_short_and_keeps_recorded_offset(qt_app, audit, timestamp, expected):
    root, summary = audit
    summary["events"][0]["start_timestamp"] = timestamp
    document = build_report_document(root, summary, summary["events"])
    assert cell_text(timeline(document).cellAt(1, 0)).replace("\u00a0", " ") == expected
    assert "Times use the recorded UTC offset; full timestamps remain in events.jsonl." in document.toPlainText()
    assert summary["events"][0]["start_timestamp"] == timestamp


def test_same_frame_and_overlays_reuse_resource_even_across_snapshot_paths(qt_app, audit):
    root, summary = audit
    (root / "snapshots/two.jpg").write_bytes((root / "snapshots/one.jpg").read_bytes())
    different_frame = QImage(640, 480, QImage.Format_RGB32)
    different_frame.fill(Qt.green)
    assert different_frame.save(str(root / "snapshots/different.jpg"))
    box = {"x1": .2, "y1": .2, "x2": .5, "y2": .8, "label": "phone"}
    base = {**summary["events"][0], "snapshot_boxes": [box]}
    summary["events"] = [base, {**base, "event_id": "two", "event_type": "phone_raised"},
                         {**base, "event_id": "three", "snapshot_path": "snapshots/two.jpg"},
                         {**base, "event_id": "four", "snapshot_boxes": [{**box, "x1": .3}]},
                         {**base, "event_id": "five", "snapshot_path": "snapshots/different.jpg"}]
    document = build_report_document(root, summary, summary["events"])
    table = timeline(document)
    names = [cell_images(table.cellAt(row, 4))[0].name() for row in range(1, 6)]
    assert names[0] == names[1] == names[2]
    assert names[3] != names[0]
    assert names[4] not in names[:4]  # Same recorded timestamp does not prove identical frames.
    assert "Saved evidence gallery" not in document.toPlainText()


@pytest.mark.skipif(QPdfDocument is None, reason="Optional QtPdf add-on unavailable for page inspection")
@pytest.mark.parametrize("event_count", [6, 12])
def test_typical_inline_snapshot_timeline_fits_two_pages(qt_app, audit, event_count):
    root, summary = audit
    summary["events"] = [{**summary["events"][0], "event_id": f"event-{index}",
                          "event_type": f"review_event_{index:02d}"} for index in range(event_count)]
    output = generate_report(root, summary)
    assert output.stat().st_size > 1000
    pdf = QPdfDocument()
    assert pdf.load(str(output)) == QPdfDocument.Error.None_
    try:
        assert 1 <= pdf.pageCount() <= 2
        text = "\n".join(pdf.getAllText(page).text() for page in range(pdf.pageCount()))
        for index in range(event_count):
            assert f"review_event_{index:02d}" in text
        assert "Saved evidence gallery" not in text
        assert "12:29:00" in text
    finally:
        pdf.close()


def test_timeline_text_and_snapshot_stay_on_same_page_at_row_boundary(qt_app, audit):
    root, summary = audit
    summary["events"] = [{**summary["events"][0], "event_id": f"event-{index}",
                          "event_type": f"review_event_{index:02d}"} for index in range(12)]
    summary["events"][5]["snapshot_path"] = None
    document = build_report_document(root, summary, summary["events"])
    writer = QPdfWriter(str(root / "layout-measurement.pdf"))
    writer.setResolution(144)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(15, 14, 15, 14), QPageLayout.Millimeter)
    page_height = writer.height() - 45
    layout = document.documentLayout()
    layout.setPaintDevice(writer)
    document.setPageSize(QSizeF(writer.width(), page_height))
    document.paginate_timeline()
    layout.documentSize()
    assert 1 <= document.pageCount() <= 2

    found_rows = []
    row_pages = set()
    for table in document.rootFrame().childFrames():
        if not isinstance(table, QTextTable) or table.columns() != 5:
            continue
        assert cell_text(table.cellAt(0, 0)) == "Time"
        for row in range(1, table.rows()):
            bounds = []
            for column in range(table.columns()):
                cell = table.cellAt(row, column)
                block = cell.firstCursorPosition().block()
                while block.isValid() and block.position() <= cell.lastCursorPosition().position():
                    bounds.append(layout.blockBoundingRect(block))
                    block = block.next()
            pages = {int(rect.top() // page_height) for rect in bounds}
            pages.update(int((rect.bottom() - .1) // page_height) for rect in bounds)
            assert len(pages) == 1, f"Timeline row {row} split across pages: {pages}"
            row_pages.update(pages)
            found_rows.append(cell_text(table.cellAt(row, 1)))
            for image in cell_images(table.cellAt(row, 4)):
                resource = document.resource(QTextDocument.ImageResource, QUrl(image.name()))
                assert isinstance(resource, QImage) and not resource.isNull()
    assert found_rows == [f"review_event_{index:02d}" for index in range(12)]
    assert row_pages == set(range(document.pageCount()))  # No blank/empty appendix page.


@pytest.mark.parametrize(("types", "expected"), [([], 100), (["phone_visible"], 70),
    (["voice_detected", "gaze_down"], 75), (["IMPERSONATION_SUSPECTED"], 50),
    (["phone_raised", "gaze_left", "gaze_right", "impersonation_suspected", "voice_detected"], 0),
    (["EARPHONE_SUSPECTED", "CLIPBOARD_ACCESSED"], 100)])
def test_rule_based_score_weights(types, expected):
    assert calculate_trust_score([{"event_id": str(index), "event_type": value}
                                  for index, value in enumerate(types)]) == expected


def test_score_deduplicates_frame_updates_and_omits_candidates():
    events = [{"event_id": "phone", "event_type": "phone_visible", "duration_seconds": duration}
              for duration in [1, 2, 3]]
    events.append({"event_id": "pending", "event_type": "phone_raised", "state": "candidate"})
    assert calculate_trust_score(events) == 70


def test_journal_final_state_dedup_and_summary_evidence(audit):
    root, summary = audit
    records = [{"record_kind": "session_header"},
               {"record_kind": "review_event", "event_id": "one", "event_type": "phone_visible",
                "action": "activated", "duration_seconds": 1},
               {"record_kind": "review_event", "event_id": "one", "event_type": "phone_visible",
                "action": "updated", "duration_seconds": 2},
               {"record_kind": "review_event", "event_id": "one", "event_type": "phone_visible",
                "action": "closed", "duration_seconds": 4, "snapshot_path": None},
               {"record_kind": "security_event", "event_id": "two", "event_type": "CLIPBOARD_ACCESSED"}]
    (root / "events.jsonl").write_text("\n".join(map(json.dumps, records)), encoding="utf-8")
    events = collect_report_events(root, summary)
    assert len(events) == 2
    assert events[0]["event_id"] == "two"  # no timestamp; ordering remains deterministic
    phone = next(event for event in events if event["event_id"] == "one")
    assert phone["duration_seconds"] == 4
    assert phone["snapshot_path"] == "snapshots/one.jpg"
    assert calculate_trust_score(events) == 70


def test_pdf_valid_atomic_and_original_images_unchanged(qt_app, audit):
    root, summary = audit
    snapshot = root / "snapshots/one.jpg"
    original = snapshot.read_bytes()
    summary["events"][0]["snapshot_boxes"] = [{"x1": .2, "y1": .2, "x2": .5, "y2": .8, "label": "phone"}]
    output = generate_report(root, summary)
    assert output == root / "exam_integrity_report.pdf"
    assert output.read_bytes().startswith(b"%PDF-")
    assert output.stat().st_size > 1000
    assert not list(root.glob("*.partial"))
    assert snapshot.read_bytes() == original


@pytest.mark.skipif(QPdfDocument is None, reason="Optional QtPdf add-on unavailable for text inspection")
def test_pdf_contains_searchable_text_and_page_footer(qt_app, audit):
    root, summary = audit
    output = generate_report(root, summary)
    document = QPdfDocument()
    assert document.load(str(output)) == QPdfDocument.Error.None_
    rendered_text = "\n".join(document.getAllText(page).text() for page in range(document.pageCount()))
    assert "Amina Abai" in rendered_text
    assert "Trust Score: 70%" in rendered_text
    assert "phone_visible" in rendered_text
    assert "Page 1 of" in rendered_text
    document.close()


@pytest.mark.skipif(QPdfDocument is None, reason="Optional QtPdf add-on unavailable for text inspection")
def test_long_timeline_paginates_without_losing_event_rows(qt_app, audit):
    root, summary = audit
    summary["events"] = [{"event_id": f"test-{index}", "event_type": f"audit_event_{index:03}",
                          "duration_seconds": 3, "state": "closed", "start_timestamp": "2026-10-07T12:00:00Z"}
                         for index in range(100)]
    output = generate_report(root, summary)
    document = QPdfDocument()
    assert document.load(str(output)) == QPdfDocument.Error.None_
    assert document.pageCount() > 1
    text = "\n".join(document.getAllText(page).text() for page in range(document.pageCount()))
    for index in range(100):
        assert f"audit_event_{index:03}" in text
    assert f"Page {document.pageCount()} of {document.pageCount()}" in text
    document.close()


@pytest.mark.parametrize("filename", ["../outside.pdf", "..\\outside.pdf", "C:\\secret.pdf", "report.html",
                                     "CON.pdf", "report:secret.pdf", "bad|name.pdf", "report.pdf "])
def test_report_output_path_cannot_escape_session(qt_app, audit, filename):
    with pytest.raises(ValueError, match="safe PDF basename"):
        generate_report(*audit, filename)


def test_summary_must_exist_before_generation(qt_app, tmp_path):
    with pytest.raises(RuntimeError, match="saved session summary"):
        generate_report(tmp_path, {})


def test_html_escaped_and_non_session_images_not_loaded(qt_app, audit, tmp_path):
    root, summary = audit
    attack = '<img src="https://remote.example/leak"><b>Not markup</b>'
    summary["candidate"]["first_name"] = attack
    summary["events"][0]["snapshot_path"] = "../private.jpg"
    doc = build_report_document(root, summary, summary["events"])
    assert attack in doc.toPlainText()
    assert "Recorded review events" in doc.toPlainText()
    assert "not a validated misconduct probability" in doc.toPlainText()
    assert "No review events" not in doc.toPlainText()
    assert "Saved evidence gallery" not in doc.toPlainText()
    assert doc.loadResource(2, "https://remote.example/leak") is None


def test_empty_report_still_explains_limitations(qt_app, audit):
    root, summary = audit
    doc = build_report_document(root, summary, [])
    assert "No review events were recorded" in doc.toPlainText()
    assert "No detected events does not prove compliant behavior" in doc.toPlainText()


def test_fontless_platform_loads_installed_font_before_rendering(qt_app):
    with patch("PySide6.QtGui.QFontDatabase.families", side_effect=[[], ["Segoe UI"]]), \
         patch("PySide6.QtGui.QFontDatabase.addApplicationFont", return_value=0) as load_font, \
         patch("proctoring.storage.report_generator.Path.is_file", return_value=True):
        assert _report_font_family() == "Segoe UI"
    load_font.assert_called_once()
    assert load_font.call_args.args[0].lower().endswith(".ttf")


def test_missing_font_fails_instead_of_creating_square_glyph_pdf(qt_app):
    with patch("PySide6.QtGui.QFontDatabase.families", return_value=[]), \
         patch("proctoring.storage.report_generator.Path.is_file", return_value=False):
        with pytest.raises(RuntimeError, match="No usable local font"):
            _report_font_family()


def test_report_job_background_callback(qt_app, audit):
    config = SimpleNamespace(generate_pdf_report=True, report_filename="job.pdf")
    callbacks = []
    job = ReportJob(*audit, config, on_complete=lambda result: callbacks.append((result, threading.current_thread())))
    assert job.close(2)
    assert job.status == "complete"
    assert job.result.path.name == "job.pdf"
    assert job.result.trust_score == 70
    assert callbacks[0][0] == job.result
    assert callbacks[0][1] is not threading.current_thread()


def test_report_job_disabled_starts_no_thread(audit):
    config = SimpleNamespace(generate_pdf_report=False)
    with patch("proctoring.storage.report_generator.threading.Thread") as thread:
        job = ReportJob(*audit, config)
        assert job.status == "disabled"
        assert job.close()
        thread.assert_not_called()


def test_report_failure_is_fail_soft_and_sanitized(audit):
    config = SimpleNamespace(generate_pdf_report=True, report_filename="job.pdf")
    with patch("proctoring.storage.report_generator.generate_report", side_effect=OSError("private user data")):
        job = ReportJob(*audit, config)
        assert job.close()
    assert job.status == "failed"
    assert job.result.path is None
    assert job.result.error == "PDF generation failed (OSError)"


def test_report_shutdown_wait_is_bounded(audit):
    entered, release = threading.Event(), threading.Event()
    def hold(*args):
        entered.set()
        release.wait(3)
        raise OSError("stop fixture")
    config = SimpleNamespace(generate_pdf_report=True, report_filename="job.pdf")
    with patch("proctoring.storage.report_generator.generate_report", side_effect=hold):
        job = ReportJob(*audit, config)
        try:
            assert entered.wait(1)
            start = time.monotonic()
            assert not job.close(.01)
            assert time.monotonic() - start < .5
        finally:
            release.set()
            assert job.close(1)
