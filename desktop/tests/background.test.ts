import test from 'node:test';
import assert from 'node:assert/strict';
import type { BackendState } from '../shared/contracts';
import { pendingReceiptOnClose, canUploadInBackground, backgroundFinished, requestBackgroundUpload } from '../electron/background';
import { validateCommand } from '../electron/security';
function state(): BackendState { return {workflow:{session:{ended:true}},protection:{enabled:false},audio:{running:false},camera:{state:'stopped'},synchronization:{can_background:true,fully_synchronized:false,pending_attempts:1}} as BackendState; }
test('background requires terminal exam plus confirmed media and protection release',()=>{
  const s=state();assert.equal(canUploadInBackground(s),true);
  s.workflow!.session.ended=false;assert.equal(canUploadInBackground(s),false);s.workflow!.session.ended=true;
  s.protection.enabled=true;assert.equal(canUploadInBackground(s),false);s.protection.enabled=false;
  s.audio.running=true;assert.equal(canUploadInBackground(s),false);s.audio.running=false;
  s.camera.state='live';assert.equal(canUploadInBackground(s),false);s.camera.state='stopped';
  s.synchronization!.can_background=false;assert.equal(canUploadInBackground(s),false);
});
test('background exit needs verified receipt cleanup and no other pending attempts',()=>{
  const s=state();assert.equal(backgroundFinished(s),false);s.synchronization!.fully_synchronized=true;
  assert.equal(backgroundFinished(s),false);s.synchronization!.pending_attempts=0;assert.equal(backgroundFinished(s),true);
});
test('renderer synchronization IPC allows only narrow empty commands',()=>{
  for(const name of ['sync.retry','sync.background','sync.exit']){
    assert.equal(validateCommand(name,{}).command,name);
    assert.throws(()=>validateCommand(name,{credential:'bad'}));
    assert.throws(()=>validateCommand(name,{path:'C:/'}));
  }
});
test('actual main handler requests release first and hides only after matching backend state',async()=>{
  const s=state();const calls:string[]=[];
  const request=async()=>{calls.push('backend');return {version:1 as const,id:'x',ok:true as const,result:s};};
  s.workflow!.session.ended=false;
  assert.equal((await requestBackgroundUpload(s,request,()=>calls.push('hide'))).ok,false);
  assert.equal(calls.length,0);
  s.workflow!.session.ended=true;
  await requestBackgroundUpload(s,request,()=>calls.push('hide'));
  assert.deepEqual(calls,['backend','hide']);
  calls.length=0;
  await requestBackgroundUpload(s,async()=>{calls.push('backend');return {...await request(),result:{...s,audio:{...s.audio,running:true}}};},()=>calls.push('hide'));
  assert.equal(calls.includes('hide'),false);
});
test('actual main handler leaves window visible after backend rejection or disconnect',async()=>{
  let hidden=false;const enter=()=>{hidden=true;};
  await requestBackgroundUpload(state(),async()=>({version:1,id:'x',ok:false,error:{code:'background_not_ready',message:'release pending'}}),enter);
  await assert.rejects(requestBackgroundUpload(state(),async()=>{throw Error('backend disconnected');},enter));
  assert.equal(hidden,false);
});

test('normal summary close warns until a complete verified receipt exists',()=>{
  const s=state();assert.equal(pendingReceiptOnClose(s),true);
  s.synchronization!.status='verifying';assert.equal(pendingReceiptOnClose(s),true);
  s.synchronization!.fully_synchronized=true;assert.equal(pendingReceiptOnClose(s),false);
  s.workflow!.session.ended=false;assert.equal(pendingReceiptOnClose(s),false);
  assert.equal(pendingReceiptOnClose(undefined),false);
});
