import { useContext } from 'react';
import { LocaleContext } from './index';

const copy = {
  disabled: ['Protection disabled — development mode', 'Защита выключена — режим разработки', 'Қорғау өшірулі — әзірлеу режимі'],
  awaiting_audit: ['Protection awaits recovery audit', 'Защита ожидает проверку восстановления', 'Қорғау қалпына келтіру тексеруін күтуде'],
  preparing: ['Preparing protection — input is unrestricted', 'Подготовка защиты — ввод не ограничен', 'Қорғау дайындалуда — енгізу шектелмеген'],
  arming: ['Activating protection…', 'Включение защиты…', 'Қорғау қосылуда…'],
  active: ['Protection active', 'Защита активна', 'Қорғау белсенді'],
  releasing: ['Releasing protection…', 'Снятие ограничений…', 'Шектеулер алынуда…'],
  released: ['Protection released', 'Ограничения сняты', 'Шектеулер алынды'],
  fault: ['Protection interrupted — exam cannot continue', 'Защита прервана — продолжить экзамен нельзя', 'Қорғау үзілді — емтиханды жалғастыру мүмкін емес'],
  unknown: ['Protection status unavailable', 'Статус защиты недоступен', 'Қорғау күйі қолжетімсіз'],
  awaiting_audit_help: ['Close this window and run the Electron recovery audit on this machine. A passing audit is required before protected Start.', 'Закройте окно и запустите проверку восстановления Electron на этом компьютере. Для защищённого запуска нужна успешная проверка.', 'Осы терезені жауып, осы компьютерде Electron қалпына келтіру тексеруін іске қосыңыз. Қорғалған іске қосу үшін тексеру сәтті өтуі керек.'],
  host_binding_required: ['Waiting for verified exam-window ownership.', 'Ожидание проверки владельца окна экзамена.', 'Емтихан терезесінің иесі тексерілуде.'],
  control_progress_required: ['Waiting for responsive exam controls.', 'Ожидание отклика элементов управления экзаменом.', 'Емтихан басқару элементтерінің жауабы күтілуде.'],
  desktop_in_use: ['Another protected session owns this desktop. Finish it before continuing.', 'Этот рабочий стол занят другой защищённой сессией. Сначала завершите её.', 'Бұл жұмыс үстелін басқа қорғалған сессия пайдаланып жатыр. Алдымен оны аяқтаңыз.'],
  geometry_pending: ['Settle the fullscreen layout before collecting gaze samples.', 'Дождитесь стабилизации полноэкранного окна перед калибровкой взгляда.', 'Көзқарасты калибрлеуден бұрын толық экранды терезенің орныққанын күтіңіз.'],
  audit_incompatible: ['The recovery audit is missing, expired or belongs to another build.', 'Проверка восстановления отсутствует, устарела или относится к другой сборке.', 'Қалпына келтіру тексеруі жоқ, мерзімі өткен немесе басқа жинаққа тиесілі.'],
  native_fault: ['The independent recovery path released protection. Start a new session after resolving the fault.', 'Независимый механизм восстановления снял ограничения. Устраните сбой и начните новую сессию.', 'Тәуелсіз қалпына келтіру механизмі шектеулерді алды. Ақауды түзетіп, жаңа сессия бастаңыз.'],
  helper_identity_unavailable: ['Protection status could not be confirmed. The exam cannot continue. Use Ctrl+Shift+Alt+Q if emergency release is needed. Start a new session only after cleanup is confirmed.', 'Не удалось подтвердить состояние защиты. Продолжить экзамен нельзя. При необходимости аварийного снятия ограничений нажмите Ctrl+Shift+Alt+Q. Начинайте новую сессию только после подтверждения безопасного завершения работы.', 'Қорғау күйін растау мүмкін болмады. Емтиханды жалғастыруға болмайды. Шектеулерді төтенше жағдайда алу қажет болса, Ctrl+Shift+Alt+Q басыңыз. Жұмыстың қауіпсіз аяқталғаны расталғаннан кейін ғана жаңа сессияны бастаңыз.'],
  foreground_containment_failed: ['The exam window could not be kept in the foreground. Protection was released and the session ended. Ask the proctor to resolve this before starting a new session.', 'Не удалось удержать окно экзамена на переднем плане. Ограничения сняты, сессия завершена. Перед новой сессией попросите проктора устранить проблему.', 'Емтихан терезесін алдыңғы қатарда ұстау мүмкін болмады. Шектеулер алынып, сессия аяқталды. Жаңа сессияны бастамас бұрын проктордан мәселені шешуді сұраңыз.'],
  active_help: ['Restrictions remain during proctor and camera-recovery pauses. End through the proctor PIN. Emergency release: Ctrl+Shift+Alt+Q.', 'Ограничения сохраняются при паузе проктора и восстановлении камеры. Завершение — по PIN проктора. Аварийное снятие: Ctrl+Shift+Alt+Q.', 'Проктор үзілісі мен камераны қалпына келтіру кезінде шектеулер сақталады. Проктор PIN коды арқылы аяқтаңыз. Төтенше босату: Ctrl+Shift+Alt+Q.'],
  preparing_help: ['The final window geometry is set before calibration. Restrictions begin only after protected Start is acknowledged.', 'Окончательное положение окна задаётся до калибровки. Ограничения включаются только после подтверждения защищённого старта.', 'Терезенің соңғы өлшемі калибрлеуден бұрын орнатылады. Шектеулер қорғалған бастау расталғаннан кейін ғана қосылады.'],
  diagnostics: ['Protection diagnostics', 'Диагностика защиты', 'Қорғау диагностикасы'],
} as const;
export type ProtectionText = keyof typeof copy;
export function useProtectionText() {
  const locale = useContext(LocaleContext);
  return (key: ProtectionText) => copy[key][locale === 'ru' ? 1 : locale === 'kk' ? 2 : 0];
}
