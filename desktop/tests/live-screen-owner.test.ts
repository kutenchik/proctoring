import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSync } from 'esbuild';
import { createRequire } from 'node:module';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { validScreenDiagnostic, screenCode } from '../../shared/screen-diagnostic';
const require = createRequire(import.meta.url);

async function streaming(h:ReturnType<typeof harness>) {
  await h.live.start(h.lease);const socket=h.sockets.at(-1);
  socket.onmessage({data:JSON.stringify({type:'stream.ready',viewer_id:h.lease.viewer_id,role:'student',lease_seconds:30,peer_connected:true})});
  await new Promise(r=>setImmediate(r));
  h.live.transport='relay';return socket;
}

function harness() {
  let now=0,captures=0,rects=[{x:10,y:10,width:5,height:5}],displayCount=1;
  let afterCapture:()=>void|Promise<void>=()=>{};
  let bounds={x:0,y:0,width:100,height:100};
  const timers=new Set(),listeners=new Map(),sockets:any[]=[],windows:any[]=[],hosts:any[]=[];
  let sourceIds=['1'],empty=false,sourceWidth=100;
  const image={isEmpty:()=>empty,getSize:()=>({width:sourceWidth,height:100}),toBitmap:()=>Buffer.alloc(40000),toJPEG:()=>{bitmap=Buffer.alloc(40000);return Buffer.from([255,216,255,224,0,0,255,217]);}};
  let bitmap:Buffer|undefined;
  let zoom=1,wcDestroyed=false,displayId=1,scale=1,queries=0;
  let afterQuery:(n:number)=>void=()=>{};
  class WC extends EventEmitter { mainFrame={}; sent:any[]=[]; isDestroyed(){return wcDestroyed;} send(...v:any[]){this.sent.push(v);} setWindowOpenHandler(){} async executeJavaScript(){afterQuery(++queries);return rects;} getZoomFactor(){return zoom;} }
  class Window extends EventEmitter { webContents=new WC(); destroyed=false; focused=false; constructor(){super();windows.push(this);} isDestroyed(){return this.destroyed;} isFocused(){return this.focused;} isMaximized(){return false;} destroy(){this.destroyed=true;this.emit('closed');} async loadFile(){} getContentBounds(){return bounds;} }
  class WS { static OPEN=1; readyState=1; bufferedAmount=0; sent:any[]=[]; closed=false; onopen:any;onmessage:any;onerror:any;onclose:any;
    constructor(){sockets.push(this);} send(s:string){this.sent.push(JSON.parse(s));} close(){this.closed=true;} }
  const electron={BrowserWindow:Window,ipcMain:{on:(k:string,v:any)=>listeners.set(k,v),removeListener:(k:string)=>listeners.delete(k)},
    session:{fromPartition:()=>({setPermissionRequestHandler(){},setPermissionCheckHandler(){},on(){}})},
    screen:{getAllDisplays:()=>Array.from({length:displayCount},()=>({id:displayId,size:{width:100,height:100},bounds:{x:0,y:0,width:100,height:100},scaleFactor:scale})),getDisplayMatching:()=>({id:displayId,size:{width:100,height:100},bounds:{x:0,y:0,width:100,height:100},scaleFactor:scale})},
    desktopCapturer:{async getSources(){captures++;await afterCapture();return sourceIds.map(id=>({display_id:id,thumbnail:image}));}},
    nativeImage:{createFromBitmap:(b:Buffer)=>{bitmap=b;return{toJPEG:()=>Buffer.from([255,216,255,224,0,0,255,217])};}}};
  const code=buildSync({entryPoints:[path.resolve('electron/live_screen.ts')],bundle:true,platform:'node',format:'cjs',write:false,external:['electron']}).outputFiles[0].text;
  const module={exports:{} as any};
  new Function('require','module','exports','__dirname','WebSocket','setInterval','clearInterval','performance',code)(
    (name:string)=>name==='electron'?electron:require(name),module,module.exports,path.resolve('build-electron'),WS,
    (fn:any)=>{timers.add(fn);return{unref(){},fn};},(t:any)=>timers.delete(t.fn),{now:()=>now});
  const owner=new Window(),bridge={status:{state:'connected'},terminated:false,async host(command:string,payload:any){hosts.push({command,payload});return{ok:true,data:{messages:[]}};}};
  const live=new module.exports.LiveScreen(owner,bridge);
  const state={live_teacher:{connection:'online',consent:{accepted:true,version:3,acknowledged:true}},admission:{attempt_id:'a'},workflow:{session_id:'session-'+'a'.repeat(32),session:{started:true,ended:false}}};
  live.update(state);
  const lease={viewer_id:'a'.repeat(32),attempt_id:'a',session_id:state.workflow.session_id,sender_token:'capability',expires_at:'2026-10-14T00:00:00Z',lease_seconds:30,server_url:'http://127.0.0.1:8000'};
  return{live,lease,state,hosts,sockets,windows,listeners,timers,setTime:(v:number)=>now=v,captures:()=>captures,bitmap:()=>bitmap,
    setSources:(ids:string[],isEmpty=false,width=100)=>{sourceIds=ids;empty=isEmpty;sourceWidth=width;},
    setZoom:(v:number)=>{zoom=v;},setWCDestroyed:()=>{wcDestroyed=true;},setDisplayId:(v:number)=>{displayId=v;},setScale:(v:number)=>{scale=v;},afterQuery:(fn:typeof afterQuery)=>{afterQuery=fn;},
    setRects:(v:typeof rects)=>{rects=v;},setBounds:(v:typeof bounds)=>{bounds=v;},afterCapture:(fn:()=>void|Promise<void>)=>{afterCapture=fn;},setDisplays:(count:number)=>{displayCount=count;}};
}
test('trusted capture owner starts only after authorization+transport, shares unmasked pixels and stops on terminal/dispose',async()=>{
  const h=harness();h.setTime(1000);await h.live.tick();assert.equal(h.captures(),0);
  await h.live.start(h.lease);const socket=h.sockets[0];socket.onopen();
  assert.equal(socket.sent[0].token,'capability');assert.equal(h.captures(),0);
  socket.onmessage({data:JSON.stringify({type:'stream.ready',viewer_id:'a'.repeat(32),role:'student',lease_seconds:30,peer_connected:false})});await new Promise(r=>setImmediate(r));
  h.setTime(6000);await h.live.tick();assert.equal(h.captures(),0);
  socket.onmessage({data:JSON.stringify({type:'peer.ready',viewer_id:'a'.repeat(32)})});
  h.setTime(7100);await h.live.tick(); // report tick before first capture; direct timeout -> own relay
  assert.equal(socket.sent.some((m:any)=>m.type==='quality'),false,'no unknown/zero frame dimensions before the first capture');
  assert.equal(h.captures(),1);assert.equal(socket.sent.some((m:any)=>m.type==='transport'&&m.transport==='relay'),true);
  assert.equal(socket.sent.some((m:any)=>m.type==='frame'),true);assert.equal(h.bitmap()![10*400+10*4+3],0);
  assert.equal(h.hosts.some((m:any)=>m.payload?.state==='live'),false);
  socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:1})});h.setTime(8200);await h.live.tick();
  assert.equal(socket.sent.some((m:any)=>m.type==='quality'&&m.width===100&&m.ack_roundtrip_ms!==null),true);
  assert.equal(h.hosts.some((m:any)=>m.payload?.state==='live'),true);
  h.live.update({...h.state,workflow:{...h.state.workflow,session:{started:true,ended:true}}});
  assert.equal(socket.closed,true);const count=h.captures();h.setTime(9000);await h.live.tick();assert.equal(h.captures(),count);
  h.live.close();h.live.close();assert.equal(h.timers.size,0);assert.equal(h.listeners.size,0);assert.equal(h.windows.slice(1).every(w=>w.destroyed),true);
});
test('expired/replaced viewer and backend disconnect destroy sockets and owned RTC renderer',async()=>{
  const h=harness();await h.live.start(h.lease);const first=h.sockets[0];
  await h.live.start({...h.lease,viewer_id:'second'});assert.equal(first.closed,true);
  h.setTime(30000);await h.live.tick();assert.equal(h.sockets[1].closed,true);assert.equal(h.captures(),0);
  h.live.close();assert.equal(h.timers.size,0);
});
test('moving/resizing/minimizing, zoom and DOM reflow during capture preserve full-monitor viewing',async()=>{
  const h=harness(),socket=await streaming(h),generation=h.live.generation;
  for(let i=0;i<40;i++) {
    h.afterCapture(()=>{h.setBounds(i%2?{x:-32000,y:-32000,width:0,height:0}:{x:i,y:i,width:50+i,height:80});h.setZoom(1+i/100);h.setRects([]);});
    h.setTime(1000+i*250);await h.live.tick();
    socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:h.live.sequence})});
    assert.equal(socket.closed,false);assert.equal(h.live.generation,generation);
  }
  assert.equal(socket.sent.filter((m:any)=>m.type==='frame').length,40);
  assert.ok(h.bitmap()!.every(v=>v===0),'no pixel redaction');h.live.close();
});

