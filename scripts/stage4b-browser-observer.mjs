// Optional operator-installed diagnostics for a normal remote teacher browser.
// No network requests, payload interception, credentials, pixels or recordings.
import { ViewerClock } from './stage4b-viewer-clock.mjs';
import { validStreamTrace } from '../shared/stream-trace.ts';

export function start(deadline) {
  if (window.__stage4bObserver) throw Error('Observer already installed; do not restart this run');
  const remaining = deadline - Date.now();
  if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 1800000) throw Error('Use the coordinator deadline, within 30 minutes');
  const started = performance.now();
  const clock = new ViewerClock({ overallStart: started, overallMs: remaining });
  const records = []; let firstFailure = null, plannedViewer = null, planned = false, timer, cap;
  let deliveryTrace = null;
  const safe = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(value) ? value : null;
  const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  const box = document.createElement('aside');
  box.style.cssText = 'position:fixed;bottom:8px;right:8px;z-index:99999;background:#fff;color:#111;border:2px solid #555;padding:10px;font:14px sans-serif;max-width:300px';
  const label = document.createElement('div'); label.textContent = 'Numerical observer active (no frames saved)'; box.append(label);
  const button = (text, action) => { const b = document.createElement('button'); b.textContent = text; b.onclick = action; box.append(b); return b; };
  const save = () => {
    const blob = new Blob([JSON.stringify({ schema: 2, topology: 'remote-teacher; server and student colocated', deadline, first_failure: firstFailure, delivery_trace: deliveryTrace, records }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'stage4b-remote-teacher-metrics.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  button('Save numerical diagnostics', save);
  const mark = button('Mark planned teacher-network interruption', () => {
    if (planned) return;
    const last = records.at(-1); if (!last?.viewer_id) { label.textContent = 'Wait for an active viewer before marking'; return; }
    planned = true; plannedViewer = last.viewer_id; mark.disabled = true;
    label.textContent = 'Planned interruption marked. Disconnect only the remote teacher network on coordinator signal.';
  });
  const finish = reason => {
    clearInterval(timer); clearTimeout(cap);
    const panel = document.querySelector('[data-stream-observation]');
    // Normal application Stop preserves server authorization/cleanup semantics.
    const stop = [...(panel?.querySelectorAll('button') ?? [])].find(b => b.textContent.trim() === 'Stop viewing');
    if (stop && !stop.disabled) stop.click();
    label.textContent = `Observation ended: ${reason}. Save diagnostics; do not restart viewing.`;
    mark.disabled = true;
  };
  document.body.append(box);
  window.__stage4bObserver = { save }; // Only explicit numeric export is exposed.
  const sample = () => {
    try {
      const panel = document.querySelector('[data-stream-observation]');
      const v = JSON.parse(panel?.getAttribute('data-stream-observation') ?? 'null');
      const d = JSON.parse(panel?.getAttribute('data-stream-metrics') ?? 'null');
      const trace = JSON.parse(panel?.getAttribute('data-stream-trace') ?? 'null');
      if(validStreamTrace(trace)) deliveryTrace = trace;
      const now = performance.now();
      const row = { at: Date.now(), observer_ms: now - started, viewer_id: safe(v?.viewer_id), state: safe(v?.state), reason: safe(v?.reason), transport: safe(v?.transport),
        frames: number(d?.frames), firstPresentedAt: number(d?.firstPresentedAt), lastPresentedAt: number(d?.lastPresentedAt),
        ack_roundtrip_ms: number(v?.quality?.ack_roundtrip_ms), canvas_visible: panel?.querySelector('canvas')?.style.visibility === 'visible',
        expected_network: !!plannedViewer && v?.viewer_id === plannedViewer };
      row.timing = clock.sample(now, row); records.push(row);
      if (clock.firstFailure && !firstFailure) firstFailure = { ...row };
      if (row.timing.stop) finish(row.timing.stop);
      else if (records.length >= 1800) finish('sample_limit');
    } catch { finish('observer_error'); }
  };
  timer = setInterval(sample, 1000); cap = setTimeout(() => finish('overall_deadline'), remaining); sample();
  return 'Observer installed. Use English UI. No viewer or devices were started.';
}
