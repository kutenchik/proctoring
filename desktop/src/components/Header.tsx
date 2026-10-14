import { CircleCheck, FlaskConical, ShieldOff, Sprout, Unplug } from 'lucide-react';
import type { Locale, ConnectionStatus } from '../../shared/contracts';
import { Badge } from './ui';
import { useT } from '../locales';
import type { TextKey } from '../locales';
import { useW } from '../locales/workflow';
import { ViewingIndicator } from './LiveTeacher';
import type { LiveTeacherState } from '../../shared/contracts';
import { ProtectionStatus } from './ProtectionStatus';
import type { ProtectionState } from '../../shared/contracts';
export function Header({ locale, setLocale, fixture, connection, stage, workflow = false, languageLocked = false, protection, liveTeacher }: { locale: Locale; setLocale: (v: Locale) => void; fixture: boolean; connection: ConnectionStatus; stage: TextKey; workflow?: boolean; languageLocked?: boolean; protection?: ProtectionState; liveTeacher?: LiveTeacherState }) {
  const t = useT();
  const w = useW();
  return <header className={`app-header${workflow ? ' app-header-workflow' : ''}`}><div className="brand"><div className="brand-symbol"><Sprout aria-hidden="true" size={22}/></div><div><span className="brand-name">Local Proctoring</span><span className="brand-stage">{t(stage)}</span></div></div><div className="header-tools"><ViewingIndicator live={liveTeacher}/><Badge tone={!fixture && connection.state === 'connected' ? 'success' : 'neutral'}>{fixture ? <FlaskConical aria-hidden="true" size={14}/> : connection.state === 'connected' ? <CircleCheck aria-hidden="true" size={14}/> : <Unplug aria-hidden="true" size={14}/>}<span>{fixture ? t('fixture') : connection.state === 'connected' ? t('connected') : connection.state === 'connecting' ? t('connecting') : t('disconnected')}</span></Badge><>{protection ? <ProtectionStatus protection={protection} connected={connection.state === 'connected'}/> : <span className="protection-status"><ShieldOff aria-hidden="true" size={15}/>{workflow ? w('development') : t('protectionOff')}</span>}</><label className="sr-only" htmlFor="language">{t('language')}</label><select id="language" disabled={languageLocked} className="language-select" value={locale} onChange={e => setLocale(e.target.value as Locale)}><option value="en">EN</option><option value="ru">RU</option><option value="kk">ҚАЗ</option></select></div></header>;
}
export function Stepper({ current }: { current: number }) { const t = useT(); return <nav aria-label={t('progress')} className="stepper">{(['stepDevices', 'stepGaze', 'stepReady'] as const).map((key, i) => <div key={key} className={`step ${i === current ? 'step-current' : ''} ${i < current ? 'step-complete' : ''}`} aria-current={i === current ? 'step' : undefined}><span className="step-number">{i < current ? <CircleCheck aria-hidden="true" size={16}/> : `0${i + 1}`}</span><span>{t(key)}</span></div>)}</nav>; }