test('transient API failure discards attempt and retries with same lease and bounded backoff',async()=>{
  const h=harness(),socket=await streaming(h),generation=h.live.generation;
  h.afterCapture(()=>{throw Error('private error');});h.setTime(1000);await h.live.tick();
  assert.equal(h.bitmap(),undefined);assert.equal(socket.closed,false);assert.equal(h.live.recovering,true);
  assert.equal(socket.sent.some((m:any)=>m.type==='frame'),false);
  h.setTime(1100);await h.live.tick();assert.equal(h.captures(),1);
  h.afterCapture(()=>{});h.setTime(1300);await h.live.tick();
  assert.equal(h.live.recovering,true);socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:1})});
  assert.equal(h.live.recovering,false);assert.equal(h.live.generation,generation);h.live.close();
});

test('API retries preserve deadlines, reject stale ACK and stop on consent loss or display change',async()=>{
  for(const failure of ['deadline','consent','display','zoom']) {
    const h=harness(),socket=await streaming(h);h.setTime(1000);await h.live.tick();
    h.afterCapture(()=>{throw Error('capture unavailable');});h.setTime(1300);await h.live.tick();
    socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:1})});assert.equal(h.live.lastAck,0);
    h.afterCapture(()=>{});
    if(failure==='consent')h.live.update({...h.state,live_teacher:{...h.state.live_teacher,consent:{accepted:false,version:3,acknowledged:false}}});
    if(failure==='display')h.setDisplayId(2);
    if(failure==='zoom')h.setZoom(1.5);
    h.setTime(failure==='deadline'?14000:2000);await h.live.tick();
    assert.equal(socket.closed,failure!=='zoom',failure);
    if(failure!=='zoom')assert.equal(socket.sent.filter((m:any)=>m.type==='frame').length,1);
    h.live.close();
  }
});

