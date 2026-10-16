import test from 'node:test';
import assert from 'node:assert/strict';
import { finishShutdown } from '../electron/shutdown';

test('failed capture cleanup cannot strand healthy or disconnected main shutdown', async () => {
  for (const connected of [true, false]) {
    const calls: string[] = [];
    await finishShutdown({
      preparation: [() => { calls.push('capture'); throw Error('disposed capture'); }, () => { calls.push('shortcuts'); }],
      closePresentation: () => { calls.push('presentation'); },
      endSession: () => { calls.push(connected ? 'release' : 'already-disconnected'); },
      closeBackend: () => { calls.push('backend'); },
      quit: () => { calls.push('quit'); }, reportErrors: () => { calls.push('reported'); },
    } as Parameters<typeof finishShutdown>[0]);
    assert.deepEqual(calls, ['capture', 'shortcuts', 'presentation', connected ? 'release' : 'already-disconnected', 'backend', 'quit', 'reported']);
  }
});

test('terminal cleanup runs every finalizer and reports failures without rejecting', async () => {
  const order = ['presentation', 'emergency', 'backend', 'quit'];
  for (const failing of [[], ...order.map(name => [name]), order]) {
    const calls: string[] = [], reports: unknown[][] = [];
    const step = (name: string) => async () => { calls.push(name); if (failing.includes(name)) throw new Error(name); };
    await assert.doesNotReject(finishShutdown({ closePresentation: step('presentation'), endSession: step('emergency'),
      closeBackend: step('backend'), quit: step('quit'), reportErrors: errors => { calls.push('reported'); reports.push(errors); } }));
    assert.deepEqual(calls, failing.length ? [...order, 'reported'] : order);
    assert.equal(reports.length, failing.length ? 1 : 0);
    if (failing.length) assert.deepEqual(reports[0].map(error => (error as Error).message), failing);
  }
});
