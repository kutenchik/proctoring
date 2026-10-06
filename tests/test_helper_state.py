import pytest

from proctoring.security.helper import HelperRuntime


class FakeClock:
    now = 10.0

    def __call__(self):
        return self.now


class FakeBackend:
    def __init__(self, pid, hwnd, blocking, on_event, on_emergency):
        self.pid, self.hwnd, self.blocking = pid, hwnd, blocking
        self.on_event, self.on_emergency = on_event, on_emergency
        self.hook_installed = self.hotkey_registered = False
        self.pumps = self.polls = 0

    def enable(self):
        self.hook_installed = self.hotkey_registered = True

    def release(self):
        self.hook_installed = self.hotkey_registered = False

    def pump(self):
        self.pumps += 1

    def poll_foreground(self):
        self.polls += 1


@pytest.fixture
def harness():
    events = []
    clock = FakeClock()
    runtime = HelperRuntime(123, events.append, clock=clock, backend_factory=FakeBackend)
    return runtime, clock, events


def arm(runtime, **kwargs):
    runtime.command({"command": "enable", "pid": 123, "hwnd": 456,
                     "request_id": "arm", **kwargs})


def test_audit_enable_disable_and_response_id(harness):
    runtime, clock, events = harness
    arm(runtime)
    assert runtime.lease.armed and not runtime.lease.blocking_enabled
    assert events[-1]["request_id"] == "arm"
    assert events[-1]["hook_installed"] and events[-1]["hotkey_registered"]
    runtime.command({"command": "disable", "request_id": "off"})
    assert not runtime.lease.armed and runtime.backend is None
    assert events[-1]["request_id"] == "off"
    assert not events[-1]["hook_installed"] and not events[-1]["hotkey_registered"]


def test_repeated_enable_disable(harness):
    runtime, _, _ = harness
    for _ in range(5):
        arm(runtime)
        assert runtime.lease.armed
        runtime.command({"command": "disable"})
        assert not runtime.lease.armed


def test_backend_release_precedes_status_or_emergency_evidence(harness):
    runtime, _, events = harness
    arm(runtime, blocking=True)
    backend = runtime.backend
    runtime.emit = lambda event: (events.append(event),
                                  pytest.fail("Native restrictions still installed")
                                  if backend.hook_installed else None)
    runtime.command({"command": "emergency", "request_id": "recover"})
    assert events[-1]["status"] == "RECOVERY"
    assert events[-1]["request_id"] == "recover"
    assert events[-2]["event_type"] == "EMERGENCY_RELEASE"


def test_native_emergency_callback_releases_without_ui(harness):
    runtime, _, events = harness
    arm(runtime)
    runtime.backend.on_emergency()
    assert not runtime.lease.armed
    assert events[-2]["event_type"] == "EMERGENCY_RELEASE"


@pytest.mark.parametrize("condition,reason", [
    ({"parent_alive": False}, "parent_exited"),
    ({"input_open": False}, "stdin_eof"),
])
def test_parent_death_and_eof_release_even_before_first_heartbeat(harness, condition, reason):
    runtime, _, events = harness
    arm(runtime)
    runtime.tick(**condition)
    assert not runtime.lease.armed and runtime.stop_requested
    assert runtime.lease.reason == reason
    assert events[-2]["event_type"] == "PROTECTION_RECOVERY"


def test_lost_heartbeat_recovery_remains_latched(harness):
    runtime, clock, events = harness
    arm(runtime, heartbeat_timeout=1)
    clock.now = 11
    runtime.tick()
    assert runtime.lease.reason == "heartbeat_timeout" and not runtime.lease.armed
    runtime.command({"command": "heartbeat", "sent_at": 11})
    runtime.command({"command": "disable", "reason": "session_end"})
    assert not runtime.lease.armed and events[-1]["status"] == "RECOVERY"


@pytest.mark.parametrize("sent_at", [9.0, 10.6, float("nan"), float("inf")])
def test_stale_and_future_heartbeat_cannot_extend_lease(harness, sent_at):
    runtime, clock, events = harness
    arm(runtime, heartbeat_timeout=1)
    clock.now = 10.5
    runtime.command({"command": "heartbeat", "sent_at": sent_at, "request_id": "beat"})
    assert runtime.lease.last_heartbeat == 10
    assert events[-1]["kind"] == "error" and events[-1]["request_id"] == "beat"


def test_heartbeat_uses_sent_time_not_queue_processing_time(harness):
    runtime, clock, _ = harness
    arm(runtime, heartbeat_timeout=1)
    clock.now = 10.9
    runtime.command({"command": "heartbeat", "sent_at": 10.4})
    clock.now = 11.4
    runtime.tick()
    assert not runtime.lease.armed


@pytest.mark.parametrize("fields", [{"pid": 999}, {"hwnd": 0}, {"blocking": "false"},
                                   {"heartbeat_timeout": 0}, {"foreground_poll_ms": 0}])
def test_invalid_enable_never_installs_hooks(harness, fields):
    runtime, _, events = harness
    arm(runtime, **fields)
    assert runtime.backend is None and not runtime.lease.armed
    assert events[-2]["kind"] == "error"
    assert events[-2]["request_id"] == "arm"


def test_hook_install_failure_rolls_back(harness):
    runtime, _, events = harness
    backends = []

    class FailedBackend(FakeBackend):
        def enable(self):
            super().enable()
            backends.append(self)
            raise OSError("Hotkey is unavailable")

    runtime.backend_factory = FailedBackend
    arm(runtime, blocking=True)
    assert not backends[0].hook_installed
    assert runtime.backend is None and not runtime.lease.armed
    assert events[-2]["kind"] == "error"


def test_shutdown_and_bounded_lease(harness):
    runtime, clock, events = harness
    arm(runtime, max_session_seconds=0.5)
    clock.now = 10.5
    runtime.tick()
    assert runtime.lease.reason == "lease_expired" and not runtime.lease.armed
    runtime.command({"command": "shutdown", "request_id": 42})
    assert runtime.stop_requested and events[-1]["request_id"] == 42


def test_callback_failure_becomes_recovery(harness):
    runtime, _, events = harness
    arm(runtime)
    runtime.backend.on_event("PROTECTION_RECOVERY", {"reason": "keyboard_callback_error"})
    assert runtime.backend is None and not runtime.lease.armed
    assert events[-1]["status"] == "RECOVERY"