test('old masked consent and unacknowledged new consent never authorize capture',async()=>{
  for(const consent of [{accepted:true,version:1,acknowledged:true},{accepted:true,version:2,acknowledged:true},{accepted:true,version:3,acknowledged:false}]) {
    const h=harness();h.live.update({...h.state,live_teacher:{...h.state.live_teacher,consent}});await h.live.start(h.lease);
    h.setTime(1000);await h.live.tick();assert.equal(h.captures(),0);assert.equal(h.sockets.length,0);h.live.close();
  }
});

test('malformed stream messages close only the owned viewer without an uncaught main-process error',async()=>{
  for(const value of [null,[],{type:'stream.ready',viewer_id:'a'.repeat(32),role:'student',peer_connected:true,lease_seconds:'30'},{type:'renewed',viewer_id:'a'.repeat(32),lease_seconds:300}]) {
    const h=harness();await h.live.start(h.lease);const socket=h.sockets[0];
    assert.doesNotThrow(()=>socket.onmessage({data:JSON.stringify(value)}));
    assert.equal(socket.closed,true);assert.equal(h.captures(),0);h.live.close();
  }
});

test('first capture failure survives generic cleanup; secondary errors and private exceptions stay separate',async()=>{
  const h=harness(),socket=await streaming(h);
  h.setSources([]);socket.close=()=>{throw Error('secret https://private.invalid/?token=abc');};
  h.setTime(1000);await h.live.tick();
  const d=h.live.diagnostic;
  assert.equal(d.code,'monitor_capture_unavailable');assert.equal(d.transport,'relay');
  assert.equal(d.capture_state,'in_flight');assert.equal(d.requested,false);
  assert.deepEqual(d.secondary,['socket_cleanup_failed']);assert.ok(validScreenDiagnostic(d));
  h.live.stopLease('disconnected');h.live.close();assert.equal(h.live.diagnostic,d);
  assert.equal(JSON.stringify(d).includes('secret'),false);
  assert.equal(screenCode('https://private.invalid/?token=abc'),'unknown_failure');
  assert.equal(h.hosts.filter((m:any)=>m.payload?.diagnostic).length,1);
});

