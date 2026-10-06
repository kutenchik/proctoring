import pytest

from proctoring.security.policy import HelperLease, KeyboardPolicy, LoopWatchdog, ModifierState, WindowPolicy


@pytest.mark.parametrize("vk,modifiers,action", [
    (0x09, {"alt": True}, "BLOCKED_ALT_TAB"),
    (0x09, {"alt": True, "shift": True}, "BLOCKED_ALT_TAB"),
    (0x5B, {}, "BLOCKED_WINDOWS_KEY"),
    (0x5C, {}, "BLOCKED_WINDOWS_KEY"),
    (0x43, {"ctrl": True}, "BLOCKED_COPY"),
    (0x43, {"ctrl": True, "shift": True}, "BLOCKED_COPY"),
    (0x56, {"ctrl": True}, "BLOCKED_PASTE"),
    (0x2D, {"ctrl": True}, "BLOCKED_COPY"),
    (0x2D, {"shift": True}, "BLOCKED_PASTE"),
    (0x2C, {}, "BLOCKED_SCREENSHOT"),
    (0x2C, {"alt": True}, "BLOCKED_SCREENSHOT"),
    (0x73, {"alt": True}, "BLOCKED_CLOSE"),
    (0x1B, {"alt": True}, "BLOCKED_ALT_ESCAPE"),
    (0x1B, {"ctrl": True}, "BLOCKED_START_MENU"),
    (0x1B, {"ctrl": True, "shift": True}, "BLOCKED_TASK_MANAGER"),
])
def test_named_shortcuts_and_keyup_are_blocked(vk, modifiers, action):
    policy = KeyboardPolicy(blocking=True)
    first = policy.evaluate(vk, True, **modifiers)
    assert first.suppress and first.emit and first.action == action
    assert policy.evaluate(vk, True, **modifiers).suppress
    assert not policy.evaluate(vk, True, **modifiers).emit
    assert policy.evaluate(vk, False).suppress
    assert policy.evaluate(vk, True, **modifiers).emit


def test_audit_reports_same_rule_without_suppression():
    policy = KeyboardPolicy()
    decision = policy.evaluate(0x09, True, alt=True)
    assert decision.emit and decision.action == "BLOCKED_ALT_TAB"
    assert not decision.suppress
    assert not policy.evaluate(0x09, False).suppress


def test_releasing_modifier_does_not_unblock_held_shortcut():
    policy = KeyboardPolicy(True)
    policy.evaluate(0x43, True, ctrl=True)
    assert policy.evaluate(0x43, True, ctrl=False).suppress
    assert not policy.evaluate(0x43, True, ctrl=False).emit
    policy.evaluate(0x43, False)
    assert not policy.evaluate(0x43, True).suppress


@pytest.mark.parametrize("blocking", [False, True])
def test_emergency_has_priority_during_another_shortcut(blocking):
    policy = KeyboardPolicy(blocking)
    policy.evaluate(0x09, True, alt=True)
    result = policy.evaluate(0x51, True, ctrl=True, shift=True, alt=True)
    assert result.emergency and result.emit and not result.suppress
    assert policy.evaluate(0x51, True, ctrl=True, shift=True, alt=True).emergency
    assert not policy.evaluate(0x51, True, ctrl=True, shift=True, alt=True).emit


@pytest.mark.parametrize("vk", [0x41, 0x20, 0x08, 0x0D, 0x2E])
def test_ordinary_typing_and_secure_delete_are_not_suppressed(vk):
    assert not KeyboardPolicy(True).evaluate(vk, True, ctrl=True, alt=True).suppress


def test_only_exact_parent_pid_and_its_dialogs_are_allowed():
    policy = WindowPolicy(1234)
    assert policy.allowed(1234)
    assert not policy.allowed(1235)
    assert not policy.allowed(0)
    assert not policy.should_report(90, 1234)
    assert not policy.should_report(91, 1234)
    assert policy.should_report(100, 5678)
    assert not policy.should_report(100, 5678)
    assert policy.should_report(101, 5678)
    assert not policy.should_report(90, 1234)
    assert policy.should_report(101, 5678)
    assert not policy.should_report(0, 0)


def test_lease_boundary_and_heartbeat_never_rearms():
    lease = HelperLease()
    lease.arm(10, blocking=True, heartbeat_timeout=5)
    assert lease.expired(14.999) is None
    assert lease.expired(15) == "heartbeat_timeout"
    lease.release("heartbeat_timeout")
    lease.heartbeat(16)
    assert not lease.armed and not lease.blocking_enabled
    assert lease.reason == "heartbeat_timeout"
    lease.release("shutdown")
    assert lease.reason == "heartbeat_timeout"


def test_lease_retained_parent_eof_and_bounded_test_release():
    lease = HelperLease()
    lease.arm(10, blocking=False, heartbeat_timeout=5, max_session_seconds=10)
    lease.heartbeat(19)
    assert lease.expired(19.99) is None
    assert lease.expired(20) == "lease_expired"
    assert lease.expired(11, parent_alive=False) == "parent_exited"
    assert lease.expired(11, input_open=False) == "stdin_eof"


@pytest.mark.parametrize("timeout", [0, -1, 0.49, 31, float("inf"), float("nan")])
def test_bad_lease_timeouts_rejected(timeout):
    with pytest.raises(ValueError):
        HelperLease().arm(0, blocking=False, heartbeat_timeout=timeout)


def test_old_heartbeat_cannot_rewind_watchdog():
    lease = HelperLease()
    lease.arm(10, blocking=False, heartbeat_timeout=5)
    lease.heartbeat(12)
    lease.heartbeat(11)
    assert lease.last_heartbeat == 12


@pytest.mark.parametrize("ctrl", [0xA2, 0xA3, 0x11])
@pytest.mark.parametrize("shift", [0xA0, 0xA1, 0x10])
@pytest.mark.parametrize("alt", [0xA4, 0xA5, 0x12])
def test_modifier_transitions_recognize_emergency_then_release(ctrl, shift, alt):
    modifiers = ModifierState()
    for vk in (ctrl, shift, alt):
        modifiers.update(vk, True)
    assert KeyboardPolicy(True).evaluate(0x51, True, **modifiers.values()).emergency
    modifiers.update(ctrl, False)
    assert not KeyboardPolicy(True).evaluate(0x51, True, **modifiers.values()).emergency


def test_modifier_seed_and_independent_left_right_keys():
    modifiers = ModifierState([0xA2, 0xA3])
    modifiers.update(0xA2, False)
    assert modifiers.values()["ctrl"]
    modifiers.update(0xA3, False)
    assert not modifiers.values()["ctrl"]


def test_helper_loop_sentinel_has_independent_monotonic_deadline():
    watchdog = LoopWatchdog(10, timeout_seconds=3)
    assert not watchdog.expired(12.999)
    assert watchdog.expired(13)
    watchdog.pulse(12)
    assert not watchdog.expired(14.999)
    assert watchdog.expired(15)
    watchdog.pulse(11)  # An old pulse cannot rewind the deadline.
    assert watchdog.last_pulse == 12
