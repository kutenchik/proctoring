import { Children, cloneElement, isValidElement, useEffect, useId, useRef, type ReactElement, type ReactNode } from 'react';
import { RefreshCw } from 'lucide-react';
import { ApiError } from './api';
import { useI18n } from './i18n';

export function ErrorMessage({error}: {error: unknown}) {
  const {t} = useI18n(); const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (error) ref.current?.focus(); }, [error]);
  if (!error) return null;
  const key = error instanceof Error ? error.message : 'request_failed';
  const known = t(key) !== key;
  return <div ref={ref} role="alert" tabIndex={-1} className="notice error">
    <strong>{t(known ? key : 'request_failed')}</strong>
    {error instanceof ApiError && (error.serverMessage || error.fields.length > 0) && <details><summary>{t('serverDetails')}</summary><p lang="en">{error.serverMessage || error.fields.join(', ')}</p></details>}
    {error instanceof ApiError && !known && <small>{error.code}</small>}
    {error instanceof ApiError && error.status === 401 && <a className="button" href="#/login">{t('login')}</a>}
  </div>;
}
export function Loading() { const {t} = useI18n(); return <p role="status" className="loading"><RefreshCw size={18} aria-hidden="true" />{t('loading')}</p>; }
export function PageTitle({title, description, action}: {title: string; description?: string; action?: ReactNode}) {
  return <div className="page-title"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action}</div>;
}
export function Field({label, children, hint}: {label: string; children: ReactNode; hint?: string}) {
  const id = useId();
  return <div className="field"><label htmlFor={id}>{label}</label>{Children.map(children, child => isValidElement(child) && ['input','select','textarea'].includes(String(child.type)) ? cloneElement(child as ReactElement<Record<string,unknown>>, {id, 'aria-describedby': hint ? `${id}-hint` : undefined}) : child)}{hint && <small id={`${id}-hint`}>{hint}</small>}</div>;
}
