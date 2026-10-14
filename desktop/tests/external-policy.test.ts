import test from 'node:test';
import assert from 'node:assert/strict';
import { ExamNavigationPolicy, safeExternalBounds } from '../electron/external_policy';
import { validateEvidence, validateExternal, validateCommand } from '../electron/security';

test('external document policy preserves exact-host HTTP(S) behavior', () => {
  const policy = new ExamNavigationPolicy('https://exam.example.edu/start?token=not-a-real-token', []);
  for (const url of ['https://exam.example.edu/question/2', 'http://exam.example.edu/form', 'https://EXAM.EXAMPLE.EDU./quiz']) assert.equal(policy.allows(url), true, url);
  for (const url of ['https://google.com/', 'https://chatgpt.com/', 'https://sub.exam.example.edu/', 'https://exam.example.edu.evil.test/', 'https://exam.example.edu@evil.test/', 'file:///C:/Windows/win.ini', 'javascript:alert(1)', 'data:text/html,test', 'https://exam.example.edu:/', 'https://exam.example.edu\\@evil.test/', 'https://%65xam.example.edu/']) assert.equal(policy.allows(url), false, url);
  assert.throws(() => new ExamNavigationPolicy('https://exam.example.edu/', ['example.edu']));
  assert.throws(() => new ExamNavigationPolicy('https://exam.example.edu/', ['*.example.edu']));
});
test('controlled loopback test allowance is explicit, not a production policy bypass', () => {
  const policy = new ExamNavigationPolicy('http://127.0.0.1:49152/fixture', ['127.0.0.1']);
  assert.equal(policy.allows('http://127.0.0.1:49152/next'), true);
  assert.equal(policy.allows('http://localhost:49152/next'), false);
  assert.equal(policy.allows('http://127.1:49152/next'), false);
  const ipv6 = new ExamNavigationPolicy('http://[0:0:0:0:0:0:0:1]/', ['::1']);
  assert.equal(ipv6.allows('http://[::1]/next'), true);
});
test('native bounds reserve trusted chrome and monitoring even for oversized renderer request', () => {
  const box = safeExternalBounds({ x: 0, y: 0, width: 9999, height: 9999 }, { width: 1280, height: 720 });
  assert.ok(box); assert.equal(box.y, 108); assert.ok(box.x + box.width <= 976); assert.ok(box.y + box.height <= 708);
  const scaled = safeExternalBounds({ x: 16, y: 120, width: 500, height: 200 }, { width: 1280, height: 720 }, 1.5);
  assert.deepEqual(scaled, { x: 24, y: 180, width: 750, height: 300 });
  assert.equal(safeExternalBounds({ x: 9999, y: 9999, width: 20, height: 20 }, { width: 1280, height: 720 }), null);
});
test('evidence and native-view intents cannot supply arbitrary paths, URLs or authorization', () => {
  const request = { session_id: `session-${'a'.repeat(32)}`, kind: 'snapshot', event_id: 'event-000001', action: 'open' };
  assert.equal(validateEvidence(request).event_id, 'event-000001');
  for (const patch of [{ session_id: '../secret' }, { event_id: '../../secret' }, { path: 'C:/secret.pdf' }, { kind: 'config' }]) assert.throws(() => validateEvidence({ ...request, ...patch }));
  assert.throws(() => validateExternal({ action: 'reload', url: 'https://evil.test/' }));
  assert.throws(() => validateExternal({ action: 'layout', bounds: { x: NaN, y: 0, width: 100, height: 100 }, visible: true, modal: false }));
  assert.throws(() => validateCommand('proctor.resume', { pin: '1234', authenticated: true }));
  assert.throws(() => validateCommand('calibration.presented', { token: 'a', target: 'DOWN', geometry: {} }));
  assert.equal(validateCommand('calibration.presented', { token: 'a', target: 'DOWN', geometry_id: 'from-main' }).command, 'calibration.presented');
});
