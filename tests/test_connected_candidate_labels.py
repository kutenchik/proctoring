"""Identity display compatibility only; no remote network or PDF writer runs."""
from PySide6.QtWidgets import QApplication

from proctoring.storage.report_generator import build_report_document
from proctoring.storage.remote_dispatcher import format_telegram_message


def test_connected_full_name_and_institutional_id_in_report(tmp_path):
    app = QApplication.instance() or QApplication([])
    summary = {'candidate': {'full_name': 'Әлия <Әкім>', 'first_name': '', 'last_name': '',
                             'group_id': 'CS-1', 'student_id': 'S-123'}, 'session_id': 'safe-test'}
    report = build_report_document(tmp_path, summary, [])
    assert 'Әлия <Әкім>' in report.toPlainText()
    assert 'CS-1 / S-123' in report.toPlainText()
    assert '&lt;Әкім&gt;' in report.toHtml()


def test_existing_remote_format_uses_connected_full_name_without_sending():
    result = format_telegram_message('session_start', {'candidate': {'full_name': 'Алия Әкім', 'group_id': 'CS-1'}})
    assert 'Candidate: Алия Әкім' in result
