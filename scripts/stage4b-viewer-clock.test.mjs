import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ViewerClock } from './stage4b-viewer-clock.mjs';
const make = () => new ViewerClock({ overallStart: 0, overallMs: 900000, viewerMs: 300000 });
const sample = (id, first, state = 'live') => ({ viewer_id: id, firstPresentedAt: first, frames: first === null ? 0 : 1, state, reason: 'capture_failed' });
test('manual fresh viewer gets independent clock despite old expired clock', () => {
  const c = make(); c.sample(0, sample('old', 0)); c.sample(290000, sample('old', 0, 'stopped'));
  assert.equal(c.sample(291000, sample('fresh', 291000)).elapsed_ms, 0);
  const v = c.sample(321000, sample('fresh', 291000)); assert.equal(v.stop, null); assert.equal(v.idle_complete, true);
});
test('time begins at first actual displayed frame, not ready; repeats do not reset', () => {
  const c = make(); assert.equal(c.sample(100, sample('a', null)).elapsed_ms, null);
  c.sample(2000, sample('a', 1800)); assert.equal(c.sample(31800, sample('a', 9999)).elapsed_ms, 30000);
});
test('recovery and stale observations do not reset same viewer clock or claim continuity', () => {
  const c = make(); c.sample(0, sample('a', 0)); c.sample(10000, sample('a', 0, 'recovering'));
  assert.equal(c.sample(210000, sample('a', 0)).sustained_time_complete, true);
});
test('overall deadline cannot be extended by new identity', () => {
  const c = make(); c.sample(899000, sample('new', 899000)); assert.equal(c.sample(900000, sample('new', 899000)).stop, 'overall_deadline');
});
test('no frames still has bounded viewer timeout', () => { const c = make(); c.sample(0, sample('a', null)); assert.equal(c.sample(300000, sample('a', null)).stop, 'viewer_deadline'); });
test('first terminal failure persists through cleanup and prevents restart', () => {
  const c = make(); c.sample(2, sample('a', 1, 'unavailable')); c.sample(3, sample('a', 1, 'stopped'));
  assert.equal(c.sample(4, sample('b', 4)).stop, 'terminal_failure'); assert.equal(c.firstFailure.at, 2);
});
test('explicit stop is not terminal; return to same ID cannot refresh its timer', () => {
  const c = make(); c.sample(0, sample('a', 0)); assert.equal(c.sample(1, sample('a', 0, 'stopped')).stop, null);
  c.sample(2, sample('b', 2)); assert.equal(c.sample(300000, sample('a', 0)).stop, 'viewer_deadline'); assert.equal(c.firstFailure, null);
});
test('bounded identity set and invalid identity rejection', () => {
  const c = make(); for (const id of ['a','b','c']) c.sample(1, sample(id, 1));
  assert.equal(c.sample(2, sample('d', 2)).stop, 'viewer_limit'); assert.throws(() => c.sample(2, sample('secret?url', 2)));
});
test('planned network loss permits fresh authorization but never excuses privacy failure', () => {
  const c = make(); assert.equal(c.sample(1, { ...sample('a', 1, 'unavailable'), expected_network: true, reason: 'connection_lost' }).stop, null);
  assert.equal(c.sample(2, sample('b', 2)).elapsed_ms, 0);
  assert.equal(c.sample(3, { ...sample('b', 2, 'unavailable'), expected_network: true }).stop, 'terminal_failure');
});
