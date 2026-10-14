import { StreamTrace, validStreamTrace } from '../../shared/stream-trace';
import test from 'node:test';
import assert from 'node:assert/strict';
import { ReviewEventCache } from '../src/hooks/reviewEventCache';
const record=(state:string,id='event-1')=>({event_id:id,event_type:'second_person',state,record_kind:'review_event',activated_timestamp:'2026-10-14T10:00:00Z'});
test('journal replay cannot resurrect a closed snapshot or roll back a sustained warning',()=>{
  const cache=new ReviewEventCache();cache.snapshot([record('closed')],40);
  for(let sequence=0;sequence<40;sequence++)cache.journal([{sequence,record:record(sequence%2?'active':'clearing')}]);
  assert.equal(cache.values()[0].state,'closed');assert.equal(cache.values().length,1);
  cache.journal([{sequence:41,record:record('active','event-2')}]);
  cache.snapshot([record('closed')],40);
  assert.deepEqual(cache.values().map(r=>r.state),['closed','active']);
});
test('clearing is same ID; repeated updates and unordered replay do not duplicate/reorder events',()=>{
  const cache=new ReviewEventCache();
  cache.snapshot([record('active')],1);
  for(let sequence=1;sequence<100;sequence++)cache.journal([{sequence,record:record(sequence%2?'clearing':'active')}]);
  cache.journal([{sequence:2,record:record('closed')}]);
  assert.equal(cache.values().length,1);assert.equal(cache.values()[0].state,'clearing');
  cache.journal([{sequence:100,record:record('closed')},{sequence:101,record:record('active','event-2')}]);
  assert.deepEqual(cache.values().map(r=>r.event_id),['event-1','event-2']);
});

test('trace validation accepts only finite bounded numeric rows and no private fields',()=>{
  // This production schema is shared with the observer and terminal diagnostic.
  const trace=new StreamTrace();for(let i=0;i<200;i++)trace.record('send',i,100);
  assert.equal(trace.snapshot().records.length,128);assert.equal(trace.snapshot().counts.send,200);
  assert.equal(validStreamTrace(trace.snapshot()),true);
  assert.equal(validStreamTrace({...trace.snapshot(),payload:'private'}),false);
});
