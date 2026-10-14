import { useEffect, useRef, useState } from 'react';
import { MotionConfig, motion } from 'motion/react';
import { FlaskConical, Info } from 'lucide-react';
import type { Locale } from '../shared/contracts';
import { Header, Stepper } from './components/Header';
import { fixtureMode, reconnect, useBackend } from './hooks/backend';
import { LocaleContext, translate, type TextKey } from './locales';
import { scenes, type Scene } from './fixtures/scenes';
import { SetupScreen, type RegistrationForm } from './screens/SetupScreen';
import { CalibrationScreen } from './screens/CalibrationScreen';
import { ReadyScreen } from './screens/ReadyScreen';
import { ExamScreen } from './screens/ExamScreen';
import { SummaryScreen } from './screens/SummaryScreen';
import { LiveWorkflow } from './screens/LiveWorkflow';
import { DisconnectedScreen } from './screens/DisconnectedScreen';
import { useControlProgress } from './hooks/controlProgress';
import { ConnectedPreparation } from './screens/ConnectedJoin';
export default function App() {
  const backend = useBackend();
  const lastProtection = useRef(backend.state?.protection);
  if (backend.state) lastProtection.current = backend.state.protection;
  useControlProgress(backend.state, !fixtureMode && backend.connection.state === 'connected');
  const [locale, setLocale] = useState<Locale>('en'); const [localeChosen, setLocaleChosen] = useState(false);
  const initial = new URLSearchParams(window.location.search).get('scene');
  const [scene, setScene] = useState<Scene>(fixtureMode && scenes.some(s => s.id === initial) ? initial as Scene : 'setup');
  const [form, setForm] = useState<RegistrationForm>({ firstName: '', lastName: '', group: '' });
  useEffect(() => { if (!localeChosen && backend.state) setLocale(backend.state.language); }, [backend.state?.language, localeChosen]);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  const t = (key: TextKey) => translate(locale, key);
  const workflow = !fixtureMode ? backend.state?.workflow : undefined;
  const workflowHeader = !!workflow || (!fixtureMode && !!lastProtection.current?.requested);
  const inExam = workflow ? workflow.step === 'exam' || workflow.step === 'paused' : scene === 'exam' || scene.startsWith('pause'); const inSummary = workflow ? workflow.step === 'summary' : scene.startsWith('summary'); const gaze = workflow ? workflow.step === 'calibration' : scene.startsWith('gaze');
  const ready = workflow ? workflow.step === 'ready' : scene === 'ready';
  const languageLocked = !!workflow && ['awaiting_presentation', 'preparing', 'collecting'].includes(workflow.calibration.phase);
  const connectionLost = !fixtureMode && backend.connection.state === 'disconnected';
  const stage = inExam ? 'exam' : inSummary ? 'summary' : gaze ? 'calibration' : ready ? 'ready' : 'setup';
  return <LocaleContext.Provider value={locale}><MotionConfig reducedMotion="user"><a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>{t("skipToMain")}</a><Header locale={locale} setLocale={v => { setLocale(v); setLocaleChosen(true); }} fixture={fixtureMode} connection={backend.connection} stage={stage} workflow={workflowHeader} languageLocked={languageLocked} protection={fixtureMode ? undefined : lastProtection.current} liveTeacher={fixtureMode ? undefined : backend.state?.live_teacher}/><main id="main-content" tabIndex={-1} className={`app-main ${inExam ? 'exam-main' : ''}`}>
    {fixtureMode && <div className="fixture-bar"><div><FlaskConical aria-hidden="true" size={17}/><p><strong>{t('fixture')}</strong><span>{t('fixtureNote')}</span></p></div><label><span className="sr-only">{t('previewState')}</span><select aria-label={t('previewState')} value={scene} onChange={e => setScene(e.target.value as Scene)}>{scenes.map(s => <option key={s.id} value={s.id}>{t(s.key)}</option>)}</select></label></div>}
    {!inExam && !inSummary && scene !== 'disconnected' && !connectionLost && <Stepper current={gaze ? 1 : ready ? 2 : 0}/>}
    {!fixtureMode && backend.error && !connectionLost && <div className="notice notice-error" role="alert"><Info aria-hidden="true" size={18}/><div><strong>{t('technicalError')}</strong><p>{backend.error}</p></div></div>}
    {backend.state?.admission?.policy_applied && !workflow?.session.started && <ConnectedPreparation admission={backend.state.admission} busy={backend.busy}/>}
    <motion.div key={connectionLost ? 'lost' : fixtureMode ? stage : 'live'} initial={inExam ? false : { opacity: .85, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .14 }}>
      {connectionLost || scene === 'disconnected' ? <DisconnectedScreen retry={() => fixtureMode ? setScene('setup') : void reconnect()} busy={backend.busy} error={backend.error ?? backend.connection.reason}/> : !fixtureMode && backend.state?.mode === 'exam_workflow' ? <LiveWorkflow state={backend.state} busy={backend.busy} error={backend.error} form={form} setForm={setForm}/> : inSummary ? <SummaryScreen scene={scene} setScene={setScene}/> : inExam ? <ExamScreen scene={scene} setScene={setScene}/> : gaze ? <CalibrationScreen scene={scene} setScene={setScene}/> : scene === 'ready' ? <ReadyScreen setScene={setScene}/> : <SetupScreen state={backend.state} fixture={fixtureMode} busy={backend.busy} connected={fixtureMode || backend.connection.state === 'connected'} scene={scene} setScene={setScene} form={form} setForm={setForm}/>}
    </motion.div>
  </main></MotionConfig></LocaleContext.Provider>;
}
