export const securityText = {
  en: ['Checking exam security', 'Preparing verification', 'Usually 2–5 minutes. Temporary verification windows may appear. Leave the keyboard and test windows available.', 'Emergency release', 'Completed checks', 'Waiting for verified report and process cleanup', 'Security check failed. Close the app, address the cause and reopen it to confirm a retry.', 'Retry after addressing the cause?', 'Retry', 'Close'],
  ru: ['Проверка безопасности экзамена', 'Подготовка проверки', 'Обычно 2–5 минуты. Могут появляться временные окна проверки. Не занимайте клавиатуру и оставляйте тестовые окна доступными.', 'Аварийное отключение', 'Завершено проверок', 'Ожидание подтверждённого отчёта и завершения процессов', 'Проверка не пройдена. Закройте приложение, устраните причину и откройте его снова для подтверждения повтора.', 'Повторить после устранения причины?', 'Повторить', 'Закрыть'],
  kk: ['Емтихан қауіпсіздігі тексерілуде', 'Тексеруге дайындық', 'Әдетте 2–5 минут. Уақытша тексеру терезелері ашылуы мүмкін. Пернетақта мен сынақ терезелерін бос ұстаңыз.', 'Төтенше босату', 'Аяқталған тексерулер', 'Расталған есеп пен процестердің аяқталуын күту', 'Тексеру сәтсіз аяқталды. Қолданбаны жабыңыз, себебін түзетіп, қайталауды растау үшін қайта ашыңыз.', 'Себепті түзеткеннен кейін қайталау керек пе?', 'Қайталау', 'Жабу'],
};
export function securityStrings(language: string) { return securityText[language as keyof typeof securityText] || securityText.en; }
const stages: Record<string, [string, string, string]> = {
  binding_identity: ['Window identity', 'Идентификация окна', 'Терезені сәйкестендіру'],
  wrong_hwnd_rejected: ['Rejecting an unrelated window', 'Отклонение чужого окна', 'Бөгде терезені қабылдамау'],
  wrong_stale_identity_rejected: ['Rejecting stale identity', 'Отклонение устаревшей идентичности', 'Ескірген сәйкестікті қабылдамау'],
  normal_release: ['Normal release', 'Обычное отключение', 'Қалыпты босату'],
  repeated_cycles: ['Repeated recovery', 'Повторные циклы восстановления', 'Қайталама қалпына келтіру'],
  emergency_shortcut: ['Emergency shortcut', 'Аварийное сочетание клавиш', 'Төтенше пернелер тіркесімі'],
  pin_modal_emergency: ['Emergency release in PIN dialog', 'Аварийный выход из окна ПИН-кода', 'PIN терезесінен төтенше шығу'],
  external_focus_emergency: ['Emergency release outside the window', 'Аварийный выход вне окна', 'Терезеден тыс төтенше шығу'],
  renderer_loss_observer_alive: ['Interface loss recovery', 'Восстановление после потери интерфейса', 'Интерфейс жоғалғанда қалпына келтіру'],
  main_loss: ['Main process loss recovery', 'Восстановление после остановки приложения', 'Қолданба тоқтағанда қалпына келтіру'],
  main_stall: ['Main process stall recovery', 'Восстановление при зависании приложения', 'Қолданба қатып қалғанда қалпына келтіру'],
  backend_loss: ['Backend loss recovery', 'Восстановление после остановки службы', 'Қызмет тоқтағанда қалпына келтіру'],
  backend_stall: ['Backend stall recovery', 'Восстановление при зависании службы', 'Қызмет қатып қалғанда қалпына келтіру'],
  control_eof: ['Control channel loss', 'Потеря канала управления', 'Басқару арнасының жоғалуы'],
  lost_release_ack: ['Missing release acknowledgement', 'Потеря подтверждения отключения', 'Босатуды растаудың жоғалуы'],
  helper_suspension: ['Suspended helper recovery', 'Восстановление при приостановке помощника', 'Көмекші кідіргенде қалпына келтіру'],
  helper_loop_failure: ['Helper failure recovery', 'Восстановление после сбоя помощника', 'Көмекші істен шыққанда қалпына келтіру'],
  forced_release: ['Forced release', 'Принудительное отключение', 'Мәжбүрлі босату'],
  replay_rejected: ['Rejecting repeated commands', 'Отклонение повторной команды', 'Қайталанған пәрменді қабылдамау'],
  overlapping_helper_rejected: ['Rejecting a duplicate helper', 'Отклонение второго помощника', 'Екінші көмекшіні қабылдамау'],
  recovery_reregister: ['Restoring emergency registration', 'Восстановление аварийной регистрации', 'Төтенше тіркеуді қалпына келтіру'],
};
export function auditStageLabel(name: string, language: string) {
  return stages[name]?.[language === 'ru' ? 1 : language === 'kk' ? 2 : 0] || securityStrings(language)[0];
}
export function securityHtml(language: string) {
  const t = securityStrings(language);
  return `<!doctype html><html lang="${['en','ru','kk'].includes(language) ? language : 'en'}"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>Local Proctoring</title><style>body{background:#f8f6f1;color:#233d35;font:16px 'Segoe UI',sans-serif;margin:0;padding:40px}main{background:white;border:1px solid #e3ded4;border-radius:20px;padding:32px}h1{font-size:28px;margin-top:12px}p{line-height:1.6}progress{width:100%;height:12px;accent-color:#407447}small{color:#586b61}#stage{overflow-wrap:anywhere}</style><small>Local Proctoring</small><main><h1>${t[0]}</h1><p id="stage">${t[1]}</p><progress id="progress" max="21" value="0"></progress><p>${t[4]}: <strong id="count">0 / 21</strong></p><p>${t[2]}</p><p>${t[3]}: <strong>Ctrl+Shift+Alt+Q</strong></p><small id="outcome">${t[5]}</small></main></html>`;
}
