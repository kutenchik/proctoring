"""Optional checks never read camera frames or perform network requests."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from threading import Event
from unittest.mock import patch

import pytest
from PySide6.QtCore import QObject, Signal, QMimeData
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from proctoring.settings import SystemChecksConfig
from proctoring.security.system_checks import SystemIntegrityChecker, detect_vm_vendor, MULTIMONITOR_REASON


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("count,ready", [(0, True), (1, True), (2, False), (3, False)])
def test_monitor_enumeration_and_hotplug(app, count, ready):
    checker = SystemIntegrityChecker(SystemChecksConfig(block_multimonitor=True))
    with patch.object(QGuiApplication, "screens", return_value=[object()] * count):
        # Resolve method at call time as real hot-plug queries do.
        checker._screens_provider = QGuiApplication.screens
        status = checker.status()
    assert status["ready"] is ready
    assert status["screen_count"] == count
    assert status["reason"] == (MULTIMONITOR_REASON if count > 1 else "")


def test_display_removal_unblocks_without_restart(app):
    screens = [object(), object()]
    checker = SystemIntegrityChecker(SystemChecksConfig(block_multimonitor=True), screens_provider=lambda: screens)
    assert not checker.status()["ready"]
    screens.pop()
    assert checker.status()["ready"]


def test_disabled_checks_create_no_worker_or_clipboard_connection(app):
    checker = SystemIntegrityChecker(SystemChecksConfig(), screens_provider=lambda: pytest.fail("screens queried"))
    checker.start_vm_check()
    checker.start_exam()
    assert checker.status()["ready"]
    assert checker._vm_thread is None
    assert not checker._clipboard_connected
    assert checker.drain_events() == []


@pytest.mark.parametrize("values,expected", [
    (["VMware, Inc."], "VMware"), (["Oracle", "VirtualBox"], "VirtualBox"),
    (["QEMU Standard PC"], "QEMU"), (["Xen"], "Xen"),
    (["Microsoft Corporation", "Virtual Machine"], "Microsoft Virtual Machine"),
    (["Microsoft Corporation", "Surface Laptop"], None), (["ASUSTeK", "Intel"], None),
])
def test_vm_heuristic_requires_specific_vendor_signals(values, expected):
    assert detect_vm_vendor(values) == expected


def test_vm_probe_is_background_and_fail_soft(app):
    begun, release = Event(), Event()
    def probe():
        begun.set()
        release.wait(2)
        raise OSError("not logged")
    checker = SystemIntegrityChecker(SystemChecksConfig(vm_check_enabled=True), vm_probe=probe)
    checker.start_vm_check()
    assert begun.wait(1)
    assert checker.status()["ready"]
    assert checker.metadata()["virtual_machine"]["status"] == "checking"
    release.set()
    checker.close(1)
    assert checker.metadata()["virtual_machine"]["reason"] == "probe_failed"
    assert checker.drain_events() == []


def test_vm_metadata_and_audit_event_are_identifiable(app):
    checker = SystemIntegrityChecker(SystemChecksConfig(vm_check_enabled=True),
        vm_probe=lambda: {"status": "complete", "suspected": True, "vendor": "QEMU"})
    checker.start_vm_check()
    checker.close(1)
    assert checker.metadata()["virtual_machine"]["suspected"]
    assert checker.metadata()["virtual_machine"]["audit_code"] == "VIRTUAL_MACHINE_DETECTED"
    assert checker.drain_events()[0]["event_type"] == "VIRTUAL_MACHINE_DETECTED"
    assert checker.drain_events() == []


class Clipboard(QObject):
    dataChanged = Signal()
    def __init__(self):
        super().__init__()
        self.mime = QMimeData()
        self.clear_count = 0
    def mimeData(self):
        return self.mime
    def set_text(self, value):
        self.mime.setText(value)
        self.dataChanged.emit()
    def clear(self):
        self.clear_count += 1
        self.mime.clear()
        self.dataChanged.emit()


def test_clipboard_guard_only_active_during_exam_and_never_retains_contents(app):
    clipboard = Clipboard()
    checker = SystemIntegrityChecker(SystemChecksConfig(clipboard_guard_enabled=True), clipboard=clipboard)
    clipboard.set_text("private before exam")
    assert not checker.drain_events()
    checker.start_exam()
    assert clipboard.clear_count == 1
    event = checker.drain_events()[0]
    assert event["event_type"] == "CLIPBOARD_ACCESSED"
    assert "private" not in str(event)
    clipboard.set_text("")
    assert clipboard.clear_count == 1
    clipboard.set_text("private copied text")
    assert clipboard.clear_count == 2  # clear-induced signal does not recurse.
    assert len(checker.drain_events()) == 1
    checker.stop()
    clipboard.set_text("after exam")
    assert clipboard.clear_count == 2
    assert not checker.drain_events()
    checker.stop()  # Idempotent cleanup.


def test_callback_does_not_duplicate_clipboard_audit_in_drain(app):
    clipboard, calls = Clipboard(), []
    checker = SystemIntegrityChecker(SystemChecksConfig(clipboard_guard_enabled=True), clipboard=clipboard)
    checker.start_exam(calls.append)
    clipboard.set_text("test")
    assert len(calls) == 1
    assert checker.drain_events() == []
    checker.stop()


def test_clipboard_guard_does_not_materialize_image_payloads(app):
    clipboard = Clipboard()
    checker = SystemIntegrityChecker(SystemChecksConfig(clipboard_guard_enabled=True), clipboard=clipboard)
    checker.start_exam()
    class LazyImage:
        def formats(self):
            return ["image/png"]
        def data(self, _):
            pytest.fail("Large image bytes must not be materialized")
        def clear(self):
            self.formats = lambda: []
    clipboard.mime = LazyImage()
    clipboard.dataChanged.emit()
    assert clipboard.clear_count == 1
    assert len(checker.drain_events()) == 1
    checker.stop()
