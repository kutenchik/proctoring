import test from 'node:test';
import assert from 'node:assert/strict';
import { start } from './stage4b-browser-observer.mjs';

function fixture(t) {
  let now = 100, value = { viewer_id: 'v1', state: 'live', transport: 'relay' }, delivery = { frames: 1, firstPresentedAt: 100, lastPresentedAt: 100 }, stops = 0;
  const callbacks = [], elements = [];
  const stop = { textContent: 'Stop viewing', disabled: false, click: () => stops++ };
  const panel = { getAttribute: name => JSON.stringify(name === 'data-stream-observation' ? value : delivery), querySelector: () => ({ style: { visibility: 'visible' } }), querySelectorAll: () => [stop] };
  const document = { body: { append() {} }, querySelector: () => panel, createElement: tag => { const e = { tag, style: {}, textContent: '', append() {}, click() {} }; elements.push(e); return e; } };
  for (const [name, v] of Object.entries({ window: {}, document, setInterval: fn => { callbacks.push(fn); return 1; }, clearInterval() {}, setTimeout: fn => { callbacks.push(fn); return 2; }, clearTimeout() {} })) {
    const old = Object.getOwnPropertyDescriptor(globalThis, name); Object.defineProperty(globalThis, name, { value: v, configurable: true });
    t.after(() => old ? Object.defineProperty(globalThis, name, old) : delete globalThis[name]);
  }
  t.mock.method(performance, 'now', () => now);
  return { begin: () => start(Date.now() + 600000), tick: n => { now = n; callbacks[0](); }, set: v => { value = v; }, stops: () => stops, elements };
}
test('browser observer does not start or stop a normal viewer and refuses duplicate installation', t => {
  const f = fixture(t); assert.match(f.begin(), /No viewer or devices/); f.tick(30100); assert.equal(f.stops(), 0); assert.throws(() => f.begin());
});
test('browser observer stops once on terminal failure and keeps numeric export available', t => {
  const f = fixture(t); f.begin(); f.set({ viewer_id: 'v1', state: 'unavailable', reason: 'capture_failed' }); f.tick(200);
  assert.equal(f.stops(), 1); assert.equal(typeof window.__stage4bObserver.save, 'function');
});
test('planned remote network marker excuses only that viewer connection loss', t => {
  const f = fixture(t); f.begin(); f.elements.find(e => e.textContent === 'Mark planned teacher-network interruption').onclick();
  f.set({ viewer_id: 'v1', state: 'unavailable', reason: 'connection_lost' }); f.tick(200); assert.equal(f.stops(), 0);
  f.set({ viewer_id: 'v2', state: 'unavailable', reason: 'connection_lost' }); f.tick(300); assert.equal(f.stops(), 1);
});
