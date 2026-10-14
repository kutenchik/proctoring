import type { BackendState } from '../../shared/contracts';
import { Button } from './ui';
import { command } from '../hooks/backend';
import { useSyncText } from '../locales/synchronization';
import { clockText } from '../lib/presentation';
export function Synchronization({state,busy}: {state:BackendState;busy:boolean}) {
  const t=useSyncText();const sync=state.synchronization;
  if(!sync) return null;
  return <section className="panel" aria-label={t('title')}><h2>{t('title')}</h2><p role="status">{t(sync.status)}</p>
    {sync.error && <p className="quiet-note">{t('detail')}: <code>{sync.error}</code></p>}
    {sync.recovery_required && <div className="notice"><strong>{t('recovery')}</strong><p>{t('recoveryHelp')}</p><p>{t('remaining')}: {clockText(sync.remaining_seconds ?? 0)}</p><Button variant="secondary" disabled={busy||!!state.admission?.busy} onClick={()=>void command('connected.refresh')}>{t('refresh')}</Button></div>}
    {sync.fully_synchronized ? <p>{t('cleanup')}</p> : state.workflow?.session.ended && <><div className="actions wrap"><Button variant="secondary" disabled={busy} onClick={()=>void command('sync.retry')}>{t('retry')}</Button><Button disabled={busy||!sync.can_background} onClick={()=>void command('sync.background')}>{t('background')}</Button><Button variant="secondary" disabled={busy} onClick={()=>void command('sync.exit')}>{t('exit')}</Button></div><p className="quiet-note">{t('exitHelp')}</p></>}
  </section>;
}
