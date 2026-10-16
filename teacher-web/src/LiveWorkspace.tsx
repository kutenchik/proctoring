import { AudioEvidencePlayer } from './AudioEvidencePlayer';
import {AttemptPolicy} from './Configuration';
import { EventSnapshot } from './EventSnapshot';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, Monitor, Maximize2, Square, Radio, Send, RefreshCw } from 'lucide-react';
import { api, type Exam } from './api';
import { useI18n } from './i18n';
import { ErrorMessage, Field, PageTitle } from './ui';
import { displayTime } from './time';
function eventLabel(code:string,t:(key:string)=>string){const key=`event_${code.toLowerCase()}`;return t(key)===key?code:t(key);}
import { commandAllowed, mayExtendPreparation, mayAuthorizeRestart, timerText, type CommandType, type LiveCommand, type LiveStudent, type ViewerLease } from './live-model';
import { LiveViewer, type ViewState } from './live-viewer';
import { useLive } from './use-live';
import { screenCode } from '../../shared/screen-diagnostic';
import './live.css';

const commandLabels:Record<CommandType,string>={monitoring_policy:'monitoringPolicy',warning:'liveWarning',pause:'livePause',resume:'liveResume',end:'liveEnd',add_time:'liveAddTime',monitoring_recovery:'liveMonitoringRecovery',display_recovery:'liveDisplayRecovery'};
const resultLabels:Record<LiveCommand['status'],string>={sent:'liveSent',delivered:'liveDelivered',applied:'liveApplied',rejected:'liveRejected',not_delivered:'liveNotDelivered',execution_unconfirmed:'liveUnconfirmed'};
const stateLabels={preparation:'livePreparation',running:'liveRunning',paused:'livePaused',ended:'liveEnded'};
const pauseLabels:Record<string,string>={teacher:'liveTeacherPause',teacher_pause:'liveTeacherPause',monitoring:'liveMonitoringPause',monitoring_unavailable:'liveMonitoringPause',recovery_pin:'liveRecoveryPause',monitoring_recovery:'liveRecoveryPause',display:'liveDisplayPause',display_configuration:'liveDisplayPause',proctor:'liveProctorPause'};

function RecordedControls({student}:{student:LiveStudent}) {
  const {t,language}=useI18n();const [action,setAction]=useState<'extend'|'recover'|null>(null),[busy,setBusy]=useState(false),[saved,setSaved]=useState(false),[error,setError]=useState<unknown>(null);
  const [deadline,setDeadline]=useState(student.preparation_deadline),[granted,setGranted]=useState(false);
  useEffect(()=>{setDeadline(student.preparation_deadline);},[student.preparation_deadline]);
  const extend=mayExtendPreparation(student),recover=mayAuthorizeRestart(student)&&!granted;
  if(!deadline&&!student.restart_recovery?.interruption_id)return null;
  async function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();if(busy||!action||(action==='extend'?!extend:!recover))return;
    const reason=String(new FormData(e.currentTarget).get('reason')).trim();setBusy(true);setError(null);
    try{
      const result=await api.request<{preparation_deadline?:string}>(`/attempts/${encodeURIComponent(student.attempt_id)}/${action==='extend'?'extend':'recovery/authorize'}`,'POST',{reason,...(action==='recover'?{interruption_id:student.restart_recovery?.interruption_id}:{})});
      if(action==='extend'&&result.preparation_deadline)setDeadline(result.preparation_deadline);if(action==='recover')setGranted(true);setAction(null);setSaved(true);
    }catch(err){setError(err);}finally{setBusy(false);}
  }
  return <section className="panel live-recorded"><h2>{t('liveRecordedControls')}</h2><p className="small muted">{t('liveRecordedHint')}</p>{deadline&&<p>{t('prepDeadline')}: {displayTime(deadline,language)}</p>}{student.restart_recovery?.interruption_id&&<p className="notice">{t(granted||student.restart_recovery.grant_id?'liveRestartGranted':'liveRestartPending')}</p>}
    <ErrorMessage error={error}/>{saved&&<p role="status" className="notice success">{t('liveRecordedSaved')}</p>}
    <div className="form-actions">{extend&&<button onClick={()=>{setAction('extend');setSaved(false);}}>{t('extend')}</button>}{recover&&<button onClick={()=>{setAction('recover');setSaved(false);}}>{t('liveAuthorizeRestart')}</button>}</div>
    {action&&<form onSubmit={submit}><Field label={t('reason')}><textarea name="reason" required maxLength={1000} rows={2}/></Field><div className="form-actions"><button className="primary" disabled={busy}>{t('confirm')}</button><button type="button" onClick={()=>setAction(null)}>{t('cancel')}</button></div></form>}
  </section>;
}

