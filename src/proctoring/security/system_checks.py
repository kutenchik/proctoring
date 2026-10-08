"""Optional preflight checks and a GUI-thread clipboard guard.

VM detection is a best-effort vendor heuristic, not evidence of misconduct.
No clipboard content is persisted. Registry work never runs on the Qt thread.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import sys
import threading
from typing import Callable

from PySide6.QtCore import QThread
from PySide6.QtGui import QGuiApplication

from ..settings import SystemChecksConfig


MULTIMONITOR_REASON = "Multiple monitors detected. Please disconnect external displays before proceeding."


def detect_vm_vendor(values: list[str]) -> str | None:
    text = " ".join(str(value) for value in values).casefold()
    for token, vendor in (("vmware", "VMware"), ("virtualbox", "VirtualBox"),
                          ("innotek", "VirtualBox"), ("qemu", "QEMU"), ("xen", "Xen")):
        if token in text:
            return vendor
    if "microsoft" in text and "virtual machine" in text:
        return "Microsoft Virtual Machine"
    return None


def read_windows_vm_metadata() -> dict:
    if sys.platform != "win32":
        return {"status": "unavailable", "reason": "unsupported_platform", "suspected": False}
    try:
        import winreg
        values = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as key:
            for name in ("SystemManufacturer", "SystemProductName", "BIOSVendor", "BIOSVersion",
                         "BaseBoardManufacturer", "BaseBoardProduct", "SystemBiosVersion"):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                values.extend(value if isinstance(value, list) else [str(value)])
        vendor = detect_vm_vendor(values)
        return {"status": "complete", "suspected": vendor is not None, "vendor": vendor,
                "method": "registry_vendor_heuristic", "not_proof": True}
    except (OSError, ImportError):
        return {"status": "unavailable", "reason": "registry_unavailable", "suspected": False}


class SystemIntegrityChecker:
    def __init__(self, config: SystemChecksConfig, *, screens_provider: Callable | None = None,
                 clipboard=None, vm_probe: Callable | None = None):
        self.config = config
        self._screens_provider = screens_provider or QGuiApplication.screens
        self._clipboard = clipboard
        self._vm_probe = vm_probe or read_windows_vm_metadata
        self._vm = {"status": "not_started" if config.vm_check_enabled else "disabled", "suspected": False}
        self._lock = threading.Lock()
        self._events = deque()
        self._vm_thread = None
        self._active = False
        self._clearing = False
        self._clipboard_connected = False
        self._callback = None

    def status(self) -> dict:
        count, reason = None, ""
        if self.config.block_multimonitor:
            try:
                count = len(self._screens_provider())
                if count > 1:
                    reason = MULTIMONITOR_REASON
            except (RuntimeError, OSError):
                # Missing display enumeration is explicitly unavailable, not
                # proof of a second display. Headless demos remain usable.
                reason = "Display count unavailable; system check could not verify displays."
        return {"ready": count is None or count <= 1, "screen_count": count,
                "reason": reason, "vm": self.metadata()["virtual_machine"]}

    def metadata(self) -> dict:
        with self._lock:
            return {"virtual_machine": deepcopy(self._vm),
                    "clipboard_guard_enabled": self.config.clipboard_guard_enabled,
                    "block_multimonitor": self.config.block_multimonitor}

    def start_vm_check(self) -> None:
        if not self.config.vm_check_enabled or self._vm_thread is not None:
            return
        with self._lock:
            self._vm = {"status": "checking", "suspected": False}
        self._vm_thread = threading.Thread(target=self._check_vm, name="system-vm-check", daemon=True)
        self._vm_thread.start()

    def _check_vm(self):
        try:
            result = self._vm_probe()
            if not isinstance(result, dict):
                raise ValueError("Invalid probe result")
            result = deepcopy(result)
            if result.get("suspected"):
                result["audit_code"] = "VIRTUAL_MACHINE_DETECTED"
        except Exception:
            result = {"status": "unavailable", "reason": "probe_failed", "suspected": False}
        with self._lock:
            self._vm = result
            if result.get("suspected"):
                self._events.append({"event_type": "VIRTUAL_MACHINE_DETECTED",
                                     "description": "Virtual machine vendor heuristic matched; requires review",
                                     "details": deepcopy(result)})

    def drain_events(self) -> list[dict]:
        with self._lock:
            records = list(self._events)
            self._events.clear()
        return records

    @staticmethod
    def _require_gui_thread():
        app = QGuiApplication.instance()
        if app is not None and QThread.currentThread() != app.thread():
            raise RuntimeError("Clipboard operations must run on the Qt GUI thread")
        return app

    def start_exam(self, callback: Callable | None = None) -> None:
        if not self.config.clipboard_guard_enabled or self._active:
            return
        app = self._require_gui_thread()
        if self._clipboard is None:
            if app is None:
                return
            self._clipboard = QGuiApplication.clipboard()
        self._callback = callback
        self._active = True
        self._clipboard.dataChanged.connect(self._clipboard_changed)
        self._clipboard_connected = True
        self._clipboard_changed()

    def _clipboard_changed(self):
        if not self._active or self._clearing:
            return
        self._require_gui_thread()
        mime = self._clipboard.mimeData()
        formats = list(mime.formats()) if mime is not None else []
        # Inspect format availability only: requesting image/custom payloads
        # can materialize a large or lazily supplied clipboard image on Qt.
        # Retain the cheap empty-text check used by ordinary text clear signals.
        if not formats or (formats == ["text/plain"] and not mime.text()):
            return
        self._clearing = True
        try:
            self._clipboard.clear()
        finally:
            self._clearing = False
        event = {"event_type": "CLIPBOARD_ACCESSED", "description": "Clipboard content cleared during exam",
                 "details": {"content_retained": False}}
        if self._callback is not None:
            self._callback(deepcopy(event))
        else:
            with self._lock:
                self._events.append(event)

    def stop(self) -> None:
        self._require_gui_thread()
        self._active = False
        if self._clipboard_connected:
            try:
                self._clipboard.dataChanged.disconnect(self._clipboard_changed)
            except (RuntimeError, TypeError):
                pass
            self._clipboard_connected = False
        self._callback = None

    def close(self, timeout: float = 0.0) -> None:
        self.stop()
        if self._vm_thread is not None and timeout > 0:
            self._vm_thread.join(timeout=min(timeout, 2.0))
