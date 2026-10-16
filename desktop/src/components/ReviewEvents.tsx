import { useRef } from 'react';
import { TriangleAlert } from 'lucide-react';
import type { ReviewEvent } from '../../shared/contracts';
import { useT } from '../locales';
import { useW } from '../locales/workflow';
import { localTime } from '../lib/presentation';
export function useEventLabel() {
  const t = useT(); const w = useW();
  return (record: ReviewEvent) => {
    const kind = record.event_type;
    if (kind === 'remote_access_detected') return w('remoteReview');
    if (kind === 'presentation_attack_suspected') return w('livenessReview');
    if (kind === 'identity_mismatch_suspected') return w('advancedIdentityReview');
    if (kind === 'phone_raised') return t('phoneRaised');
    if (kind === 'phone_visible') return w('phone');
    if (kind === 'second_person') return w('secondPerson');
    if (kind === 'face_absent') return w('faceAbsent');
    if (kind.startsWith('gaze_') || kind === 'HEAD_DOWN') return w('gazeAway');
    if (kind === 'VOICE_DETECTED') return t('audioActivity');
    if (kind.includes('IDENTITY') || kind.toUpperCase().includes('IMPERSONATION')) return w('identityReview');
    if (kind.includes('CLIPBOARD')) return w('clipboardReview');
    if (kind.includes('EARPHONE')) return w('earphoneReview');
    return typeof record.label === 'string' ? record.label : kind;
  };
}
export function eventTimestamp(record: ReviewEvent) { return typeof record.activated_timestamp === 'string' ? record.activated_timestamp : typeof record.start_timestamp === 'string' ? record.start_timestamp : record.timestamp; }
export function ReviewEvents({ records, healthy = true }: { records: ReviewEvent[]; healthy?: boolean }) {
  const t = useT(); const label = useEventLabel();
  const selected = useRef<string | null>(null);
  const ongoing = records.filter(record => record.state === 'active' || record.state === 'clearing');
  const active = healthy ? ongoing.find(record => record.event_id === selected.current) ?? ongoing[0] : undefined;
  selected.current = active?.event_id ?? null;
  const recent = [...records].reverse().slice(0, 5);
  return <><div className="review-warning-slot">{active && <div className="notice notice-warning review-warning" role="status" data-active-event-id={active.event_id}><TriangleAlert size={19} aria-hidden="true"/><div><strong>{label(active)}</strong><p>{t('warningHelp')}</p></div></div>}</div><div className="recent-events"><h3>{t('recentEvents')}</h3>{recent.length ? recent.map(record => <div className="event-item" key={record.event_id} data-event-id={record.event_id}><span className="event-dot"/><div><strong>{label(record)}</strong><small className="numeric">{localTime(eventTimestamp(record))} · {t('review')}</small></div></div>) : <div className="quiet-note"><strong>{t('noEvents')}</strong><p>{t('noEventsHint')}</p></div>}</div></>;
}
