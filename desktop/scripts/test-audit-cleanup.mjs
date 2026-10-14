// Private unarmed fixture regression. Never bind, arm, inject keys or open devices.
import { spawn } from 'node:child_process';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import electron from 'electron';

const output = path.resolve('../artifacts/electron-stage3-audit-cleanup');
await mkdir(output, { recursive: true });
const results = [];
for (let cycle = 0; cycle < 3; cycle++) {
  const token = randomBytes(32).toString('hex');
  const env = { ...process.env, PROCTORING_AUDIT_FIXTURE_TOKEN: token,
    PROCTORING_AUDIT_OUTPUT: path.join(output, 'unused-unarmed-report.json') };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.PROCTORING_AUDIT_CONFIG;
  delete env.PROCTORING_RECOVERY_REPORT;
  const child = spawn(electron, [process.cwd(), '--recovery-fixture'], {
    windowsHide: true, stdio: ['ignore', 'ignore', 'pipe', 'ipc'], env,
  });
  const pending = new Map();
  let stderr = '', readyResolve, readyReject;
  const ready = new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject; });
  child.stderr.on('data', data => { stderr = (stderr + data.toString('utf8')).slice(-32768); });
  child.on('message', message => {
    if (message?.token !== token) return;
    if (message.ready) readyResolve(message);
    const request = pending.get(message.id);
    if (request) { clearTimeout(request.timer); pending.delete(message.id); request.resolve(message); }
  });
  child.on('error', readyReject);
  const exited = new Promise(resolve => child.once('exit', (code, signal) => {
    readyReject(new Error('Fixture exited before ready'));
    for (const item of pending.values()) { clearTimeout(item.timer); item.resolve({ ok: false, error: 'Fixture exited' }); }
    pending.clear(); resolve({ code, signal });
  }));
  const ask = (command, payload = {}) => new Promise((resolve, reject) => {
    const id = randomUUID();
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('Unarmed fixture request timed out')); }, 14000);
    pending.set(id, { resolve, timer });
    child.send({ token, id, command, payload }, error => { if (error) { clearTimeout(timer); pending.delete(id); reject(error); } });
  });
  let watchdog;
  try {
    await Promise.race([ready, new Promise((_, reject) => { watchdog = setTimeout(() => reject(new Error('Fixture startup timed out')), 20000); })]);
    clearTimeout(watchdog);
    const before = await ask('endpoint', { command: 'audit.status' });
    assert.equal(before.ok, true);
    assert.equal(before.result.ok, true);
    assert.equal(before.result.result.helper_pid, null, 'No helper may be started by this regression');
    const crash = await ask('endpoint', { command: 'audit.crash' });
    assert.equal(crash.result.ok, false);
    // Exercise queued/current polling after the owned endpoint has died.
    await new Promise(resolve => setTimeout(resolve, 350));
    const after = await ask('endpoint', { command: 'audit.status' });
    assert.equal(after.result.ok, false);
    const started = performance.now();
    await ask('close'); // Process exit is the completion acknowledgement.
    const exit = await Promise.race([exited, new Promise((_, reject) => { watchdog = setTimeout(() => reject(new Error('Fixture close timed out')), 14000); })]);
    clearTimeout(watchdog);
    assert.equal(exit.code, 0);
    assert.equal(child.killed, false);
    assert.doesNotMatch(stderr, /Uncaught Exception|UnhandledPromiseRejection|fixture_cleanup_failed|EPIPE/);
    results.push({ cycle: cycle + 1, passed: true, helper_started: false, fixture_pid: child.pid,
      exit_code: exit.code, close_ms: Math.round(performance.now() - started), forced_termination: false,
      diagnostics: stderr.split(/\r?\n/).filter(line => line.startsWith('AUDIT_FIXTURE_DIAGNOSTIC ')) });
  } finally {
    clearTimeout(watchdog);
    if (child.exitCode === null && child.signalCode === null) {
      child.kill(); await exited; // Exact owned fixture only; this is a failed test.
    }
    await writeFile(path.join(output, `unarmed-cycle-${cycle + 1}.stderr.txt`), stderr);
  }
}
await writeFile(path.join(output, 'unarmed-crash-cleanup.json'), JSON.stringify({ passed: true, native_hooks: false,
  devices_opened: false, calibration_or_exam_started: false, results }, null, 2));
console.log(JSON.stringify({ passed: true, results }));
