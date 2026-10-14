import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { EventEmitter } from 'node:events';
import { once } from 'node:events';
import { execFile, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { promisify } from 'node:util';
import { PythonBridge } from '../electron/bridge';
import { validateState } from '../electron/security';
import type { Command } from '../shared/contracts';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const python = process.env.PROCTORING_PYTHON || path.join(repo, '.venv', 'Scripts', 'python.exe');
const unavailable = process.platform !== 'win32' ? 'The preview transport is Windows-only'
  : !existsSync(python) ? 'Project Python virtual environment is not installed' : false;

test('unresolved owned process cleanup remains explicit and cannot admit another owner', async () => {
  const bridge = new PythonBridge('must-not-spawn-python', 'unused.toml', repo);
  const child = Object.assign(new EventEmitter(), { exitCode: null as number | null, signalCode: null,
    stdin: { end() {} } });
  Reflect.set(bridge, 'child', child);
  bridge.host = async () => ({ version: 1, id: 'test', ok: false, error: { code: 'closed', message: 'test' } });
  await bridge.close();
  assert.equal(bridge.terminated, false, 'Reconnect must use this ownership guard');
  assert.equal(bridge.status.reason, 'cleanup_pending');
  await bridge.start();
  assert.equal(Reflect.get(bridge, 'child'), child);
  child.exitCode = 0;
  assert.equal(bridge.terminated, true);
});

test('closing while preview listen is pending cannot spawn a late backend', async () => {
  const bridge = new PythonBridge('must-not-spawn-python', 'unused.toml', repo);
  let releaseListen!: () => void;
  let previewCloses = 0;
  bridge.preview.listen = () => new Promise<void>(resolve => { releaseListen = resolve; });
  bridge.preview.close = () => { previewCloses += 1; };
  const starting = bridge.start();
  assert.equal(bridge.status.state, 'connecting');
  const closing = bridge.close();
  assert.equal(bridge.close(), closing, 'Repeated close must await the same cleanup');
  await closing;
  releaseListen();
  await starting;
  assert.equal(bridge.status.state, 'disconnected');
  assert.equal(bridge.status.reason, 'closed');
  assert.ok(previewCloses >= 2, 'Transport established during close must also be released');
  assert.equal(Reflect.get(bridge, 'child'), undefined, 'No child may appear after closure');
  await bridge.start();
  assert.equal(Reflect.get(bridge, 'child'), undefined, 'A closed bridge is terminal');
  const command = await bridge.command('state.get');
  assert.equal(command.ok, false);
});

test('a throwing disconnect callback cannot strand pending requests', t => {
  const bridge = new PythonBridge('must-not-spawn-python', 'unused.toml', repo);
  const messages: unknown[] = [];
  t.mock.method(console, 'error', (...args: unknown[]) => messages.push(args));
  let resolved = 0;
  const pending = Reflect.get(bridge, 'pending') as Map<string, unknown>;
  pending.set('pending', { timer: setTimeout(() => { throw new Error('Pending timer was not cleared'); }, 1000), resolve(result: any) { assert.equal(result.ok, false); resolved++; } });
  bridge.onDisconnected = () => { throw new Error('Disposed native UI'); };
  Reflect.get(bridge, 'disconnected').call(bridge, 'closed');
  assert.equal(resolved, 1); assert.equal(pending.size, 0);
  assert.equal(bridge.status.reason, 'presentation_callback_failed');
  assert.equal(messages.length, 1, 'The presentation failure is explicit, not swallowed');
});

test('a throwing state callback settles its valid reply and still closes the owned backend', { skip: unavailable, timeout: 20_000 }, async t => {
  const bridge = new PythonBridge(python, path.join(repo, 'config/default.example.toml'), repo);
  const errors: unknown[] = []; t.mock.method(console, 'error', (...args: unknown[]) => errors.push(args));
  const reasons: string[] = []; bridge.onDisconnected = reason => reasons.push(reason);
  try {
    await bridge.start();
    bridge.onState = () => { throw new Error('Disposed native UI'); };
    const response = await bridge.command('state.get');
    assert.equal(response.ok, true, 'Valid transport data is not a protocol error');
    await bridge.close();
    assert.ok(reasons.includes('presentation_callback_failed'));
    assert.ok(!reasons.includes('invalid_backend_message'));
    assert.equal(Reflect.get(bridge, 'pending').size, 0);
    assert.equal(bridge.terminated, true);
    assert.ok(errors.length > 0);
  } finally { await bridge.close(); }
});

test('real setup bridge round-trip requires explicit capture and cannot start an exam', {
  skip: unavailable, timeout: 20_000,
}, async () => {
  const bridge = new PythonBridge(python, path.join(repo, 'config/default.example.toml'), repo);
  try {
    await bridge.start();
    assert.equal(bridge.status.state, 'connected', JSON.stringify(bridge.status));
    const initial = await bridge.command('state.get');
    assert.equal(initial.version, 1);
    assert.equal(initial.ok, true);
    assert.equal(initial.result.mode, 'exam_workflow');
    assert.equal(initial.result.consent_accepted, false);
    assert.equal(initial.result.protection.enabled, false);
    assert.equal(initial.result.audio.running, false);
    assert.equal(initial.result.camera.state, 'not_started');
    assert.equal(initial.result.camera.selected_key, null);
    assert.equal(initial.result.camera.source_width, null);
    assert.equal(initial.result.workflow?.session.started, false);
    assert.equal(initial.result.workflow?.readiness.ready, false);
    // Reject malformed measurements before a renderer attempts formatting or
    // displays an invented readiness value. Nullable pending samples are valid.
    const withAudio = (patch: object) => ({ ...initial.result, audio: { ...initial.result.audio,
      check: { ...initial.result.audio.check, ...patch } } });
    assert.doesNotThrow(() => validateState(withAudio({ processed_speech: null })));
    for (const patch of [{ threshold: '0.1' }, { gain: Infinity }, { gain_limited: 'yes' },
      { resolved_device: {} }, { stream_format: { channels: [] } }]) {
      assert.throws(() => validateState(withAudio(patch)));
    }

    const blocked = await bridge.command('camera.start');
    assert.equal(blocked.ok, false);
    if (blocked.ok) throw new Error('Capture started without consent');
    assert.equal(blocked.error.code, 'consent_required');

    const consent = await bridge.command('consent.set', { accepted: true });
    assert.equal(consent.ok, true);
    assert.notEqual(consent.id, initial.id);
    assert.equal(consent.result.consent_accepted, true);
    assert.equal(consent.result.audio.running, false);
    assert.equal(consent.result.camera.state, 'not_started');
    assert.equal(await bridge.preview.next(), null);

    const exam = await bridge.command('exam.start' as Command);
    assert.equal(exam.ok, false);
    if (exam.ok) throw new Error('The setup bridge exposed exam control');
    assert.notEqual(exam.error.code, 'invalid_command', 'Backend state must reject an allowed but premature exam command');
    assert.equal(bridge.status.state, 'connected');
  } finally {
    await bridge.close();
  }
  assert.equal(bridge.status.state, 'disconnected');
  const closed = await bridge.command('state.get');
  assert.equal(closed.ok, false);
  await bridge.close();
});

test('abrupt death of the owned Python tree is terminal and cannot silently restart', {
  skip: unavailable, timeout: 20_000,
}, async () => {
  const bridge = new PythonBridge(python, path.join(repo, 'config/default.example.toml'), repo);
  const reasons: string[] = [];
  bridge.onDisconnected = reason => reasons.push(reason);
  try {
    await bridge.start();
    assert.equal(bridge.status.state, 'connected');
    assert.equal(bridge.latestState?.audio.running, false);
    assert.equal(bridge.latestState?.camera.state, 'not_started');
    assert.equal(bridge.latestState?.workflow?.session.started, false);
    const stateBeforeDeath = bridge.latestState;
    const child = Reflect.get(bridge, 'child') as ChildProcessWithoutNullStreams;
    assert.equal(child.spawnfile, python);
    assert.ok(child.pid && child.exitCode === null);
    const exited = once(child, 'exit');
    // Only the process tree directly owned by this test is terminated. In
    // particular, the separate operator application and its backend are untouched.
    await promisify(execFile)('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
    await exited;
    assert.equal(bridge.terminated, true);
    assert.equal(bridge.status.state, 'disconnected');
    assert.equal(bridge.status.reason, 'python_exited');
    assert.ok(reasons.includes('python_exited'));
    assert.equal(await bridge.preview.next(), null);
    await bridge.start();
    assert.equal(Reflect.get(bridge, 'child'), undefined, 'No replacement backend may be spawned');
    assert.equal(bridge.latestState, stateBeforeDeath, 'No invented fresh session snapshot');
    const retry = await bridge.command('state.get');
    assert.equal(retry.ok, false);
    if (!retry.ok) assert.equal(retry.error.code, 'backend_unavailable');
  } finally { await bridge.close(); }
});

test('control EOF makes the actual Python backend exit gracefully without a kill', {
  skip: unavailable, timeout: 20_000,
}, async () => {
  const bridge = new PythonBridge(python, path.join(repo, 'config/default.example.toml'), repo);
  try {
    await bridge.start();
    assert.equal(bridge.status.state, 'connected');
    assert.equal(bridge.latestState?.audio.running, false);
    assert.equal(bridge.latestState?.camera.state, 'not_started');
    const child = Reflect.get(bridge, 'child') as ChildProcessWithoutNullStreams;
    const exited = once(child, 'exit');
    // Main-process exit closes this pipe. No explicit shutdown RPC is sent,
    // exercising the backend's independent EOF cleanup path.
    child.stdin.end();
    const [code, signal] = await exited;
    assert.equal(code, 0);
    assert.equal(signal, null);
    assert.equal(child.killed, false);
    assert.equal(bridge.terminated, true);
    assert.equal(bridge.status.state, 'disconnected');
    await bridge.start();
    assert.equal(Reflect.get(bridge, 'child'), undefined);
  } finally { await bridge.close(); }
});
