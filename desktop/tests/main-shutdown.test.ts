import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { buildSync } from 'esbuild';
import { createRequire } from 'node:module';
import path from 'node:path';
const require = createRequire(import.meta.url);
const code = buildSync({ entryPoints: ['electron/main.ts'], bundle: true, platform: 'node', format: 'cjs', write: false,
  external: ['electron', './bridge', './live_screen', './runtime', './external', './geometry', './host_binding'],
}).outputFiles[0].text;

async function harness(throwCapture = false) {
  const calls: string[] = [], shortcuts = new Map<string, () => void>();
  let owner: any, backend: any;
  class Window extends EventEmitter {
    webContents = Object.assign(new EventEmitter(), { mainFrame: {}, setWindowOpenHandler() {}, isDestroyed: () => false,
      send: (name: string) => { calls.push(name); } });
    constructor() { super(); owner = this; }
    isDestroyed() { return false; } isMinimized() { return false; }
    removeMenu() {} show() {} async loadURL() {}
  }
  const app = Object.assign(new EventEmitter(), { isPackaged: false, requestSingleInstanceLock: () => true,
    whenReady: async () => {}, getPath: () => '.', quit: () => { calls.push('quit'); } });
  const partition = Object.assign(new EventEmitter(), { setPermissionRequestHandler() {}, setPermissionCheckHandler() {},
    webRequest: { onHeadersReceived() {} } });
  const electron = { app, BrowserWindow: Window, session: { fromPartition: () => partition }, screen: new EventEmitter(),
    ipcMain: { handle() {} }, globalShortcut: { register: (key: string, fn: () => void) => shortcuts.set(key, fn),
      unregisterAll: () => { calls.push('shortcuts'); }, unregister() {} }, dialog: { showMessageBox: async () => ({ response: 0 }) } };
  class Bridge {
    terminated = false; latestState: any; onDisconnected?: () => void;
    diagnostics = { record() {}, fail() {} };
    constructor() { backend = this; }
    async start() {} async command() { return { ok: false }; }
    async host(name: string) { calls.push(name); return { ok: true }; }
    async close() { calls.push('backend'); this.terminated = true; }
  }
  const replacements: Record<string, unknown> = {
    './bridge': { PythonBridge: Bridge },
    './runtime': { resolveRuntime: () => ({ python: 'never-spawn', config: 'unused', backendCwd: '.' }), ensureRuntimeConfig() {} },
    './live_screen': { LiveScreen: class { update() {} stopLease() {} close() { calls.push('capture'); if (throwCapture) throw Error('disposed'); } } },
    './external': { ExternalExam: class { intent() {} close() { calls.push('presentation'); } }, emergencyInput: () => false },
    './geometry': { GeometryOwner: class {} }, './host_binding': {},
  };
  const module = { exports: {} }, fakeProcess = { ...process, argv: ['electron', '.'], exitCode: 0 };
  new Function('require', 'module', 'exports', '__dirname', 'process', 'setInterval', 'clearInterval', 'console', code)(
    (name: string) => name === 'electron' ? electron : replacements[name] ?? require(name), module, module.exports,
    path.resolve('build-electron'), fakeProcess, () => ({ unref() {} }), () => {}, { error() {} });
  await new Promise(r => setImmediate(r));
  assert.ok(backend, 'Actual main startup must reach its bridge'); assert.equal(calls.length, 0);
  return { calls, owner, backend, shortcuts, async close() { owner.emit('close', { preventDefault() {} }); await new Promise(r => setImmediate(r)); } };
}

for (const disconnected of [false, true]) for (const throws of [false, true]) {
  test(`actual main normal close: disconnected=${disconnected}, capture cleanup throws=${throws}`, async () => {
    const h = await harness(throws);
    if (disconnected) { h.backend.terminated = true; h.backend.onDisconnected(); }
    await h.close();
    assert.deepEqual(h.calls, ['capture', 'shortcuts', 'presentation', 'backend', 'quit']);
    await h.close(); assert.equal(h.calls.filter(c => c === 'quit').length, 1);
  });
}

test('active session close retains privileged handling; emergency still reaches backend before quit', async () => {
  const h = await harness();
  h.backend.latestState = { workflow: { session: { started: true, ended: false } } };
  await h.close();
  assert.equal(h.calls.join(','), 'proctoring:request-end');
  h.shortcuts.get('Control+Shift+Alt+Q')!();
  await new Promise(r => setImmediate(r));
  assert.ok(h.calls.indexOf('emergency.end') < h.calls.indexOf('backend'));
  assert.equal(h.calls.at(-1), 'quit');
});
