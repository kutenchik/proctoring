import test from 'node:test';
import assert from 'node:assert/strict';
import { AuditClient } from '../electron/audit_client';

// A real owned Node child, without Qt, devices, a native helper or suppression.
const endpoint = `
const readline = require('node:readline');
readline.createInterface({input:process.stdin}).on('line', line => {
  const request = JSON.parse(line);
  if (request.command === 'audit.crash') process.exit(23);
  if (request.command === 'hang') return;
  process.stdout.write(JSON.stringify({version:1,id:request.id,ok:true,result:{protection:{},native:{},backend_pid:process.pid}})+'\\n');
  if (request.command === 'shutdown') process.exit(0);
});
`;
const start = () => new AuditClient(process.execPath, ['-e', endpoint], process.cwd(), 'a'.repeat(32));

test('owned audit endpoint crash settles in-flight polls and later writes fail promptly', async () => {
  const client = start();
  try {
    assert.equal((await client.raw('audit.status')).ok, true);
    const pending = client.raw('hang');
    const requests = [client.raw('audit.crash'), ...Array.from({ length: 20 }, () => client.raw('audit.status'))];
    const results = await Promise.all([pending, ...requests]);
    assert.ok(results.every(result => result.ok === false));
    assert.equal(client.available, false);
    assert.equal((await client.raw('audit.status')).ok, false);
    const closing = client.close();
    assert.equal(client.close(), closing);
    await closing;
    assert.equal(client.child.exitCode, 23);
    assert.equal(client.child.killed, false, 'Endpoint crashed itself; cleanup must not kill it');
  } finally { await client.close(); }
});

test('stdin error event is consumed, settles all pending requests, and permits cleanup', async () => {
  const client = start();
  try {
    await client.raw('audit.status');
    const pending = [client.raw('hang'), client.raw('hang')];
    const error = Object.assign(new Error('controlled stream failure'), { code: 'EPIPE' });
    assert.doesNotThrow(() => client.child.stdin.emit('error', error));
    assert.ok((await Promise.all(pending)).every(result => !result.ok));
    assert.equal(client.available, false);
    assert.equal((await client.raw('audit.status')).ok, false);
  } finally { await client.close(); }
  assert.equal(client.child.killed, false);
});

test('close rejects subsequent commands while sharing one graceful child cleanup', async () => {
  const client = start();
  await client.raw('audit.status');
  const closing = client.close();
  assert.equal(client.close(), closing);
  assert.equal((await client.raw('audit.status')).ok, false);
  await closing;
  assert.equal(client.child.exitCode, 0);
  assert.equal(client.child.killed, false);
});
