import test from 'node:test';
import assert from 'node:assert/strict';
import { TeacherApi, ApiError } from '../src/api';
import { zonedDateTimeToUtc, routeFromHash } from '../src/time';
import { translate } from '../src/i18n';

test('wall times use the chosen zone instead of browser local time', () => {
  assert.equal(zonedDateTimeToUtc('2026-10-13T15:30', 'Asia/Qyzylorda'), '2026-10-13T10:30:00.000Z');
  assert.equal(zonedDateTimeToUtc('2026-10-13T15:30', 'UTC'), '2026-10-13T15:30:00.000Z');
});
test('invalid timezone, invalid calendar date and missing wall time are rejected', () => {
  assert.throws(() => zonedDateTimeToUtc('2026-10-13T15:30','not/a/zone'), /invalid_timezone/);
  assert.throws(() => zonedDateTimeToUtc('2026-02-31T15:30','UTC'), /invalid_datetime/);
  assert.throws(() => zonedDateTimeToUtc('','UTC'), /invalid_datetime/);
});
test('DST nonexistent and twice-occurring times cannot silently choose offsets', () => {
  assert.throws(() => zonedDateTimeToUtc('2026-03-08T02:30','America/New_York'), /nonexistent_time/);
  assert.throws(() => zonedDateTimeToUtc('2026-11-01T01:30','America/New_York'), /ambiguous_time/);
  assert.equal(zonedDateTimeToUtc('2026-11-01T03:30','America/New_York'), '2026-11-01T08:30:00.000Z');
});
test('invitation and reset hash links parse without HTTP query tokens', () => {
  assert.deepEqual(routeFromHash('#/invite?token=abc'), {page:'invite',token:'abc'});
  assert.deepEqual(routeFromHash('#/reset?token=xyz'), {page:'reset',token:'xyz'});
  assert.deepEqual(routeFromHash('#/exam/exam-1'), {page:'detail',id:'exam-1'});
});
test('all three languages cover essential actions', () => {
  for (const language of ['en','ru','kk'] as const) for (const key of ['login','createExam','reason','attemptHint','phaseHint','saveSet','clientReported']) assert.notEqual(translate(language,key),key);
  assert.equal(translate('en','unknown-key'), 'unknown-key');
  assert.notEqual(translate('ru','login'), translate('kk','login'));
});
test('mutations use same-origin cookies and the active CSRF value', async () => {
  const oldFetch = global.fetch; let received: {url: unknown; options?: RequestInit} | undefined;
  global.fetch = async (url, options) => { received = {url, options}; return Response.json({ok:true}); };
  try {
    const api = new TeacherApi(); api.setAuth({teacher:{id:'teacher',name:'Teacher',email:'test@example.invalid'},csrf_token:'csrf-one'});
    await api.request('/attempts/a/extend','POST',{reason:'extra setup time'});
    assert.equal(received?.url, '/api/v1/attempts/a/extend');
    assert.equal(received?.options?.credentials, 'same-origin');
    assert.equal((received?.options?.headers as Record<string,string>)['X-CSRF-Token'], 'csrf-one');
    api.setAuth(null); await api.request('/auth/login','POST',{email:'test@example.invalid',password:'fake'});
    assert.equal((received?.options?.headers as Record<string,string>)['X-CSRF-Token'], undefined);
  } finally { global.fetch = oldFetch; }
});
test('network and validation failures are explicit errors, not successful empty state', async () => {
  const oldFetch = global.fetch;
  try {
    global.fetch = async () => { throw new Error('offline'); };
    await assert.rejects(new TeacherApi().request('/exams'), (e: unknown) => e instanceof ApiError && e.code === 'network_unavailable');
    global.fetch = async () => Response.json({detail:{code:'invalid_window',message:'Invalid window'}},{status:400});
    await assert.rejects(new TeacherApi().request('/exams','POST',{}), (e: unknown) => e instanceof ApiError && e.code === 'invalid_window' && e.status === 400);
  } finally {global.fetch = oldFetch;}
});
test('API refuses origin escape paths', async () => {
  await assert.rejects(new TeacherApi().request('//example.invalid'), /invalid_api_path/);
});
