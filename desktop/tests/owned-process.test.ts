import test from 'node:test';
import assert from 'node:assert/strict';
import type { ChildProcess } from 'node:child_process';
import { OwnedProcess } from '../electron/owned_process';

test('forced fallback requires unchanged PID creation executable owner and command', async () => {
  const original = { pid: 42, created: 'time', executable: 'python.exe', owner: 'test', command: 'private' };
  for (const key of [undefined, ...Object.keys(original)] as Array<keyof typeof original | undefined>) {
    let calls = 0, kills = 0;
    const child = { pid: 42, exitCode: null, signalCode: null, kill: () => { kills++; return true; } } as unknown as ChildProcess;
    const owned = new OwnedProcess(child, async () => ++calls === 1 || !key ? { ...original } : { ...original, [key]: 'changed' });
    assert.equal(await owned.terminate(), key === undefined);
    assert.equal(kills, key === undefined ? 1 : 0);
  }
});

test('missing identity and exited children are never forced', async () => {
  let kills = 0;
  const child = { pid: 42, exitCode: null, signalCode: null, kill: () => { kills++; return true; } } as unknown as ChildProcess;
  const owned = new OwnedProcess(child, async () => undefined);
  assert.equal(await owned.terminate(), false);
  assert.equal(kills, 0);
});
