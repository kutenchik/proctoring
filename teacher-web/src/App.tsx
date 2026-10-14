import { LiveWorkspace } from './LiveWorkspace';
import { ErrorMessage, Loading, PageTitle, Field } from './ui';
import { AttemptReview, DownloadButton } from './AttemptReview';
import { Children, cloneElement, Component, isValidElement, useEffect, useId, useRef, useState, type FormEvent, type ReactElement, type ReactNode } from 'react';
import { ArrowLeft, ArrowRight, BookOpen, CalendarDays, Check, ChevronRight, Clock3, GraduationCap, LogOut, Plus, RefreshCw, ShieldCheck, Upload, Users } from 'lucide-react';
import { api, ApiError, type Attempt, type Auth, type Exam, type ExamInput, type LibrarySummary, type QuestionSet } from './api';
import { useI18n, type Language } from './i18n';
import { displayTime, routeFromHash, zonedDateTimeToUtc, type Route } from './time';

function navigate(path: string) { window.location.hash = path; }
function useRoute(): Route {
  const [route, setRoute] = useState(() => routeFromHash(window.location.hash));
  useEffect(() => {
    // Link secrets stay in memory only; no history/referrer/storage persistence.
    if (route.token) history.replaceState(null, '', `${location.pathname}${location.search}#/${route.page}`);
  }, [route]);
  useEffect(() => { const change = () => setRoute(routeFromHash(window.location.hash)); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, []);
  return route;
}

function AuthScreen({route, onAuth}: {route: Route; onAuth: (auth: Auth) => void}) {
  const {t} = useI18n(); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(null); const [saved, setSaved] = useState(false);
  const invite = route.page === 'invite'; const reset = route.page === 'reset';
  const special = (invite || reset) && !saved;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget); setBusy(true); setError(null);
    try {
      if (special) {
        await api.request(invite ? '/auth/accept-invite' : '/auth/reset-password', 'POST', {token: route.token, ...(invite ? {name: form.get('name')} : {}), password: form.get('password')});
        setSaved(true);
      } else onAuth(await api.login(String(form.get('email')).trim(), String(form.get('password'))));
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <div className="auth-layout"><section className="auth-intro"><div className="icon-tile"><GraduationCap aria-hidden="true" /></div><p className="eyebrow">Local Proctoring</p><h1>{t('welcome')}</h1><p>{t('private')}</p><p className="auth-note">{t('inviteOnly')}</p></section>
    <section className="panel auth-card"><h2>{t(special ? invite ? 'invited' : 'reset' : 'login')}</h2>
      {saved && <p role="status" className="notice success">{t('authSaved')}</p>}<ErrorMessage error={error} />
      {special && !route.token ? <p className="notice error">{t('invalidLink')}</p> : <form onSubmit={submit}>
        {special && invite && <Field label={t('name')}><input name="name" autoComplete="name" required maxLength={120} /></Field>}
        {!special && <Field label={t('email')}><input name="email" type="email" autoComplete="username" required maxLength={254} /></Field>}
        <Field label={t('password')} hint={special ? t('passwordHint') : undefined}><input key={special ? 'new' : 'current'} name="password" type="password" autoComplete={special ? 'new-password' : 'current-password'} minLength={special ? 12 : undefined} maxLength={128} required /></Field>
        <button className="primary full" disabled={busy}>{t(busy ? 'saving' : special ? invite ? 'acceptInvite' : 'savePassword' : 'login')}<ArrowRight size={18} aria-hidden="true" /></button>
      </form>}
    </section></div>;
}

function ExamCard({exam}: {exam: Exam}) {
  const {t, language} = useI18n();
  return <article className="panel exam-card"><div className="card-top"><span className={`badge ${exam.phase}`}>{t(exam.phase)}</span><span className="muted">{t(exam.exam_type)}</span></div>
    <h2><a href={`#/exam/${encodeURIComponent(exam.id)}`}>{exam.title}</a></h2>
    <div className="code-line"><span>{t('code')}</span><strong className="exam-code">{exam.code}</strong></div>
    <dl className="card-data"><div><dt><CalendarDays size={16} aria-hidden="true" />{t('admission')}</dt><dd>{displayTime(exam.admission_start, language, exam.timezone)}<br />— {displayTime(exam.admission_close, language, exam.timezone)}<small>{exam.timezone}</small></dd></div><div><dt><Clock3 size={16} aria-hidden="true" />{t('duration')}</dt><dd>{exam.duration_seconds / 60} {t('minutes')}</dd></div></dl>
    <div className="counts"><span><Users size={16} aria-hidden="true" />{exam.participant_count} {t('participants')}</span><span>{exam.attempt_count} {t('attempts')}</span></div>
    <a className="text-link" href={`#/exam/${encodeURIComponent(exam.id)}`}>{t('details')}<ChevronRight size={17} aria-hidden="true" /></a></article>;
}

function ExamsPage() {
  const {t} = useI18n(); const [items, setItems] = useState<Exam[] | null>(null); const [error, setError] = useState<unknown>(null); const [phase, setPhase] = useState<Exam['phase']>('active'); const [revision, setRevision] = useState(0);
  useEffect(() => { let current = true; setError(null); api.request<{items: Exam[]}>('/exams').then(data => {if (current) setItems(data.items);}).catch(e => {if (current) setError(e);}); return () => {current = false;}; }, [revision]);
  const filtered = items?.filter(exam => exam.phase === phase);
  return <><PageTitle title={t('exams')} description={t('examIntro')} action={<a className="button primary" href="#/create"><Plus size={18} aria-hidden="true" />{t('createExam')}</a>} />
    <p className="info-line">{t('persisted')}</p><div className="section-toolbar"><div className="tabs" aria-label={t('exams')}>{(['active', 'upcoming', 'completed'] as const).map(value => <button key={value} aria-pressed={phase === value} onClick={() => setPhase(value)}>{t(value)}<span>{items ? items.filter(e => e.phase === value).length : '—'}</span></button>)}</div><button className="quiet" onClick={() => setRevision(x => x + 1)}><RefreshCw size={16} aria-hidden="true" />{t('refresh')}</button></div>
    <p className="small muted">{t('phaseHint')}</p><ErrorMessage error={error} />
    {!items && !error ? <Loading /> : filtered?.length ? <div className="exam-grid">{filtered.map(exam => <ExamCard key={exam.id} exam={exam} />)}</div> : !error && <div className="empty"><CalendarDays size={32} aria-hidden="true" /><h2>{t('noExams')}</h2></div>}
  </>;
}

function QuestionPreview({document, unsaved}: {document: QuestionSet; unsaved?: boolean}) {
  const {t} = useI18n();
  return <section className="question-preview"><div className="preview-heading"><h2>{document.title}</h2>{unsaved && <span className="badge">{t('previewOnly')}</span>}</div><p className="muted small">{document.questions.length} {t('questionCount')} · {t('scoring')}</p>
    <ol className="questions">{document.questions.map(q => <li key={q.id}><span className="badge">{t(q.type)}</span><h3>{q.prompt}</h3><ul>{q.options.map(option => <li key={option.id} className={q.correct_option_ids.includes(option.id) ? 'correct-option' : ''}><span>{option.text}</span>{q.correct_option_ids.includes(option.id) && <span className="correct-label"><Check size={14} aria-hidden="true" />{t('correct')}</span>}</li>)}</ul><small className="technical">{q.id}</small></li>)}</ol>
  </section>;
}

function LibraryPage() {
  const {t} = useI18n(); const [items, setItems] = useState<LibrarySummary[] | null>(null); const [preview, setPreview] = useState<QuestionSet | null>(null); const [unsaved, setUnsaved] = useState(false); const [file, setFile] = useState<File | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(null); const [saved, setSaved] = useState(false);
  async function load() { setItems((await api.request<{items: LibrarySummary[]}>('/libraries')).items); }
  useEffect(() => { load().catch(setError); }, []);
  async function importFile(event: FormEvent) {
    event.preventDefault(); if (!file || busy) return; setBusy(true); setError(null); setSaved(false); setPreview(null); setUnsaved(false);
    try { setPreview(await api.preview(file)); setUnsaved(true); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function save() { if (!preview || busy) return; setBusy(true); setError(null); try { const result = await api.request<QuestionSet>('/libraries', 'POST', preview); setPreview(result); setUnsaved(false); setSaved(true); await load(); } catch (e) {setError(e);} finally {setBusy(false);} }
  async function open(id: string) { setBusy(true); setError(null); setSaved(false); try {setPreview(await api.request<QuestionSet>(`/libraries/${encodeURIComponent(id)}`)); setUnsaved(false);} catch (e) {setError(e);} finally {setBusy(false);} }
  return <><PageTitle title={t('library')} description={t('libraryIntro')} /><div className="library-layout"><section className="panel"><div className="section-heading"><Upload aria-hidden="true" /><h2>{t('importSet')}</h2></div><p className="muted">{t('importHint')}</p><form onSubmit={importFile}><Field label={t('file')}><input type="file" accept=".json,.xlsx" required onChange={e => {setFile(e.target.files?.[0] ?? null); setSaved(false);}} /></Field><button className="primary" disabled={!file || busy}>{t(busy ? 'loading' : 'preview')}</button></form><a className="text-link" href="/samples/README.txt" target="_blank" rel="noreferrer">{t('schema')}<ArrowRight size={16} aria-hidden="true" /></a></section>
    <section className="panel"><h2>{t('savedSets')}</h2>{!items ? <Loading /> : !items.length ? <p className="muted">{t('noSets')}</p> : <ul className="library-list">{items.map(item => <li key={item.id}><button className="library-button" disabled={busy} onClick={() => open(item.id)}><BookOpen size={20} aria-hidden="true" /><span><strong>{item.title}</strong><small>{item.question_count} {t('questionCount')}</small></span><ChevronRight size={18} aria-hidden="true" /></button></li>)}</ul>}</section></div>
    <ErrorMessage error={error} />{saved && <p role="status" className="notice success">{t('saved')}</p>}{preview && <div className="panel preview-panel"><QuestionPreview document={preview} unsaved={unsaved} />{unsaved && <div className="form-actions"><button className="primary" onClick={save} disabled={busy}>{t(busy ? 'saving' : 'saveSet')}</button><button disabled={busy} onClick={() => {setPreview(null); setUnsaved(false);}}>{t('cancel')}</button></div>}</div>}</>;
}

function CreatePage() {
  const {t} = useI18n(); const [type, setType] = useState<'native' | 'external'>('native'); const [items, setItems] = useState<LibrarySummary[]>([]); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>(null);
  useEffect(() => {api.request<{items: LibrarySummary[]}>('/libraries').then(data => setItems(data.items)).catch(setError);}, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(null); const values = new FormData(event.currentTarget); setBusy(true);
    try {
      const timezone = String(values.get('timezone')).trim();
      const admission_start = zonedDateTimeToUtc(String(values.get('opens')), timezone); const admission_close = zonedDateTimeToUtc(String(values.get('closes')), timezone);
      if (admission_close <= admission_start) throw new Error('invalid_window');
      const exam: ExamInput = { title: String(values.get('title')).trim(), exam_type: type, admission_start, admission_close, timezone,
        duration_seconds: Number(values.get('duration')) * 60,
        ...(type === 'native' ? {library_id: String(values.get('library'))} : {external_url: String(values.get('url')).trim()}),
        shuffle_questions: values.has('shuffle_questions'), shuffle_options: values.has('shuffle_options'), audio_monitoring: values.has('audio_monitoring'), save_snapshots: values.has('save_snapshots'), protection_mode: values.get('protection_mode') === 'protected' ? 'protected' : 'unprotected',
      };
      const created = await api.request<Exam>('/exams', 'POST', exam); navigate(`/exam/${encodeURIComponent(created.id)}`);
    } catch (e) { setError(e); } finally {setBusy(false);} }
  return <><a className="text-link" href="#/exams"><ArrowLeft size={16} aria-hidden="true" />{t('back')}</a><PageTitle title={t('createExam')} description={t('snapshotHint')} /><form className="panel creation-form" onSubmit={submit}><ErrorMessage error={error} />
    <div className="form-grid"><Field label={t('title')}><input name="title" required maxLength={200} /></Field><Field label={t('examType')}><select value={type} onChange={event => setType(event.target.value as typeof type)}><option value="native">{t('native')}</option><option value="external">{t('external')}</option></select></Field>
      <Field label={t('timezone')} hint={t('timezoneHint')}><input name="timezone" required defaultValue={Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'} list="timezones" /><datalist id="timezones"><option value="Asia/Qyzylorda" /><option value="Asia/Almaty" /><option value="Europe/Moscow" /><option value="UTC" /></datalist></Field><Field label={`${t('duration')} (${t('minutes')})`}><input name="duration" type="number" min="1" max="480" step="1" defaultValue="30" required /></Field><Field label={t('opens')}><input name="opens" type="datetime-local" required /></Field><Field label={t('closes')}><input name="closes" type="datetime-local" required /></Field></div>
      {type === 'native' ? <Field label={t('questions')}><select name="library" required defaultValue=""><option value="" disabled>{t('chooseSet')}</option>{items.map(item => <option key={item.id} value={item.id}>{item.title} ({item.question_count})</option>)}</select>{!items.length && <a href="#/library">{t('importSet')}</a>}</Field> : <Field label={t('externalUrl')} hint={t('externalHint')}><input name="url" type="url" pattern="https://.*" required placeholder="https://" /></Field>}
      <fieldset><legend>{t('settings')}</legend><div className="check-grid">{(['shuffle_questions','shuffle_options','audio_monitoring','save_snapshots'] as const).map((name, index) => <label className="check-field" key={name}><input type="checkbox" name={name} disabled={index < 2 && type === 'external'} defaultChecked={index > 1} /><span>{t(['shuffleQuestions','shuffleOptions','audio','snapshots'][index])}</span></label>)}</div><Field label={t('protection')} hint={t('protectionHint')}><select name="protection_mode" defaultValue="unprotected"><option value="unprotected">{t('unprotected')}</option><option value="protected">{t('protected')}</option></select></Field></fieldset><div className="form-actions"><button className="primary" disabled={busy}><Plus size={18} aria-hidden="true" />{t(busy ? 'saving' : 'createExam')}</button><a className="button" href="#/exams">{t('cancel')}</a></div>
    </form></>;
}

function ExamDetail({id}: {id: string}) {
  const {t, language} = useI18n(); const [exam, setExam] = useState<Exam | null>(null); const [attempts, setAttempts] = useState<Attempt[]>([]); const [error, setError] = useState<unknown>(null); const [busy, setBusy] = useState(false); const [action, setAction] = useState<{attempt: Attempt; type: 'extend' | 'allow-repeat'} | null>(null); const [saved, setSaved] = useState(false); const [revision, setRevision] = useState(0); const reasonRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {let current = true; setError(null); Promise.all([api.request<Exam>(`/exams/${encodeURIComponent(id)}`), api.request<{items: Attempt[]}>(`/exams/${encodeURIComponent(id)}/attempts`)]).then(([value, list]) => {if (current) {setExam(value); setAttempts(list.items);}}).catch(e => {if (current) setError(e);}); return () => {current = false;};}, [id, revision]);
  useEffect(() => { if (action) reasonRef.current?.focus(); }, [action]);
  async function submitAction(event: FormEvent<HTMLFormElement>) {event.preventDefault(); if (!action) return; const reason = String(new FormData(event.currentTarget).get('reason')).trim(); if (!reason) return; setBusy(true); setError(null); setSaved(false); try {await api.request(`/attempts/${encodeURIComponent(action.attempt.id)}/${action.type}`, 'POST', {reason}); setAction(null); setSaved(true); setRevision(x => x + 1);} catch (e) {setError(e);} finally {setBusy(false);}}
  return <><a className="text-link" href="#/exams"><ArrowLeft size={16} aria-hidden="true" />{t('back')}</a><ErrorMessage error={error} />{!exam ? !error && <Loading /> : <><PageTitle title={exam.title} description={`${t('code')}: ${exam.code}`} action={<div className="form-actions"><a className="button primary" href={`#/live/${encodeURIComponent(id)}`}>{t('liveWorkspace')}</a><button onClick={() => setRevision(x => x + 1)}><RefreshCw size={16} aria-hidden="true" />{t('refresh')}</button></div>} /><div className="detail-layout"><section className="panel"><h2>{t('settings')}</h2><dl className="detail-data"><div><dt>{t('examType')}</dt><dd>{t(exam.exam_type)}</dd></div><div><dt>{t('opens')}</dt><dd>{displayTime(exam.admission_start, language, exam.timezone)}</dd></div><div><dt>{t('closes')}</dt><dd>{displayTime(exam.admission_close, language, exam.timezone)}</dd></div><div><dt>{t('timezone')}</dt><dd>{exam.timezone}</dd></div><div><dt>{t('duration')}</dt><dd>{exam.duration_seconds / 60} {t('minutes')}</dd></div><div><dt>{t('protection')}</dt><dd>{t(exam.policy.protection_mode)}</dd></div>{(['shuffle_questions','shuffle_options','audio_monitoring','save_snapshots'] as const).map((name, index) => <div key={name}><dt>{t(['shuffleQuestions','shuffleOptions','audio','snapshots'][index])}</dt><dd>{t(exam.policy[name] ? 'on' : 'off')}</dd></div>)}</dl>{exam.exam_type === 'external' && <><p className="technical">{exam.external_url}</p><p className="notice">{t('externalHint')}</p></>}</section><section className="panel detail-note"><ShieldCheck size={28} aria-hidden="true" /><h2>{t('attempts')}</h2><p>{t('attemptHint')}</p><p className="small muted">{t('persisted')}</p></section></div>
    <section className="attempt-section"><div className="section-title"><h2>{t('attempts')} ({attempts.length})</h2><DownloadButton url={`/api/v1/exams/${encodeURIComponent(id)}/export.xlsx`} label={t("xlsxExport")} filename="exam-attempts.xlsx" /></div>{saved && <p className="notice success" role="status">{t('actionSaved')}</p>}{!attempts.length ? <div className="empty">{t('noAttempts')}</div> : <div className="attempt-list">{attempts.map(attempt => <article key={attempt.id} className="panel attempt-card"><div><h3>{attempt.full_name}</h3><p className="small muted">{t('studentId')}: {attempt.student_id} · {t('group')}: {attempt.group}</p><p className="technical small">{attempt.id}</p></div><div><span className="badge">{t(['admitted','preparation_expired','started','finished'].includes(attempt.status) ? attempt.status : 'unknown')}</span><p className="small">{t('prepDeadline')}: {displayTime(attempt.preparation_deadline, language, exam.timezone)}</p><p className="small">{attempt.score != null && attempt.total != null ? `${t('clientReported')}: ${attempt.score} / ${attempt.total}` : t('noResult')}</p></div><div className="attempt-actions"><a className="button" href={`#/attempt/${encodeURIComponent(attempt.id)}`}>{t("openAttempt")}</a>{['admitted','preparation_expired'].includes(attempt.status) && <button onClick={() => {setAction({attempt, type: 'extend'}); setSaved(false);}}>{t('extend')}</button>}{['preparation_expired','finished'].includes(attempt.status) && (attempt.repeat_authorized ? <span className="badge">{t('repeatGranted')}</span> : <button onClick={() => {setAction({attempt, type: 'allow-repeat'}); setSaved(false);}}>{t('repeat')}</button>)}</div></article>)}</div>}
      {action && <form className="panel action-form" onSubmit={submitAction}><h3>{t(action.type === 'extend' ? 'extend' : 'repeat')} · {action.attempt.full_name}</h3><Field label={t('reason')} hint={t('auditHint')}><textarea ref={reasonRef} name="reason" required minLength={3} maxLength={1000} rows={3} /></Field><div className="form-actions"><button className="primary" disabled={busy}>{t(busy ? 'saving' : 'confirm')}</button><button type="button" disabled={busy} onClick={() => setAction(null)}>{t('cancel')}</button></div></form>}
    </section>{exam.quiz && <details className="panel preview-panel"><summary>{t('questions')} ({exam.quiz.questions.length})</summary><QuestionPreview document={exam.quiz} /></details>}</>}</>;
}

function CrashMessage() { const {t} = useI18n(); return <div className="notice error"><p>{t('crash')}</p><button onClick={() => location.reload()}>{t('refresh')}</button></div>; }
export class PageBoundary extends Component<{children: ReactNode}, {failed: boolean}> {state = {failed: false}; static getDerivedStateFromError() {return {failed: true};} render() {return this.state.failed ? <CrashMessage /> : this.props.children;} }

export function App() {
  const {t, language, setLanguage} = useI18n(); const route = useRoute(); const [auth, setAuth] = useState<Auth | null>(null); const [checking, setChecking] = useState(true); const [error, setError] = useState<unknown>(null);
  useEffect(() => {api.me().then(setAuth).catch(e => {if (!(e instanceof ApiError && e.status === 401)) setError(e);}).finally(() => setChecking(false));}, []);
  async function logout() {setError(null); try {await api.logout(); setAuth(null); navigate('/login');} catch (e) {setError(e);} }
  function onAuth(value: Auth) { setAuth(value); setError(null); navigate('/exams'); }
  const special = route.page === 'invite' || route.page === 'reset' || route.page === 'login';
  return <><header className="header"><a className="brand" href="#/exams"><span className="brand-symbol"><GraduationCap size={22} aria-hidden="true" /></span><span>Local Proctoring<small>{t('teacher')}</small></span></a>{auth && !special && <nav aria-label={t('teacher')}><a href="#/exams" aria-current={route.page !== 'library' ? 'page' : undefined}>{t('exams')}</a><a href="#/library" aria-current={route.page === 'library' ? 'page' : undefined}>{t('library')}</a></nav>}<div className="header-controls"><label className="language-field"><span className="sr-only">{t('language')}</span><select aria-label={t("language")} value={language} onChange={e => setLanguage(e.target.value as Language)}><option value="en">EN</option><option value="ru">RU</option><option value="kk">ҚАЗ</option></select></label>{auth && <><span className="teacher-name">{auth.teacher.name}</span><button className="quiet" aria-label={t("logout")} title={t("logout")} onClick={logout}><LogOut size={17} aria-hidden="true" /><span>{t('logout')}</span></button></>}</div></header><main><ErrorMessage error={error} />{checking ? <Loading /> : !auth || special ? <AuthScreen key={route.page} route={route} onAuth={onAuth} /> : <PageBoundary key={route.page + route.id}>{route.page === 'library' ? <LibraryPage /> : route.page === 'create' ? <CreatePage /> : route.page === 'detail' && route.id ? <ExamDetail id={route.id} /> : route.page === 'live' && route.id ? <LiveWorkspace id={route.id} csrf={auth.csrf_token}/> : route.page === 'attempt' && route.id ? <AttemptReview id={route.id} /> : <ExamsPage />}</PageBoundary>}</main><footer>{t('liveStage')}</footer></>;
}
