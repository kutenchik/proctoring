import {useEffect, useRef, useState, type FormEvent} from 'react';
import {ArrowLeft, Copy, LockKeyhole, Plus, Save, Settings2} from 'lucide-react';
import {api, ApiError} from './api';
import {useI18n} from './i18n';
import {ErrorMessage, Loading, PageTitle} from './ui';
import {labelFor, PolicyFields, useText, type Catalog, type Policy, type Profile} from './Configuration';

const phrases = {
 defaultName:['Default','По умолчанию','Әдепкі'],
 intro:['Save monitoring settings once, then select them when creating an exam.','Сохраните настройки мониторинга и выбирайте их при создании экзамена.','Бақылау параметрлерін сақтап, емтихан жасағанда таңдаңыз.'],
 new:['New configuration','Новая конфигурация','Жаңа конфигурация'],
 name:['Configuration name','Название конфигурации','Конфигурация атауы'],
 back:['Back to configurations','К конфигурациям','Конфигурацияларға оралу'],
 manage:['Manage configurations','Управление конфигурациями','Конфигурацияларды басқару'],
 select:['Configuration','Конфигурация','Конфигурация'],
 custom:['Custom','Пользовательская','Жеке'],
 builtin:['Built-in · Read only','Встроенная · Только чтение','Кіріктірілген · Тек оқу'],
 edit:['Edit','Изменить','Өзгерту'],
 view:['View settings','Посмотреть настройки','Параметрлерді көру'],
 save:['Save changes','Сохранить изменения','Өзгерістерді сақтау'],
 saveAs:['Save as new configuration','Сохранить как новую конфигурацию','Жаңа конфигурация ретінде сақтау'],
 saved:['Configuration saved','Конфигурация сохранена','Конфигурация сақталды'],
 saving:['Saving…','Сохранение…','Сақталуда…'],
 dirty:['Unsaved changes','Есть несохранённые изменения','Сақталмаған өзгерістер'],
 leave:['Discard unsaved configuration changes?','Отменить несохранённые изменения конфигурации?','Конфигурацияның сақталмаған өзгерістерін алып тастау керек пе?'],
 remove:['Delete configuration','Удалить конфигурацию','Конфигурацияны жою'],
 confirmDelete:['Delete this configuration? Existing exams will keep their settings.','Удалить конфигурацию? Настройки существующих экзаменов сохранятся.','Конфигурация жойылсын ба? Бұрынғы емтихан параметрлері сақталады.'],
 empty:['No custom configurations yet','Пользовательских конфигураций пока нет','Әзірге жеке конфигурациялар жоқ'],
 emptyHint:['Start from Default or duplicate a saved configuration.','Начните со стандартной или создайте копию сохранённой конфигурации.','Әдепкіден бастаңыз немесе сақталған конфигурацияны көшіріңіз.'],
 defaultHint:['Default cannot be changed. Duplicate it to make your own configuration.','Стандартную конфигурацию изменить нельзя. Создайте копию для своих настроек.','Әдепкіні өзгерту мүмкін емес. Өз параметрлеріңіз үшін көшірме жасаңыз.'],
 snapshot:['A saved copy of these settings will be frozen into the exam.','Сохранённая копия этих настроек будет закреплена за экзаменом.','Осы параметрлердің сақталған көшірмесі емтиханға бекітіледі.'],
 more:['More actions','Другие действия','Басқа әрекеттер'],
 copy:['Copy','Копия','Көшірме'],
 cancel:['Cancel','Отмена','Бас тарту'],
 invalid:['Check the highlighted fields and enter a configuration name.','Проверьте выделенные поля и введите название конфигурации.','Белгіленген өрістерді тексеріп, конфигурация атауын енгізіңіз.'],
 conflict:['This configuration changed elsewhere. Your draft is preserved; reload to review the saved version or save a new copy.','Конфигурация изменена в другом окне. Черновик сохранён: обновите страницу для проверки или сохраните новую копию.','Конфигурация басқа жерде өзгертілген. Жоба сақталды: бетті жаңартыңыз немесе жаңа көшірме сақтаңыз.'],
 failed:['Could not save the configuration. Check your connection and try again.','Не удалось сохранить конфигурацию. Проверьте соединение и повторите.','Конфигурация сақталмады. Байланысты тексеріп, қайталаңыз.'],
 renameHint:['Edit the name here, then save changes.','Измените название и сохраните изменения.','Атауын өзгертіп, өзгерістерді сақтаңыз.'],
};
function useWords(){const {language}=useI18n();return (key:keyof typeof phrases)=>phrases[key][language==='ru'?1:language==='kk'?2:0];}

