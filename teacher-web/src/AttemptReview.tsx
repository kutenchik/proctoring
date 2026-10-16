import { AudioEvidencePlayer } from './AudioEvidencePlayer';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, CheckCircle2, ChevronDown, Download, FileCheck2, FileClock, History, Image, RefreshCw, ShieldAlert, Trash2 } from 'lucide-react';
import { api, ApiError } from './api';
import { useI18n } from './i18n';
import { displayTime } from './time';
import { ErrorMessage, Field, Loading, PageTitle } from './ui';
import { conclusionDecisions, decisionFor, eventsInGroup, evidenceUrl, mayFinalize, reviewedPdfUrl, reviewDecisions, reviewPayload, safeDuration, type Conclusion, type EventGroup, type ManualObservation, type ReviewChange, type ReviewDecision, type ReviewDocument, type ReviewEvent } from './review-model';
import './review.css';

type Save = (path: string, body: unknown) => Promise<void>;
const attemptPath = (id: string) => `/attempts/${encodeURIComponent(id)}`;

export function DownloadButton({url, label, filename}: {url: string; label: string; filename: string}) {
  const {t} = useI18n(); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(null);
  async function download() {
    setBusy(true); setError(null);
    try {
      if (!url.startsWith('/api/v1/') || url.includes('..')) throw new Error('downloadFailed');
      const response = await fetch(url, {credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(30000)});
      if (!response.ok) throw new ApiError('downloadFailed',response.status);
      const blobUrl = URL.createObjectURL(await response.blob()); const link = document.createElement('a');
      link.href = blobUrl; link.download = filename; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl),1000);
    } catch {setError(new Error('downloadFailed'));} finally {setBusy(false);}
  }
  return <div className="report-download"><button onClick={download} disabled={busy}><Download size={16} aria-hidden="true" />{busy ? t('loading') : label}</button><ErrorMessage error={error} /></div>;
}

function ChangeHistory({items}: {items: ReviewChange[]}) {
  const {t,language} = useI18n();
  return <details className="review-history"><summary><History size={15} aria-hidden="true" />{t('history')} ({items.length})</summary>
    {!items.length ? <p className="small muted">{t('noHistory')}</p> : <ol>{items.map((item,index) => <li key={index}>
      <p><strong>{item.teacher_name || item.author_name || item.teacher_id || '—'}</strong> · {displayTime(item.updated_at || item.created_at,language)}</p>
      {(item.old_decision || item.new_decision || item.decision) && <p>{item.old_decision ? `${t(item.old_decision)} → ` : ''}{t(item.new_decision || item.decision || 'not_reviewed')}</p>}
      {item.old_comment != null && <p className="muted">{t('previousDecision')}: {item.old_comment || '—'}</p>}
      {(item.new_comment != null || item.comment != null) && <p>{item.new_comment ?? item.comment}</p>}
      {item.category && <p>{item.category}</p>}{item.description && <p>{item.description}</p>}{item.cancelled && <span className="badge">{t('cancelled')}</span>}
    </li>)}</ol>}
  </details>;
}

function DecisionEditor({events, onSave, onCancel}: {events: ReviewEvent[]; onSave: (decision: ReviewDecision, comment: string) => Promise<void>; onCancel: () => void}) {
  const {t} = useI18n(); const first = events.length === 1 ? decisionFor(events[0]) : null;
  const [decision,setDecision] = useState<ReviewDecision>(first?.decision ?? 'not_reviewed'); const [comment,setComment] = useState(first?.comment ?? ''); const [busy,setBusy] = useState(false); const [error,setError] = useState<unknown>(null); const input = useRef<HTMLSelectElement>(null);
  useEffect(() => {input.current?.focus();},[]);
  async function submit(event: FormEvent) {event.preventDefault(); setBusy(true); setError(null); try {await onSave(decision,comment);} catch(e) {setError(e);} finally {setBusy(false);}}
  return <form className="inline-review-form" onSubmit={submit}><ErrorMessage error={error} />{events.length > 1 && <p className="notice">{t('bulkWarning')} ({events.length})</p>}
    <Field label={t('reviewStatus')}><select ref={input} value={decision} onChange={e => setDecision(e.target.value as ReviewDecision)}>{reviewDecisions.map(value => <option key={value} value={value}>{t(value)}</option>)}</select></Field>
    <Field label={t('reviewComment')}><textarea value={comment} onChange={e => setComment(e.target.value)} maxLength={4000} rows={3} /></Field>
    <div className="form-actions"><button className="primary" disabled={busy}>{t(busy ? 'saving' : 'saveReview')}</button><button type="button" onClick={onCancel} disabled={busy}>{t('cancel')}</button></div>
  </form>;
}

