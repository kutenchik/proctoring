import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { authorizeStartup, type Inspection, type StartupDependencies } from '../electron/startup_gate';
import { securityHtml, securityStrings } from '../electron/startup_screen';

async function fixture(t: any) {
  const root = await mkdtemp(path.join(tmpdir(), 'startup-gate-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const current = path.join(root, 'current.json');
  await writeFile(path.join(root, 'evidence'), 'pending student evidence');
  let runs = 0, valid = false, retry = false, prompts = 0;
  const identity: Inspection = { identity: { build: 'A', machine: 'M' }, config_sha256: 'config', report_path: current, valid: false, language: 'en' };
  const d: StartupDependencies = { directory: path.join(root, 'history'), portableIdentity: 'exe-A', cancelled: () => false,
    inspect: async report => ({ ...identity, valid: report ? true : valid }),
    confirmRetry: async () => { prompts++; return retry; },
    run: async report => { runs++; await writeFile(report, '{"authoritative":"mock report"}'); valid = true; return { status: 'exited', exit_code: 0 }; },
  };
  return { root, current, d, identity, get runs() { return runs; }, get prompts() { return prompts; },
    expire: () => { valid = false; }, allowRetry: () => { retry = true; } };
}
test('first launch automatically audits, then reuses valid report without touching evidence/history', async t => {
  const f = await fixture(t);
  assert.equal(await authorizeStartup(f.d), true); assert.equal(f.runs, 1); assert.equal(f.prompts, 0);
  assert.equal(await authorizeStartup(f.d), true); assert.equal(f.runs, 1);
  assert.equal(await readFile(path.join(f.root, 'evidence'), 'utf8'), 'pending student evidence');
  const directory = path.join(f.d.directory, (await readdir(f.d.directory))[0]);
  assert.equal((await readdir(directory)).filter(x => x !== 'receipt.json').length, 1);
});

test('explicit trusted no-audit edition verifies package but never runs or invents an audit', async t => {
  const f = await fixture(t);
  f.d.inspect = async () => ({ ...f.identity, audit_required: false, valid: false });
  assert.equal(await authorizeStartup(f.d), true);
  assert.equal(f.runs, 0); assert.equal(f.prompts, 0);
  await assert.rejects(readFile(f.current));
  f.d.cancelled = () => true;
  assert.equal(await authorizeStartup(f.d), false);
  f.d.inspect = async () => { throw Error('Package integrity failed'); };
  await assert.rejects(authorizeStartup(f.d), /integrity/);
});
test('expiry, executable change, configuration and runtime changes require fresh audits', async t => {
  const f = await fixture(t); await authorizeStartup(f.d);
  f.expire(); await authorizeStartup(f.d); assert.equal(f.runs, 2);
  f.d.portableIdentity = 'exe-B'; await authorizeStartup(f.d); assert.equal(f.runs, 3);
  f.identity.config_sha256 = 'changed'; await authorizeStartup(f.d); assert.equal(f.runs, 4);
  f.identity.identity = { build: 'B' }; await authorizeStartup(f.d); assert.equal(f.runs, 5);
});
for (const status of ['failed', 'crashed', 'EPIPE']) test(`${status} cannot authorize or automatically retry`, async t => {
  const f = await fixture(t); const run = f.d.run;
  f.d.run = async report => { await run(report); return { status, exit_code: status === 'EPIPE' ? 0 : 1 }; };
  await assert.rejects(authorizeStartup(f.d), /did not finish/);
  assert.equal(await authorizeStartup(f.d), false); assert.equal(f.runs, 1); assert.equal(f.prompts, 1);
  f.allowRetry(); f.d.run = run; assert.equal(await authorizeStartup(f.d), true); assert.equal(f.runs, 2);
});
test('invalid/incomplete final report and changed runtime fail even with exit zero', async t => {
  const f = await fixture(t); f.d.inspect = async () => f.identity;
  await assert.rejects(authorizeStartup(f.d), /does not match/);
  assert.equal(await authorizeStartup(f.d), false);
});
test('never authorizes until the child and its output pipes close', async t => {
  const f = await fixture(t); const run = f.d.run;
  let release!: () => void; const closed = new Promise<void>(resolve => { release = resolve; });
  let finished = false;
  f.d.run = async report => { const result = await run(report); await closed; return result; };
  const pending = authorizeStartup(f.d).then(result => { finished = true; return result; });
  await new Promise(resolve => setTimeout(resolve, 50)); assert.equal(finished, false);
  release(); assert.equal(await pending, true);
});
test('closing startup prevents audit and Join', async t => {
  const f = await fixture(t); f.d.cancelled = () => true;
  assert.equal(await authorizeStartup(f.d), false); assert.equal(f.runs, 0);
});
test('localized progress starts at zero and never claims success from check counts', () => {
  for (const language of ['en','ru','kk']) {
    const html = securityHtml(language);
    assert.ok(html.includes(securityStrings(language)[0])); assert.ok(html.includes('0 / 21'));
    assert.ok(html.includes('Ctrl+Shift+Alt+Q')); assert.ok(html.includes(securityStrings(language)[5]));
    assert.ok(!html.includes('value="21"')); assert.ok(!html.includes('<script'));
  }
});
