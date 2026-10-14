import { ArrowRight, Camera, Check, UserRound } from 'lucide-react';
import type { WorkflowState } from '../../shared/contracts';
import { Badge, Button, Input } from '../components/ui';
import { command } from '../hooks/backend';
import { prepareCalibrationCues } from '../hooks/calibrationPresentation';
import { useT } from '../locales';
import { useC } from '../locales/connected';
import { useW } from '../locales/workflow';
import type { RegistrationForm } from './SetupScreen';
export function LiveRegistration({ workflow, busy, form, setForm }: { workflow: WorkflowState; busy: boolean; form: RegistrationForm; setForm: (form: RegistrationForm) => void }) {
  const c = useC(); const t = useT(); const w = useW(); const r = workflow.registration; const reference = workflow.reference;
  const valid = !!form.firstName.trim() && !!form.lastName.trim() && (!r.require_group || !!form.group.trim());
  const unchanged = r.candidate?.first_name === form.firstName.trim() && r.candidate.last_name === form.lastName.trim() && r.candidate.group_id === form.group.trim();
  return <section className="panel registration-panel"><div className="registration-intro"><div className="section-heading"><div className="icon-tile"><UserRound size={20} aria-hidden="true"/></div><div><h2>{t('detailsTitle')}</h2><p>{r.enabled ? t('detailsHelp') : w('registrationSkipped')}</p></div></div>{r.complete && <Badge tone="success"><Check size={14} aria-hidden="true"/>{w('savedDetails')}</Badge>}</div>
    {r.candidate?.full_name && <p>{r.candidate.full_name} · {r.candidate.student_id}<br/>{c('fixed')}</p>}
    {r.enabled && !r.candidate?.full_name && <form onSubmit={event => { event.preventDefault(); if (valid && !busy) void command('registration.submit', { first_name: form.firstName.trim(), last_name: form.lastName.trim(), group_id: form.group.trim() }); }}>
      <div className="registration-fields">{(['firstName', 'lastName', 'group'] as const).map(key => <div className="field" key={key}><label htmlFor={key}>{t(key)}{key !== 'group' || r.require_group ? ' *' : ` · ${w('optional')}`}</label><Input id={key} value={form[key]} required={key !== 'group' || r.require_group} maxLength={120} autoComplete={key === 'firstName' ? 'given-name' : key === 'lastName' ? 'family-name' : 'off'} onChange={event => setForm({ ...form, [key]: event.target.value })}/></div>)}</div><div className="actions registration-save"><Button type="submit" variant="secondary" disabled={busy || !valid || (r.complete && unchanged)}>{w('saveDetails')}</Button></div>
    </form>}
    <div className="reference-row"><div><strong>{t('referencePhoto')}</strong><p>{reference.enabled ? w('referenceHeuristic') : w('referenceDisabled')}</p>{reference.enabled && <p role="status" className={reference.ready ? 'success-text' : 'quiet-note'}>{reference.ready ? w('referenceSaved') : reference.status}</p>}</div>{reference.enabled && <Button size="small" variant="secondary" disabled={busy || !reference.can_capture} onClick={() => void command('reference.capture')}><Camera size={16} aria-hidden="true"/>{reference.ready ? w('retakeReference') : w('captureReference')}</Button>}</div>
    <div className="registration-footer"><p className="quiet-note">{w('preparationPrivacy')}</p><Button disabled={busy || !r.complete || (reference.enabled && !reference.ready)} onClick={() => { prepareCalibrationCues(); void command('calibration.start'); }}>{workflow.calibration.ready ? w('checkReady') : w('beginGaze')}<ArrowRight size={17} aria-hidden="true"/></Button></div>
  </section>;
}