function EventRow({event, attemptId, onSave, disabled}: {event: ReviewEvent; attemptId: string; onSave: Save; disabled: boolean}) {
  const {t,language} = useI18n(); const [editing,setEditing] = useState(false); const [openImage,setOpenImage] = useState<string|null>(null); const [imageFailed,setImageFailed] = useState(false);
  const review = decisionFor(event);
  return <article className="event-row"><div className="event-line"><div><p className="technical small">{event.event_id}</p><time>{displayTime(event.timestamp,language)}</time><p className="small muted">{t('eventDuration')}: {safeDuration(event.duration_seconds)}</p></div><span className={`badge decision-${review.decision}`}>{t(review.decision)}</span></div>
    {review.comment && <p className="event-comment">{review.comment}</p>}
    {!!review.version && <p className="small muted">{review.teacher_name || review.teacher_id} · {displayTime(review.created_at,language)} · {t('reportVersion')} {review.version}</p>}
    <div className="event-buttons"><button className="quiet" disabled={disabled} onClick={() => setEditing(value => !value)}>{t('individualReview')}</button>
      {event.files.filter(file => /snapshot|reference|identity/.test(file.kind)).map(file => <button key={file.id} onClick={() => {setImageFailed(false); setOpenImage(openImage === file.id ? null : file.id);}}><Image size={16} aria-hidden="true" />{t('inspectSnapshot')}</button>)}
      {!event.files.length && <small>{t('noSnapshot')}</small>}</div>
    <AudioEvidencePlayer attemptId={attemptId} audio={event.audio}/>
    {openImage && <figure className="snapshot-inspection"><figcaption>{t('historicalImage')}</figcaption>{imageFailed ? <p role="alert">{t('imageUnavailable')}</p> : <img src={evidenceUrl(attemptId,openImage)} alt={t('historicalImage')} onError={() => setImageFailed(true)} />}</figure>}
    {editing && <DecisionEditor events={[event]} onCancel={() => setEditing(false)} onSave={async (decision,comment) => {await onSave(`${attemptPath(attemptId)}/reviews`,reviewPayload([event],decision,comment)); setEditing(false);}} />}
    <ChangeHistory items={event.history} />
  </article>;
}

function GroupCard({group, document, onSave, disabled}: {group: EventGroup; document: ReviewDocument; onSave: Save; disabled: boolean}) {
  const {t} = useI18n(); const [editing,setEditing] = useState(false); const events = eventsInGroup(document,group);
  return <section className="panel event-group"><div className="group-heading"><div><h3>{t(`event_${group.event_type.toLowerCase()}`) === `event_${group.event_type.toLowerCase()}` ? group.event_type : t(`event_${group.event_type.toLowerCase()}`)}</h3><p className="technical small">{group.event_type}</p><p className="muted small">{events.length} {t('eventCount')}</p></div><button disabled={disabled || !events.length} onClick={() => setEditing(value => !value)}>{t('reviewGroup')}</button></div>
    {editing && <DecisionEditor events={events} onCancel={() => setEditing(false)} onSave={async (decision,comment) => {await onSave(`${attemptPath(document.attempt.id)}/reviews`,reviewPayload(events,decision,comment)); setEditing(false);}} />}
    <details open={events.length <= 3}><summary><ChevronDown size={16} aria-hidden="true" />{t('timeline')} ({events.length})</summary>{events.map(event => <EventRow key={event.event_id} event={event} attemptId={document.attempt.id} onSave={onSave} disabled={disabled} />)}</details>
  </section>;
}

