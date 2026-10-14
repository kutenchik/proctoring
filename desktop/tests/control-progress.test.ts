import test from 'node:test';
import assert from 'node:assert/strict';
import { ControlProgress } from '../electron/control_progress';
import { nativeHandleHex } from '../electron/host_binding';
import { validateCommand } from '../electron/security';

const lease = { lease_id: 'a'.repeat(32), nonce: 'b'.repeat(32), sequence: 1 };
const receipt = { ...lease, snapshot_seq: 12, session_id: 'session-test', render_generation: 1 };
test('observer polling cannot renew a missing renderer challenge', () => {
  let time = 0;
  const progress = new ControlProgress(() => time);
  assert.ok(progress.offer(lease, 12, 'session-test'));
  for (time = 100; time < 1600; time += 100) progress.offer(lease, 12 + time, 'session-test');
  assert.equal(progress.accept(receipt, 'session-test'), null, 'Fresh observer snapshots cannot mask a frozen presentation');
});
test('fresh committed progress is consumed once and requires growing render generations', () => {
  const progress = new ControlProgress(() => 0);
  progress.offer(lease, 12, 'session-test');
  assert.deepEqual(progress.accept(receipt, 'session-test'), { ...lease, main_sequence: 1 });
  assert.equal(progress.accept(receipt, 'session-test'), null);
  progress.confirm(lease, true);
  assert.equal(progress.offer(lease, 13, 'session-test'), null, 'A replay cannot generate another challenge');
  const next = { ...lease, nonce: 'c'.repeat(32), sequence: 2 };
  progress.offer(next, 13, 'session-test');
  assert.equal(progress.accept({ ...receipt, ...next, snapshot_seq: 13 }, 'session-test'), null);
  assert.deepEqual(progress.accept({ ...receipt, ...next, snapshot_seq: 13, render_generation: 2 }, 'session-test'), { ...next, main_sequence: 2 });
});
test('rejected pre-exam receipt can retry under the new session without extending its deadline', () => {
  let time = 0; const progress = new ControlProgress(() => time);
  progress.offer(lease, 12, null);
  const first = { ...receipt, session_id: null };
  assert.ok(progress.accept(first, null));
  time = 300; progress.offer(lease, 13, 'session-test');
  progress.confirm(lease, false);
  assert.ok(progress.offer(lease, 13, 'session-test'));
  assert.ok(progress.accept({ ...receipt, snapshot_seq: 13, render_generation: 2 }, 'session-test'));
  progress.confirm(lease, false);
  time = 1600;
  progress.offer(lease, 14, 'session-other');
  assert.equal(progress.accept({ ...receipt, session_id: 'session-other', snapshot_seq: 14, render_generation: 3 }, 'session-other'), null);
});
test('a missed initial subscription gets the same bounded challenge again', () => {
  let time = 0; const progress = new ControlProgress(() => time);
  const first = progress.offer(lease, 12, null);
  time = 301; assert.deepEqual(progress.offer(lease, 13, null), first);
  time = 1600; assert.equal(progress.accept({ ...receipt, session_id: null }, null), null);
});
test('wrong session, stale UI snapshot and unsolicited nonce do not acknowledge control progress', () => {
  const progress = new ControlProgress(() => 0);
  progress.offer(lease, 12, 'session-test');
  for (const change of [{ session_id: 'other' }, { snapshot_seq: 11 }, { nonce: 'f'.repeat(32) }, { render_generation: 0 }, { path: 'C:/secret' }]) {
    assert.equal(progress.accept({ ...receipt, ...change }, 'session-test'), null);
  }
  assert.ok(progress.accept(receipt, 'session-test'));
});
test('native HWND conversion preserves unsigned pointer width without numeric truncation', () => {
  const handle = Buffer.alloc(8); handle.writeBigUInt64LE(0xfedcba9876543210n);
  assert.equal(nativeHandleHex(handle), '0xfedcba9876543210');
  const short = Buffer.alloc(4); short.writeUInt32LE(0xfedcba98);
  assert.equal(nativeHandleHex(short), '0xfedcba98');
  assert.throws(() => nativeHandleHex(Buffer.alloc(8)));
  assert.throws(() => nativeHandleHex(Buffer.alloc(6)));
});
test('renderer cannot bind HWNDs or supply privileged progress directly', () => {
  const binding = { launch_id: '1'.repeat(32), host_pid: 123, windows: [{ hwnd: '0xfedcba9876543210', role: 'exam' }],
    runtime: { electron_version: '44.7.0', app_version: '0.1.0', build_kind: 'source', build_id: '2'.repeat(64) } };
  assert.throws(() => validateCommand('host.bind', binding));
  assert.equal(validateCommand('host.bind', binding, true).command, 'host.bind');
  assert.throws(() => validateCommand('host.bind', { ...binding, windows: [{ hwnd: '0x0', role: 'exam' }] }, true));
  assert.throws(() => validateCommand('host.bind', { ...binding, allowed_pids: [123] }, true));
  const progress = { ...lease, main_sequence: 1, session_id: null, snapshot_seq: 1 };
  assert.throws(() => validateCommand('host.progress', progress));
  assert.equal(validateCommand('host.progress', progress, true).command, 'host.progress');
});
