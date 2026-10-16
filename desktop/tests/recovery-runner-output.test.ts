import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSync } from 'esbuild';
import { EventEmitter } from 'node:events';
import { PassThrough, Writable } from 'node:stream';
import { createRequire } from 'node:module';
import { mkdtempSync, readFileSync, readdirSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
const require = createRequire(import.meta.url);

test('actual recovery runner aborts, closes fixtures and persists FAILED after output loss', async () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'audit-runner-output-'));
  const output = path.join(directory, 'report.json');
  let created = 0, closed = 0, quit = 0;
  const code = buildSync({ entryPoints: ['electron/recovery_audit.ts'], bundle: true, platform: 'node', format: 'cjs', write: false, external: ['electron'] }).outputFiles[0].text;
  class Window extends EventEmitter {
    destroyed = false;
    webContents = { executeJavaScript: async () => {} };
    async loadURL() {} isDestroyed() { return this.destroyed; } destroy() { this.destroyed = true; }
  }
  const electron = { app: { whenReady: async () => {}, isPackaged: false, quit: () => { quit++; } }, BrowserWindow: Window };
  const stdout = new Writable({ write(_data, _encoding, done) { done(Object.assign(Error('private output failure'), { code: 'EPIPE' })); } });
  const fakeProcess = { ...process, resourcesPath: path.resolve('.'), argv: ['electron', '.', '--audit-output', output], stdout, stderr: new PassThrough() };
  const module = { exports: {} as any };
  const http = { createServer: () => ({ listen: (_port: number, _host: string, callback: () => void) => callback(),
    address: () => ({ port: 0 }), close: (callback: () => void) => callback() }) };
  new Function('require', 'module', 'exports', '__dirname', 'process', code)(
    (name: string) => name === 'electron' ? electron : name === 'node:http' ? http : require(name),
    module, module.exports, path.resolve('build-electron'), fakeProcess);
  const identity = { fingerprint: 'a'.repeat(64), host_executable: 'owned', machine: {}, runtime: {}, protection_policy: {} };
  const fixture = () => {
    created++; let isClosed = false;
    return { ready: Promise.resolve(), latest: undefined,
      ask: async () => ({ ok: true, result: { audit_identity: identity } }),
      state: async () => ({ native: { prepared: true } }),
      close: async () => { if (!isClosed) { isClosed = true; closed++; } },
    };
  };
  try {
    await assert.rejects(module.exports.runRecoveryAudit(fixture), /audit_output_epipe/);
    const report = JSON.parse(readFileSync(output, 'utf8'));
    assert.equal(report.passed, false); assert.equal(report.status, 'failed');
    assert.equal(report.first_failure, 'audit_output_epipe');
    assert.equal(created, 1, 'No later fixture can start after output failure');
    assert.equal(closed, 1); assert.equal(quit, 1);
    assert.ok(!JSON.stringify(report).includes('private output failure'));
  } finally {
    for (const name of readdirSync(directory)) unlinkSync(path.join(directory, name));
    rmdirSync(directory);
  }
});
