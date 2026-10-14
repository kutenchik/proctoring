import { useContext } from 'react';
import { LocaleContext } from './index';
const text: Record<string, [string,string,string]> = {
  title: ['Evidence synchronization','Синхронизация материалов','Материалдарды синхрондау'],
  detail: ['Detail','Причина','Себебі'],
  offline: ['Offline — local materials are retained','Нет связи — материалы сохранены локально','Байланыс жоқ — материалдар жергілікті сақталған'],
  pending: ['Pending synchronization','Ожидает синхронизации','Синхрондауды күтуде'],
  verifying: ['Files uploaded — awaiting a verified completion receipt','Файлы отправлены — ожидается проверенная квитанция','Файлдар жіберілді — расталған түбіртек күтілуде'],
  uploading: ['Uploading evidence','Материалы отправляются','Материалдар жіберілуде'],
  retrying: ['Retrying delivery','Повторная отправка','Қайта жіберілуде'],
  needs_attention: ['Incomplete materials — needs attention','Материалы неполные — требуется проверка','Материалдар толық емес — тексеру қажет'],
  fully_synchronized: ['Fully synchronized — matching receipt verified','Полностью синхронизировано — квитанция проверена','Толық синхрондалды — түбіртек тексерілді'],
  retry: ['Retry synchronization','Повторить синхронизацию','Синхрондауды қайталау'],
  background: ['Continue uploading in background','Продолжить отправку в фоне','Жіберуді фондық режимде жалғастыру'],
  exit: ['Exit completely','Выйти полностью','Толық шығу'],
  exitHelp: ['Complete exit keeps unsent materials. Upload resumes on your next explicit launch. Background mode stops after verified receipt and cleanup; camera and microphone stay off.','При полном выходе неотправленные материалы сохраняются до следующего запуска. Фоновый режим завершится после проверки квитанции и очистки; камера и микрофон выключены.','Толық шыққанда жіберілмеген материалдар келесі іске қосуға дейін сақталады. Фондық режим түбіртек тексеріліп, тазалау біткен соң аяқталады; камера мен микрофон өшірулі.'],
  recovery: ['Interrupted attempt — teacher approval required','Прерванная попытка — требуется разрешение преподавателя','Үзілген әрекет — оқытушының рұқсаты қажет'],
  recoveryHelp: ['This computer retains your answers and remaining time. Ask the teacher to authorize recovery, refresh, then repeat device and gaze checks. Closing time is not counted.','Ответы и оставшееся время сохранены на этом компьютере. Запросите разрешение преподавателя, обновите статус и повторите проверки устройств и взгляда. Время закрытого приложения не учитывается.','Жауаптар мен қалған уақыт осы компьютерде сақталған. Оқытушыдан рұқсат алып, күйді жаңартыңыз және құрылғы мен көзқарас тексерулерін қайталаңыз. Қолданба жабық болған уақыт есептелмейді.'],
  refresh: ['Refresh recovery approval','Обновить разрешение','Рұқсат күйін жаңарту'],
  remaining: ['Saved time remaining','Сохранённое оставшееся время','Сақталған қалған уақыт'],
  cleanup: ['Local uploaded evidence has been removed after complete server receipt. Reports and snapshots remain on the teacher server.','Загруженные локальные материалы удалены после полной квитанции сервера. Отчёты и снимки сохранены на сервере преподавателя.','Толық сервер түбіртегінен кейін жүктелген жергілікті материалдар жойылды. Есептер мен суреттер оқытушы серверінде сақталады.'],
};
export function useSyncText() { const locale = useContext(LocaleContext); return (key: string) => (text[key] ?? text.needs_attention)[locale === 'ru' ? 1 : locale === 'kk' ? 2 : 0]; }
