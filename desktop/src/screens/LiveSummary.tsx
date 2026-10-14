import { useC } from '../locales/connected';
import { useState } from 'react';
import { Clock3, FileText, Image, ListChecks, ShieldCheck } from 'lucide-react';
import type { BackendState, EvidenceIntent, ReviewEvent, WorkflowState } from '../../shared/contracts';
import { Badge, Button } from '../components/ui';
import { eventTimestamp, useEventLabel } from '../components/ReviewEvents';
import { command } from '../hooks/backend';
import { useReviewEvents } from '../hooks/reviewEvents';
import { clockText, localTime } from '../lib/presentation';
import { useT } from '../locales';
import { useW } from '../locales/workflow';
import { ProtectionStatus } from '../components/ProtectionStatus';
export function LiveSummary({ state, workflow, busy }: { state: BackendState; workflow: WorkflowState; busy: boolean }) {
  const c = useC(); const t = useT(); const w = useW(); const label = useEventLabel(); const summary = workflow.summary;
  const history = useReviewEvents(workflow);
  const [evidenceError, setEvidenceError] = useState<string | null>(null); const [opening, setOpening] = useState(false);
  const evidence = async (kind: EvidenceIntent['kind'], action: EvidenceIntent['action'], eventId?: string) => {
    if (!workflow.session_id || !window.proctoring) return;
    setOpening(true); setEvidenceError(null);
    try { const result = await window.proctoring.evidence({ session_id: workflow.session_id, kind, action, ...(eventId ? { event_id: eventId } : {}) }); if (!result.ok && !result.cancelled) setEvidenceError(result.error ?? w('evidenceMissing')); }
    catch { setEvidenceError(w('evidenceMissing')); } finally { setOpening(false); }
  };
  const protectionFailure = state.protection.requested && (state.protection.state === 'fault' || state.protection.reason === 'helper_identity_unavailable')
    ? <section className="panel" role="alert"><ProtectionStatus protection={state.protection} detail/></section> : null;
  if (!summary) return <>{protectionFailure}<section className="panel disconnected-panel"><h1>{w('ended')}</h1><p>{w('reportPending')}</p></section></>;
  const records = [...history.records].sort((a, b) => (eventTimestamp(a) ?? '').localeCompare(eventTimestamp(b) ?? ''));
  const candidate = workflow.registration.candidate; const score = typeof summary.score === 'number' ? summary.score : null;
  const elapsed = typeof summary.elapsed_seconds === 'number' ? summary.elapsed_seconds : workflow.session.elapsed_seconds;
  const endedAt = typeof summary.ended_at === 'string' ? summary.ended_at : null; const startedAt = typeof summary.started_at === 'string' ? summary.started_at : null;
  return <>{protectionFailure}<div className="page-title"><div><p className="eyebrow">{t('summary')}</p><h1>{w('ended')}</h1><p>{t('summaryHelp')}</p></div><Badge>{w('development')}</Badge></div><div className="summary-candidate"><strong>{candidate ? (candidate.full_name || `${candidate.first_name} ${candidate.last_name}`) : w('registrationNotRequired')}</strong><span>{candidate?.group_id}</span><small>{w('sessionId')}: {workflow.session_id}</small></div>
    <div className="summary-stats"><div><Clock3 size={20} aria-hidden="true"/><span>{t('elapsed')}</span><strong className="numeric">{clockText(elapsed)}</strong></div><div><ListChecks size={20} aria-hidden="true"/><span>{t('score')}</span><strong className="numeric">{score === null ? '—' : `${score} / ${typeof summary.total_questions === 'number' ? summary.total_questions : workflow.quiz.total} (${Math.round(score / (Number(summary.total_questions ?? workflow.quiz.total) || 1) * 100)}%)`}</strong></div><div><ShieldCheck size={20} aria-hidden="true"/><span>{t('observations')}</span><strong className="numeric">{typeof summary.event_count === 'number' ? summary.event_count : records.length}</strong></div></div>
    <div className="summary-meta"><span>{w('startedAt')}: {localTime(startedAt)}</span><span>{w('endedAt')}: {localTime(endedAt)}</span><span>{w('endReason')}: {typeof summary.end_reason === 'string' ? summary.end_reason : workflow.session.end_reason}</span></div>{workflow.quiz.mode === 'external' && <p className="quiet-note">{w('noScore')} {w('externalHelp')}</p>}
    {evidenceError && <p className="inline-error" role="alert">{evidenceError}</p>}
    {history.error && <p className="inline-error" role="status">{w('historyError')}</p>}{!history.error && history.pending && <p className="quiet-note" role="status">{w('historyLoading')}</p>}<section className="panel timeline-panel"><div className="section-heading"><h2>{t('timeline')}</h2><Badge>{t('review')}</Badge></div>{records.length ? <div className="table-wrapper"><table><thead><tr><th>{t('time')}</th><th>{t('observation')}</th><th>{w('duration')}</th><th>{t('evidence')}</th></tr></thead><tbody>{records.map(record => <tr key={record.event_id} data-event-id={record.event_id}><td className="numeric">{localTime(eventTimestamp(record))}</td><td><strong>{label(record)}</strong><small>{t('review')} · {record.event_id}</small></td><td className="numeric">{typeof record.duration_seconds === 'number' ? `${record.duration_seconds.toFixed(1)} ${w('seconds')}` : '—'}</td><td>{record.snapshot_path || record.snapshot ? <Button variant="secondary" size="small" disabled={opening} onClick={() => void evidence('snapshot', 'open', record.event_id)}><Image size={15} aria-hidden="true"/>{w('snapshot')}</Button> : <Badge>{t('noSnapshot')}</Badge>}</td></tr>)}</tbody></table></div> : <div className="empty-state"><ShieldCheck size={32} aria-hidden="true"/><h3>{t('noEvents')}</h3></div>}<p className="quiet-note">{t('readyFooter')}</p></section>
    <section className={`report-panel ${workflow.report.status === 'failed' ? 'report-error' : ''}`}><FileText size={24} aria-hidden="true"/><div><h3>{t('report')}</h3><p role="status">{workflow.report.available ? workflow.report.file_name : workflow.report.status === 'failed' ? t('reportError') : workflow.report.status === 'disabled' ? w('reportDisabled') : w('reportPending')}</p>{workflow.report.error && <p className="error-text">{workflow.report.error}</p>}</div><div className="actions wrap">{workflow.report.available ? <><Button variant="secondary" disabled={opening} onClick={() => void evidence('report', 'open')}>{w('reportOpen')}</Button><Button variant="secondary" disabled={opening} onClick={() => void evidence('report', 'save')}>{w('reportSave')}</Button></> : workflow.report.status === 'failed' ? <Button disabled={busy} onClick={() => void command('report.retry')}>{w('reportRetry')}</Button> : null}</div></section>
    {workflow.reference.ready && <Button variant="ghost" disabled={opening} onClick={() => void evidence('reference', 'open')}>{w('referenceImage')}</Button>}
    {state.admission && !state.synchronization && <p className="data-note" role="status">{c(`finish_${state.admission.finish_status ?? 'not_sent'}`)}</p>}
    <div className="data-note">{state.admission ? c('privacy') : state.config.remote_enabled ? `${w('deliveryConfigured')}: ${state.config.remote_destinations.join(', ')} · ${w('deliveryPending')}` : t('noRemote')}</div>
    <details className="panel diagnostics-panel"><summary>{t('technicalError')}</summary><pre className="technical">{JSON.stringify({ lifecycle: summary.lifecycle, security_events: summary.security_events, storage_error: summary.storage_error, snapshot_errors: summary.snapshot_errors }, null, 2)}</pre></details>
  </>;
}