function ManualEditor({observation, cancel, onSave, onClose}: {observation?: ManualObservation; cancel?: boolean; onSave: (body: Record<string,unknown>) => Promise<void>; onClose: () => void}) {
  const {t} = useI18n(); const [busy,setBusy] = useState(false); const [error,setError] = useState<unknown>(null); const [confirmed,setConfirmed] = useState(false); const categoryRef = useRef<HTMLInputElement>(null);
  useEffect(() => {categoryRef.current?.focus();},[]);
  async function submit(event: FormEvent<HTMLFormElement>) {event.preventDefault(); if(cancel && !confirmed) return; const data = new FormData(event.currentTarget); setBusy(true); setError(null); try {await onSave({category: String(data.get('category')).trim(), description: String(data.get('description')).trim(), ...(observation ? {expected_version:observation.version,cancelled:!!cancel} : {})}); onClose();} catch(e) {setError(e);} finally {setBusy(false);}}
  return <form className="inline-review-form" onSubmit={submit}><h3>{t(cancel ? 'cancelManual' : observation ? 'correctManual' : 'addManual')}</h3><ErrorMessage error={error} />
    <Field label={t('category')}><input ref={categoryRef} name="category" defaultValue={observation?.category} required maxLength={100} readOnly={cancel} /></Field>
    <Field label={t('description')}><textarea name="description" defaultValue={observation?.description} required maxLength={4000} rows={4} readOnly={cancel} /></Field>
    {cancel && <label className="check-field"><input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /><span>{t('cancelManualConfirm')}</span></label>}
    <div className="form-actions"><button className="primary" disabled={busy || (!!cancel && !confirmed)}>{t(busy ? 'saving' : 'confirm')}</button><button type="button" onClick={onClose} disabled={busy}>{t('cancel')}</button></div>
  </form>;
}

function ManualPanel({document,onSave,disabled}: {document: ReviewDocument; onSave: Save; disabled: boolean}) {
  const {t,language} = useI18n(); const [editing,setEditing] = useState<{observation?:ManualObservation;cancel?:boolean}|null>(null); const base = `${attemptPath(document.attempt.id)}/manual`;
  return <section className="panel review-section"><div className="section-title"><h2>{t('manualTitle')}</h2><button disabled={disabled} onClick={() => setEditing({})}>{t('addManual')}</button></div><p className="muted small">{t('manualHint')}</p>
    {!document.manual_observations.length && <p className="empty-note">{t('noManual')}</p>}
    {document.manual_observations.map(item => <article key={item.id} className={`manual-card ${item.cancelled ? 'manual-cancelled' : ''}`}><div className="event-line"><h3>{item.category}</h3><span className="badge">{t(item.phase)}</span></div><p>{item.description}</p><p className="small muted">{t('author')}: {item.author_name} · {t('createdAt')}: {displayTime(item.created_at,language)}</p>
      {item.cancelled ? <p className="badge">{t('cancelled')}</p> : <div className="event-buttons"><button disabled={disabled} onClick={() => setEditing({observation:item})}>{t('correctManual')}</button><button className="quiet" disabled={disabled} onClick={() => setEditing({observation:item,cancel:true})}>{t('cancelManual')}</button></div>}
      <ChangeHistory items={item.history} />
    </article>)}
    {editing && <ManualEditor key={editing.observation?.id + String(editing.cancel)} {...editing} onClose={() => setEditing(null)} onSave={body => onSave(editing.observation ? `${base}/${encodeURIComponent(editing.observation.id)}` : base,body)} />}
  </section>;
}

