import test from 'node:test';
import assert from 'node:assert/strict';
import { assertSuppressedProbe, assertOrdinaryInputProbe, assertControlLossRelease, assertNormalRelease, assertCrossProcessForegroundRecovery, assertSuspendedOwnerDeath, runProtectedCheck } from '../electron/protected_assertions';

test('native protected check requires both native event and absent target delivery', () => {
  assert.throws(() => assertSuppressedProbe('BLOCKED_COPY', 'KeyC', [], {}));
  assert.throws(() => assertSuppressedProbe('BLOCKED_COPY', 'KeyC', [{ event_type: 'BLOCKED_COPY', details: { suppressed: false } }], {}));
  assert.throws(() => assertSuppressedProbe('BLOCKED_COPY', 'KeyC', [{ event_type: 'BLOCKED_COPY', details: { suppressed: true } }], { KeyC: 1 }));
  assert.doesNotThrow(() => assertSuppressedProbe('BLOCKED_COPY', 'KeyC', [{ event_type: 'BLOCKED_COPY', details: { suppressed: true } }], {}));
});

test('failed ordinary input or cleanup stops the sequence before another arm', async () => {
  for (const failIn of ['action', 'cleanup']) {
    let arms = 0, cleanups = 0; const records: boolean[] = [];
    await assert.rejects(async () => {
      for (const name of ['first', 'must_not_arm']) await runProtectedCheck(name, async () => {
        arms++; if (failIn === 'action') throw new Error('ordinary input unconfirmed');
      }, async () => { cleanups++; if (failIn === 'cleanup') throw new Error('owner cleanup unconfirmed'); }, (_name, passed) => records.push(passed));
    });
    assert.equal(arms, 1); assert.equal(cleanups, 1); assert.deepEqual(records, [false]);
  }
});

test('ordinary input requires matching physical down and up with no stuck modifiers', () => {
  const probe = { counts: { KeyA: 1 }, ups: { KeyA: 1 }, events: [{ type: 'keydown', code: 'KeyA' }, { type: 'keyup', code: 'KeyA' }] };
  assert.doesNotThrow(() => assertOrdinaryInputProbe('KeyA', probe));
  assert.throws(() => assertOrdinaryInputProbe('KeyA', { ...probe, counts: { Unidentified: 1 } }));
  assert.throws(() => assertOrdinaryInputProbe('KeyA', { ...probe, counts: { KeyA: 2 } }));
  assert.throws(() => assertOrdinaryInputProbe('KeyA', { ...probe, ups: {} }));
  assert.throws(() => assertOrdinaryInputProbe('KeyA', { ...probe, events: probe.events.map(e => ({ ...e, ctrl: true })) }));
});

test('renderer failure must have its own native release cause and bounded native timestamps', () => {
  const state = { native: { reason: 'control_progress_lost', control_confirmed_at: 100, released_at: 105.1 }, protection: { state: 'fault' }, protection_policy: { heartbeat_timeout_seconds: 5 } };
  assert.ok(Math.abs(assertControlLossRelease(state) - 5.1) < .0001);
  for (const reason of ['emergency_shortcut', 'lease_expired', 'audit_release']) {
    assert.throws(() => assertControlLossRelease({ ...state, native: { ...state.native, reason } }));
  }
  for (const released_at of [99, 106.01, NaN, Infinity, null, '105']) {
    assert.throws(() => assertControlLossRelease({ ...state, native: { ...state.native, released_at } }));
  }
  assert.throws(() => assertControlLossRelease({ ...state, protection_policy: {} }));
  assert.throws(() => assertControlLossRelease({ ...state, protection: { state: 'released' } }));
});

test('normal native release must also stay released in public presentation state', () => {
  const state = { protection: { state: 'released', reason: 'normal_disable' }, native: { armed: false, blocking_enabled: false, hook_installed: false, hotkey_registered: false, reason: 'normal_disable' } };
  assert.doesNotThrow(() => assertNormalRelease(state, 'normal_disable'));
  assert.throws(() => assertNormalRelease({ ...state, protection: { ...state.protection, state: 'fault' } }, 'normal_disable'));
  assert.throws(() => assertNormalRelease({ ...state, native: { ...state.native, hook_installed: true } }, 'normal_disable'));
  assert.throws(() => assertNormalRelease(state, 'completed'));
});

