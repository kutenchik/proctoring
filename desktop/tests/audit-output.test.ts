import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { buildSync } from 'esbuild';
import { PassThrough, Writable } from 'node:stream';
import { AuditOutput } from '../electron/audit_output';
const guard = buildSync({ entryPoints: ['electron/audit_output.ts'], bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;

test('closing the progress reader must not leave an uncaught audit write failure', async () => {
  // Real child/output pipe, production audit writer; no native fixture.
  const child = spawn(process.execPath, ['-e', guard + `
    const output=new module.exports.AuditOutput(process.stdout,process.stderr,()=>{});
    process.send('ready');
    process.on('message', () => {
      let count=0;
      const timer=setInterval(async () => {
        try { await output.write({native_audit:'binding_identity',passed:true}); }
        catch { clearInterval(timer); process.send({status:'failed',passed:false,failure:output.failure},()=>process.exit(0)); }
        if (++count===10) { clearInterval(timer); process.exit(2); }
      }, 50);
    });
  `], { stdio: ['ignore', 'pipe', 'pipe', 'ipc'], windowsHide: true });
  assert.ok(child.stdout && child.stderr);
  let stderr = ''; child.stderr.on('data', data => { stderr = (stderr + data).slice(-4096); });
  const exited = once(child, 'exit');
  await once(child, 'message');
  const closed = once(child.stdout, 'close');
  child.stdout.destroy(); // Simulates the short-lived launch shell/output reader.
  await closed;
  const result = once(child, 'message');
  child.send('write');
  const [report] = await result;
  const [code] = await exited;
  assert.equal(code, 0, stderr);
  assert.equal(report.status, 'failed'); assert.equal(report.passed, false);
  assert.match(report.failure, /^audit_output_/);
  assert.equal(stderr, '', 'No uncaught exception or recursive stderr logging');
});

test('stderr failure aborts too and preserves first failure across late cleanup errors', async () => {
  const stdout = new PassThrough(), stderr = new PassThrough();
  const failures: string[] = [];
  const output = new AuditOutput(stdout, stderr, code => failures.push(code));
  await output.write({ passed: false });
  stderr.emit('error', Object.assign(Error('private details'), { code: 'EPIPE' }));
  stdout.emit('error', Error('secondary'));
  assert.deepEqual(failures, ['audit_output_epipe']);
  await assert.rejects(output.write({ passed: true }), /audit_output_epipe/);
  assert.throws(() => output.assertHealthy(), /audit_output_epipe/);
});

test('synchronous write failure and closed stream fail without an uncaught exception', async () => {
  const stdout = new Writable({ write() { throw Object.assign(Error('private'), { code: 'EPIPE' }); } });
  const output = new AuditOutput(stdout, new PassThrough(), () => {});
  await assert.rejects(output.write({ passed: true }), /audit_output_epipe/);
  stdout.emit('error', Error('late'));
  const closed = new PassThrough(); closed.destroy();
  const other = new AuditOutput(closed, new PassThrough(), () => {});
  await assert.rejects(other.write({ passed: true }), /audit_output_closed/);
});
