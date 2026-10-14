// Stage 4B bounded student observer (maximum 1800 state polls). Numerical state only; never starts devices/exams.
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {appendFile,mkdir,writeFile,rename} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';
import os from 'node:os';

const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const testRoot=path.join(repo,'build/stage4b-student');
const require=createRequire(path.join(repo,'desktop/package.json'));
// Bundle the source validator so its shared TypeScript imports resolve in Node.
const validator=require('esbuild').buildSync({entryPoints:[path.join(repo,'shared/screen-diagnostic.ts')],bundle:true,platform:'node',format:'esm',write:false}).outputFiles[0].text;
const {validScreenDiagnostic}=await import('data:text/javascript;base64,'+Buffer.from(validator).toString('base64'));
const run=promisify(execFile);
const option=name=>{const i=process.argv.indexOf(name);return i<0?null:process.argv[i+1];};
if(process.argv.includes('--help')) {
  console.log('node scripts/observe_stage4b_student.mjs --unprotected --config <absolute TOML> [--output-name run-01]');
  console.log('Requires explicit safe TOML and isolated LOCALAPPDATA. Operator controls all devices, consent, calibration and exam. No pixels, answers, credentials or PINs are collected.');
  process.exit(0);
}
if(!process.argv.includes('--operator-approved'))throw new Error('Explicit physical operator approval is required');
if(!process.argv.includes('--unprotected'))throw new Error('Explicit --unprotected is required');
const configured=option('--config');
if(!configured||configured.startsWith('--'))throw new Error('Explicit --config is required');
const config=path.resolve(configured),name=option('--output-name')||'run-01';
if(!/^[a-zA-Z0-9_-]{1,64}$/.test(name))throw new Error('Output name must be a simple local label');
const python=option('--python')?path.resolve(option('--python')):path.join(repo,'.venv/Scripts/python.exe');
const check=await run(python,['-B','-c',"import json,sys,tomllib;d=tomllib.load(open(sys.argv[1],'rb'));print(json.dumps({'protection':d.get('protection',{}).get('enabled'),'blocking':d.get('security',{}).get('blocking_enabled'),'connected':d.get('connected',{}).get('enabled'),'http':d.get('connected',{}).get('allow_loopback_http'),'origin':d.get('connected',{}).get('server_url'),'clipboard':d.get('security',{}).get('system_checks',{}).get('clipboard_guard_enabled'),'vm':d.get('security',{}).get('system_checks',{}).get('vm_check_enabled')}))",config],{windowsHide:true,timeout:10000});
const flags=JSON.parse(check.stdout);
if(flags.protection!==false||flags.blocking!==false||flags.connected!==true||flags.http!==false||flags.clipboard!==false||flags.vm!==false||!/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(flags.origin))throw new Error('Observer requires explicit protection=false, blocking=false, connected=true');
const checked=await run(python,['-B','-c',"from pathlib import Path;from proctoring.config import load_config;import json,sys;c=load_config(Path(sys.argv[1]));print(json.dumps({'protection':c.protection.enabled,'blocking':c.blocking_enabled,'connected':c.connected.enabled,'remote':c.remote.enabled}))",config],{cwd:repo,windowsHide:true,timeout:10000});
const actual=JSON.parse(checked.stdout);
if(actual.protection!==false||actual.blocking!==false||actual.connected!==true||actual.remote!==false)throw new Error('Validated runtime configuration is not safe connected mode');
const output=path.join(testRoot,name),local=path.join(output,'student-localappdata');
await mkdir(testRoot,{recursive:true});await mkdir(output);await mkdir(local,{recursive:true}); // never overwrite a previous observer run
const env={...process.env,LOCALAPPDATA:local,PROCTORING_PYTHON:python};
for(const key of ['ELECTRON_RUN_AS_NODE','PROCTORING_DEV_URL','PYTHONPATH','PYTHONHOME','PROCTORING_PACKAGE_ROOT','PROCTORING_HOST_LAUNCH_ID','PROCTORING_BACKEND_NONCE'])delete env[key];
const {_electron:electron}=require('playwright');
const began=performance.now();
const app=await electron.launch({args:[path.join(repo,'desktop'),'--config',config],cwd:path.join(repo,'desktop'),env,timeout:60000});
const child=app.process(),rootPid=child.pid;
let samples=0;const MAX_SAMPLES=1800;
let closed=false,latest=null,readErrors=0,resourceErrors=0,resourceBusy=false,previousResourceAt=null;
const exceptions={renderer_page_errors:0,renderer_console_errors:0,main_uncaught_markers:0};
app.on('close',()=>{closed=true;});
const watched=new WeakSet();
const watch=page=>{if(watched.has(page))return;watched.add(page);page.on('pageerror',()=>exceptions.renderer_page_errors++);page.on('console',m=>{if(m.type()==='error')exceptions.renderer_console_errors++;});};
app.on('window',watch);
child.stderr?.on('data',chunk=>{if(/Uncaught Exception|UnhandledPromiseRejection|A JavaScript error occurred/.test(String(chunk)))exceptions.main_uncaught_markers++;});
const page=await app.firstWindow();watch(page);
await page.waitForFunction(()=>!!window.proctoring,null,{timeout:60000});
const startup={first_window_bridge_ms:performance.now()-began,first_authoritative_state_ms:null};
const num=x=>typeof x==='number'&&Number.isFinite(x)?x:null;
const code=x=>typeof x==='string'&&/^[a-zA-Z0-9_:-]{1,160}$/.test(x)?x:null;
const event=e=>({record_kind:code(e.record_kind),event_id:code(e.event_id),event_type:code(e.event_type),action:code(e.action),state:code(e.state),
  timestamp:typeof e.timestamp==='string'?e.timestamp:null,duration_seconds:num(e.duration_seconds),elapsed_seconds:num(e.elapsed_seconds),snapshot_available:!!e.snapshot_path});
