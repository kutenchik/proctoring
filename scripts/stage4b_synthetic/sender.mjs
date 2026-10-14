// Production LiveScreen with synthetic capture/native adapters. No Electron runtime.
// Private configuration and generated JPEGs travel only over parent-owned stdin.
import {createRequire} from 'node:module';
import {EventEmitter} from 'node:events';
import {createInterface} from 'node:readline';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(path.join(root,'desktop/package.json'));
let live,deadline,timer,pending,config,requestId=0,closed=false;
const emit=v=>process.stdout.write(JSON.stringify(v)+'\n');
class WC extends EventEmitter {mainFrame={};isDestroyed(){return false;}send(){}setWindowOpenHandler(){}getZoomFactor(){return 1;}}
class Window extends EventEmitter {webContents=new WC();destroyed=false;isDestroyed(){return this.destroyed;}isFocused(){return true;}isMaximized(){return false;}getContentBounds(){return {x:0,y:0,width:640,height:360};}async loadFile(){}destroy(){this.destroyed=true;this.emit('closed');}}
const display={id:1,bounds:{x:0,y:0,width:640,height:360},size:{width:640,height:360},scaleFactor:1};
const electron={BrowserWindow:Window,ipcMain:new EventEmitter(),session:{fromPartition:()=>({setPermissionRequestHandler(){},setPermissionCheckHandler(){},on(){}})},screen:{getAllDisplays:()=>[display],getDisplayMatching:()=>display}};
function stop(code){if(closed)return;closed=true;if(live){live.stopLease(code);live.close();}clearInterval(timer);pending?.reject(Error('stopped'));pending=null;emit({type:'closed',code});}
async function initialize(c) {
  if(config)throw Error('already_started');
  const u=new URL(c.origin),local=['127.0.0.1','localhost','[::1]'].includes(u.hostname);
  if(u.protocol!=='https:'||u.username||u.password||u.search||u.hash||u.pathname!=='/'||(!local&&(!process.argv.includes('--operator-approved-public')||!/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(c.origin))))throw Error('origin_rejected');
  if(!Number.isFinite(c.deadline)||c.deadline<=Date.now()||c.deadline-Date.now()>900000)throw Error('deadline_rejected');
  config=c;deadline=c.deadline;
  const {build}=require('esbuild');
  const output=await build({entryPoints:[path.join(root,'desktop/electron/live_screen.ts')],bundle:true,platform:'node',format:'cjs',write:false,external:['electron'],plugins:[{name:'synthetic-capture-only',setup(b){b.onResolve({filter:/^\.\/screen_capture$/},()=>({path:'capture',namespace:'synthetic'}));b.onLoad({filter:/.*/,namespace:'synthetic'},()=>({contents:'export class TransientMonitorCapture extends Error {} export async function captureExamMonitor(){return globalThis.__syntheticFrame();}',loader:'js'}));}}]});
  globalThis.__syntheticFrame=()=>new Promise((resolve,reject)=>{
    if(pending){reject(Error('capture_unavailable'));return;}
    const id=++requestId;pending={id,resolve,reject};emit({type:'generate',id});
  });
  const module={exports:{}};
  new Function('require','module','exports','__dirname',output.outputFiles[0].text)(name=>name==='electron'?electron:require(name),module,module.exports,path.join(root,'desktop/build-electron'));
  const messages=[];
  const bridge={status:{state:'connected'},terminated:false,async host(command,payload){
    if(command==='live.capture')emit({type:'sender_status',state:payload.state,reason:payload.reason,viewer_id:payload.viewer_id,transport:payload.transport,diagnostic:payload.diagnostic??null});
    return {ok:true,data:{messages:messages.splice(0,32)}};
  }};
  globalThis.__syntheticMessages=messages;
  live=new module.exports.LiveScreen(new Window(),bridge);
  live.update({live_teacher:{connection:'online',consent:{accepted:true,version:2,acknowledged:true}},admission:{attempt_id:c.attempt_id},workflow:{session_id:c.session_id,session:{started:true,ended:false}}});
  timer=setInterval(()=>{
    if(Date.now()>=deadline){stop('stopped');process.exitCode=0;input.close();return;}
    emit({type:'sample',viewer_id:live.lease?.viewer_id??null,trace:live.deliveryTrace.snapshot(),last_ack:live.lastAckSequence,transport:live.transport,pending_ack:live.sentTimes.size,lease_remaining_ms:Math.max(0,Math.round(live.deadline-performance.now()))});
  },1000);
  emit({type:'ready'});
}
const input=createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',line=>{void(async()=>{
  if(line.length>400000)throw Error('message_limit');const m=JSON.parse(line);
  if(m.type==='init')await initialize(m);
  else if(m.type==='frame'&&pending?.id===m.id){const p=pending;pending=null;p.resolve({jpeg:Buffer.from(m.jpeg_base64,'base64'),width:640,height:360});}
  else if(m.type==='view.start'&&live){if(globalThis.__syntheticMessages.length>=32)throw Error('queue_full');globalThis.__syntheticMessages.push({...m,server_url:config.origin});}
  else if(['view.stop','view.expired'].includes(m.type)&&live){globalThis.__syntheticMessages.push(m);}
  else if(m.type==='exit'){stop('stopped');input.close();}
  else throw Error('invalid_message');
})().catch(()=>{emit({type:'fatal',code:'fixture_protocol_failed'});stop('stopped');input.close();process.exitCode=1;});});
input.on('close',()=>{stop('stopped');process.exit();});
