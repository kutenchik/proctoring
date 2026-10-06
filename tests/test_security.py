import math
from concurrent.futures import ThreadPoolExecutor

import pytest

from proctoring.clock import FakeClock
from proctoring.security import EmergencyRelease, HeartbeatWatchdog, NoOpProtection, PinVerifier


def test_protection_never_enables_blocking():
    protection = NoOpProtection()
    protection.arm()
    assert protection.armed
    assert protection.blocking_enabled is False
    with pytest.raises(ValueError, match="disabled"):
        NoOpProtection(blocking_enabled=True)


def test_release_idempotent_and_can_rearm():
    protection = NoOpProtection()
    protection.arm()
    protection.release("normal_exit")
    protection.release("second_call")
    assert not protection.armed
    assert protection.release_reason == "normal_exit"
    protection.arm()
    assert protection.release_reason is None
    assert protection.armed


def test_emergency_releases_before_callback_and_invokes_once():
    protection = NoOpProtection()
    protection.arm()
    states = []
    emergency = EmergencyRelease(protection, lambda: states.append(protection.armed))
    assert emergency.trigger()
    assert not emergency.trigger()
    assert states == [False]
    assert emergency.triggered
    assert protection.release_reason == "emergency_shortcut"


def test_emergency_callback_error_cannot_prevent_release():
    protection = NoOpProtection()
    protection.arm()

    def fail():
        assert not protection.armed
        raise RuntimeError("UI finalization failed")

    emergency = EmergencyRelease(protection, fail)
    with pytest.raises(RuntimeError, match="UI finalization failed"):
        emergency.trigger()
    assert not protection.armed
    assert not emergency.trigger()


def test_concurrent_emergency_triggers_callback_once():
    protection = NoOpProtection()
    protection.arm()
    calls = []
    emergency = EmergencyRelease(protection, lambda: calls.append("released"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: emergency.trigger(), range(20)))
    assert sum(results) == 1
    assert calls == ["released"]


def test_watchdog_monotonic_cutoff_and_no_rearming():
    clock = FakeClock()
    protection = NoOpProtection()
    protection.arm()
    watchdog = HeartbeatWatchdog(protection, 5.0, clock)
    clock.advance(4.9)
    clock.timestamp = "1900-01-01T00:00:00+00:00"
    assert not watchdog.check()
    clock.advance(0.1)
    assert watchdog.check()
    assert protection.release_reason == "heartbeat_timeout"
    assert not watchdog.check()
    watchdog.heartbeat()
    assert not protection.armed


def test_heartbeat_postpones_watchdog():
    clock = FakeClock()
    protection = NoOpProtection()
    protection.arm()
    watchdog = HeartbeatWatchdog(protection, 5.0, clock)
    clock.advance(4)
    watchdog.heartbeat()
    clock.advance(4)
    assert not watchdog.check()
    clock.advance(1)
    assert watchdog.check()


@pytest.mark.parametrize("timeout", [0, -1, math.inf, math.nan])
def test_watchdog_rejects_invalid_timeouts(timeout):
    with pytest.raises(ValueError):
        HeartbeatWatchdog(NoOpProtection(), timeout, FakeClock())


def test_pin_verification_preserves_leading_zeroes_and_is_salted():
    first = PinVerifier("0246")
    second = PinVerifier("0246")
    assert first.verify("0246")
    assert not first.verify("246")
    assert not first.verify("0247")
    assert not first.verify(246)
    assert first._salt != second._salt
    assert first._digest != second._digest
    assert "0246" not in repr(vars(first))


def test_empty_pin_rejected():
    with pytest.raises(ValueError):
        PinVerifier("")
