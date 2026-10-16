import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { mkdtempSync, readFileSync, writeFileSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { ensureRuntimeConfig, resolveRuntime } from '../electron/runtime';

const options = { packaged: true, appRoot: 'C:/bundle/resources/app', resources: 'C:/bundle/resources', executable: 'C:/bundle/LocalProctoring.exe',
  cwd: 'C:/operator', argv: [], env: { LOCALAPPDATA: 'C:/local', PROCTORING_PYTHON: 'C:/untrusted/python.exe', PROCTORING_DEV_URL: 'http://127.0.0.1:5173' } };
test('packaged runtime uses only bundled backend and writable local config', () => {
  const r = resolveRuntime(options);
  assert.equal(r.python, path.join(options.resources, 'backend', 'ProctoringBackend.exe'));
  assert.deepEqual(r.supervisorPrefix, ['--desktop-supervisor']);
  assert.deepEqual(r.auditPrefix, ['--electron-recovery-audit']);
  assert.equal(r.dev, false);
  assert.equal(path.dirname(r.config), path.join('C:/local', 'LocalProctoring', 'Student'));
  assert.match(path.basename(r.config), /^config-[a-f0-9]{24}\.toml$/);
  assert.equal(r.auditOutput, path.join('C:/local', 'LocalProctoring', 'Student', 'audits', 'startup-current.json'));
});
test('packaged explicit config resolves against caller cwd while source preserves repo behavior', () => {
  assert.equal(resolveRuntime({ ...options, argv: ['--config', 'custom.toml'] }).config, path.resolve(options.cwd, 'custom.toml'));
  const source = resolveRuntime({ ...options, packaged: false, argv: ['--config', 'config/demo.toml'] });
  assert.equal(source.config, path.resolve(options.appRoot, '..', 'config/demo.toml'));
  assert.equal(source.dev, true);
  assert.throws(() => resolveRuntime({ ...options, argv: ['--config'] }), /requires a path/);
});
test('first-run defaults are copied once and unexpected edits block default launch', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'proctoring-runtime-'));
  try {
    mkdirSync(path.join(dir, 'resources'));
    writeFileSync(path.join(dir, 'resources/default.example.toml'), '[protection]\nenabled=false\n');
    const r = resolveRuntime({ ...options, resources: path.join(dir, 'resources'), env: { LOCALAPPDATA: dir } });
    ensureRuntimeConfig(r);
    assert.match(readFileSync(r.config, 'utf8'), /enabled=false/);
    writeFileSync(r.config, '# operator settings'); assert.throws(()=>ensureRuntimeConfig(r), /configuration changed/);
    assert.equal(readFileSync(r.config, 'utf8'), '# operator settings');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