function Actions({student,connected,remember,onError}:{student:LiveStudent;connected:boolean;remember:(items:LiveCommand[])=>void;onError:(e:unknown)=>void}) {
  const {t}=useI18n();const [type,setType]=useState<CommandType>('warning'),[busy,setBusy]=useState(false),[text,setText]=useState(''),[seconds,setSeconds]=useState(60),[confirmed,setConfirmed]=useState(false);
  const request=useRef<{id:string;body:string}|null>(null);
  async function submit(e:FormEvent){
    e.preventDefault();if(busy||!commandAllowed(student,type,connected))return;
    const payload:Record<string,unknown>=type==='warning'?{text:text.trim()}:{reason:text.trim()};
    if(type==='end')payload.confirm=confirmed;if(type==='add_time')payload.seconds=seconds;
    if(type==='monitoring_recovery')payload.outage_id=student.status?.monitoring_outage?.outage_id;
    if(type==='display_recovery')payload.incident_id=student.status?.display.incident_id;
    const body=JSON.stringify({type,payload});if(request.current?.body!==body)request.current={id:crypto.randomUUID().replaceAll('-',''),body};
    setBusy(true);onError(null);
    try {const response=await api.request<{command:LiveCommand}>(`/attempts/${encodeURIComponent(student.attempt_id)}/commands`,'POST',{request_id:request.current.id,type,payload});remember([response.command]);request.current=null;setText('');setConfirmed(false);}
    catch(error){onError(error);}finally{setBusy(false);}
  }
  return <section className="panel live-actions"><h2>{t('liveCommands')}</h2><p className="small muted">{t('liveCommandHint')}</p><form onSubmit={submit}>
    <Field label={t('liveCommands')}><select value={type} onChange={e=>{setType(e.target.value as CommandType);setConfirmed(false);}}>{(Object.keys(commandLabels) as CommandType[]).filter(v=>v!=='monitoring_policy').map(value=><option key={value} value={value} disabled={!commandAllowed(student,value,connected)}>{t(commandLabels[value])}</option>)}</select></Field>
    <Field label={t(type==='warning'?'liveMessage':'reason')}><textarea value={text} onChange={e=>setText(e.target.value)} required maxLength={type==='warning'?400:1000} rows={2}/></Field>
    {type==='add_time'&&<Field label={t('liveSeconds')}><input type="number" min={1} max={3600} step={1} value={seconds} onChange={e=>setSeconds(Number(e.target.value))} required/></Field>}
    {type==='end'&&<label className="check-field"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)} required/>{t('liveConfirmEnd')}</label>}
    <button className={type==='end'?'danger':'primary'} disabled={busy||!text.trim()||!commandAllowed(student,type,connected)||(type==='end'&&!confirmed)}><Send size={16} aria-hidden="true"/>{t(busy?'saving':'liveSend')}</button>
  </form></section>;
}