// One API adapter for overview, editor and selector; policy documents stay canonical.
const profilesApi={
 list:()=>api.request<{items:Profile[]}>('/configuration/profiles'),
 get:(id:string)=>api.request<Profile>(`/configuration/profiles/${encodeURIComponent(id)}`),
 save:(name:string,policy:Policy,existing?:Profile)=>api.request<Profile>(existing?`/configuration/profiles/${encodeURIComponent(existing.id)}`:'/configuration/profiles',existing?'PUT':'POST',{name:name.trim(),policy,...existing?{version:existing.version}:{}}),
 remove:(id:string)=>api.request(`/configuration/profiles/${encodeURIComponent(id)}`,'DELETE'),
};
const summaryKeys=['events.second_person.enabled','audio.enabled','events.phone_visible.enabled','snapshots_enabled'];
function Summary({catalog,policy}:{catalog:Catalog;policy:Policy}){
 const {language}=useI18n(),t=useText();
 return <dl className="configuration-summary">{summaryKeys.map(key=>{const field=catalog.fields.find(f=>f.key===key);return field&&<div key={key}><dt>{labelFor(field.labels,language)}</dt><dd className={policy.values[key]?'enabled':''}>{t(policy.values[key]?'on':'off')}</dd></div>;})}</dl>;
}

export function ConfigurationPicker({onChange}:{onChange:(policy:Policy)=>void}){
 const t=useText(),w=useWords();const [items,setItems]=useState<Profile[]>([]),[catalog,setCatalog]=useState<Catalog|null>(null),[selected,setSelected]=useState('default'),[error,setError]=useState<unknown>(null);
 useEffect(()=>{let alive=true;Promise.all([profilesApi.list(),api.request<Catalog>('/configuration/catalog')]).then(([p,c])=>{if(alive){setItems(p.items);setCatalog(c);onChange(p.items.find(p=>p.id==='default')!.policy);}}).catch(setError);return()=>{alive=false;};},[]);
 const profile=items.find(p=>p.id===selected);
 return <section className="configuration-picker"><div className="configuration-picker-heading"><h2>{t('title')}</h2><a href="#/configurations">{w('manage')}</a></div><ErrorMessage error={error}/>{catalog&&profile?<><label>{w('select')}<select value={selected} onChange={e=>{const p=items.find(p=>p.id===e.target.value)!;setSelected(p.id);onChange(p.policy);}}>{items.map(p=><option value={p.id} key={p.id}>{p.builtin?w('defaultName'):p.name}</option>)}</select></label><Summary catalog={catalog} policy={profile.policy}/><p className="small muted">{w('snapshot')}</p></>:!error&&<Loading/>}</section>;
}

