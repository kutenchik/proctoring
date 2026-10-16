import { useEffect, useRef, useState } from 'react';
import type { EventSnapshotState } from './live-model';
import { evidenceUrl } from './review-model';
import { useI18n } from './i18n';
import { gainChain } from './audio-playback';

export function AudioEvidencePlayer({attemptId,audio}:{attemptId:string;audio?:EventSnapshotState}) {
  const {t}=useI18n(), element=useRef<HTMLAudioElement>(null);
  const graph=useRef<{context:AudioContext;chain:ReturnType<typeof gainChain>}|null>(null);
  const [gain,setGain]=useState(1),[failed,setFailed]=useState(false);
  const item=audio?.item_id;
  useEffect(()=>{const media=element.current;return ()=>{media?.pause();graph.current?.chain.close();void graph.current?.context.close();graph.current=null;};},[item]);
  async function prepare(value=gain) {
    try {
      if (!element.current) return;
      if (!graph.current) {
        const context=new AudioContext();
        graph.current={context,chain:gainChain(context,context.createMediaElementSource(element.current))};
      }
      graph.current.chain.set(value);
      await graph.current.context.resume();
    } catch {setFailed(true);}
  }
  if (!audio || audio.status==='not_applicable' || audio.status==='disabled') return null;
  return <section className="audio-evidence" aria-label={t('audioEvidence')}>
    {audio.status==='available'&&item ? <>
      <audio ref={element} controls preload="metadata" src={evidenceUrl(attemptId,item)} aria-label={t('audioEvidence')}
        onPlay={()=>{setFailed(false);void prepare();}} onError={()=>setFailed(true)}/>
      <label>{t('audioGain')} <output>{gain.toFixed(1)}×</output>
        <input type="range" min="1" max="4" step="0.25" value={gain} onChange={e=>{const value=Number(e.target.value);setGain(value);void prepare(value);}}/>
      </label>
      <button type="button" onClick={()=>{setGain(1);void prepare(1);}}>{t('audioReset')}</button>
      {audio.reason&&<small>{t('audioPartial')}</small>}
      {failed&&<p role="alert">{t('audioFailed')} <button type="button" onClick={()=>{setFailed(false);element.current?.load();}}>{t('retry')}</button></p>}
    </> : <p role="status">{t(audio.status==='pending'?'audioPending':'audioUnavailable')}</p>}
    <small>{t('audioCaution')}</small>
  </section>;
}
