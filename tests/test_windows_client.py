from dataclasses import replace
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from proctoring.config import DEFAULT_CONFIG, load_config
from proctoring.security import NoOpProtection, create_protection
from proctoring.security.settings import ProtectionConfig
from proctoring.security.windows import WindowsProtection
from proctoring.security.helper_process import OwnedHelperProcess


def test_safe_factory_never_starts_helper():
    adapter = create_protection(load_config())
    assert isinstance(adapter, NoOpProtection)
    adapter.configure_window(123, os.getpid())
    adapter.heartbeat()
    adapter.arm()
    assert adapter.status == "INACTIVE"
    assert adapter.drain_events() == []
    adapter.close()


def test_demo_config_explicitly_selects_windows_adapter():
    config = load_config(DEFAULT_CONFIG.with_name("protected-demo.example.toml"))
    assert config.protection.enabled
    adapter = create_protection(config)
    assert isinstance(adapter, WindowsProtection)
    assert adapter.blocking_enabled
    assert not adapter.armed
    assert adapter.status == "INACTIVE"
    assert adapter._process is None
    adapter.close()


def test_cannot_configure_another_process_or_invalid_window():
    adapter = WindowsProtection(ProtectionConfig(enabled=True))
    with pytest.raises(ValueError):
        adapter.configure_window(12, os.getpid() + 1)
    with pytest.raises(ValueError):
        adapter.configure_window(0, os.getpid())


def test_helper_acknowledgements_drive_status_and_event_records():
    adapter = WindowsProtection(ProtectionConfig(enabled=True))
    adapter._consume({"kind": "status", "armed": True, "blocking_enabled": True,
                      "status": "ACTIVE", "reason": None, "request_id": "start"})
    assert adapter.armed and adapter.status == "ACTIVE"
    adapter._consume({"kind": "security", "event_type": "BLOCKED_COPY",
                      "description": "Copy shortcut suppressed", "details": {"action": "Ctrl+C"}})
    event, = adapter.drain_events()
    assert event["event_type"] == "BLOCKED_COPY"
    assert event["timestamp"] and event["event_id"]
    assert event["details"] == {"action": "Ctrl+C"}
    assert adapter.drain_events() == []
    adapter._consume({"kind": "status", "armed": False, "blocking_enabled": False,
                      "status": "RECOVERY", "reason": "heartbeat_timeout"})
    adapter.release("normal_exit")
    assert adapter.status == "RECOVERY"
    assert adapter.release_reason == "heartbeat_timeout"


def test_failed_heartbeat_terminates_own_helper_and_latches_recovery(monkeypatch):
    adapter = WindowsProtection(ProtectionConfig(enabled=True))
    adapter._armed = True
    adapter._status = "ACTIVE"
    calls = []
    monkeypatch.setattr(adapter, "_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stalled")))
    monkeypatch.setattr(adapter, "_terminate_owned_helper", lambda: calls.append("terminate"))
    adapter.heartbeat()
    assert calls == ["terminate"]
    assert not adapter.armed and adapter.status == "RECOVERY"
    assert adapter.drain_events()[0]["event_type"] == "PROTECTION_RECOVERY"
    adapter.heartbeat()
    assert calls == ["terminate"]