export function ConfigurationsPage(){
 const {t:ui}=useI18n(),t=useText(),w=useWords();const [items,setItems]=useState<Profile[]|null>(null),[catalog,setCatalog]=useState<Catalog|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
 useEffect(()=>{let alive=true;Promise.all([profilesApi.list(),api.request<Catalog>('/configuration/catalog')]).then(([p,c])=>{if(alive){setItems(p.items);setCatalog(c);}}).catch(setError);return()=>{alive=false;};},[]);
 async function remove(p:Profile){if(busy||!window.confirm(w('confirmDelete')))return;setBusy(true);try{await profilesApi.remove(p.id);setItems(items!.filter(v=>v.id!==p.id));}catch(e){setError(e);}finally{setBusy(false);}}
 return <><PageTitle title={ui('configurations')} description={w('intro')} action={<a href="#/configuration/new" className="button primary"><Plus size={18} aria-hidden="true"/>{w('new')}</a>}/><ErrorMessage error={error}/>{!items&&!error&&<Loading/>}{items&&catalog&&<><div className="configuration-grid">{items.map(p=><article key={p.id} className="panel configuration-card"><div className="card-top"><span className="badge">{p.builtin?<><LockKeyhole size={13} aria-hidden="true"/>{w('builtin')}</>:w('custom')}</span><Settings2 size={18} aria-hidden="true"/></div><h2><a href={`#/configuration/${p.id}`}>{p.builtin?w('defaultName'):p.name}</a></h2><Summary catalog={catalog} policy={p.policy}/><div className="configuration-card-actions"><a className="button" href={`#/configuration/${p.id}`}>{w(p.builtin?'view':'edit')}</a><a className="button quiet" href={`#/configuration/new?from=${p.id}`}><Copy size={16} aria-hidden="true"/>{t('duplicate')}</a>{!p.builtin&&<details className="configuration-more"><summary aria-label={w('more')+' — '+p.name}>•••</summary><button disabled={busy} onClick={()=>void remove(p)}>{w('remove')}</button></details>}</div></article>)}</div>{!items.some(p=>!p.builtin)&&<div className="empty"><h2>{w('empty')}</h2><p>{w('emptyHint')}</p><a className="text-link" href="#/configuration/new">{w('new')}</a></div>}</>}</>;
}

function same(a:Policy,b:Policy){return a.schema_version===b.schema_version&&Object.keys(a.values).length===Object.keys(b.values).length&&Object.entries(a.values).every(([k,v])=>v===b.values[k]);}