test('display/owner guards reject before encoding and preserve exact first operands',async()=>{
  for(const operand of ['window','webcontents','count','display','scale']) {
    const h=harness(),socket=await streaming(h);
    h.afterCapture(()=>{
      if(operand==='window')h.windows[0].destroy();if(operand==='webcontents')h.setWCDestroyed();
      if(operand==='count')h.setDisplays(2);if(operand==='display')h.setDisplayId(2);if(operand==='scale')h.setScale(1.25);
    });h.setTime(1000);await h.live.tick();
    const d=h.live.diagnostic;
    assert.ok(validScreenDiagnostic(d));assert.equal(socket.sent.some((m:any)=>m.type==='frame'),false);
    assert.equal(h.bitmap(),undefined);assert.equal(socket.closed,true);
    // Authorization is checked first when the owner disappears.
    if(!['window','webcontents'].includes(operand)) {
      assert.equal(d.geometry!.stage,'after_sources');
      assert.ok(d.geometry!.failed.includes(({count:'display_count',display:'display_id',scale:'display_scale'} as any)[operand]));
    }
    h.live.stopLease('disconnected');h.live.close();assert.equal(h.live.diagnostic,d);
  }
});

test('focus/blur and click/scroll layout updates preserve viewer, bounded events detach at close',async()=>{
  const h=harness(),socket=await streaming(h),owner=h.windows[0],generation=h.live.generation;
  for(let i=0;i<40;i++) {
    h.afterCapture(()=>{owner.focused=!owner.focused;owner.emit(owner.focused?'focus':'blur');});
    h.setRects([{x:10,y:10+i%20,width:5,height:5}]);
    h.setTime(1000+i*250);await h.live.tick();
    socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:h.live.sequence})});
    assert.equal(socket.closed,false);assert.equal(h.live.generation,generation);
  }
  h.afterCapture(()=>h.setScale(1.1));h.setTime(11500);await h.live.tick();
  const d=h.live.diagnostic;assert.equal(d.geometry.events.length,16);assert.ok(validScreenDiagnostic(d));
  const saved=JSON.stringify(d);owner.emit('resize');assert.equal(JSON.stringify(d),saved);
  h.live.close();assert.equal(owner.eventNames().length,0);assert.equal(owner.webContents.eventNames().length,0);
  assert.equal(h.listeners.size,0);assert.equal(h.timers.size,0);
});

test('intentional viewer stop during pending capture discards completion and removes observers',async()=>{
  const h=harness(),socket=await streaming(h);let release!:()=>void;
  h.afterCapture(()=>new Promise<void>(r=>release=r));h.setTime(1000);
  const pending=h.live.tick();await new Promise(r=>setImmediate(r));h.live.stopLease('teacher_stopped');
  release();await pending;
  assert.equal(socket.sent.some((m:any)=>m.type==='frame'),false);assert.equal(h.live.diagnostic.code,'teacher_stopped');
  assert.equal(h.live.diagnostic.geometry,undefined);h.live.close();assert.equal(h.windows[0].eventNames().length,0);
});

