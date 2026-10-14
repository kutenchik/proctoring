import { Check, Mic, MicOff, Volume2 } from 'lucide-react';
import { command, useAudio } from '../hooks/backend';
import { useT } from '../locales';
import { Button, Badge } from './ui';
export function AudioCard({ fixtureState, enabled, busy, connected = true, examEnabled = true, onFixtureNext }: { fixtureState?: 'idle' | 'ambient' | 'speak' | 'ready'; enabled: boolean; busy: boolean; connected?: boolean; examEnabled?: boolean; onFixtureNext?: () => void }) {
  const t = useT(); const audio = useAudio(); const fixture = fixtureState !== undefined;
  const state = fixtureState ?? audio?.check.state ?? 'idle';
  const running = connected && (fixture ? state !== 'idle' : !!audio?.running);
  const fresh = fixture || (audio?.frame_age_seconds !== null && audio?.frame_age_seconds !== undefined && audio.frame_age_seconds <= 0.5);
  const level = running && fresh ? fixture ? state === 'ambient' ? 0.018 : state === 'speak' ? 0.145 : 0.025 : audio?.processed_level ?? 0 : 0;
  const threshold = fixture ? .08 : audio?.check.committed_threshold ?? audio?.check.threshold;
  const progress = fixture ? state === 'ambient' ? .45 : state === 'speak' ? .62 : 1 : audio?.check.progress ?? 0;
  const checking = state === 'ambient' || state === 'speak';
  const ready = state === 'ready'; const failure = !!audio?.error || ['failed', 'unavailable', 'no_signal', 'noisy', 'clipping'].includes(state);
  const rejection = audio?.check.rejection_code;
  const failureText = state === 'clipping' ? t('micClipping') : state === 'noisy' ? t('micNoise') : rejection === 'insufficient_contrast' || rejection === 'processed_contrast' ? t('micContrast') : rejection === 'insufficient_activity' ? t('micNoActivity') : rejection === 'steady_activity' ? t('micSteady') : t('micUnavailable');
  const title = state === 'ambient' ? t('quiet') : state === 'speak' ? t('speak') : ready ? t('micReady') : failure ? t('micFailed') : t('micIdle');
  return <section className="audio-card" aria-labelledby="audio-title"><div className="section-heading"><div className={`icon-tile ${ready ? 'icon-success' : ''}`}>{ready ? <Check aria-hidden="true" size={20}/> : <Mic aria-hidden="true" size={20}/>}</div><div><h3 id="audio-title">{title}</h3><p>{checking ? state === 'speak' ? t('speakHelp') : t('audioHelp') : ready && (fixture || audio?.check.gain_limited) ? t('micUsable') : t('noRecording')}</p></div>{fixture && <Badge>{t('fixture')}</Badge>}</div>
    <div className="meter-header"><label id="level-label">{t('level')}</label><span className="numeric">{running && fresh ? level.toFixed(3) : '—'}</span></div>
    <div className="meter" role="meter" aria-labelledby="level-label" aria-valuemin={0} aria-valuemax={1} aria-valuenow={level}><div className={`meter-fill ${threshold && level >= threshold ? 'meter-high' : ''}`} style={{ width: `${Math.min(100, level / .4 * 100)}%` }}/>{threshold != null && threshold > 0 && <div className="meter-threshold" style={{ left: `${Math.min(99, threshold / .4 * 100)}%` }}/>}</div>
    <div className="meter-caption"><span>0</span><span>{t('threshold')}: <b className="numeric">{threshold?.toFixed(4) ?? '—'}</b></span><span>0.40+</span></div>
    {checking && <div className="audio-progress"><progress aria-label={t('progress')} value={progress} max={1}/><span className="numeric">{Math.round(progress * 100)}%</span></div>}
    {failure && !fixture && <div role="status" className="inline-error"><MicOff aria-hidden="true" size={16}/><div>{failureText}<details><summary>{t('technicalError')}</summary><small>{audio?.error ?? audio?.check.reason}</small></details></div></div>}
    <div className="actions wrap"><Button variant="secondary" size="small" disabled={!enabled || busy || checking} onClick={() => fixture ? onFixtureNext?.() : void command('audio.calibrate')}><Volume2 aria-hidden="true" size={16}/>{ready || failure ? t('retry') : t('calibrateMic')}</Button>{!fixture && <Button size="small" variant="ghost" disabled={!enabled || busy} onClick={() => void command(running ? 'audio.stop' : 'audio.start')}>{running ? t('stopMic') : t('testMic')}</Button>}{fixture && checking && <Button variant="ghost" size="small" onClick={onFixtureNext}>{t('next')}</Button>}</div>
    {!examEnabled && <p className="quiet-note">{t('audioNotEnabled')}</p>}
    {ready && <details className="details"><summary>{t('diagnostics')}</summary><div className="technical">{t('gain')}: {fixture ? '3.2' : audio?.check.gain?.toFixed(2) ?? '—'} · {t('threshold')}: {threshold?.toFixed(5) ?? '—'}{!fixture && <><br/>{audio?.check.threshold_source}<br/>{audio?.check.reason}</>}</div></details>}
  </section>;
}
