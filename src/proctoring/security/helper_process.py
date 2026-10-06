"""Retain the exact helper process, including Windows venv redirector children.

The handle is opened before validating ancestry and retained until cleanup. A
reused numeric PID can therefore never redirect fallback termination to another
process. Only the launched process or its verified descendant is accepted.
"""
import ctypes
from ctypes import wintypes
import os


class OwnedHelperProcess:
    def __init__(self, pid: int, launcher, *, kernel32=None, process_factory=None):
        if type(pid) is not int or pid <= 0 or pid == os.getpid():
            raise ValueError("Helper reported an invalid or parent-process PID")
        if launcher is None or launcher.poll() is not None:
            raise ValueError("Helper launcher is not running")
        if kernel32 is None:
            if os.name != "nt":
                raise OSError("Retained helper handles require Windows")
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32 = kernel32
        self.pid = pid
        self.handle = None
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        # PROCESS_TERMINATE | SYNCHRONIZE; the retained handle identifies the
        # actual process object even after it exits, rather than a mutable PID.
        self.handle = kernel32.OpenProcess(0x00100001, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.alive():
                raise ValueError("Reported helper process already exited")
            if process_factory is None:
                import psutil
                process_factory = psutil.Process
            if pid != launcher.pid:
                ancestors = process_factory(pid).parents()
                if not any(parent.pid == launcher.pid for parent in ancestors):
                    raise ValueError("Reported helper PID is not the launched process or its descendant")
            if launcher.poll() is not None or not self.alive():
                raise ValueError("Helper or launcher exited during ownership validation")
        except BaseException:
            self.close()
            raise

    def alive(self) -> bool:
        if self.handle is None:
            return False
        result = self.kernel32.WaitForSingleObject(self.handle, 0)
        if result == 0:
            return False
        if result == 0x102:  # WAIT_TIMEOUT
            return True
        raise ctypes.WinError(ctypes.get_last_error())

    def terminate_and_wait(self, timeout: float = 1.) -> None:
        if self.handle is None:
            raise RuntimeError("Helper process handle is closed")
        if not self.alive():
            return
        if not self.kernel32.TerminateProcess(self.handle, 1):
            # A natural exit can race with the termination request.
            if not self.alive():
                return
            raise ctypes.WinError(ctypes.get_last_error())
        result = self.kernel32.WaitForSingleObject(self.handle, max(1, int(timeout * 1000)))
        if result != 0:
            raise RuntimeError("Hook-owning helper termination was not confirmed within the deadline")

    def close(self) -> None:
        if self.handle is not None:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None
