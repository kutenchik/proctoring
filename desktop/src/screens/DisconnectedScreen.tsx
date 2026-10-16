import { Unplug } from 'lucide-react';
import { Button } from '../components/ui';
import { useT } from '../locales';
import { terminalConnection } from '../../shared/connection';
export function DisconnectedScreen({ retry, busy, error, reason }: { retry: () => void; busy: boolean; error?: string | null; reason?: string }) {
  const t = useT(), terminal = terminalConnection(reason);
  return <section className="panel disconnected-panel"><div className="connection-icon"><Unplug aria-hidden="true" size={34}/></div><p className="eyebrow">{t('disconnected')}</p><h1>{t('connectionTitle')}</h1><p>{t('connectionHelp')}</p>
    {!terminal && <Button disabled={busy} onClick={retry}>{t('reconnect')}</Button>}
    <p className="quiet-note">{t(terminal ? 'backendEndedHelp' : 'reconnectHelp')}</p>
    {error && <details className="details"><summary>{t('technicalError')}</summary><p className="technical">{error}</p></details>}</section>;
}
