import { ArrowRight, Check, CircleAlert, UserRound } from 'lucide-react';
import type { BackendState, WorkflowState } from '../../shared/contracts';
import { Badge, Button } from '../components/ui';
import { command } from '../hooks/backend';
import { useT } from '../locales';
import { useW } from '../locales/workflow';
import { ProtectionStatus } from '../components/ProtectionStatus';
import { useC } from '../locales/connected';

export function LiveReady({ state, workflow, busy }: { state: BackendState; workflow: WorkflowState; busy: boolean }) {
  const c = useC(); const t = useT(); const w = useW(); const candidate = workflow.registration.candidate;
  const labels: Record<string, string> = { advanced: w('advancedChecks'), admission: c('title'), camera: t('camera'), microphone: t('microphone'), audio: t('microphone'), reference: t('reference'), registration: t('detailsTitle'), calibration: t('gaze'), gaze: t('gaze'), devices: t('deviceSection'), system: w('systemChecks'), monitoring: t('monitoring'), consent: t('consent'), protection: t('protection') };
  return <div className="ready-layout"><div className="page-title"><div><p className="eyebrow">03 / {t('stepReady')}</p><h1>{workflow.readiness.ready ? t('readyTitle') : t('stepReady')}</h1><p>{t('readyHelp')}</p></div></div><section className="panel ready-panel"><div className="candidate-summary"><div className="candidate-icon"><UserRound size={26} aria-hidden="true"/></div><div><h2>{candidate ? (candidate.full_name || `${candidate.first_name} ${candidate.last_name}`) : w('registrationSkipped')}</h2><p>{candidate?.group_id}</p><span className="quiet-note">{workflow.quiz.mode === 'external' ? w('externalExam') : w('nativeExam')}</span></div></div>
    <div className="readiness-list">{workflow.readiness.checks.map(check => <div className="readiness-row" key={check.id}>{check.status === 'ready' ? <Check size={18} aria-hidden="true"/> : <CircleAlert size={18} aria-hidden="true"/>}<div><span>{labels[check.id] ?? check.id}</span>{check.message && <p className="quiet-note">{check.id === 'admission' ? c(check.status === 'ready' ? 'fixed' : 'preparation_expired') : check.message}</p>}</div><Badge tone={check.status === 'ready' ? 'success' : check.status === 'blocked' ? 'warning' : 'neutral'}>{check.status === 'ready' ? t('readyCheck') : check.status === 'not_enabled' ? t('notEnabled') : w('unmet')}</Badge></div>)}<div className="readiness-row"><ProtectionStatus protection={state.protection} detail/></div></div>
    <div className="ready-action"><p>{t('readyFooter')}</p><Button disabled={busy || !!state.admission?.busy || !workflow.readiness.ready} onClick={() => void command('exam.start')}>{w('start')}<ArrowRight size={18} aria-hidden="true"/></Button></div>
    <p className="data-note">{state.admission ? c('privacy') : state.config.remote_enabled ? `${w('deliveryConfigured')}: ${state.config.remote_destinations.join(', ')}` : t('noRemote')}</p>
    <Button variant="ghost" disabled={busy} onClick={() => void command('setup.show')}>{w('backDevices')}</Button>
    </section></div>;
}
