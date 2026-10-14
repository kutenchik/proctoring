import test from 'node:test';
import assert from 'node:assert/strict';
import { PresentationGate } from '../electron/presentation';

test('new minimize/crash during asynchronous sync keeps presentation paused', () => {
  const gate = new PresentationGate();
  assert.equal(gate.lose(), true);
  assert.equal(gate.lose(), false); // repeated expired-lease tick
  const receipt = gate.beginSync()!;
  assert.equal(gate.beginSync(), null); // no overlapping acknowledgements
  assert.equal(gate.lose(), true); // new loss must enqueue a fresh backend pause
  assert.equal(gate.lose(), false);
  assert.equal(gate.finishSync(receipt, true), false); // late success is stale
  assert.equal(gate.lost, true);
  const fresh = gate.beginSync()!;
  assert.equal(gate.finishSync(fresh, true), true);
  assert.equal(gate.lost, false);
});

test('failed receipt never clears presentation loss', () => {
  const gate = new PresentationGate(); gate.lose();
  const receipt = gate.beginSync()!;
  assert.equal(gate.finishSync(receipt, false), false);
  assert.equal(gate.lost, true);
  assert.notEqual(gate.beginSync(), null);
});