const limitations=[
 'Observer uses public state.get/events.get only. It never changes consent, devices, calibration, answers, PIN, protection or exam lifecycle.',
 'Observer RPC refreshes presentation traffic; this is not a watchdog/renderer-loss test.',
 'No screen/webcam frames, screenshots, candidate identity, answers, PINs, tokens or message text are stored.',
 'Capture quality is observed separately from teacher quality packets: delivered FPS and capture-to-presentation-ACK round trip, never one-way latency.',
 'Resource sums double-count shared memory; observer overhead and its Node/PowerShell are outside the app tree. No per-process network throughput is available here.',
 'Error counters are diagnostic observations, not proof that no native dialog appeared; operator confirmation is required.'
];
const known=new Map(),cpuLast=new Map();let peakWorking=0,peakPrivate=0,journalSession=null,journalCursor=0;
const save=async()=>{const target=path.join(output,'operator-result.json');await writeFile(target+'.partial',JSON.stringify({schema:1,mode:'source-unprotected',
 config_path:config,isolated_localappdata:local,root_pid:rootPid,startup,latest,read_errors:readErrors,resource_errors:resourceErrors,exceptions,
 application_closed:closed,peak_working_set_sum_bytes:peakWorking,peak_private_bytes_sum:peakPrivate,journal_cursor_observed:journalCursor,limitations},null,2));await rename(target+'.partial',target);};
