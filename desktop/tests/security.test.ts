import test from 'node:test';
import assert from 'node:assert/strict';
import { PRODUCTION_CSP, trustedRenderer, validateCommand } from '../electron/security';
import { validatePreview } from '../electron/preview';

test('allowlist admits typed workflow intents and rejects privileged/arbitrary commands', () => {
  assert.equal(validateCommand('state.get', {}).command, 'state.get');
  assert.equal(validateCommand('setup.show', {}).command, 'setup.show');
  assert.throws(() => validateCommand('setup.show', { ready: true }));
  assert.equal(validateCommand('camera.select', { key: 'qt-id' }).command, 'camera.select');
  assert.equal(validateCommand('exam.start', {}).command, 'exam.start');
  assert.throws(() => validateCommand('exam.start', { ready: true }));
  for (const command of ['shutdown', 'host.external', 'host.evidence', 'presentation.sync', 'geometry.changed', 'exec', 'file.read', 'pin.submit', 'remote.send']) assert.throws(() => validateCommand(command, {}));
  assert.throws(() => validateCommand('camera.select', { key: 'a', path: 'C:\\secret' }));
  assert.throws(() => validateCommand('consent.set', { accepted: 'true' }));
  assert.throws(() => validateCommand('state.get', []));
  assert.throws(() => validateCommand('camera.select', { key: 'x'.repeat(17000) }));
});
test('trusted UI URL requires exact origin and path', () => {
  const url = 'http://127.0.0.1:5173/';
  assert.equal(trustedRenderer(url, url), true);
  for (const wrong of ['http://localhost:5173/', 'http://127.0.0.1:5173/remote', 'https://127.0.0.1:5173/', 'http://127.0.0.1.attacker.test:5173/']) assert.equal(trustedRenderer(wrong, url), false);
  assert.equal(trustedRenderer('file:///C:/other.html', 'file:///C:/index.html'), false);
  assert.match(PRODUCTION_CSP, /connect-src 'none'/);
  assert.match(PRODUCTION_CSP, /frame-src 'none'/);
});
test('preview requires matching bounded image metadata', () => {
  const frame = { sequence: 2, captured_at: 123, width: 640, height: 480, source_width: 1280, source_height: 960, mime: 'image/jpeg', jpeg_base64: 'YQ==', overlays: [] };
  assert.equal(validatePreview(frame).source_width, 1280);
  for (const patch of [{ source_width: NaN }, { width: 0 }, { jpeg_base64: '<script>' }, { jpeg_base64: 'x'.repeat(700001) }, { mime: 'text/html' }]) assert.throws(() => validatePreview({ ...frame, ...patch }));
});
