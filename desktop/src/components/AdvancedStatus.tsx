import {useContext} from 'react';
import {LocaleContext} from '../locales';
const labels:Record<string,string[]>={
 remote:['Remote-access checks','Проверки удалённого доступа','Қашықтан қол жеткізуді тексеру'],
 worker:['Face analysis','Анализ лица','Бетті талдау'],
 identity:['Face comparison','Сравнение лица','Бетті салыстыру'],
 liveness:['Passive liveness','Пассивная проверка живого лица','Тірілікті пассивті тексеру'],
 awaiting_consent:['Awaiting consent','Ожидается согласие','Келісім күтілуде'],
 initializing:['Preparing models/checks','Подготовка моделей/проверок','Модельдер/тексерулер дайындалуда'],
 ready:['Worker ready','Обработчик готов','Өңдегіш дайын'],
 complete:['Observation available; absence is not proven','Наблюдение доступно; отсутствие не доказано','Бақылау қолжетімді; жоқтығы дәлелденбеген'],
 partial:['Partial observation','Неполное наблюдение','Толық емес бақылау'],
 unavailable:['Unavailable — operator attention required','Недоступно — требуется оператор','Қолжетімсіз — оператор қажет'],
 stopped:['Stopped','Остановлено','Тоқтатылды'],
 disabled:['Disabled','Отключено','Өшірілген'],
 inconclusive:['Inconclusive','Неопределённый результат','Нақты емес нәтиже'],
 reference_required:['Capture a reference before starting','Сделайте эталон до начала','Бастамас бұрын эталон түсіріңіз'],
 enrolled:['Reference enrolled locally','Эталон сохранён локально','Эталон жергілікті тіркелді'],
 match:['Matches enrolled face','Соответствует эталону','Эталонға сәйкес'],
 suspected:['Suspicious observation; review required','Подозрительное наблюдение; требуется проверка','Күмәнді бақылау; тексеру қажет'],
 passed:['Liveness observation passed','Проверка живого лица пройдена','Тірілікті бақылау өтті'],
 face_missing:['Face missing','Лицо отсутствует','Бет көрінбейді'],
 multiple_faces:['Multiple faces; comparison withheld','Несколько лиц; сравнение не выполняется','Бірнеше бет; салыстыру орындалмайды'],
 ambiguous_face:['Primary face ambiguous','Основное лицо неоднозначно','Негізгі бет анық емес'],
 low_quality:['Face quality insufficient','Недостаточное качество лица','Бет сапасы жеткіліксіз'],
 liveness_inconclusive:['Liveness does not permit comparison','Проверка живого лица не разрешает сравнение','Тірілік нәтижесі салыстыруға рұқсат бермейді'],
};
export function AdvancedStatus({values}:{values?:Record<string,string>}){
 const locale=useContext(LocaleContext),index=locale==='ru'?1:locale==='kk'?2:0;
 if(!values||!Object.keys(values).length)return null;
 const label=(key:string)=>(labels[key]||labels.inconclusive)[index];
 return <div className="quiet-note" role="status">{Object.entries(values).map(([key,state])=><p key={key}>{label(key)}: {label(state)}</p>)}</div>;
}