test('source selection failures retain only matching count and numeric thumbnail geometry',async()=>{
  for(const failure of ['missing','duplicate','empty','size','aspect','oversize']) {
    const h=harness(),socket=await streaming(h);
    h.setSources(failure==='missing'?['private-source-name']:failure==='duplicate'?['1','1']:['1'],failure==='empty',failure==='size'?0:failure==='aspect'?50:failure==='oversize'?2000:100);
    h.setTime(1000);await h.live.tick();const d=h.live.diagnostic;
    assert.equal(d.code,'monitor_capture_unavailable');assert.equal(d.geometry!.stage,'source_selection');assert.ok(validScreenDiagnostic(d));
    assert.deepEqual(d.geometry!.failed,[failure==='duplicate'?'source_ambiguous':['aspect','oversize'].includes(failure)?'source_size':`source_${failure}`]);
    assert.equal(socket.sent.some((m:any)=>m.type==='frame'),false);assert.equal(h.bitmap(),undefined);
    assert.equal(JSON.stringify(d).includes('private-source-name'),false);h.live.close();
  }
});

test('geometry validator rejects private text, unbounded events and nonfinite numeric evidence',async()=>{
  const h=harness();await streaming(h);h.afterCapture(()=>h.setScale(1.1));h.setTime(1000);await h.live.tick();
  const d=h.live.diagnostic,g=d.geometry;
  const event={event:'focus',at:1,content:[0,0,1,1],zoom:1,focused:true};
  for(const patch of [{stage:'private-url'},{events:Array(17).fill(event)},{events:[{...event,answer:'secret'}]},
    {failed:['zoom','zoom']},{before:{...g.before,zoom:NaN}},{before:{...g.before,content:['secret',0,1,1]}}])
    assert.equal(validScreenDiagnostic({...d,geometry:{...g,...patch}}),false);
  h.live.close();
});

test('quiz selections, changes, navigation, rapid revisions and progress keep the same lease and deliver frames',async()=>{
  const h=harness(),socket=await streaming(h);const generation=h.live.generation;
  for(let i=0;i<60;i++) {
    h.live.update({...h.state,workflow:{...h.state.workflow,quiz:{current_index:i%2,answers:{0:i%3},answered:1,total:2,revision:i},
      session:{...h.state.workflow.session,elapsed_seconds:i,remaining_seconds:600-i}}});
    // DOM changes do not participate in monitor capture coordinates.
    h.setRects([{x:10+i%20,y:10,width:5,height:5}]);h.setTime(1000+i*250);await h.live.tick();
    socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:h.live.sequence})});
    assert.equal(socket.closed,false);assert.equal(h.live.generation,generation);
  }
  assert.equal(socket.sent.filter((m:any)=>m.type==='frame').length,60);assert.equal(h.live.diagnostic,undefined);
  h.live.close();assert.equal(h.live.diagnostic.requested,true);
});

test('delayed capture from old generation cannot send or terminate the replacement viewer',async()=>{
  for(const rejects of [false,true]) {
    const h=harness(),socket=await streaming(h);let finish!:()=>void;
    h.afterCapture(()=>new Promise<void>((resolve,reject)=>{finish=()=>rejects?reject(Error('private capture error')):resolve();}));
    h.setTime(1000);const capture=h.live.tick();await new Promise(r=>setImmediate(r));
    await h.live.start({...h.lease,viewer_id:'b'.repeat(32)});const next=h.sockets.at(-1);finish();await capture;
    assert.equal(socket.closed,true);assert.equal(next.closed,false);assert.equal(h.live.lease.viewer_id,'b'.repeat(32));
    assert.equal(h.live.diagnostic.code,'viewer_changed');assert.equal(socket.sent.some((m:any)=>m.type==='frame'),false);h.live.close();
  }
});

test('websocket close details are bounded and redacted, never copied as free text',async()=>{
  const h=harness(),socket=await streaming(h);
  socket.onclose({code:1006,reason:'https://private.invalid/answer?token=secret'});
  assert.equal(h.live.diagnostic.ws_close_code,1006);assert.equal(h.live.diagnostic.ws_close_reason,'redacted');
  assert.equal(h.live.diagnostic.code,'stream_disconnected');assert.ok(validScreenDiagnostic(h.live.diagnostic));h.live.close();
});

