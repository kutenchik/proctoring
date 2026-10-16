import test from 'node:test';
import assert from 'node:assert/strict';
import { runOwnedAudit } from '../scripts/run-recovery-audit.mjs';

test('launcher drains both streams and stays alive until its child closes', async () => {
  const begin = Date.now();
  const stages = [];
  const result = await runOwnedAudit(process.execPath, ['-e', `
    console.log(JSON.stringify({audit_stage:'binding_identity'}));
    console.log(JSON.stringify({native_audit:'binding_identity',passed:true,detail:'SECRET'}));
    process.stderr.write('SECRET raw error');
    setTimeout(()=>{console.log(JSON.stringify({native_audit:'normal_release',passed:true}));},150);
  `], { onStage: name => stages.push(name) });
  assert.equal(result.status, 'exited'); assert.equal(result.exit_code, 0);
  assert.ok(Date.now() - begin >= 150);
  assert.equal(result.progress.length, 2);
  assert.deepEqual(stages, ['binding_identity']);
  assert.ok(result.stderr_bytes > 0);
  assert.ok(!JSON.stringify(result).includes('SECRET'));
});

test('launcher reports failed spawn and failing child exit without fabricating audit success', async () => {
  const failed = await runOwnedAudit(process.execPath, ['-e', 'process.exit(23)']);
  assert.equal(failed.status, 'failed'); assert.equal(failed.exit_code, 23);
  const missing = await runOwnedAudit('this-executable-must-not-exist', []);
  assert.equal(missing.status, 'failed'); assert.equal(missing.spawn_failed, true);
});

test('launcher cancellation closes output reader, waits for child cleanup, and reports failed', { timeout: 5000 }, async () => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 150);
  try {
    const result = await runOwnedAudit(process.execPath, ['-e', `
      process.stdout.on('error',()=>process.exit(0));
      setInterval(()=>process.stdout.write('progress\\n'),25);
    `], { signal: controller.signal });
    assert.equal(result.cancellation_requested, true);
    assert.equal(result.exit_code, 0, 'Child handled release itself; no process kill');
    assert.equal(result.status, 'failed');
  } finally { clearTimeout(timer); }
});
