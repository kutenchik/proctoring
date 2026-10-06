"""Verify native release failure paths without installing Windows resources."""
from types import SimpleNamespace

import pytest

from proctoring.security import win32_backend
from proctoring.security.win32_backend import WindowsBackend


class HelperExited(BaseException):
    pass


def backend(monkeypatch, hook_result=True, hotkey_result=True):
    calls = []

    def unhook(handle):
        calls.append(("unhook", handle))
        if isinstance(hook_result, BaseException):
            raise hook_result
        return hook_result

    def unregister(hwnd, identifier):
        calls.append(("unregister", hwnd, identifier))
        if isinstance(hotkey_result, BaseException):
            raise hotkey_result
        return hotkey_result

    def exit_helper(code):
        calls.append(("exit_helper", code))
        raise HelperExited(code)

    monkeypatch.setattr(win32_backend.os, "_exit", exit_helper)
    instance = WindowsBackend.__new__(WindowsBackend)
    instance.hook = 123
    instance.hotkey_registered = True
    instance.user32 = SimpleNamespace(UnhookWindowsHookEx=unhook, UnregisterHotKey=unregister)
    return instance, calls


def test_successful_release_removes_both_resources_and_is_idempotent(monkeypatch):
    instance, calls = backend(monkeypatch)
    instance.release()
    instance.release()
    assert calls == [("unhook", 123), ("unregister", None, instance.HOTKEY_ID)]
    assert instance.hook is None
    assert instance.hotkey_registered is False


@pytest.mark.parametrize("hook_result,hotkey_result", [
    (False, True), (True, False), (False, False),
    (OSError("unhook failed"), True), (True, OSError("unregister failed")),
    (OSError("unhook failed"), OSError("unregister failed")),
    (KeyboardInterrupt(), True), (True, KeyboardInterrupt()),
])
def test_release_failure_attempts_both_then_exits_only_helper(monkeypatch, hook_result, hotkey_result):
    instance, calls = backend(monkeypatch, hook_result, hotkey_result)
    with pytest.raises(HelperExited) as exit_info:
        instance.release()
    assert exit_info.value.args == (4,)
    assert calls == [("unhook", 123), ("unregister", None, instance.HOTKEY_ID), ("exit_helper", 4)]
    # Failed removals must not be represented locally as confirmed release.
    assert instance.hook == (None if hook_result is True else 123)
    assert instance.hotkey_registered is (False if hotkey_result is True else True)


@pytest.mark.parametrize("hook_present,hotkey_present", [(False, True), (True, False), (False, False)])
def test_partial_or_empty_registration_releases_only_owned_resources(monkeypatch, hook_present, hotkey_present):
    instance, calls = backend(monkeypatch)
    instance.hook = 123 if hook_present else None
    instance.hotkey_registered = hotkey_present
    instance.release()
    expected = []
    if hook_present:
        expected.append(("unhook", 123))
    if hotkey_present:
        expected.append(("unregister", None, instance.HOTKEY_ID))
    assert calls == expected
    assert instance.hook is None
    assert instance.hotkey_registered is False