function ConclusionPanel({document,onSave,disabled}: {document: ReviewDocument; onSave: Save; disabled: boolean}) {
  const {t,language} = useI18n(); const [decision,setDecision] = useState(''); const [confirmed,setConfirmed] = useState(false); const [busy,setBusy] = useState(false); const [error,setError] = useState<unknown>(null);
  useEffect(() => {setConfirmed(false);},[document.unreviewed_count,document.conclusion?.version]);
  async function submit(event: FormEvent<HTMLFormElement>) {event.preventDefault(); if(!mayFinalize(document,confirmed) || !decision) return; const data = new FormData(event.currentTarget); setBusy(true); setError(null); try {await onSave(`${attemptPath(document.attempt.id)}/conclusions`,{expected_version:document.conclusion?.version ?? 0,decision,comment:String(data.get('comment')).trim(),confirm_unreviewed:confirmed}); setDecision('');} catch(e){setError(e);}finally{setBusy(false);}}
  const current = document.conclusion;
  return <section className="panel review-section"><h2>{t('conclusionTitle')}</h2><p className="muted small">{t('conclusionHint')}</p>
    {current ? <div className="current-conclusion"><strong>{t(current.decision === 'insufficient_evidence' ? 'conclusion_insufficient' : current.decision)}</strong><p>{current.comment}</p><p className="small muted">{current.teacher_name} · {displayTime(current.created_at,language)} · {t('conclusionVersion')} {current.version}</p><p className="small">{t('unreviewedCount')}: {current.unreviewed_count}</p>{current.needs_reconsideration && <p className="notice warning"><ShieldAlert size={18} aria-hidden="true" />{t('reconsideration')}</p>}</div> : <p>{t('noConclusion')}</p>}
    {!document.can_finalize && <p className="notice warning">{t('conclusionBlocked')}</p>}
    <form onSubmit={submit}><ErrorMessage error={error} /><fieldset disabled={!document.can_finalize || disabled || busy}><legend>{t('conclusionTitle')}</legend><Field label={t('chooseConclusion')}><select required value={decision} onChange={e => setDecision(e.target.value)}><option value="">{t('chooseConclusion')}</option>{conclusionDecisions.map(value => <option key={value} value={value}>{t(value === 'insufficient_evidence' ? 'conclusion_insufficient' : value)}</option>)}</select></Field><Field label={t('finalComment')}><textarea name="comment" maxLength={4000} rows={3} /></Field>
      {document.unreviewed_count > 0 && <div className="notice warning"><strong>{t('unreviewedCount')}: {document.unreviewed_count}</strong><label className="check-field"><input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /><span>{t('confirmUnreviewed')}</span></label></div>}
      <button className="primary" disabled={!decision || !mayFinalize(document,confirmed) || busy}>{t(busy ? 'saving' : 'finalizeConclusion')}</button></fieldset></form>
  </section>;
}

