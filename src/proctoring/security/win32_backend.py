"""Transient Windows hooks owned by the helper process, never persistent policy.

No other-process termination, BlockInput, secure-sequence handling, registry
changes, or typed-character collection occurs here. Exiting this helper removes
its hooks if a native release operation fails.
"""

import ctypes
from ctypes import wintypes
import os
import time
from typing import Callable

from .policy import KeyboardPolicy, ModifierState, WindowPolicy


class ParentProcess:
    """Retain a handle so PID reuse cannot extend the original parent's lease."""

    def __init__(self, pid: int):
        if os.name != "nt":
            raise OSError("Windows protection is available only on Windows")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def alive(self) -> bool:
        return bool(self.handle) and self.kernel32.WaitForSingleObject(self.handle, 0) == 0x102

    def close(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


class WindowsBackend:
    HOTKEY_ID = 0x4D51
    FOREGROUND_FAILURE_SECONDS = 1.0

    def __init__(self, pid: int, hwnd: int, blocking: bool,
                 on_event: Callable[[str, dict], None], on_emergency: Callable[[], None], *,
                 host_binding=None, desktop_lock_owned=False, clock=time.monotonic):
        if os.name != "nt":
            raise OSError("Windows protection is available only on Windows")
        self.pid, self.hwnd, self.blocking = pid, hwnd, blocking
        self.on_event, self.on_emergency = on_event, on_emergency
        self.keyboard = KeyboardPolicy(blocking)
        self.modifiers = ModifierState()
        self.windows = WindowPolicy(pid)
        self.host_binding = host_binding
        self.desktop_lock_owned = desktop_lock_owned
        self._desktop_lock = None
        self._identity_native = None
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.hook = None
        self.hotkey_registered = False
        self._last_allowed = hwnd
        self._clock = clock
        self._foreign_since = None
        self._foreground_attempts = 0
        self._configure()

    @property
    def hook_installed(self) -> bool:
        return bool(self.hook)

    def _configure(self) -> None:
        u = self.user32
        self._hook_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                            wintypes.WPARAM, wintypes.LPARAM)

        class KeyboardData(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        self._keyboard_data_type = KeyboardData
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, self._hook_type, wintypes.HINSTANCE,
                                        wintypes.DWORD]
        u.SetWindowsHookExW.restype = wintypes.HANDLE
        u.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
        u.UnhookWindowsHookEx.restype = wintypes.BOOL
        u.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM,
                                    wintypes.LPARAM]
        u.CallNextHookEx.restype = ctypes.c_ssize_t
        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u.RegisterHotKey.restype = wintypes.BOOL
        u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u.UnregisterHotKey.restype = wintypes.BOOL
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT, wintypes.UINT]
        u.PeekMessageW.restype = wintypes.BOOL
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.TranslateMessage.restype = wintypes.BOOL
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.restype = ctypes.c_ssize_t
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        for name in ("IsWindow", "IsWindowVisible", "IsIconic", "SetForegroundWindow"):
            fn = getattr(u, name)
            fn.argtypes = [wintypes.HWND]
            fn.restype = wintypes.BOOL
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.ShowWindow.restype = wintypes.BOOL
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    def window_pid(self, hwnd: int) -> int:
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def enable(self) -> None:
        if self.host_binding is not None and not self.host_binding.valid():
            raise ValueError('Electron native binding is no longer valid')
        if not self.user32.IsWindow(self.hwnd) or self.window_pid(self.hwnd) != self.pid:
            raise ValueError("Exam HWND must belong to the exact approved parent process")
        if not self.desktop_lock_owned:
            from .electron_binding import NativeIdentity
            self._identity_native = NativeIdentity()
            self._desktop_lock = self._identity_native.desktop_mutex()
        self._callback = self._hook_type(self._keyboard_callback)
        # Seed held modifiers outside the callback. LowLevelKeyboardProc runs
        # before Windows updates async key state; thereafter track transitions.
        self.modifiers = ModifierState(vk for vk in range(0xA0, 0xA6)
                                       if self.user32.GetAsyncKeyState(vk) & 0x8000)
        try:
            # MOD_NOREPEAT | CONTROL | SHIFT | ALT. This is a backup to the hook.
            self.hotkey_registered = bool(self.user32.RegisterHotKey(
                None, self.HOTKEY_ID, 0x4000 | 0x0002 | 0x0004 | 0x0001, 0x51))
            if not self.hotkey_registered:
                raise ctypes.WinError(ctypes.get_last_error())
            self.hook = self.user32.SetWindowsHookExW(
                13, self._callback, self.kernel32.GetModuleHandleW(None), 0)
            if not self.hook:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.release()
            raise

    def release(self) -> None:
        # These calls run on the hook/message-pump thread and are idempotent.
        failed = False
        if self.hook:
            try:
                if self.user32.UnhookWindowsHookEx(self.hook):
                    self.hook = None
                else:
                    failed = True
            except BaseException:
                failed = True
        if self.hotkey_registered:
            try:
                if self.user32.UnregisterHotKey(None, self.HOTKEY_ID):
                    self.hotkey_registered = False
                else:
                    failed = True
            except BaseException:
                failed = True
        if failed:
            # This backend runs only in the disposable helper. Never report a
            # successful release without native confirmation. A raised exception
            # can be swallowed by ctypes callbacks; process teardown instead
            # guarantees Windows removes this helper's remaining resources.
            os._exit(4)
        if self._desktop_lock:
            self._identity_native.release_mutex(self._desktop_lock)
            self._desktop_lock = None

    def _keyboard_callback(self, code: int, message: int, pointer: int) -> int:
        if code < 0:
            return self.user32.CallNextHookEx(self.hook, code, message, pointer)
        try:
            if message not in (0x0100, 0x0101, 0x0104, 0x0105):
                return self.user32.CallNextHookEx(self.hook, code, message, pointer)
            data = ctypes.cast(pointer, ctypes.POINTER(self._keyboard_data_type)).contents
            down = message in (0x0100, 0x0104)
            self.modifiers.update(data.vkCode, down)
            modifiers = self.modifiers.values()
            modifiers["alt"] = modifiers["alt"] or bool(data.flags & 0x20)
            decision = self.keyboard.evaluate(data.vkCode, down, **modifiers)
            if decision.emergency:
                # Callback releases native restrictions before queuing any output.
                self.on_emergency()
                return self.user32.CallNextHookEx(None, code, message, pointer)
            if decision.action and decision.emit:
                self.on_event(decision.action, {"suppressed": decision.suppress,
                                               "audit": not self.blocking})
            if decision.suppress:
                return 1
        except BaseException:
            # A failing callback must fail open rather than trap user input.
            self.release()
            self.on_event("PROTECTION_RECOVERY", {"reason": "keyboard_callback_error"})
        return self.user32.CallNextHookEx(self.hook, code, message, pointer)

    def pump(self) -> None:
        message = wintypes.MSG()
        # Bound work so an input flood cannot starve the independent lease check.
        for _ in range(200):
            if not self.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                break
            if message.message == 0x0312 and message.wParam == self.HOTKEY_ID:
                self.on_emergency()
            else:
                self.user32.TranslateMessage(ctypes.byref(message))
                self.user32.DispatchMessageW(ctypes.byref(message))

    def poll_foreground(self) -> None:
        if not self.hook:
            self._foreign_since = None
            self._foreground_attempts = 0
            return
        hwnd = int(self.user32.GetForegroundWindow() or 0)
        if not hwnd:
            # No secure-desktop action. Preserve an existing loss deadline: a
            # transient NULL during foreign switches is not confirmed recovery.
            return
        pid = self.window_pid(hwnd)
        allowed = self.host_binding.allows(hwnd) if self.host_binding else self.windows.allowed(pid)
        if allowed:
            self._last_allowed = hwnd
            self._foreign_since = None
            self._foreground_attempts = 0
            self.windows.should_report(hwnd, pid)
            return
        if self.windows.should_report(hwnd, pid, allowed=False if self.host_binding else None):
            self.on_event("UNAUTHORIZED_WINDOW", {
                "hwnd": hwnd, "pid": pid, "audit": not self.blocking,
                "action": "foreground_switch"})
        if not self.blocking:
            self._foreign_since = None
            self._foreground_attempts = 0
            return
        now = self._clock()
        if self._foreign_since is None:
            self._foreign_since = now
        self._foreground_attempts += 1
        target = self._last_allowed
        if (not self.user32.IsWindowVisible(target) or self.window_pid(target) != self.pid or
                (self.host_binding and not self.host_binding.allows(target))):
            target = self.hwnd
        foreground_requested = False
        if (self.user32.IsWindow(target) and self.window_pid(target) == self.pid and
                (not self.host_binding or self.host_binding.allows(target))):
            if self.user32.IsIconic(target):
                self.user32.ShowWindow(target, 9)  # SW_RESTORE
            # Windows may legitimately refuse this. Never attach to other threads.
            foreground_requested = bool(self.user32.SetForegroundWindow(target))
        # A successful BOOL is not proof that this HWND remains foreground.
        # The uninterrupted outage only clears after observing an allowed window.
        current = int(self.user32.GetForegroundWindow() or 0)
        if not current:
            return
        current_pid = self.window_pid(current)
        current_allowed = self.host_binding.allows(current) if self.host_binding else self.windows.allowed(current_pid)
        if current_allowed:
            self._last_allowed = current
            self._foreign_since = None
            self._foreground_attempts = 0
            self.windows.should_report(current, current_pid)
            return
        elapsed = self._clock() - self._foreign_since
        if elapsed >= self.FOREGROUND_FAILURE_SECONDS:
            # Remove native restrictions before evidence/IPC or media cleanup.
            # The helper's existing recovery path makes the exam terminal; it
            # must not keep claiming protected operation in another application.
            attempts = self._foreground_attempts
            self.release()
            self.on_event('PROTECTION_RECOVERY', {
                'reason': 'foreground_containment_failed', 'elapsed_seconds': elapsed,
                'attempts': attempts,
                'set_foreground_returned': foreground_requested,
                'hwnd': current, 'pid': current_pid, 'target_hwnd': target,
                'failure_bound_seconds': self.FOREGROUND_FAILURE_SECONDS,
            })