const resources=async()=>{
 if(resourceBusy||closed||samples>=MAX_SAMPLES)return;resourceBusy=true;
 try {
  const {stdout}=await run('powershell.exe',['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',path.join(repo,'scripts/observe_electron_resources.ps1')],{windowsHide:true,timeout:10000,maxBuffer:4*1024*1024});
  const all=JSON.parse(stdout),at=performance.now(),byPid=new Map(all.map(r=>[r.pid,r]));const root=byPid.get(rootPid);if(!root)return;
  if(known.has(rootPid)&&known.get(rootPid)!==root.created)throw new Error('Owned root identity changed');known.set(rootPid,root.created);
  let changed=true;while(changed){changed=false;for(const r of all){const parent=byPid.get(r.parent);if(parent&&known.get(parent.pid)===parent.created&&r.created>=parent.created&&known.get(r.pid)!==r.created){known.set(r.pid,r.created);changed=true;}}}
  const owned=all.filter(r=>known.get(r.pid)===r.created);let cpuDelta=0;
  for(const r of owned){const key=`${r.pid}:${r.created}`;if(cpuLast.has(key))cpuDelta+=Math.max(0,r.cpu_100ns-cpuLast.get(key));cpuLast.set(key,r.cpu_100ns);}
  const working=owned.reduce((s,r)=>s+r.working_set_bytes,0),privateBytes=owned.reduce((s,r)=>s+r.private_bytes,0);
  peakWorking=Math.max(peakWorking,working);peakPrivate=Math.max(peakPrivate,privateBytes);
  await appendFile(path.join(output,'resources.jsonl'),JSON.stringify({observer_seconds:(at-began)/1000,process_count:owned.length,
   working_set_sum_bytes:working,private_bytes_sum:privateBytes,cpu_percent_machine:previousResourceAt===null?null:100*(cpuDelta/1e7)/((at-previousResourceAt)/1000)/os.availableParallelism(),processes:owned})+'\n');previousResourceAt=at;
 }catch{resourceErrors++;}finally{resourceBusy=false;}
};
const resourceTimer=setInterval(()=>{void resources();},3000);void resources();
console.log(JSON.stringify({stage:'operator_ready',root_pid:rootPid,output,isolated_localappdata:local,note:'No devices/exam start automatically; wait for operator instructions.'}));
try {
 while(!closed){
  if(samples>=MAX_SAMPLES){await new Promise(r=>setTimeout(r,1000));continue;}
  samples++;
  try{
   const response=await page.evaluate(()=>window.proctoring.command('state.get'));
   if(response.ok&&response.result.workflow){
    const s=response.result,w=s.workflow,now=performance.now(),l=s.live_teacher,sy=s.synchronization;
    if(startup.first_authoritative_state_ms===null)startup.first_authoritative_state_ms=now-began;
    latest={at:Date.now(),observer_seconds:(now-began)/1000,session_id:code(w.session_id),attempt_id:code(s.admission?.attempt_id),step:code(w.step),snapshot_seq:w.snapshot_seq,
     protection:{requested:s.protection.requested,enabled:s.protection.enabled,state:code(s.protection.state)},
     camera:{state:code(s.camera.state),width:num(s.camera.source_width),height:num(s.camera.source_height),fps:num(s.camera.fps),frame_age_seconds:num(s.camera.frame_age_seconds)},
     audio:{running:s.audio.running,state:code(s.audio.check.state),gain:num(s.audio.check.gain),threshold:num(s.audio.check.committed_threshold),level:num(s.audio.processed_level)},
     reference_ready:w.reference.ready,calibration:{phase:code(w.calibration.phase),target:code(w.calibration.target),ready:w.calibration.ready,accepted_samples:num(w.calibration.accepted_samples)},
     monitoring:{healthy:w.monitoring.healthy,reason:code(w.monitoring.reason),fps:num(w.monitoring.fps),latency_ms:{face:num(w.monitoring.latency_ms?.face),yolo:num(w.monitoring.latency_ms?.yolo)}},
     session:{started:w.session.started,ended:w.session.ended,running:w.session.running,duration_seconds:num(w.session.duration_seconds),elapsed_seconds:num(w.session.elapsed_seconds),remaining_seconds:num(w.session.remaining_seconds),pause_reasons:w.session.pause_reasons.map(code).filter(Boolean),end_reason:code(w.session.end_reason)},
     quiz:{answered:num(w.quiz.answered),total:num(w.quiz.total)},event_cursor:w.events.cursor,events:w.events.records.map(event),
     live:l?{connection:code(l.connection),error:code(l.error),consent:{version:l.consent.version,accepted:l.consent.accepted,acknowledged:l.consent.acknowledged},
      screen_diagnostic:validScreenDiagnostic(l.screen_diagnostic)?l.screen_diagnostic:null,
      viewing:{viewer_id:code(l.viewing.viewer_id),state:code(l.viewing.state),transport:code(l.viewing.transport),reason:code(l.viewing.reason)},
      display:{count:num(l.display.count),ready:l.display.ready,calibration_ready:l.display.calibration_ready,approval_required:l.display.approval_required},message_count:l.messages.length}:null,
     synchronization:sy?{status:code(sy.status),error:code(sy.error),phase:code(sy.phase),fully_synchronized:sy.fully_synchronized,pending_attempts:num(sy.pending_attempts)}:null,
     report:{status:code(w.report.status),available:w.report.available}};
    if(s.protection.requested||s.protection.enabled)throw new Error('Unexpected protected runtime: no observer actions permitted');
    await appendFile(path.join(output,'states.jsonl'),JSON.stringify(latest)+'\n');
    if(w.session_id!==journalSession){journalSession=w.session_id;journalCursor=0;}
    if(journalSession&&journalCursor<w.events.cursor){const r=await page.evaluate(after=>window.proctoring.command('events.get',{after,limit:100}),journalCursor);if(r.ok&&r.data){for(const row of r.data.records)await appendFile(path.join(output,'event-history.jsonl'),JSON.stringify({sequence:row.sequence,...event(row.record)})+'\n');journalCursor=r.data.cursor;}}
    if(latest.live?.screen_diagnostic&&!latest.live.screen_diagnostic.requested&&latest.session.started&&!latest.session.ended) {try{await writeFile(path.join(output,'sender-first-terminal.json'),JSON.stringify(latest,null,2),{flag:'wx'});}catch(error){if(error.code!=='EEXIST')throw error;}}
    await save();
   }else readErrors++;
  }catch{if(!closed)readErrors++;}
  if(!closed)await new Promise(r=>setTimeout(r,1000));
 }
}finally{clearInterval(resourceTimer);while(resourceBusy)await new Promise(r=>setTimeout(r,50));await save();console.log(JSON.stringify({stage:'operator_closed',output,ended:latest?.session.ended??false,exceptions}));}