test('suspension requires the same protected owner to die, without a different native release', () => {
  const before = { helper_pid: 42, helper_created: '123', helper_alive: true, native: { armed: true, blocking_enabled: true, reason: 'enabled' } };
  const result = { result: { termination_confirmed: true, helper_pid: 42 } };
  const after = { ...before, helper_alive: false, native: { reason: 'enabled', termination_confirmed: true }, protection: { reason: 'helper_exited' } };
  assert.doesNotThrow(() => assertSuspendedOwnerDeath(before, result, after));
  assert.throws(() => assertSuspendedOwnerDeath(before, { result: { termination_confirmed: false, helper_pid: 42 } }, after));
  assert.throws(() => assertSuspendedOwnerDeath(before, result, { ...after, helper_created: '456' }));
  assert.throws(() => assertSuspendedOwnerDeath(before, result, { ...after, helper_alive: true }));
  assert.throws(() => assertSuspendedOwnerDeath(before, result, { ...after, native: { ...after.native, reason: 'emergency_shortcut' } }));
  assert.throws(() => assertSuspendedOwnerDeath(before, result, { ...after, protection: { reason: 'lease_expired' } }));
  assert.throws(() => assertSuspendedOwnerDeath({ ...before, native: { ...before.native, armed: false } }, result, after));
});

test('cross-process foreground recovery distinguishes actual restoration from bounded containment failure', () => {
  const observation = { target: { pid: 22, hwnd: '0x42', created: '123456789' }, started_at: 100, ended_at: 101.75,
    samples: [{ at: 100, kind: 'exam', hwnd: '0x41' }, { at: 100.2, kind: 'foreign', hwnd: '0x42' }, { at: 100.4, kind: 'exam', hwnd: '0x41' }] };
  const protection_policy = { foreground_poll_ms: 100 };
  const restored = { foreground_observation: observation, native: { armed: true, blocking_enabled: true }, protection: { state: 'active', enabled: true }, protection_policy };
  assert.equal(assertCrossProcessForegroundRecovery(restored, 11, 22, '0x42').outcome, 'restored');
  assert.throws(() => assertCrossProcessForegroundRecovery(restored, 22, 22, '0x42'));
  assert.throws(() => assertCrossProcessForegroundRecovery(restored, 11, 23, '0x42'));
  assert.throws(() => assertCrossProcessForegroundRecovery(restored, 11, 22, '0x43'));
  assert.throws(() => assertCrossProcessForegroundRecovery({ ...restored, foreground_observation: { ...observation, target: { ...observation.target, created: '' } } }, 11, 22, '0x42'));
  assert.throws(() => assertCrossProcessForegroundRecovery({ ...restored, foreground_observation: { ...observation, samples: [observation.samples[0]] } }, 11, 22, '0x42'), /NOT RUN/);
  const terminal = { foreground_observation: { ...observation, samples: observation.samples.slice(0, 2) },
    native: { armed: false, blocking_enabled: false, hook_installed: false, hotkey_registered: false, reason: 'foreground_containment_failed', released_at: 101.3 },
    protection: { state: 'fault', reason: 'foreground_containment_failed' }, protection_policy };
  assert.equal(assertCrossProcessForegroundRecovery(terminal, 11, 22, '0x42').outcome, 'terminal_failure');
  for (const reason of ['lease_expired', 'normal_disable', 'control_progress_lost']) {
    assert.throws(() => assertCrossProcessForegroundRecovery({ ...terminal, native: { ...terminal.native, reason } }, 11, 22, '0x42'));
  }
  for (const released_at of [99, 101.8, NaN, null]) {
    assert.throws(() => assertCrossProcessForegroundRecovery({ ...terminal, native: { ...terminal.native, released_at } }, 11, 22, '0x42'));
  }
  assert.throws(() => assertCrossProcessForegroundRecovery({ ...terminal, native: { ...terminal.native, hook_installed: true } }, 11, 22, '0x42'));
  assert.throws(() => assertCrossProcessForegroundRecovery({ ...terminal, protection: { state: 'released', reason: 'foreground_containment_failed' } }, 11, 22, '0x42'));
  assert.throws(() => assertCrossProcessForegroundRecovery({ ...restored, foreground_observation: { ...observation, samples: [...observation.samples, { at: 101, kind: 'foreign', hwnd: '0x42' }] } }, 11, 22, '0x42'));
  assert.throws(() => assertCrossProcessForegroundRecovery({ ...restored, protection_policy: {} }, 11, 22, '0x42'));
  const slowPoll = assertCrossProcessForegroundRecovery({ ...terminal, foreground_observation: { ...terminal.foreground_observation, ended_at: 102.6 }, native: { ...terminal.native, released_at: 102.3 }, protection_policy: { foreground_poll_ms: 1000 } }, 11, 22, '0x42');
  assert.deepEqual(slowPoll.bound, { native_seconds: 1, poll_seconds: 1, scheduler_seconds: .4, total_seconds: 2.4 });
});