function ReportPanel({document,onSave}: {document: ReviewDocument; onSave: Save}) {
  const {t,language} = useI18n(); const [error,setError] = useState<unknown>(null); const [retrying,setRetrying] = useState<number|null>(null);
  const versions = [...document.conclusion_history]; if(document.conclusion && !versions.some(value => value.version === document.conclusion?.version)) versions.push(document.conclusion);
  async function retry(version: number) {setRetrying(version);setError(null);try{await onSave(`${attemptPath(document.attempt.id)}/reports/reviewed/${version}/retry`,{});}catch(e){setError(e);}finally{setRetrying(null);}}
  const original = document.sync.files?.some(file => file.kind === 'original_pdf' && file.complete);
  return <section className="panel review-section"><h2>{t('reportsTitle')}</h2><ErrorMessage error={error} />
    <div className="report-row"><strong>{t('originalPdf')}</strong>{original && !document.sync.deleted_at ? <DownloadButton url={`/api/v1${attemptPath(document.attempt.id)}/reports/original`} label={t('originalPdf')} filename="original-report.pdf" /> : <span className="muted small">{t('reportPending')}</span>}</div>
    {versions.sort((a,b) => b.version-a.version).map((item:Conclusion) => <div className="report-row" key={item.version}><div><strong>{t('reviewedPdf')} · {t('reportVersion')} {item.version}</strong><p className="small muted">{item.teacher_name} · {displayTime(item.created_at,language)}</p><p className="small">{t(item.decision === 'insufficient_evidence' ? 'conclusion_insufficient' : item.decision)}</p></div>
      {item.report_status === 'ready' && !document.sync.deleted_at ? <DownloadButton url={reviewedPdfUrl(document.attempt.id,item.version)} label={`${t('reviewedPdf')} ${item.version}`} filename={`reviewed-report-v${item.version}.pdf`} /> : <div><p className="small muted">{t('reportPending')}</p>{!document.sync.deleted_at && ['pending','failed'].includes(item.report_status) && <button disabled={retrying != null} onClick={() => retry(item.version)}>{t(retrying === item.version ? 'loading' : 'retry')}</button>}</div>}</div>)}
  </section>;
}

function ReferenceImages({document}:{document:ReviewDocument}) {
  const {t}=useI18n();const [open,setOpen]=useState<string|null>(null);const [failed,setFailed]=useState(false);
  const images=document.sync.files?.filter(file=>file.kind==='reference'&&file.complete)??[];
  if(!images.length||document.sync.deleted_at)return null;
  return <section className="panel review-section"><h2>{t('referenceImage')}</h2><p className="small muted">{t('historicalImage')}</p>{images.map(file=><button key={file.id} onClick={()=>{setFailed(false);setOpen(open===file.id?null:file.id);}}><Image size={16} aria-hidden="true" />{t('inspectReference')}</button>)}{open&&<figure className="snapshot-inspection"><figcaption>{t('historicalImage')}</figcaption>{failed?<p role="alert">{t('imageUnavailable')}</p>:<img src={evidenceUrl(document.attempt.id,open)} alt={t('referenceImage')} onError={()=>setFailed(true)}/>}</figure>}</section>;
}

function RecoveryAndRetention({document,onSave}: {document: ReviewDocument; onSave: Save}) {
  const {t,language} = useI18n(); const [busy,setBusy] = useState(false); const [error,setError] = useState<unknown>(null); const [confirmDelete,setConfirmDelete] = useState(false);
  const recovery = document.sync.recovery; const canRecover = document.sync.lifecycle === 'interrupted' && !!recovery?.interruption_id && !recovery.grant_id;
  const canDelete = document.can_finalize && !document.sync.deleted_at;
  async function submit(event: FormEvent<HTMLFormElement>, action: 'recovery'|'delete') {event.preventDefault(); const form = new FormData(event.currentTarget); setBusy(true);setError(null);try{await onSave(`${attemptPath(document.attempt.id)}/${action === 'recovery' ? 'recovery/authorize' : 'materials/delete'}`,{reason:String(form.get('reason')).trim(),...(action === 'recovery' ? {interruption_id:recovery?.interruption_id} : {confirm:confirmDelete})});setConfirmDelete(false);}catch(e){setError(e);}finally{setBusy(false);}}
  return <><section className="panel review-section"><h2>{t('recoveryTitle')}</h2><p className="muted small">{t('recoveryHint')}</p>{recovery?.grant_id && <p className="notice">{t('recoveryAuthorized')}</p>}{canRecover ? <form onSubmit={e => submit(e,'recovery')}><Field label={t('reason')}><textarea name="reason" required minLength={3} maxLength={1000} rows={2} /></Field><button disabled={busy}>{t('grantRecovery')}</button></form> : <p className="small muted">{t('recoveryUnavailable')} {t('terminalNoRecovery')}</p>}</section>
    <section className="panel review-section retention-panel"><h2>{t('deletionTitle')}</h2><p className="small muted">{t('retentionUntil')}: {displayTime(document.sync.retention_until,language)}</p><ErrorMessage error={error} />{document.sync.deleted_at ? <p className="notice">{t('materialsDeleted')} · {displayTime(document.sync.deleted_at,language)}</p> : <form onSubmit={e => submit(e,'delete')}><p className="small">{t('deleteHint')}</p>{!canDelete && <p className="notice warning">{t('deleteBlocked')}</p>}<fieldset disabled={!canDelete || busy}><legend>{t('deleteEvidence')}</legend><Field label={t('reason')}><textarea name="reason" required minLength={3} maxLength={1000} rows={2} /></Field><label className="check-field"><input type="checkbox" required checked={confirmDelete} onChange={e => setConfirmDelete(e.target.checked)} /><span>{t('deleteConfirm')}</span></label><button className="danger" disabled={!confirmDelete || busy}><Trash2 size={16} aria-hidden="true" />{t('deleteEvidence')}</button></fieldset></form>}</section></>;
}

