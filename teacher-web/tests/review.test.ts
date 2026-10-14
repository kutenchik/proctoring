import test from 'node:test';
import assert from 'node:assert/strict';
import { conclusionDecisions, decisionFor, eventsInGroup, evidenceUrl, mayFinalize, reviewPayload, safeDuration, type ReviewEvent } from '../src/review-model';
import { translate } from '../src/i18n';
import { routeFromHash } from '../src/time';
const event = (id: string, version=0): ReviewEvent => ({event_id:id,event_type:'phone_visible',timestamp:'2026-10-14T08:00:00Z',duration_seconds:1,category:'behavioral',files:[],history:[],review:version?{version,decision:'confirmed',comment:'existing'}:null});
test('bulk review preserves every original event identity and expected version', () => {
  assert.deepEqual(reviewPayload([event('e1'),event('e2',3)],'false_positive',' corrected '),{items:[{event_id:'e1',expected_version:0,decision:'false_positive',comment:'corrected'},{event_id:'e2',expected_version:3,decision:'false_positive',comment:'corrected'}]});
});
test('group display does not merge records or overwrite individual exceptions', () => {
  const events=[event('e1'),event('e2',2),event('e3')];
  const members=eventsInGroup({events},{id:'g1',event_ids:['e1','e2'],event_type:'phone_visible',category:'behavioral'});
  assert.equal(members.length,2);assert.equal(decisionFor(members[0]).decision,'not_reviewed');assert.equal(decisionFor(members[1]).version,2);assert.equal(events.length,3);
});
test('conclusion cannot be enabled by finished status or checkbox without server eligibility', () => {
  assert.equal(mayFinalize({can_finalize:false,unreviewed_count:0},true),false);
  assert.equal(mayFinalize({can_finalize:true,unreviewed_count:2},false),false);
  assert.equal(mayFinalize({can_finalize:true,unreviewed_count:2},true),true);
  assert.equal(mayFinalize({can_finalize:true,unreviewed_count:0},false),true);
});
test('evidence URL uses exact teacher-owned route and encoded opaque segments', () => {
  assert.equal(evidenceUrl('a/1','x#2'),'/api/v1/attempts/a%2F1/evidence/x%232');
  assert.deepEqual(routeFromHash('#/attempt/abc'),{page:'attempt',id:'abc'});
});
test('invalid durations display unavailable without inventing zero', () => {
  assert.equal(safeDuration(null),'—');assert.equal(safeDuration('3'),'—');assert.equal(safeDuration(NaN),'—');assert.equal(safeDuration(-1),'—');assert.equal(safeDuration(3.125),'3.13');
});
test('new review actions and outcomes have EN/RU/KK translations; conclusion is not inferred', () => {
  for(const language of ['en','ru','kk'] as const) for(const key of ['receiptPending','conclusionBlocked','reviewGroup','manualTitle','confirmUnreviewed','deleteConfirm','grantRecovery','historicalImage','verifiedScore']) assert.notEqual(translate(language,key),key);
  assert.deepEqual(conclusionDecisions,['none_confirmed','violation_confirmed','insufficient_evidence']);
});

test('actual session lifecycle event codes have readable labels in every interface language', () => {
  for(const code of ['monitoring_failed','monitoring_recovered','monitoring_interruption_ended','application_interrupted','application_recovered','connected_terminal','session_started','session_recovered','session_ended','proctor_paused','proctor_resumed','recovery_pin_required','presentation_lost','presentation_recovered']) {
    for(const language of ['en','ru','kk'] as const) assert.notEqual(translate(language,`event_${code}`),`event_${code}`);
  }
});
