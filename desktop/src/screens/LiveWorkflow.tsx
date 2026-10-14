import { useEffect, useRef } from 'react';
import type { BackendState } from '../../shared/contracts';
import { SetupScreen, type RegistrationForm } from './SetupScreen';
import { LiveRegistration } from './LiveRegistration';
import { LiveCalibration } from './LiveCalibration';
import { LiveReady } from './LiveReady';
import { LiveExam } from './LiveExam';
import { LiveSummary } from './LiveSummary';
import { useW } from '../locales/workflow';
import { useCalibrationCue } from '../hooks/calibrationPresentation';
import { ConnectedJoin } from './ConnectedJoin';
import { ProtectionStatus } from '../components/ProtectionStatus';
import { DisplayRequirement } from '../components/LiveTeacher';
import { Synchronization } from '../components/Synchronization';
export function LiveWorkflow({ state, busy, error, form, setForm }: { state: BackendState; busy: boolean; error: string | null; form: RegistrationForm; setForm: (v: RegistrationForm) => void }) {
  const w = useW(); const hydrated = useRef(false); const workflow = state.workflow;
  useCalibrationCue(workflow?.calibration);
  useEffect(() => {
    if (hydrated.current || !workflow) return;
    hydrated.current = true;
    const candidate = workflow.registration.candidate;
    if (candidate && !form.firstName && !form.lastName && !form.group) setForm({ firstName: candidate.first_name, lastName: candidate.last_name, group: candidate.group_id });
  }, [workflow?.registration.candidate]);
  if (!workflow) return <section className="panel"><p role="status">{w('backendNeeded')}</p></section>;
  if (state.admission && !state.admission.policy_applied) return <ConnectedJoin admission={state.admission} busy={busy}/>;
  const content = workflow.step === 'calibration' ? <LiveCalibration state={state} workflow={workflow} busy={busy}/> :
    workflow.step === 'ready' ? <LiveReady state={state} workflow={workflow} busy={busy}/> :
    workflow.step === 'exam' || workflow.step === 'paused' ? <LiveExam state={state} workflow={workflow} busy={busy} error={error}/> :
    workflow.step === 'summary' ? <LiveSummary state={state} workflow={workflow} busy={busy}/> :
    <>{state.protection.requested && <section className="panel"><ProtectionStatus protection={state.protection} detail/></section>}<SetupScreen state={state} fixture={false} busy={busy} connected scene="setup" setScene={() => {}} form={form} setForm={setForm} registrationContent={<LiveRegistration workflow={workflow} busy={busy} form={form} setForm={setForm}/>}/></>;
  return <><Synchronization state={state} busy={busy}/><DisplayRequirement live={state.live_teacher}/>{content}</>;
}