export function AttemptReview({id}: {id:string}) {
  const {t,language} = useI18n(); const [document,setDocument] = useState<ReviewDocument|null>(null); const [error,setError] = useState<unknown>(null); const [loading,setLoading] = useState(false); const [saved,setSaved] = useState(false); const [deleted,setDeleted] = useState(false);
  async function load() {setLoading(true);setError(null);try{setDocument(await api.request<ReviewDocument>(`${attemptPath(id)}/review`));}catch(e){setError(e);throw e;}finally{setLoading(false);}}
  useEffect(() => {void load().catch(() => {});},[id]);
  const save: Save = async (path,body) => {setSaved(false);const result = await api.request<{deleted?:boolean}>(path,'POST',body);if(path.endsWith('/materials/delete') && result.deleted === true) {setDeleted(true);setDocument(null);return;}await load();setSaved(true);};
  if(deleted) return <><a className="text-link" href="#/exams"><ArrowLeft size={16} aria-hidden="true" />{t('back')}</a><PageTitle title={t('materialsDeleted')} /><p className="notice success" role="status">{t('materials_deleted')}</p></>;
  if(!document) return <><ErrorMessage error={error} />{loading && <Loading />}{error && <button onClick={() => void load().catch(() => {})}>{t('retry')}</button>}</>;
  const sync = document.sync; const receiptComplete = sync.receipt_complete === true; const timing = sync.timing;
  const behavioral = document.groups.filter(group => group.category === 'behavioral'); const technical = document.groups.filter(group => group.category === 'technical'); const disabled = loading || !!sync.deleted_at;
  return <><a className="text-link" href={`#/exam/${encodeURIComponent(document.exam.id)}`}><ArrowLeft size={16} aria-hidden="true" />{t('backExam')}</a><PageTitle title={document.attempt.full_name} description={`${document.exam.title} · ${t('attemptNumber')} ${document.attempt.sequence}`} action={<button onClick={() => void load().catch(() => {})} disabled={loading}><RefreshCw size={16} aria-hidden="true" />{t('refresh')}</button>} />
    <ErrorMessage error={error} />{saved && <p className="notice success" role="status">{t('reviewSaved')}</p>}
    <section className={`sync-banner ${receiptComplete ? 'sync-complete' : 'sync-incomplete'}`} aria-label={t('synchronization')}>{receiptComplete ? <CheckCircle2 aria-hidden="true" /> : <FileClock aria-hidden="true" />}<div><h2>{t(sync.deleted_at ? 'materialsDeleted' : receiptComplete ? 'receiptComplete' : 'receiptPending')}</h2><p>{t(receiptComplete ? 'serverRecordOnly' : 'syncPendingHelp')}</p><p className="small"><strong>{t('status')}:</strong> {t(sync.status || document.attempt.status)} · {t(sync.lifecycle || document.attempt.lifecycle || 'unknown')}</p></div></section>
    <section className="panel review-section"><div className="attempt-facts"><div><span>{t('studentId')}</span><strong>{document.attempt.student_id}</strong></div><div><span>{t('group')}</span><strong>{document.attempt.group}</strong></div><div><span>{t('recordedStart')}</span><strong>{displayTime(timing?.started_at || document.attempt.started_at,language,document.exam.timezone)}</strong></div><div><span>{t('recordedEnd')}</span><strong>{displayTime(timing?.ended_at || document.attempt.finished_at,language,document.exam.timezone)}</strong></div><div><span>{t('activeSeconds')}</span><strong>{timing?.elapsed_seconds ?? '—'}</strong></div><div><span>{t('remainingSeconds')}</span><strong>{timing?.remaining_seconds ?? '—'}</strong></div></div><p className="technical small">{document.attempt.id}</p><ResultSummary document={document} /></section>
    <section className="panel review-section"><h2>{t('manifest')}</h2><p className="small muted">{t('serverRecordOnly')}</p><ul className="material-list">{(sync.manifest?.items ?? []).map(item => {const file=sync.files?.find(file => file.id === item.id); const state=item.status==='disabled'?'disabled':item.status==='optional_absent'?'optional':item.status==='missing_error'?'productionError':file?.complete?'received':'pending';return <li key={item.id}><span className="technical">{item.relative_path || item.id}</span><span className={`badge ${file?.complete ? 'active' : ''}`}>{t(state)}</span><small>{t(item.required?'required':'optional')}{item.status==='present' ? ` · ${file?.received_bytes ?? 0} / ${item.size ?? '—'} B` : ''}</small>{item.error && <p className="material-error">{item.error}</p>}</li>;})}</ul>{sync.receipt?.verified_at && <p className="small">{t('syncedAt')}: {displayTime(sync.receipt.verified_at,language)}</p>}</section>
    <section className="review-section"><h2>{t('timeline')}</h2><p className="small muted">{t('groupingHint')}</p><p className="notice">{t('observationHint')}</p><h3 className="review-subheading">{t('behavior')}</h3>{behavioral.length ? behavioral.map(group => <GroupCard key={group.id} group={group} document={document} onSave={save} disabled={disabled} />) : <p className="empty-note">{t('noEvents')}</p>}<h3 className="review-subheading">{t('technical')}</h3><p className="small muted">{t('technicalHint')}</p>{technical.length ? technical.map(group => <GroupCard key={group.id} group={group} document={document} onSave={save} disabled={disabled} />) : <p className="empty-note">{t('noEvents')}</p>}</section>
    <ReferenceImages document={document}/><ManualPanel document={document} onSave={save} disabled={disabled} /><ConclusionPanel document={document} onSave={save} disabled={disabled} /><ReportPanel document={document} onSave={save} /><RecoveryAndRetention document={document} onSave={save} />
  </>;
}

function ResultSummary({document}: {document:ReviewDocument}) {
  const {t} = useI18n(); const result = document.sync.server_result; const client = document.sync.client_result; const score = result?.score; const total = result?.total;
  return <div className="result-summary"><h3>{t('verifiedScore')}</h3>{document.exam.exam_type === 'external' ? <p>{t('noExternalGrade')}</p> : <><p>{typeof score === 'number' && typeof total === 'number' ? `${score} / ${total}` : t('scoreUnverified')}</p><p className="small">{t('localScore')}: {typeof client?.score === 'number' && typeof client?.total === 'number' ? `${client.score} / ${client.total}` : document.attempt.score != null ? `${document.attempt.score} / ${document.attempt.total ?? '—'}` : '—'}</p>{result?.consistent === false && <p className="notice warning">{t('scoreMismatch')}</p>}<p className="small muted">{t('scoreCaveat')}</p></>}</div>;
}
