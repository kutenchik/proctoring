import { useEffect, useRef, useState } from 'react';
import { Globe, RefreshCw } from 'lucide-react';
import type { ExternalStatus } from '../../shared/contracts';
import { Button } from './ui';
import { useW } from '../locales/workflow';

export async function hideExternalExam() {
  if (window.proctoring?.mode === 'live') await window.proctoring.external({ action: 'hide' });
}

/** Native content lives in Electron main. CSS stacking is never its safety boundary. */
export function ExternalExam({ active, modal }: { active: boolean; modal: boolean }) {
  const w = useW(); const slot = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<ExternalStatus | null>(null);
  useEffect(() => {
    const api = window.proctoring;
    if (!api || api.mode !== 'live') return;
    let disposed = false; let inFlight = false;
    const layout = async () => {
      if (disposed || inFlight || !slot.current) return;
      inFlight = true;
      try {
        const r = slot.current.getBoundingClientRect();
        const next = await api.external({ action: 'layout', bounds: { x: r.x, y: r.y, width: r.width, height: r.height }, visible: active && !modal, modal });
        if (!disposed) setStatus(next);
      } catch { if (!disposed) setStatus({ configured: true, state: 'failed', visible: false, message: '' }); }
      finally { inFlight = false; }
    };
    const observer = new ResizeObserver(() => void layout());
    if (slot.current) observer.observe(slot.current);
    window.addEventListener('scroll', layout, true);
    window.addEventListener('resize', layout);
    const timer = window.setInterval(() => void layout(), 350);
    void layout();
    return () => { disposed = true; observer.disconnect(); clearInterval(timer); window.removeEventListener('scroll', layout, true); window.removeEventListener('resize', layout); void api.external({ action: 'hide' }).catch(() => {}); };
  }, [active, modal]);
  return <section className="panel external-panel">
    <div className="section-heading"><Globe size={20} aria-hidden="true"/><h2>{w('externalExam')}</h2><Button className="push-right" size="small" variant="secondary" disabled={!active || modal} onClick={() => void window.proctoring?.external({ action: 'reload' }).then(setStatus)}><RefreshCw size={15} aria-hidden="true"/>{w('reload')}</Button></div>
    <p className="quiet-note external-disclosure">{w('externalHelp')}</p>
    {status?.state === 'blocked' && <p className="inline-error" role="status">{w('externalBlocked')}</p>}
    {status?.state === 'failed' && <div className="inline-error" role="status"><span>{w('externalUnavailable')}<small>{status.message}</small></span></div>}
    <div ref={slot} className="external-exam-slot" data-testid="external-exam-slot" aria-label={w('externalExam')}>
      {!active || modal ? <span>{w('pauseOther')}</span> : status?.state !== 'ready' ? <span>{w('loadingExternal')}</span> : null}
    </div>
  </section>;
}
