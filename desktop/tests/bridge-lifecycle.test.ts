import test from 'node:test';
import assert from 'node:assert/strict';
import { PythonBridge } from '../electron/bridge';
import { Lifecycle } from '../electron/lifecycle';
import { EventEmitter } from 'node:events';
import { PassThrough, Writable } from 'node:stream';
import { mkdtempSync, readFileSync, existsSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

function fixture() {
  const bridge = new PythonBridge('never-spawn', 'unused', '.');
  const requests: any[] = [];
  const child = Object.assign(new EventEmitter(), { exitCode: null as number | null, signalCode: null,
    stdout: new PassThrough(), stderr: new PassThrough(),
    stdin: new Writable({ write(data, _encoding, done) {
      const request = JSON.parse(String(data)); requests.push(request);
      if (request.command === 'shutdown') queueMicrotask(() => { child.exitCode = 0; child.emit('exit', 0, null); });
      done();
    } }),
  });
  Reflect.set(bridge, 'child', child);
  Reflect.get(bridge, 'observeChild').call(bridge, child);
  return { bridge, child, requests };
}

test('cleanup does not replace the first unexpected disconnect', async () => {
  const bridge = new PythonBridge('never-spawn', 'unused', '.');
  Reflect.get(bridge, 'disconnected').call(bridge, 'backend_pipe_closed');
  await bridge.close();
  assert.equal(bridge.status.reason, 'backend_pipe_closed');
});

test('recoverable camera error keeps control connected and exposes safe operation error', async () => {
  const { bridge, child, requests } = fixture();
  const pending = bridge.command('camera.start');
  const error = { code: 'camera_initialization_failed', message: 'Camera initialization failed; check permissions and connection, then retry camera' };
  child.stdout.write(JSON.stringify({ version: 1, id: requests[0].id, ok: false, error }) + '\n');
  assert.deepEqual((await pending as any).error, error);
  assert.equal(bridge.status.state, 'connected');
  assert.equal(bridge.diagnostics.snapshot().lastResponse, 'camera.start');
  await bridge.close();
});

for (const failure of ['backend-exit', 'supervisor-exit', 'pipe-end', 'pipe-error'] as const) {
  test(`camera pending during ${failure} settles without killing main or replacing first failure`, async () => {
    const { bridge, child } = fixture();
    let notified = 0; bridge.onDisconnected = () => { notified++; };
    const pending = bridge.command('camera.start');
    if (failure === 'backend-exit') child.stderr.write('PROCTORING_LIFECYCLE:{"event":"backend_exited","code":3221225477}\n');
    if (failure.endsWith('exit')) { child.exitCode = -1073741819; child.emit('exit', child.exitCode, null); }
    else if (failure === 'pipe-end') child.stdout.end();
    else child.stdin.emit('error', Error('SECRET must not be logged'));
    const response = await pending;
    assert.equal(response.ok, false); assert.ok(notified > 0);
    const first = bridge.diagnostics.snapshot().firstFailure;
    await bridge.close();
    assert.deepEqual(bridge.diagnostics.snapshot().firstFailure, first);
    assert.equal(first?.request, 'camera.start');
    assert.equal(first?.cameraOperation, 1);
    assert.ok(!JSON.stringify(bridge.diagnostics.snapshot()).includes('SECRET'));
    if (failure.endsWith('exit')) assert.ok(bridge.diagnostics.snapshot().transitions.some(e => e.windowsStatus === '0xc0000005'));
    assert.equal((await bridge.command('state.get')).ok, false);
  });
}

test('diagnostic parser handles chunks, bounds history, rejects raw/private fields', () => {
  const log = new Lifecycle();
  const line = 'PROCTORING_LIFECYCLE:{"event":"camera_failed","classification":"os","message":"SECRET"}\n';
  log.stderr(Buffer.from(line.slice(0, 12))); log.stderr(Buffer.from(line.slice(12)));
  const first = log.snapshot().firstFailure;
  assert.equal(first?.reason, 'camera_failed');
  log.stderr(Buffer.from('x'.repeat(10000) + '\n'));
  for (let i = 0; i < 100; i++) log.stderr(Buffer.from('PROCTORING_LIFECYCLE:{"event":"backend_shutdown"}\n'));
  assert.deepEqual(log.snapshot().firstFailure, first);
  assert.equal(log.snapshot().transitions.length, 32);
  assert.ok(!JSON.stringify(log.snapshot()).includes('SECRET'));
  assert.ok(JSON.stringify(log.snapshot()).length < 16000);
});

test('local diagnostics retain first failure atomically and one previous launch', () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'proctoring-lifecycle-'));
  const file = path.join(directory, 'backend-lifecycle.json');
  try {
    const log = new Lifecycle(file);
    log.sent('camera.start'); log.fail('backend_pipe_closed'); log.record('main_quit_requested');
    const first = JSON.parse(readFileSync(file, 'utf8'));
    assert.equal(first.firstFailure.reason, 'backend_pipe_closed');
    const next = new Lifecycle(file); next.record('supervisor_started');
    assert.deepEqual(JSON.parse(readFileSync(`${file}.previous`, 'utf8')), first);
    assert.ok(readFileSync(file).length < 65536);
  } finally {
    for (const target of [file, `${file}.previous`, `${file}.tmp`]) if (existsSync(target)) unlinkSync(target);
    rmdirSync(directory);
  }
});
