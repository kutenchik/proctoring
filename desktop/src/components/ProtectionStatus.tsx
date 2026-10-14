import { ShieldAlert, ShieldCheck, ShieldOff } from 'lucide-react';
import type { ProtectionState } from '../../shared/contracts';
import { useProtectionText, type ProtectionText } from '../locales/protection';

export function ProtectionStatus({ protection, connected = true, detail = false }: {
  protection?: ProtectionState; connected?: boolean; detail?: boolean;
}) {
  const t = useProtectionText();
  const requested = !!protection?.requested;
  const state = !connected && requested ? 'unknown' : protection?.state ?? 'disabled';
  // A request/fullscreen/arming acknowledgement is never displayed as ACTIVE.
  const actual = state === 'active' && protection?.enabled === true;
  const label = state === 'active' && !actual ? 'unknown' : state;
  const Icon = actual ? ShieldCheck : requested ? ShieldAlert : ShieldOff;
  const supported = new Set(['awaiting_audit', 'host_binding_required', 'control_progress_required', 'desktop_in_use', 'geometry_pending', 'audit_incompatible', 'native_fault', 'foreground_containment_failed', 'helper_identity_unavailable']);
  const reason = protection?.reason ?? '';
  const help: ProtectionText = reason === 'awaiting_audit' ? 'awaiting_audit_help'
    : supported.has(reason) ? reason as ProtectionText
    : state === 'awaiting_audit' ? 'awaiting_audit_help' : actual ? 'active_help' : state === 'fault' ? 'native_fault' : 'preparing_help';
  return <div className={detail ? 'protection-detail' : 'protection-status'} data-protection-state={label}>
    <span className="protection-label" role={detail ? undefined : 'status'} aria-live={detail ? undefined : 'polite'}><Icon aria-hidden="true" size={16}/><span>{t(label as ProtectionText)}</span></span>
    {detail && requested && <><p className="quiet-note">{t(help)}</p>{protection?.audit && <details className="technical"><summary>{t('diagnostics')}</summary><p>{protection.audit.message}</p><code>{protection.audit.path}</code></details>}</>}
  </div>;
}
