// Same-origin, authenticated numerical export. No pixels, frame interception or credentials.
import {validStreamTrace} from '../../shared/stream-trace.ts';
export function validServerTrace(v) {
  const stages=['received','accepted','rejected','rate_dropped','budget_dropped','replaced','send_started','send_completed','send_timeout','ack_received','ack_forwarded','ack_rejected','closed'];
  const number=n=>Number.isSafeInteger(n)&&n>=0;
  return !!v&&Object.keys(v).sort().join(',')==='counts,records'&&v.counts&&typeof v.counts==='object'&&!Array.isArray(v.counts)&&
    Object.entries(v.counts).every(([k,n])=>stages.includes(k)&&number(n))&&Array.isArray(v.records)&&v.records.length<=128&&
    v.records.every(r=>r&&Object.keys(r).sort().join(',')==='at_ms,sequence,stage,value'&&stages.includes(r.stage)&&Number.isSafeInteger(r.sequence)&&r.sequence>=-1&&number(r.at_ms)&&number(r.value));
}
export function start(deadline) {
  if(window.__stage4bSyntheticObserver)throw Error('Already installed');
  if(!Number.isFinite(deadline)||deadline<=Date.now()||deadline-Date.now()>900000)throw Error('Use the approved deadline');
  const rows=[];let firstFailure=null,viewerId=null,trace=null,server=null,timer,closed=false,saving=false,first=null,lastFrames=0,maxGap=0,lastPresented=null,firstPresented=null;
  const safe=v=>typeof v==='string'&&/^[a-zA-Z0-9_-]{1,128}$/.test(v)?v:null;
  const num=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0?v:null;
  const box=document.createElement('aside');box.style.cssText='position:fixed;bottom:8px;right:8px;z-index:99999;background:white;color:black;padding:12px;border:2px solid #555';
  const label=document.createElement('div');label.textContent='Synthetic numerical observer active; no frames saved';box.append(label);
  const stop=()=>{const panel=document.querySelector('[data-stream-observation]');const b=[...(panel?.querySelectorAll('button')??[])].find(b=>b.textContent.trim()==='Stop viewing');if(b&&!b.disabled)b.click();};
  async function save() {
    if(saving)return;saving=true;
    try {
      let exportFailed=false;
      try { if(viewerId){
        const response=await fetch('/api/v1/live/view/'+viewerId+'/diagnostics',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(5000)});
        if(!response.ok)throw Error('diagnostic_export_failed');
        const raw=await response.text();if(raw.length>65536)throw Error('diagnostic_limit');
        const value=JSON.parse(raw);if(value.viewer_id!==viewerId||!validServerTrace(value.trace))throw Error('invalid_diagnostics');
        server={viewer_id:viewerId,trace:value.trace};
      }} catch {exportFailed=true;firstFailure??={at:Date.now(),code:'diagnostic_export_failed'};stop();}
      const elapsed=firstPresented===null||lastPresented===null?0:lastPresented-firstPresented;
      const value={schema:1,synthetic_only:true,network:'operator must confirm separate network',deadline,viewer_id:viewerId,first_failure:firstFailure,
        duration_ms:elapsed,frames:lastFrames,delivered_fps:elapsed>0?lastFrames*1000/elapsed:null,max_presentation_gap_ms:maxGap,
        teacher_trace:trace,server,records:rows};
      const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='stage4b-synthetic-metrics.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      label.textContent=exportFailed?'Server export FAILED; teacher evidence saved. Stop the run; preserve the browser.':'Saved teacher AND owned-server numeric diagnostics. Keep the file before shutdown.';
    } catch {firstFailure??={at:Date.now(),code:'diagnostic_export_failed'};stop();label.textContent='Export FAILED: preserve this browser and stop the run; do not restart.';}
    finally {saving=false;}
  }
  const button=document.createElement('button');button.textContent='Stop and save numerical diagnostics';button.onclick=()=>{stop();setTimeout(()=>void save(),500);};box.append(button);document.body.append(box);
  const sample=()=>{
    if(closed)return;
    try {
      const panel=document.querySelector('[data-stream-observation]');
      const v=JSON.parse(panel?.getAttribute('data-stream-observation')??'null');
      const d=JSON.parse(panel?.getAttribute('data-stream-metrics')??'null');
      const t=JSON.parse(panel?.getAttribute('data-stream-trace')??'null');if(validStreamTrace(t))trace=t;
      const id=safe(v?.viewer_id);if(id&&viewerId&&id!==viewerId)throw Error('one_viewer_only');if(id)viewerId=id;
      const now=Date.now();const row={at:now,viewer_id:id,state:safe(v?.state),reason:safe(v?.reason),transport:safe(v?.transport),frames:num(d?.frames),
        first_presented_ms:num(d?.firstPresentedAt),last_presented_ms:num(d?.lastPresentedAt),ack_roundtrip_ms:num(v?.quality?.ack_roundtrip_ms),
        canvas_visible:panel?.querySelector('canvas')?.style.visibility==='visible'};
      if(row.frames>0&&first===null){first=now-(performance.now()-row.first_presented_ms);firstPresented=row.first_presented_ms;}
      if(row.frames!==null)lastFrames=row.frames;
      if(row.last_presented_ms!==null){if(lastPresented!==null&&row.last_presented_ms>lastPresented)maxGap=Math.max(maxGap,row.last_presented_ms-lastPresented);lastPresented=row.last_presented_ms;}
      rows.push(row);
      if(row.state==='unavailable')firstFailure??={...row};
      if(first!==null&&!firstFailure)label.textContent=`${Math.floor((now-first)/1000)}s / 120s; ${lastFrames} displayed frames. Check numbered frames keep changing.`;
      if(firstFailure||now>=deadline||rows.length>=900||row.state==='stopped'&&viewerId){closed=true;clearInterval(timer);stop();void save();}
    } catch {firstFailure??={at:Date.now(),code:'observer_failed'};closed=true;clearInterval(timer);stop();void save();}
  };
  timer=setInterval(sample,1000);window.__stage4bSyntheticObserver={save};sample();
  return 'Synthetic observer ready. Start exactly one viewer on coordinator signal.';
}
