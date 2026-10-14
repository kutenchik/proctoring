import test from 'node:test';
import assert from 'node:assert/strict';
import { AuditRunIdentity } from '../electron/recovery_identity';

const identity = { machine: { id: 'test-machine' }, runtime: { build_id: 'b'.repeat(64), build_kind: 'source' },
  fingerprint: 'a'.repeat(64), host_executable: 'C:/owned/electron.exe', protection_policy: { heartbeat_timeout_seconds: 5 } };

test('audit compares every fixture and final reporter with the first run identity', () => {
  const guard = new AuditRunIdentity();
  assert.equal(guard.stable, false);
  guard.observe(identity);
  guard.observe({ ...identity, runtime: { ...identity.runtime } });
  assert.equal(guard.stable, true);
  assert.throws(() => guard.observe({ ...identity, fingerprint: 'c'.repeat(64) }), /changed/);
  assert.equal(guard.stable, false);
  assert.throws(() => guard.observe(identity), /changed earlier/, 'Restoring the original file cannot erase a mid-run mismatch');
});

test('missing native identity cannot silently establish a baseline', () => {
  for (const invalid of [undefined, null, {}, { ...identity, fingerprint: 'bad' }]) {
    const guard = new AuditRunIdentity();
    assert.throws(() => guard.observe(invalid), /missing or malformed/);
    assert.throws(() => guard.observe(identity), /changed earlier/);
  }
});

test('baseline cannot be mutated by a later response or caller', () => {
  const guard = new AuditRunIdentity(); const first = structuredClone(identity);
  guard.observe(first); first.protection_policy.heartbeat_timeout_seconds = 30;
  const saved = guard.initial!; (saved.runtime as Record<string, unknown>).build_kind = 'packaged';
  guard.observe(identity);
  assert.equal(guard.stable, true);
  assert.throws(() => guard.observe(first), /changed/);
});