export function LiveWorkspace({id,csrf}:{id:string;csrf:string}) {
  const {t,language}=useI18n();const [exam,setExam]=useState<Exam|null>(null),[selected,setSelected]=useState(''),[error,setError]=useState<unknown>(null);
  const [view,setView]=useState<ViewState|null>(null),[starting,setStarting]=useState(false),[admission,setAdmission]=useState(false),[closedAdmission,setClosedAdmission]=useState(false),[busy,setBusy]=useState(false);
  const viewer=useRef<LiveViewer|null>(null),lease=useRef<ViewerLease|null>(null),generation=useRef(0),canvas=useRef<HTMLCanvasElement>(null),screen=useRef<HTMLDivElement>(null);
  const stop=useCallback(()=>{generation.current++;const current=lease.current;lease.current=null;viewer.current?.close();viewer.current=null;setStarting(false);setView(previous=>previous?{...previous,state:'stopped',receivedAt:null,reason:'stopped'}:null);if(current)void api.request('/live/view/stop','POST',{viewer_id:current.viewer_id}).catch(()=>{});},[]);
  const live=useLive(id,csrf,(viewerId,reason)=>{if(lease.current?.viewer_id===viewerId)viewer.current?.close(screenCode(reason));});
  const student=live.students.find(s=>s.attempt_id===selected);
  const fresh=live.connection==='online'&&student?.presence==='online';
  useEffect(()=>{let current=true;api.request<Exam>(`/exams/${encodeURIComponent(id)}`).then(value=>{if(current)setExam(value);}).catch(e=>{if(current)setError(e);});return()=>{current=false;};},[id]);
  useEffect(()=>{if(!student)return;let current=true;api.request<{items:LiveCommand[]}>(`/attempts/${encodeURIComponent(student.attempt_id)}/commands`).then(r=>{if(current)live.remember(r.items);}).catch(e=>{if(current)setError(e);});return()=>{current=false;};},[selected]);
  useEffect(()=>{if((!fresh||!student?.capabilities?.view)&&(lease.current||starting))stop();},[fresh,student?.capabilities?.view,stop,starting]);
  useEffect(()=>{window.addEventListener('pagehide',stop);return()=>{window.removeEventListener('pagehide',stop);stop();};},[stop]);
  function select(value:string){stop();setSelected(value);setError(null);}
  async function startView(){
    if(!student||!fresh||!canvas.current||starting)return;stop();setStarting(true);setError(null);const current=++generation.current;
    try {
      const next=await api.request<ViewerLease>(`/attempts/${encodeURIComponent(student.attempt_id)}/view`,'POST',{});
      if(current!==generation.current||!canvas.current){void api.request('/live/view/stop','POST',{viewer_id:next.viewer_id}).catch(()=>{});return;}
      lease.current=next;viewer.current=new LiveViewer(next,csrf,canvas.current,setView,()=>{if(lease.current?.viewer_id===next.viewer_id){lease.current=null;viewer.current=null;void api.request('/live/view/stop','POST',{viewer_id:next.viewer_id}).catch(()=>{});}});
    }catch(e){setError(e);}finally{if(current===generation.current)setStarting(false);}
  }
  async function closeAdmissions(e:FormEvent<HTMLFormElement>){e.preventDefault();const data=new FormData(e.currentTarget);setBusy(true);setError(null);try{await api.request(`/exams/${encodeURIComponent(id)}/close-admissions`,'POST',{reason:String(data.get('reason')).trim(),confirm:data.has('confirm')});setClosedAdmission(true);setAdmission(false);}catch(err){setError(err);}finally{setBusy(false);}}
  const stateKey=view?({starting:'liveViewStarting',live:'liveViewLive',degraded:'liveViewDegraded',recovering:'liveViewRecovering',unavailable:'liveViewUnavailable',stopped:'liveViewStopped'} as const)[view.state]:'liveViewIdle';
  const commands=live.commands.filter(c=>c.attempt_id===selected);
  return <div className="live-workspace"><a className="text-link" href={`#/exam/${encodeURIComponent(id)}`}><ArrowLeft size={16}/>{t('details')}</a>
    <PageTitle title={exam?.title??t('liveWorkspace')} description={t('liveIntro')} action={<button onClick={()=>setAdmission(v=>!v)}>{t('liveCloseAdmission')}</button>}/>
    <div className={`notice ${live.connection==='online'?'success':''}`} role="status"><Radio size={18} aria-hidden="true"/> {t(live.connection==='online'?'liveConnected':live.connection==='connecting'?'liveConnecting':'liveDisconnected')}{live.connection==='offline'&&<button className="quiet" onClick={live.reconnect}><RefreshCw size={16}/>{t('retry')}</button>}</div>
    <ErrorMessage error={error}/>{closedAdmission&&<p className="notice success" role="status">{t('liveAdmissionClosed')}</p>}
    {live.partial.truncated&&<p className="notice">{t('livePartial')} ({live.students.length} / {live.partial.total})</p>}
    {admission&&<form className="panel action-form" onSubmit={closeAdmissions}><h2>{t('liveCloseAdmission')}</h2><Field label={t('reason')}><textarea name="reason" required maxLength={1000}/></Field><label className="check-field"><input name="confirm" type="checkbox" required/>{t('liveConfirmAdmission')}</label><div className="form-actions"><button className="danger" disabled={busy}>{t('confirm')}</button><button type="button" onClick={()=>setAdmission(false)}>{t('cancel')}</button></div></form>}
    <div className="live-layout"><aside className="panel live-roster"><h2>{t('liveWorkspace')}</h2>{!live.students.length?<p className="muted">{t('liveNoStudents')}</p>:<ul>{live.students.map(s=><li key={s.attempt_id}><button className={`student-choice ${s.unreviewed_count?'has-review':''}`} aria-pressed={selected===s.attempt_id} onClick={()=>select(s.attempt_id)}><strong>{s.student.full_name}</strong><span>{s.student.group} · {s.student.student_id}</span><span className={`presence ${live.connection==='online'?s.presence:'offline'}`}>{t(live.connection!=='online'||s.presence==='offline'?'liveOffline':s.presence==='online'?'liveOnline':'liveReconnecting')}</span>{s.unreviewed_count>0&&<span className="review-count">{s.unreviewed_count} · {t('liveReviewCount')}</span>}</button></li>)}</ul>}</aside>
    <div className="live-detail">{!student?<div className="empty"><Monitor size={36}/><h2>{t('liveChoose')}</h2></div>:<>
      <section className="panel"><div className="section-title"><div><h2>{student.student.full_name}</h2><p className="small muted">{student.student.group} · {student.student.student_id}</p></div><a className="button" href={`#/attempt/${encodeURIComponent(selected)}`}>{t('openAttempt')}</a></div><p className="technical small">{selected}</p>
        {!fresh&&<p className="notice">{t('liveStale')}</p>}<dl className="live-facts"><div><dt>{t('liveTimer')}</dt><dd className="live-time">{timerText(student.status?.remaining_seconds)}</dd></div><div><dt>{t('liveStatus')}</dt><dd>{student.status?t(stateLabels[student.status.state]):'—'}</dd></div><div><dt>{t('liveMonitoring')}</dt><dd>{student.status?t(student.status.monitoring_healthy?'liveHealthy':'liveUnhealthy'):'—'}</dd></div><div><dt>{t('liveProgress')}</dt><dd>{student.status?.answered!=null&&student.status.total!=null?`${student.status.answered} / ${student.status.total}`:'—'}</dd></div></dl>
        <p className="small muted">{t('liveLastContact')}: {displayTime(student.last_contact_at,language)}</p>{!!student.status?.pause_reasons.length&&<p>{t('livePauseReasons')}: {student.status.pause_reasons.map(reason=>pauseLabels[reason]?t(pauseLabels[reason]):`${t('liveTechnicalCode')}: ${reason}`).join(' · ')}</p>}
      </section>
      <section className="panel live-screen-panel" data-stream-trace={JSON.stringify(view?.trace??null)} data-stream-metrics={JSON.stringify(view?.delivery??null)} data-stream-observation={JSON.stringify({viewer_id:view?.viewer_id??null,state:view?.state??'stopped',reason:view?.reason??null,transport:view?.transport??null,quality:view?.quality??null})}><div className="section-title"><h2>{t('liveScreen')}</h2><div className="form-actions"><button onClick={startView} disabled={starting||!fresh||!student.capabilities?.view||!!lease.current}><Monitor size={16}/>{t('liveViewStart')}</button><button onClick={stop} disabled={(!view||view.state==='stopped')&&!starting}><Square size={16}/>{t('liveViewStop')}</button></div></div><p className="small muted">{t('liveScreenNote')}</p>
        <div ref={screen} className="live-screen"><canvas ref={canvas} aria-label={t('liveScreen')} style={{visibility:view?.state==='live'?'visible':'hidden'}}/>{view?.state!=='live'&&<div className="screen-message"><Monitor size={30}/><p>{t(stateKey)}</p></div>}<button className="fullscreen" aria-label={t('liveFullscreen')} onClick={()=>{void screen.current?.requestFullscreen().catch(setError);}}><Maximize2 size={18}/></button></div>
        <p className="small">{t(stateKey)}{view?.transport&&` · ${t(view.transport==='direct'?'liveDirect':'liveRelay')}`}{view?.receivedAt!=null&&` · ${t('liveFrameAge')}: ${Math.max(0,(performance.now()-view.receivedAt)/1000).toFixed(1)} s`}</p><p className="small muted">{t('liveLatencyNote')}</p>
        {view?.state==='unavailable'&&view.reason&&<p className="technical small">{t('liveTechnicalCode')}: {screenCode(view.reason)}</p>}
        {view?.quality&&<div className="small"><p>{t('liveRoundTrip')}: {view.quality.ack_roundtrip_ms==null?'—':`${view.quality.ack_roundtrip_ms.toFixed(0)} ms`} · {t('liveSendFps')}: {view.quality.send_fps.toFixed(1)} FPS · {view.quality.width} px</p><p className="muted">{t('liveRoundTripHint')}</p>{view.quality.degraded&&<p className="notice">{t('liveQualityReduced')}</p>}</div>}
      </section>
      <Actions key={selected} student={student} connected={live.connection==='online'} remember={live.remember} onError={setError}/>
      <RecordedControls key={`recorded-${selected}`} student={student}/>
      <section className="panel"><h2>{t('liveCommandHistory')}</h2>{!commands.length?<p className="muted">{t('liveNoCommands')}</p>:<ul className="live-history">{commands.map(command=><li key={command.command_id}><div><strong>{t(commandLabels[command.command_type])}</strong><span className={`badge command-${command.status}`}>{t(resultLabels[command.status])}</span></div><p>{String(command.payload.text??command.payload.reason??'')}</p><small className="muted">{displayTime(command.created_at,language)}{command.command_type==='add_time'?` · +${String(command.payload.seconds)} s`:''}</small><code className="technical small">{command.command_id}</code></li>)}</ul>}</section>
      <AttemptPolicy key={`policy:${selected}`} attemptId={selected} live={student.status?.state==='running'||student.status?.state==='paused'}/><section className="panel"><h2>{t('liveFeed')}</h2><p className="small muted">{t('liveFeedHint')}</p>{(['behavioral','technical'] as const).map(category=><div key={category} className="live-event-group"><h3>{t(category==='technical'?'technical':'behavior')}</h3>{!student.events.filter(e=>e.category===category).length?<p className="muted">{t('liveNoEvents')}</p>:<ol>{student.events.filter(e=>e.category===category).slice().reverse().map(event=><li key={`${selected}:${event.event_id}`}><strong>{eventLabel(event.event_type,t)}</strong><span>{displayTime(event.timestamp,language)}</span>{event.duration_seconds!=null&&<span>{event.duration_seconds.toFixed(1)} s</span>}<a href={`#/attempt/${encodeURIComponent(selected)}`}>{t('openAttempt')}</a><EventSnapshot attemptId={selected} snapshot={event.snapshot}/><AudioEvidencePlayer attemptId={selected} audio={event.audio}/></li>)}</ol>}</div>)}</section>
    </>}</div></div></div>;
}
