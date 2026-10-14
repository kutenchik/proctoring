import test from 'node:test';
import assert from 'node:assert/strict';
import { LiveViewer, type ViewState } from '../src/live-viewer';

// Production decoder with synthetic frames and no browser, network or devices.
function harness(t:any) {
  let now=0,painted=0,cleared=0,stops=0;
  const intervals=new Set<()=>void>(),timeouts=new Set<()=>void>(),sockets:any[]=[],states:ViewState[]=[];
  const pending:{resolve:(bitmap:any)=>void;reject:()=>void}[]=[];
  class WS {static OPEN=1;readyState=1;sent:any[]=[];onopen:any;onmessage:any;onclose:any;onerror:any;closed=false;
    constructor(){sockets.push(this);}send(text:string){this.sent.push(JSON.parse(text));}close(){this.closed=true;}}
  for(const [name,value] of Object.entries({WebSocket:WS,location:{href:'http://127.0.0.1/'},
    setInterval:(f:()=>void)=>{intervals.add(f);return f;},clearInterval:(f:()=>void)=>intervals.delete(f),
    setTimeout:(f:()=>void)=>{timeouts.add(f);return f;},clearTimeout:(f:()=>void)=>timeouts.delete(f),
    createImageBitmap:()=>new Promise((resolve,reject)=>pending.push({resolve,reject:()=>reject(Error('invalid synthetic frame'))}))})) {
    const original=Object.getOwnPropertyDescriptor(globalThis,name);
    Object.defineProperty(globalThis,name,{configurable:true,writable:true,value});
    t.after(()=>{if(original)Object.defineProperty(globalThis,name,original);else delete (globalThis as any)[name];});
  }
  t.mock.method(performance,'now',()=>now);
  const canvas={width:80,height:60,getContext:()=>({drawImage:()=>painted++,clearRect:()=>cleared++})};
  const viewer=new LiveViewer({viewer_id:'v'} as any,'csrf',canvas as any,s=>states.push(s),()=>stops++);
  t.after(()=>viewer.close());const socket=sockets[0];socket.onopen();
  const message=(value:any)=>socket.onmessage({data:JSON.stringify(value)});
  const frame=(sequence:number)=>message({type:'frame',viewer_id:'v',sequence,width:80,height:60,captured_at:1,jpeg_base64:'/9j/AAAA'});
  const finish=async()=>{pending.shift()!.resolve({width:80,height:60,close(){}});await Promise.resolve();await Promise.resolve();};
  const reject=async()=>{pending.shift()!.reject();await Promise.resolve();await Promise.resolve();};
  return {viewer,socket,states,frame,message,finish,reject,painted:()=>painted,cleared:()=>cleared,stops:()=>stops,intervals,timeouts,
    tick:(at:number)=>{now=at;for(const fn of intervals)fn();}};
}

test('recovery hides old image, invalidates pending decode and resumes only a fresh frame',async t=>{
  const h=harness(t);h.frame(1);await h.finish();assert.equal(h.painted(),1);
  h.frame(2);h.message({type:'capture.recovering',viewer_id:'v',through_sequence:2});
  assert.equal(h.states.at(-1)!.state,'recovering');assert.equal(h.states.at(-1)!.receivedAt,null);
  await h.finish();assert.equal(h.painted(),1,'decode started before barrier cannot paint');
  h.tick(1000);assert.equal(h.states.at(-1)!.state,'recovering');assert.equal(h.socket.closed,false);
  h.frame(3);await h.finish();assert.equal(h.painted(),2);assert.equal(h.states.at(-1)!.state,'live');
  assert.deepEqual(h.socket.sent.filter((m:any)=>m.type==='frame_ack').map((m:any)=>m.sequence),[1,3]);
});

test('late recovery notification cannot hide a newer validated direct/relay frame',async t=>{
  const h=harness(t);h.frame(3);await h.finish();const clears=h.cleared();
  h.message({type:'capture.recovering',viewer_id:'v',through_sequence:2});
  assert.equal(h.states.at(-1)!.state,'live');assert.equal(h.cleared(),clears);
  h.tick(3000);assert.equal(h.states.at(-1)!.state,'degraded');assert.ok(h.cleared()>clears);
});

