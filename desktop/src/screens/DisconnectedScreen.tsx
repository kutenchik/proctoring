import { Unplug } from 'lucide-react';
import { Button } from '../components/ui';
import { useT } from '../locales';
export function DisconnectedScreen({ retry, busy, error }: { retry: () => void; busy: boolean; error?: string | null }) { const t = useT(); return <section className="panel disconnected-panel"><div className="connection-icon"><Unplug aria-hidden="true" size={34}/></div><p className="eyebrow">{t('disconnected')}</p><h1>{t('connectionTitle')}</h1><p>{t('connectionHelp')}</p><Button disabled={busy} onClick={retry}>{t('reconnect')}</Button><p className="quiet-note">{t('reconnectHelp')}</p>{error && <details className="details"><summary>{t('technicalError')}</summary><p className="technical">{error}</p></details>}</section>; }
