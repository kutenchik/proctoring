// Numerical DOM observations only: no pixels, cookies, tokens or text export.
export function summarize(rows) {
  const pending=rows.find(r=>r.state==='pending'), available=rows.find(r=>r.state==='available');
  return {pending_observed:!!pending,thumbnail_loaded:!!available,full_image_loaded:rows.some(r=>r.full_image_loaded),
    pending_to_thumbnail_ms:pending&&available?available.monotonic_ms-pending.monotonic_ms:null};
}
export function start(attemptId, deadline) {
  if(window.__snapshotObserver)throw Error('Observer already running');
  if(!/^[a-zA-Z0-9_-]{1,128}$/.test(attemptId)||!Number.isFinite(deadline)||deadline<=Date.now()||deadline-Date.now()>900000)throw Error('Invalid bounded observer configuration');
  window.__snapshotObserver=true;
  const rows=[];let stopped=false,timer;
  const box=document.createElement('aside');box.style.cssText='position:fixed;bottom:8px;right:8px;z-index:99999;background:white;color:black;padding:12px;border:2px solid #555';
  const label=document.createElement('p');label.textContent='Synthetic snapshot observer. Use English UI. No images saved.';
  const save=document.createElement('button');save.textContent='Save snapshot numerical diagnostics';box.append(label,save);document.body.append(box);
  function sample() {
    const link=[...document.querySelectorAll('.live-event-group a')].find(a=>a.getAttribute('href')===`#/attempt/${encodeURIComponent(attemptId)}`);
    const panel=link?.closest('li')?.querySelector('.event-snapshot');
    const thumb=panel?.querySelector('.event-snapshot-slot img'),full=panel?.querySelector('figure img');
    const loaded=img=>!!img&&img.complete&&img.naturalWidth>0;
    const state=loaded(thumb)?'available':panel?.textContent.includes('Snapshot pending')?'pending':panel?'other':'absent';
    const row={monotonic_ms:Math.round(performance.now()),at_ms:Date.now(),state,full_image_loaded:loaded(full)};
    if(rows.length<3600)rows.push(row);
    label.textContent=`Synthetic snapshot: ${state}; full image loaded: ${row.full_image_loaded}`;
  }
  function finish() {
    if(stopped)return;sample();stopped=true;clearInterval(timer);
    const result={schema:1,synthetic_only:true,attempt_id:attemptId,deadline,...summarize(rows),
      timing_basis:'remote browser sampled pending UI to decoded thumbnail; includes operator wait and publication delay; not one-way network latency',records:rows};
    const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='stage4b-live-snapshot-metrics.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);save.disabled=true;
  }
  save.onclick=finish;sample();timer=setInterval(()=>{sample();if(Date.now()>=deadline)finish();},250);
  return {save:finish};
}
