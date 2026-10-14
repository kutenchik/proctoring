import test from 'node:test';
import assert from 'node:assert/strict';
import { FrameAssembler, frameChunks, frameFresh, validFrame } from '../../shared/live-screen';
import { CaptureBudget, captureAllowed, safeAcknowledgement, streamURL } from '../electron/screen_policy';
import { validateCommand } from '../electron/security';
const frame = {type:'frame' as const,viewer_id:'v',sequence:1,width:1280,height:720,captured_at:1000,jpeg_base64:'/9j/'+ 'A'.repeat(150000)};

test('screen relay payload and unordered direct chunks produce the same frame once',() => {
  const a = new FrameAssembler('v'); const chunks = frameChunks(frame);
  assert.ok(chunks.length > 2); assert.ok(chunks.every(c => c.length < 16384));
  const results = chunks.reverse().map(c => a.receive(c)).filter(Boolean);
  assert.deepEqual(results,[frame]); assert.equal(a.receive(JSON.stringify(frame)),null);
});
test('frame assembly bounds partial frames, rejects cross-viewer, expires stale and replaces backlog',() => {
  let now=0; const a=new FrameAssembler('v',()=>now), chunks=frameChunks(frame);
  a.receive(chunks[0]); now=1001; assert.equal(a.receive(chunks[1]),null);
  const fresh={...frame,sequence:2}; assert.deepEqual(a.receive(JSON.stringify(fresh)),fresh);
  for (const c of chunks) assert.equal(a.receive(c),null);
  assert.equal(a.receive(JSON.stringify({...frame,sequence:3,viewer_id:'other'})),null);
  assert.equal(a.receive(JSON.stringify({type:'frame_chunk',sequence:4,index:0,count:1000,data:'x'})),null);
  assert.equal(validFrame({...frame,jpeg_base64:'x'.repeat(400000)}),false);
  assert.equal(validFrame({...frame,width:NaN}),false);
});
test('frame freshness never extrapolates source wall time',() => {
  assert.equal(frameFresh(null,0),false); assert.equal(frameFresh(10,3009),true);
  assert.equal(frameFresh(10,3010),false); assert.equal(frameFresh(20,10),false);
});
test('capture requires current consent, active same attempt/session and unexpired lease',() => {
  const lease={viewer_id:'v',attempt_id:'a',session_id:'s',sender_token:'secret',expires_at:'2026-01-01',lease_seconds:30,server_url:'https://school.test'};
  const state={consent:true,attempt:'a',session:'s',active:true};
  assert.equal(captureAllowed(lease,state,30,29.9),true);
  for (const patch of [{consent:false},{active:false},{attempt:'old'},{session:'new'}]) assert.equal(captureAllowed(lease,{...state,...patch},30,20),false);
  assert.equal(captureAllowed(lease,state,30,30),false);
});
test('transport validates TLS/loopback and adaptive quality has strict bounds',() => {
  assert.equal(streamURL('https://school.test'), 'wss://school.test/api/v1/live/stream');
  assert.equal(streamURL('http://127.0.0.1:8000'),'ws://127.0.0.1:8000/api/v1/live/stream');
  for (const url of ['http://school.test','http://localhost:8000','https://u:p@school.test','file:///secret']) assert.throws(()=>streamURL(url));
  const b=new CaptureBudget(); for(let i=0;i<100;i++)b.congested();
  assert.equal(b.width,800);assert.equal(b.interval,500);assert.equal(b.quality,45);
  for(let i=0;i<1000;i++)b.delivered(); assert.equal(b.width,1280);assert.equal(b.interval,200);
});
test('view capabilities cannot be requested by renderer IPC; consent cannot smuggle credentials',() => {
  assert.equal(validateCommand('screen.consent',{accepted:true}).command,'screen.consent');
  assert.throws(()=>validateCommand('screen.consent',{accepted:true,credential:'secret'}));
  assert.throws(()=>validateCommand('live.poll',{}));
  assert.equal(validateCommand('live.poll',{},true).command,'live.poll');
  const p={viewer_id:'v',state:'live',transport:'relay',reason:''};
  assert.throws(()=>validateCommand('live.capture',p));
  assert.equal(validateCommand('live.capture',p,true).command,'live.capture');
  assert.throws(()=>validateCommand('live.capture',{...p,frame:'data'},true));
  assert.equal(safeAcknowledgement({type:'frame_ack',sequence:4},3),false);
});
