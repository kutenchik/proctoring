import { useState } from 'react';
import type { EventSnapshotState } from './live-model';
import { evidenceUrl } from './review-model';
import { useI18n } from './i18n';

export function EventSnapshot({attemptId,snapshot}:{attemptId:string;snapshot?:EventSnapshotState}) {
  const {t}=useI18n();
  const [open,setOpen]=useState(false),[failed,setFailed]=useState(false);
  if (!snapshot || snapshot.status==='not_applicable') return null;
  const available=snapshot.status==='available'&&snapshot.item_id;
  const reason=snapshot.reason==='capture_unavailable'?'snapshotCaptureFailed':'snapshotProductionFailed';
  return <div className="event-snapshot">
    <div className="event-snapshot-slot">
      {available&&!failed ? <button type="button" aria-expanded={open} onClick={()=>setOpen(value=>!value)}>
        <img loading="lazy" width={160} height={100} src={evidenceUrl(attemptId,snapshot.item_id!)} alt={t('inspectSnapshot')} onError={()=>setFailed(true)}/>
        <span>{t(open?'snapshotClose':'inspectSnapshot')}</span>
      </button> : <p>{t(available&&failed?'imageUnavailable':snapshot.status==='disabled'?'snapshotDisabled':snapshot.status==='unavailable'?'snapshotUnavailable':'snapshotPending')}
        {snapshot.status==='unavailable'&&<small>{t(reason)}</small>}
        {available&&failed&&<button type="button" onClick={()=>setFailed(false)}>{t('retry')}</button>}
      </p>}
    </div>
    {available&&open&&!failed&&<figure className="snapshot-inspection"><figcaption>{t('historicalImage')}</figcaption><img src={evidenceUrl(attemptId,snapshot.item_id!)} alt={t('historicalImage')} onError={()=>setFailed(true)}/></figure>}
  </div>;
}