test('recovery never extends authorization; expiry closes memory, timers and socket',t=>{
  const h=harness(t);h.message({type:'capture.recovering',viewer_id:'v',through_sequence:0});h.tick(30000);
  assert.equal(h.socket.closed,true);assert.equal(h.states.at(-1)!.state,'unavailable');
  assert.equal(h.states.at(-1)!.reason,'lease_expired');assert.equal(h.intervals.size,0);assert.equal(h.timeouts.size,0);
});

test('explicit stop prevents pending paint; network loss cannot reconnect with cached credentials',async t=>{
  const h=harness(t);h.frame(1);h.viewer.close();await h.finish();
  assert.equal(h.painted(),0);assert.equal(h.states.at(-1)!.state,'stopped');assert.equal(h.stops(),1);
  assert.equal(h.socket.closed,true);assert.equal(h.intervals.size,0);
});

test('network failure exposes unavailable and disposes the expired viewer',t=>{
  const h=harness(t);h.socket.onclose();assert.equal(h.states.at(-1)!.state,'unavailable');
  assert.equal(h.states.at(-1)!.reason,'connection_lost');assert.equal(h.stops(),1);assert.equal(h.intervals.size,0);
});

test('wrong viewer or invalid recovery barrier fails closed',t=>{
  const h=harness(t);h.message({type:'capture.recovering',viewer_id:'wrong',through_sequence:1});
  assert.equal(h.socket.closed,true);assert.equal(h.states.at(-1)!.reason,'invalid_stream');
});

test('late decoder error cannot overwrite terminal failure or recovery state',async t=>{
  const h=harness(t);h.frame(1);h.message({type:'capture.recovering',viewer_id:'v',through_sequence:1});
  await h.reject();assert.equal(h.states.at(-1)!.state,'recovering');
  h.frame(2);h.viewer.close('privacy_mask_unavailable');await h.reject();
  assert.equal(h.states.at(-1)!.state,'unavailable');assert.equal(h.states.at(-1)!.reason,'privacy_mask_unavailable');
});

test('explicit stop sends ordered request before socket teardown; server reason shows Stopped',t=>{
  const h=harness(t);h.viewer.close();
  assert.deepEqual(h.socket.sent.at(-1),{type:'view.stop',viewer_id:'v'});
  assert.equal(h.states.at(-1)!.state,'stopped');assert.equal(h.intervals.size,0);
});
test('server intentional stop is not an unexpected disconnect',t=>{
  const h=harness(t);h.message({type:'view.stop',viewer_id:'v',reason:'teacher_stopped'});
  assert.equal(h.states.at(-1)!.state,'stopped');assert.equal(h.states.at(-1)!.reason,'teacher_stopped');
});
test('stop send failure still clears pending pixels and timers',t=>{
  const h=harness(t);h.socket.send=()=>{throw Error('network');};
  h.viewer.close();assert.equal(h.socket.closed,true);assert.equal(h.intervals.size,0);assert.equal(h.stops(),1);
});

// Observer identity must survive lease cleanup and match the actual viewer.
test('diagnostic viewer identity persists through terminal cleanup', t=>{
  const h=harness(t); h.viewer.close('connection_lost');
  assert.equal(h.states.at(-1)?.viewer_id,'v');
  assert.equal(h.states.at(-1)?.state,'unavailable');
});

test('presentation trace distinguishes decode discard, actual paint and ACK creation',async t=>{
  const h=harness(t);h.frame(1);h.frame(2);h.frame(3);await h.finish();await h.finish();
  const trace=h.states.at(-1)!.trace!;
  assert.equal(trace.counts.frame_received,3);assert.equal(trace.counts.frame_replaced,1);
  assert.equal(trace.counts.presented,2);assert.equal(trace.counts.ack_sent,2);
  assert.deepEqual(trace.records.filter(r=>r.stage==='ack_sent').map(r=>r.sequence),[1,3]);
  h.viewer.close('connection_lost');assert.equal(h.states.at(-1)!.trace!.counts.ack_sent,2);
});