export function ConfigurationPage({id,source}:{id:string;source?:string}){
 const t=useText(),w=useWords();const [catalog,setCatalog]=useState<Catalog|null>(null),[saved,setSaved]=useState<Profile|null>(null),[draft,setDraft]=useState<Policy|null>(null),[name,setName]=useState(''),[error,setError]=useState<unknown>(null),[message,setMessage]=useState<keyof typeof phrases|''>(location.hash.endsWith('?saved=1')?'saved':''),[busy,setBusy]=useState(false),[copyName,setCopyName]=useState<string|null>(null);
 const fresh=id==='new',immutable=!fresh&&saved?.builtin;const dirty=!!saved&&!!draft&&(fresh?!!name||!same(draft,saved.policy):!immutable&&(name!==saved.name||!same(draft,saved.policy)));
 const allowLeave=useRef(false),dirtyRef=useRef(false),dialog=useRef<HTMLDialogElement>(null),form=useRef<HTMLFormElement>(null);dirtyRef.current=dirty;
 useEffect(()=>{let alive=true;Promise.all([api.request<Catalog>('/configuration/catalog'),profilesApi.get(fresh?source||'default':id)]).then(([c,p])=>{if(alive){setCatalog(c);setSaved(p);setDraft(p.policy);setName(fresh?(source?(p.builtin?w('defaultName'):p.name)+' — '+w('copy'):''):p.name);}}).catch(setError);return()=>{alive=false;};},[id,source]);
 useEffect(()=>{const leave=(event:Event)=>{if(!allowLeave.current&&dirtyRef.current&&!window.confirm(w('leave')))event.preventDefault();};const unload=(event:BeforeUnloadEvent)=>{if(dirtyRef.current){event.preventDefault();event.returnValue='';}};window.addEventListener('configuration-leave',leave);window.addEventListener('beforeunload',unload);return()=>{window.removeEventListener('configuration-leave',leave);window.removeEventListener('beforeunload',unload);};},[w('leave')]);
 useEffect(()=>{if(copyName===null)return;const previous=document.activeElement;dialog.current?.showModal();return()=>{if(previous instanceof HTMLElement)previous.focus();};},[copyName!==null]);
 function invalidPolicy(){return !catalog||!draft||catalog.fields.some(f=>f.type==='boolean'?typeof draft.values[f.key]!=='boolean':f.type==='choice'?!f.choices?.includes(String(draft.values[f.key])):typeof draft.values[f.key]!=='number'||!Number.isFinite(draft.values[f.key])||Number(draft.values[f.key])<f.minimum||Number(draft.values[f.key])>f.maximum||(f.key.endsWith('_confirmations')&&!Number.isInteger(draft.values[f.key])));}
 async function save(asNew=false){if(!draft||!saved||busy||(immutable&&!asNew))return;if(invalidPolicy()||!(asNew?copyName:name)?.trim()){setMessage('invalid');form.current?.querySelector<HTMLInputElement>('[aria-invalid="true"]')?.focus();return;}setBusy(true);setError(null);setMessage('');try{const p=await profilesApi.save(asNew?copyName!:name,draft,fresh||asNew?undefined:saved);allowLeave.current=fresh||asNew;dirtyRef.current=false;setSaved(p);setDraft(p.policy);setName(p.name);setCopyName(null);setMessage('saved');if(fresh||asNew)location.hash='/configuration/'+p.id+'?saved=1';}catch(e){setMessage(e instanceof ApiError&&e.code==='profile_conflict'?'conflict':'failed');}finally{setBusy(false);}}
 async function remove(){if(!saved||immutable||fresh||!window.confirm(w('confirmDelete')))return;setBusy(true);try{await profilesApi.remove(saved.id);allowLeave.current=true;dirtyRef.current=false;location.hash='/configurations';}catch(e){setError(e);setBusy(false);}}
 function submit(e:FormEvent){e.preventDefault();void save();}
 return <><a className="text-link" href="#/configurations"><ArrowLeft size={16} aria-hidden="true"/>{w('back')}</a><ErrorMessage error={error}/>{!draft||!catalog||!saved?!error&&<Loading/>:<div className="configuration-workspace"><PageTitle title={fresh?w('new'):saved.builtin?w('defaultName'):saved.name} description={immutable?w('defaultHint'):w('intro')} action={immutable?<a className="button primary" href="#/configuration/new?from=default"><Copy size={18} aria-hidden="true"/>{t('duplicate')}</a>:<button className="primary" form="configuration-form" disabled={busy||(!dirty&&!fresh)}><Save size={18} aria-hidden="true"/>{w(busy?'saving':'save')}</button>}/><div className="configuration-status"><span className="badge">{w(immutable?'builtin':'custom')}</span>{dirty&&<span role="status" className="small">{w('dirty')}</span>}</div>{message&&<p className="notice" role="status">{w(message)}</p>}<form id="configuration-form" noValidate ref={form} onSubmit={submit} className="panel configuration-editor">{!immutable&&<div className="configuration-name"><label>{w('name')}<input required aria-invalid={message==='invalid'&&!name.trim()} maxLength={120} value={name} onChange={e=>{setName(e.target.value);setMessage('');}}/></label><p className="small muted">{w('renameHint')}</p></div>}<PolicyFields catalog={catalog} policy={draft} onChange={p=>{setDraft(p);setMessage('');}} locked={!!immutable}/>{!immutable&&<div className="configuration-editor-footer"><button type="button" className="quiet" onClick={()=>{setDraft(catalog.default);setMessage('');}}>{t('defaults')}</button><button type="button" onClick={()=>{if(invalidPolicy()){setMessage('invalid');return;}setMessage('');setCopyName(name+' — '+w('copy'));}}>{w('saveAs')}</button>{!fresh&&<a className="button quiet" href={`#/configuration/new?from=${id}`}><Copy size={16} aria-hidden="true"/>{t('duplicate')}</a>}{!fresh&&<button type="button" className="quiet" disabled={busy} onClick={()=>void remove()}>{w('remove')}</button>}</div>}</form></div>}{copyName!==null&&<dialog ref={dialog} aria-label={w('saveAs')} className="panel configuration-dialog" onCancel={()=>setCopyName(null)}><form onSubmit={e=>{e.preventDefault();void save(true);}}><h2>{w('saveAs')}</h2><label>{w('name')}<input autoFocus required maxLength={120} value={copyName||''} onChange={e=>setCopyName(e.target.value)}/></label>{message&&<p role="status">{w(message)}</p>}<div className="form-actions"><button className="primary" disabled={busy}>{w(busy?'saving':'save')}</button><button type="button" onClick={()=>setCopyName(null)}>{w('cancel')}</button></div></form></dialog>}</>;
}
