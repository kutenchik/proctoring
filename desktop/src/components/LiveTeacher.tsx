import { AdvancedStatus } from './AdvancedStatus';
import { Monitor, MessageSquare } from 'lucide-react';
import type { BackendState, LiveTeacherState } from '../../shared/contracts';
import { command } from '../hooks/backend';
import { useLiveTeacherText } from '../locales/liveTeacher';
export function ScreenConsent({state,busy}:{state:BackendState;busy:boolean}) {
  const t = useLiveTeacherText(); const live = state.live_teacher;
  if (!state.admission?.policy_applied || !live || state.workflow?.session.started) return null;
  return <div className="consent-strip"><label><input data-testid="screen-consent" type="checkbox" checked={live.consent.accepted} disabled={busy} onChange={e => void command('screen.consent',{accepted:e.target.checked})}/><span>{t('consent')}<small>{t('consentHelp')}</small>{!live.consent.features?.includes('audioEvidence')&&<small>{t('audioEnergyConsent')}</small>}{live.consent.version>=4 && live.consent.features?.map(feature=><small key={feature}>{t((feature+'Consent') as 'remoteConsent'|'livenessConsent'|'identityConsent'|'audioEvidenceConsent')}</small>)}{live.consent.accepted && !live.consent.acknowledged && <small role="status">{t(live.error==='live_transport_unavailable'?'consentTransportUnavailable':'consentPending')}</small>}</span></label></div>;
}
export function ViewingIndicator({live}:{live?:LiveTeacherState}) {
  const t = useLiveTeacherText(); if (!live || !['live','degraded','recovering'].includes(live.viewing.state)) return null;
  return <span className="badge badge-success" data-testid="teacher-viewing" role="status"><Monitor size={16} aria-hidden="true"/>{t(live.viewing.state==='recovering'?'recovering':'viewing')}</span>;
}
export function TeacherMessages({live}:{live?:LiveTeacherState}) {
  const t = useLiveTeacherText(); if (!live) return null;
  const last = live.messages.at(-1);
  return <section className="teacher-messages"><AdvancedStatus values={live.advanced}/><p className="quiet-note">{t('teacher')}: {t(live.connection)}</p>
    {live.viewing.state === 'starting' && <p className="quiet-note">{t('starting')}</p>}
    {live.viewing.state === 'unavailable' && <p className="quiet-note">{t('unavailable')}</p>}
    {last && <><div className="notice" role="status"><MessageSquare size={17} aria-hidden="true"/><p>{last.text}</p></div><details><summary>{t('history')} ({live.messages.length})</summary><ol>{live.messages.map(m => <li key={m.command_id}><time>{new Date(m.timestamp).toLocaleTimeString()}</time> — {m.text}</li>)}</ol></details></>}
  </section>;
}
export function DisplayRequirement({live}:{live?:LiveTeacherState}) {
  const t = useLiveTeacherText();
  if (!live || (live.display.ready && !live.display.approval_required)) return null;
  return <div className="notice notice-error" role="status"><Monitor size={20} aria-hidden="true"/><p>{live.display.approval_required ? t('displayRecovery') : t('oneDisplay')}</p></div>;
}