test('direct failure selects existing relay without changing lease and preserves fallback cause if delivery later fails',async()=>{
  const h=harness();await streaming(h);h.live.transport='direct';const rtc=h.windows.at(-1);
  h.listeners.get('screen:transport-out')({sender:rtc.webContents,senderFrame:rtc.webContents.mainFrame},{type:'direct.failed',reason:'rtc_channel_closed'});
  assert.equal(h.live.transport,'relay');h.setTime(1000);await h.live.tick();
  assert.equal(h.sockets[0].sent.some((m:any)=>m.type==='frame'),true);
  h.setTime(14000);await h.live.tick();assert.equal(h.live.diagnostic.code,'frame_delivery_unavailable');
  assert.equal(h.live.diagnostic.fallback,'rtc_channel_closed');h.live.close();
});

test('network loss stops capture; a new authenticated ready lease is required for reconnection',async()=>{
  const h=harness(),socket=await streaming(h);h.setTime(1000);await h.live.tick();
  socket.onclose({code:1006,reason:''});h.setTime(2000);await h.live.tick();assert.equal(h.captures(),1);
  await h.live.start({...h.lease,viewer_id:'b'.repeat(32),sender_token:'fresh-capability'});
  const next=h.sockets.at(-1);next.onopen();assert.equal(next.sent[0].token,'fresh-capability');
  h.setTime(3000);await h.live.tick();assert.equal(h.captures(),1);
  next.onmessage({data:JSON.stringify({type:'stream.ready',viewer_id:'b'.repeat(32),role:'student',lease_seconds:30,peer_connected:true})});
  h.live.transport='relay';h.setTime(4000);await h.live.tick();assert.equal(h.captures(),2);
  h.live.update({...h.state,live_teacher:{...h.state.live_teacher,consent:{accepted:false}}});
  h.setTime(5000);await h.live.tick();assert.equal(h.captures(),2);assert.equal(next.closed,true);h.live.close();
});

test('ordered intentional stop is preserved before generic socket cleanup',async()=>{
  const h=harness(),socket=await streaming(h);const close=socket.onclose;
  socket.onmessage({data:JSON.stringify({type:'view.stop',viewer_id:h.lease.viewer_id,reason:'teacher_stopped'})});
  close({code:1000,reason:''});
  assert.equal(h.live.diagnostic.code,'teacher_stopped');assert.equal(h.live.diagnostic.requested,true);h.live.close();
});

test('delayed ACK stays recognizable throughout the delivery deadline; duplicate and missing ACKs cannot extend it',async()=>{
  const h=harness(),socket=await streaming(h);
  for(let i=0;i<40;i++){h.setTime(1000+i*200);await h.live.tick();}
  h.setTime(9000);socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:1})});
  assert.equal(h.live.lastAckSequence,1);assert.equal(h.live.roundtrip,8000);
  h.setTime(10000);socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:1})});
  assert.equal(h.live.lastAck,9000);
  h.setTime(22000);await h.live.tick();assert.equal(socket.closed,true);
  assert.equal(h.live.diagnostic.code,'frame_delivery_unavailable');
  assert.equal(h.live.diagnostic.delivery_trace.counts.ack_accepted,1);
  assert.equal(h.live.diagnostic.delivery_trace.counts.ack_rejected,1);
  assert.ok(h.live.diagnostic.delivery_trace.records.length<=128);h.live.close();
});

test('out-of-order ACK cannot move the accepted sequence or extend the delivery clock',async()=>{
  const h=harness(),socket=await streaming(h);
  for(let i=0;i<4;i++){h.setTime(1000+i*200);await h.live.tick();}
  h.setTime(3000);socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:3})});
  assert.equal(h.live.lastAckSequence,3);assert.equal(h.live.lastAck,3000);
  h.setTime(4000);socket.onmessage({data:JSON.stringify({type:'frame_ack',sequence:2})});
  assert.equal(h.live.lastAckSequence,3);assert.equal(h.live.lastAck,3000);
  assert.equal(h.live.deliveryTrace.snapshot().counts.ack_rejected,1);h.live.close();
});