def test_unacknowledged_disable_forces_release_before_return(monkeypatch):
    adapter = WindowsProtection(ProtectionConfig(enabled=True))
    adapter._armed = True
    calls = []
    monkeypatch.setattr(adapter, "_request", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")))
    monkeypatch.setattr(adapter, "_terminate_owned_helper", lambda: calls.append("terminated"))
    adapter.release("proctor_ended")
    assert calls == ["terminated"]
    assert adapter.status == "RECOVERY"
    assert not adapter.armed


def test_error_ack_is_not_overwritten_by_following_disarmed_status():
    adapter = WindowsProtection(ProtectionConfig(enabled=True))
    adapter._consume({"kind": "error", "message": "Emergency hotkey unavailable", "request_id": "enable"})
    adapter._consume({"kind": "status", "armed": False, "request_id": "enable"})
    assert adapter._responses["enable"]["message"] == "Emergency hotkey unavailable"


def native_handle_api():
    return SimpleNamespace(OpenProcess=Mock(return_value=987),
                           WaitForSingleObject=Mock(return_value=0x102),
                           TerminateProcess=Mock(return_value=True), CloseHandle=Mock(return_value=True))


def launcher(pid=123450):
    return SimpleNamespace(pid=pid, poll=Mock(return_value=None), terminate=Mock(),
                           wait=Mock(return_value=0), kill=Mock())


def test_retains_redirector_child_handle_after_verifying_ancestry():
    kernel = native_handle_api()
    launched = launcher()
    factory = Mock(return_value=SimpleNamespace(parents=lambda: [SimpleNamespace(pid=launched.pid)]))
    owned = OwnedHelperProcess(123451, launched, kernel32=kernel, process_factory=factory)
    assert owned.pid == 123451 and owned.alive()
    kernel.OpenProcess.assert_called_once_with(0x00100001, False, 123451)
    factory.assert_called_once_with(123451)
    kernel.WaitForSingleObject.side_effect = [0x102, 0]
    owned.terminate_and_wait()
    kernel.TerminateProcess.assert_called_once_with(987, 1)
    assert kernel.WaitForSingleObject.call_args.args == (987, 1000)
    # Termination uses the retained process handle; it never re-opens a PID.
    assert kernel.OpenProcess.call_count == 1
    owned.close()
    owned.close()
    kernel.CloseHandle.assert_called_once_with(987)


def test_direct_helper_process_also_retains_handle():
    kernel = native_handle_api()
    launched = launcher()
    factory = Mock(side_effect=AssertionError("Direct helper needs no ancestry query"))
    owned = OwnedHelperProcess(launched.pid, launched, kernel32=kernel, process_factory=factory)
    assert owned.pid == launched.pid
    owned.close()
    factory.assert_not_called()


@pytest.mark.parametrize("pid", [None, True, 0, -1, "123451", os.getpid()])
def test_invalid_helper_pids_are_never_opened_or_terminated(pid):
    kernel = native_handle_api()
    with pytest.raises(ValueError, match="PID"):
        OwnedHelperProcess(pid, launcher(), kernel32=kernel)
    kernel.OpenProcess.assert_not_called()
    kernel.TerminateProcess.assert_not_called()


def test_unrelated_helper_pid_is_rejected_without_termination():
    kernel = native_handle_api()
    factory = Mock(return_value=SimpleNamespace(parents=lambda: [SimpleNamespace(pid=77777)]))
    with pytest.raises(ValueError, match="not the launched process"):
        OwnedHelperProcess(123451, launcher(), kernel32=kernel, process_factory=factory)
    kernel.CloseHandle.assert_called_once_with(987)
    kernel.TerminateProcess.assert_not_called()


def test_launcher_exit_during_ownership_validation_rejects_handle():
    kernel = native_handle_api()
    launched = launcher()
    launched.poll.side_effect = [None, 0]
    with pytest.raises(ValueError, match="exited during ownership"):
        OwnedHelperProcess(launched.pid, launched, kernel32=kernel)
    kernel.CloseHandle.assert_called_once_with(987)
    kernel.TerminateProcess.assert_not_called()


def test_process_death_must_be_confirmed_after_termination():
    kernel = native_handle_api()
    launched = launcher()
    owned = OwnedHelperProcess(launched.pid, launched, kernel32=kernel)
    with pytest.raises(RuntimeError, match="not confirmed"):
        owned.terminate_and_wait(timeout=.05)
    assert kernel.WaitForSingleObject.call_args.args == (987, 50)
    owned.close()


def test_already_dead_helper_needs_no_termination():
    kernel = native_handle_api()
    launched = launcher()
    owned = OwnedHelperProcess(launched.pid, launched, kernel32=kernel)
    kernel.WaitForSingleObject.return_value = 0
    owned.terminate_and_wait()
    kernel.TerminateProcess.assert_not_called()
    owned.close()


def test_ready_ack_validates_and_retains_hook_owner_before_accepting(monkeypatch):
    adapter = WindowsProtection(ProtectionConfig(enabled=True))
    adapter._process = launcher()
    handle = Mock(pid=123451)
    factory = Mock(return_value=handle)
    monkeypatch.setattr("proctoring.security.windows.OwnedHelperProcess", factory)
    adapter._consume({"kind": "ready", "pid": 123451, "platform_supported": True})
    factory.assert_called_once_with(123451, adapter._process)
    assert adapter._ready and adapter._helper_process is handle
    with pytest.raises(ValueError, match="duplicate"):
        adapter._consume({"kind": "ready", "pid": 123452})
    assert adapter._helper_process is handle


def test_unverified_ready_never_allows_enable(monkeypatch):
    adapter = WindowsProtection(ProtectionConfig(enabled=True))
    adapter._process = launcher()
    monkeypatch.setattr("proctoring.security.windows.OwnedHelperProcess",
                        Mock(side_effect=ValueError("unrelated process")))
    with pytest.raises(ValueError, match="unrelated"):
        adapter._consume({"kind": "ready", "pid": 234561})
    assert not adapter._ready and adapter._helper_process is None
    adapter._process.terminate.assert_not_called()


def test_fallback_confirms_actual_owner_death_before_launcher_and_recovery(monkeypatch):
    adapter = WindowsProtection(ProtectionConfig(enabled=True))
    adapter._armed = True
    adapter._status = "ACTIVE"
    adapter._last_status = {"hook_installed": True, "hotkey_registered": True}
    order = []
    owner = SimpleNamespace(pid=123451)

    def terminate_owner(timeout):
        assert adapter.armed and adapter.status == "ACTIVE"
        assert adapter.diagnostics["hook_installed"] is True
        order.extend(["terminate_owner", "confirm_owner_dead"])

    owner.terminate_and_wait = terminate_owner
    adapter._helper_process = owner
    launched = launcher()
    launched.terminate.side_effect = lambda: order.append("terminate_launcher")
    launched.wait.side_effect = lambda timeout: order.append("wait_launcher")
    adapter._process = launched
    monkeypatch.setattr(adapter, "_request", Mock(side_effect=RuntimeError("missing ACK")))
    adapter.release("proctor_ended")
    assert order == ["terminate_owner", "confirm_owner_dead", "terminate_launcher", "wait_launcher"]
    assert adapter.status == "RECOVERY" and not adapter.armed
    assert adapter.diagnostics["termination_confirmed"] is True
    assert adapter.diagnostics["hook_installed"] is False
    assert adapter.diagnostics["hotkey_registered"] is False
    assert adapter.diagnostics["helper_pid"] == 123451


def test_failed_owner_termination_never_claims_release_or_kills_launcher(monkeypatch):
    adapter = WindowsProtection(ProtectionConfig(enabled=True))
    adapter._armed = True
    adapter._status = "ACTIVE"
    adapter._last_status = {"hook_installed": True, "hotkey_registered": True}
    adapter._helper_process = SimpleNamespace(
        terminate_and_wait=Mock(side_effect=RuntimeError("termination not confirmed")))
    adapter._process = launcher()
    monkeypatch.setattr(adapter, "_request", Mock(side_effect=RuntimeError("missing ACK")))
    with pytest.raises(RuntimeError, match="not confirmed"):
        adapter.release("proctor_ended")
    assert adapter.armed and adapter.status == "ACTIVE"
    assert adapter.diagnostics["hook_installed"] is True
    assert not adapter.drain_events()
    adapter._process.terminate.assert_not_called()


@pytest.mark.parametrize("old,new", [
    ("enabled = false\nheartbeat_timeout", "enabled = 1\nheartbeat_timeout"),
    ("heartbeat_timeout_seconds = 5.0", "heartbeat_timeout_seconds = 60"),
    ("startup_timeout_seconds = 5.0", "startup_timeout_seconds = inf"),
    ("foreground_poll_ms = 100", "foreground_poll_ms = 1"),
    ("validation_max_age_hours = 24.0", "validation_max_age_hours = 9999"),
    ('validation_report = "../artifacts/protection-validation.json"', 'validation_report = ""'),
])
def test_protection_config_rejects_unsafe_values(tmp_path, old, new):
    contents = DEFAULT_CONFIG.with_name("default.example.toml").read_text(encoding="utf-8")
    assert old in contents
    target = tmp_path / "bad.toml"
    target.write_text(contents.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(target)
