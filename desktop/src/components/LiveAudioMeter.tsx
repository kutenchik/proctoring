import { Mic, MicOff } from 'lucide-react';
import { useAudio } from '../hooks/backend';
import { useT } from '../locales';
export function LiveAudioMeter({ enabled }: { enabled: boolean }) {
  const t = useT(); const audio = useAudio();
  const fresh = enabled && audio?.running && audio.frame_age_seconds !== null && audio.frame_age_seconds <= .5;
  const level = fresh ? audio.processed_level : 0;
  const threshold = audio?.check.committed_threshold ?? audio?.check.threshold;
  return <div className="live-audio-meter"><div><span>{fresh ? <Mic size={16} aria-hidden="true"/> : <MicOff size={16} aria-hidden="true"/>}{enabled ? t('audioActivity') : t('notEnabled')}</span><span className="numeric">{fresh ? level.toFixed(3) : '—'}</span></div><div className="meter" role="meter" aria-label={t('level')} aria-valuemin={0} aria-valuemax={1} aria-valuenow={level}><div className="meter-fill" style={{ width: `${Math.min(100, level / .4 * 100)}%` }}/>{threshold != null && <div className="meter-threshold" style={{ left: `${Math.min(99, threshold / .4 * 100)}%` }}/>}</div><p className="quiet-note">{enabled ? t('audioNeutral') : t('audioNotEnabled')}</p></div>;
}
