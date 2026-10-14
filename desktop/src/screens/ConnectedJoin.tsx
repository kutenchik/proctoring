import { useState } from 'react';
import { Globe, ArrowRight, Check } from 'lucide-react';
import type { AdmissionState } from '../../shared/contracts';
import { Button, Input, Badge } from '../components/ui';
import { command } from '../hooks/backend';
import { clockText } from '../lib/presentation';
import { useC } from '../locales/connected';

export function ConnectedJoin({ admission, busy }: { admission: AdmissionState; busy: boolean }) {
  const c = useC(); const [server, setServer] = useState(admission.server_url);
  const [identity, setIdentity] = useState({ exam_code: '', full_name: '', group: '', student_id: '' });
  const pending = busy || !!admission.busy;
  let matchesVerified = false;
  try { const url = new URL(server.trim()); matchesVerified = url.origin === admission.verified_server && url.pathname === '/' && !url.search && !url.hash && !url.username && !url.password; } catch { /* Verify shows the controlled URL error. */ }
  return <section className="panel connected-join"><div className="section-heading"><div className="icon-tile"><Globe size={22} aria-hidden="true"/></div><div><h1>{c('title')}</h1><p>{c('help')}</p></div></div>
    <p className="data-note">{c('privacy')}</p>
    <form onSubmit={e => { e.preventDefault(); void command('connected.verify', {server_url: server.trim()}); }}><div className="field"><label htmlFor="teacher-server">{c('server')}</label><Input id="teacher-server" type="url" required maxLength={2048} value={server} disabled={pending || admission.admitted} onChange={e => setServer(e.target.value)} placeholder="https://exam.example.edu"/></div><div className="actions"><Button variant="secondary" disabled={pending || admission.admitted || !server.trim()}>{c('verify')}</Button>{admission.verified_server && <Badge tone="success"><Check size={14} aria-hidden="true"/>{c('verified')}</Badge>}</div></form>
    <form onSubmit={e => { e.preventDefault(); void command('connected.admit', identity); }}><div className="registration-fields">{([['exam_code','code',64], ['full_name','name',200], ['group','group',128], ['student_id','student',128]] as const).map(([key,label,max]) => <div className="field" key={key}><label htmlFor={`join-${key}`}>{c(label)}</label><Input id={`join-${key}`} required value={identity[key]} maxLength={max} disabled={pending || admission.admitted} autoComplete={key === 'full_name' ? 'name' : 'off'} onChange={e => setIdentity({...identity,[key]:e.target.value})}/></div>)}</div><Button disabled={pending || admission.admitted || !matchesVerified || Object.values(identity).some(v => !v.trim())}>{c('join')}<ArrowRight size={18} aria-hidden="true"/></Button></form>
    {pending && <p role="status">{c('waiting')}</p>}{admission.error && <p className="notice notice-error" role="alert">{c(admission.error)} <small>({admission.error})</small></p>}
  </section>;
}
export function ConnectedPreparation({ admission, busy }: { admission: AdmissionState; busy: boolean }) {
  const c = useC();
  return <section className="notice"><div><strong>{admission.exam_title}</strong><p>{admission.identity?.full_name} · {admission.identity?.group} · {admission.identity?.student_id}</p><p>{c('preparation')}: <span className="numeric">{clockText(admission.preparation_remaining_seconds)}</span></p>{admission.preparation_remaining_seconds <= 0 && <p role="status">{c('expired')}</p>}{admission.error && <p role="alert">{c(admission.error)} ({admission.error})</p>}<Button variant="secondary" size="small" disabled={busy || !!admission.busy} onClick={() => void command('connected.refresh')}>{admission.busy ? c('waiting') : c('refresh')}</Button></div></section>;
}
