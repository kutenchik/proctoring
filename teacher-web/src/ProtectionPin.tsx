import {useEffect,useState,type FormEvent} from 'react';
import {api} from './api';
import {useI18n} from './i18n';
import {Field,PageTitle,ErrorMessage} from './ui';
type Status={configured:boolean;revision:number;updated_at:string|null};
const words={
 en:{title:'Protection PIN',intro:'Security settings for your exams. PIN changes apply to future authorization requests. Emergency release remains available offline.',pin:'New PIN (6–12 digits)',confirm:'Confirm new PIN',save:'Save PIN',saved:'PIN updated',updated:'Last updated',none:'No PIN configured',mismatch:'PINs must match.',error:'Unable to save. Refresh and try again.'},
 ru:{title:'ПИН-код защиты',intro:'Безопасность ваших экзаменов. Изменения действуют для новых запросов авторизации. Аварийное освобождение доступно без сети.',pin:'Новый ПИН-код (6–12 цифр)',confirm:'Повторите ПИН-код',save:'Сохранить',saved:'ПИН-код обновлён',updated:'Последнее обновление',none:'ПИН-код не задан',mismatch:'ПИН-коды должны совпадать.',error:'Не удалось сохранить. Обновите страницу и повторите.'},
 kk:{title:'Қорғау PIN-коды',intro:'Емтихандарыңыздың қауіпсіздігі. Өзгерістер жаңа рұқсат сұрауларына қолданылады. Төтенше босату желісіз қолжетімді.',pin:'Жаңа PIN-код (6–12 сан)',confirm:'PIN-кодты растаңыз',save:'Сақтау',saved:'PIN-код жаңартылды',updated:'Соңғы жаңарту',none:'PIN-код орнатылмаған',mismatch:'PIN-кодтар сәйкес болуы керек.',error:'Сақтау мүмкін болмады. Бетті жаңартып, қайталаңыз.'}
};
export function ProtectionPin(){
 const {language}=useI18n();const t=words[language];const [status,setStatus]=useState<Status|null>(null);const [error,setError]=useState<unknown>(null);const [busy,setBusy]=useState(false);const [saved,setSaved]=useState(false);
 useEffect(()=>{api.request<Status>('/settings/protection-pin').then(setStatus).catch(setError);},[]);
 async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();if(!status||busy)return;const form=e.currentTarget;const data=new FormData(form);if(data.get('pin')!==data.get('confirm')){setError(new Error(t.mismatch));return;}setBusy(true);setError(null);setSaved(false);try{setStatus(await api.request<Status>('/settings/protection-pin','POST',{pin:data.get('pin'),confirm_pin:data.get('confirm'),revision:status.revision}));form.reset();setSaved(true);}catch{setError(new Error(t.error));}finally{setBusy(false);}}
 return <><PageTitle title={t.title} description={t.intro}/><section className="panel"><p>{status?.updated_at?`${t.updated}: ${new Date(status.updated_at).toLocaleString(language)}`:t.none}</p><ErrorMessage error={error}/>{saved&&<p role="status" className="notice success">{t.saved}</p>}<form onSubmit={submit}><Field label={t.pin}><input name="pin" type="password" inputMode="numeric" autoComplete="new-password" pattern="[0-9]{6,12}" minLength={6} maxLength={12} required/></Field><Field label={t.confirm}><input name="confirm" type="password" inputMode="numeric" autoComplete="new-password" pattern="[0-9]{6,12}" minLength={6} maxLength={12} required/></Field><button className="primary" disabled={busy||!status}>{t.save}</button></form></section></>;
}
