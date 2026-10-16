import test from 'node:test';
import assert from 'node:assert/strict';
import { runMaximumLeaseCheck } from '../electron/maximum_lease_check';

test('maximum lease establishes foreground before arming and reports a competing release', async () => {
  const order: string[] = [];
  let focused = false;
  const native = { reason: '', armed: false, blocking_enabled: false, hook_installed: false, hotkey_registered: false };
  await runMaximumLeaseCheck({
    focus: async () => { focused = true; order.push('focus'); },
    enable: async seconds => { assert.equal(seconds, 2); order.push('enable'); native.reason = focused ? 'lease_expired' : 'foreground_lost'; },
    normalInput: async () => { order.push('input'); },
    state: async () => ({ native, protection: { reason: native.reason } }),
  });
  assert.deepEqual(order, ['focus', 'enable', 'input']);
});

test('competing release cause is preserved, never accepted as maximum lease', async () => {
  await assert.rejects(runMaximumLeaseCheck({
    focus: async () => {}, enable: async () => {}, normalInput: async () => {},
    state: async () => ({ native: { reason: 'control_progress_lost' }, protection: { reason: 'control_progress_lost' } }),
  }), /control_progress_lost/);
});

test('failed foreground precondition never arms', async () => {
  let arms = 0;
  await assert.rejects(runMaximumLeaseCheck({
    focus: async () => { throw Error('Owned foreground unavailable'); },
    enable: async () => { arms++; }, normalInput: async () => {},
    state: async () => ({ native: { reason: 'lease_expired' } }),
  }), /foreground unavailable/);
  assert.equal(arms, 0);
});
