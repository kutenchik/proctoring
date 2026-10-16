import {useContext} from 'react';
import {LocaleContext} from './index';
const messages = {
  unfinished_attempt_from_different_build: ['An unfinished attempt belongs to an older app build. Its evidence is preserved. Use that build to recover it, or ask the teacher for a new attempt in a separate profile.', 'Незавершённая попытка относится к старой сборке. Материалы сохранены. Восстановите её в прежней версии или попросите преподавателя создать новую попытку в отдельном профиле.', 'Аяқталмаған әрекет ескі нұсқаға тиесілі. Материалдар сақталған. Оны ескі нұсқада қалпына келтіріңіз немесе бөлек профильде жаңа әрекет сұраңыз.'],
  invalid_pin: ['Incorrect PIN or changed PIN revision.', 'Неверный ПИН-код или его версия изменилась.', 'PIN-код қате немесе оның нұсқасы өзгерді.'],
  pin_rate_limited: ['Too many PIN attempts. Wait 15 minutes.', 'Слишком много попыток. Подождите 15 минут.', 'Тым көп әрекет. 15 минут күтіңіз.'],
  teacher_pin_not_configured: ['Ask the teacher to set a protection PIN.', 'Попросите преподавателя задать ПИН-код.', 'Оқытушыдан PIN-код орнатуды сұраңыз.'],
  pin_authorization_expired: ['PIN verification expired. Try again.', 'Время проверки истекло. Повторите.', 'Тексеру мерзімі аяқталды. Қайталаңыз.'],
  packaged_requires_protected: ['This student app requires a Protected Mode exam. Ask your teacher for a protected exam code.', 'Это приложение принимает только экзамены в защищённом режиме. Обратитесь к преподавателю.', 'Бұл қолданба тек қорғалған режимдегі емтихандарды қабылдайды. Оқытушыға хабарласыңыз.'],
  packaged_requires_unprotected: ['This student app requires an Unprotected Mode exam. Use the Protected edition for a protected exam code.', 'Это приложение принимает только экзамены без защиты. Для защищённого экзамена используйте версию Protected.', 'Бұл қолданба тек қорғалмаған емтихандарды қабылдайды. Қорғалған емтихан үшін Protected нұсқасын пайдаланыңыз.'],
  optional_face_unavailable_in_distribution: ['This edition has no DeepFace identity/liveness runtime. This exam requires a compatible edition.', 'Эта версия не содержит DeepFace. Для экзамена нужна совместимая версия.', 'Бұл нұсқада DeepFace жоқ. Емтиханға үйлесімді нұсқа қажет.'],
  "privacy": [
    "The teacher server receives your identity, attempt status, review events, saved snapshots/reference photos, quiz answers and original report. Video recordings are not uploaded. When audio evidence is enabled and you consent, short microphone clips around audio events are recorded and uploaded. Local evidence is removed only after complete verified receipt.",
    "Сервер преподавателя получает данные участника, статус попытки, события проверки, сохранённые снимки и фото, ответы и исходный отчёт. Видеозаписи не передаются. Если аудиоматериалы включены и вы дали согласие, короткие записи микрофона вокруг звуковых событий сохраняются и передаются. Локальные материалы удаляются только после полной проверенной квитанции.",
    "Оқытушы серверіне қатысушы деректері, әрекет күйі, тексеру оқиғалары, сақталған суреттер, жауаптар және бастапқы есеп жіберіледі. Бейнежазбалар жіберілмейді. Аудиоматериалдар қосылып, келісім бергенде, дыбыс оқиғаларына қатысты қысқа микрофон жазбалары сақталып, жіберіледі. Жергілікті материалдар толық тексерілген түбіртектен кейін ғана жойылады."
  ],
  "secure_storage_unavailable": [
    "Windows secure recovery storage is unavailable. Admission is blocked.",
    "Защищённое хранилище Windows недоступно. Допуск заблокирован.",
    "Windows қорғалған қоймасы қолжетімсіз. Рұқсат бұғатталған."
  ],
  "saved_attempt_requires_attention": [
    "Saved attempt could not be safely restored. Local materials are retained; contact the proctor.",
    "Сохранённую попытку не удалось безопасно восстановить. Материалы сохранены; обратитесь к проктору.",
    "Сақталған әрекетті қауіпсіз қалпына келтіру мүмкін болмады. Материалдар сақталған; прокторға хабарласыңыз."
  ],
  "finish_not_sent": [
    "Result has not been sent to the teacher server.",
    "Результат ещё не отправлен на сервер преподавателя.",
    "Нәтиже оқытушы серверіне әлі жіберілген жоқ."
  ],
  "finish_pending": [
    "Sending client-reported result…",
    "Отправка результата приложения…",
    "Қолданба нәтижесі жіберілуде…"
  ],
  "finish_sent": [
    "Teacher server acknowledged the client-reported result. This is not independently verified grading.",
    "Сервер подтвердил получение результата приложения. Это не независимая проверка оценки.",
    "Сервер қолданба нәтижесінің алынғанын растады. Бұл бағаның тәуелсіз тексеруі емес."
  ],
  "finish_failed": [
    "Result delivery failed. Local records remain saved; Stage 1 has no automatic delivery queue.",
    "Передать результат не удалось. Локальные записи сохранены; на этапе 1 нет очереди повторной отправки.",
    "Нәтиже жіберілмеді. Жергілікті жазбалар сақталды; 1-кезеңде автоматты қайта жіберу кезегі жоқ."
  ],
  "title": [
    "Join your exam",
    "Подключиться к экзамену",
    "Емтиханға қосылу"
  ],
  "help": [
    "Enter the teacher server address and your institutional student ID. No national identity number is needed.",
    "Введите адрес сервера преподавателя и учебный номер студента. Номер государственного документа не нужен.",
    "Оқытушы серверінің мекенжайын және оқу орнындағы студент нөмірін енгізіңіз. ЖСН қажет емес."
  ],
  "server": [
    "Server HTTPS URL",
    "HTTPS-адрес сервера",
    "Сервердің HTTPS мекенжайы"
  ],
  "verify": [
    "Verify server",
    "Проверить сервер",
    "Серверді тексеру"
  ],
  "verified": [
    "Server verified",
    "Сервер проверен",
    "Сервер тексерілді"
  ],
  "code": [
    "Exam code",
    "Код экзамена",
    "Емтихан коды"
  ],
  "name": [
    "Full name",
    "Полное имя",
    "Толық аты-жөні"
  ],
  "group": [
    "Group",
    "Группа",
    "Топ"
  ],
  "student": [
    "Institutional student ID",
    "Учебный номер студента",
    "Оқу орнындағы студент нөмірі"
  ],
  "join": [
    "Join and prepare",
    "Войти и подготовиться",
    "Қосылу және дайындалу"
  ],
  "waiting": [
    "Contacting teacher server…",
    "Соединение с сервером преподавателя…",
    "Оқытушы серверіне қосылуда…"
  ],
  "preparation": [
    "Preparation time remaining",
    "Осталось на подготовку",
    "Дайындыққа қалған уақыт"
  ],
  "refresh": [
    "Refresh preparation extension",
    "Проверить продление подготовки",
    "Дайындық мерзімін жаңарту"
  ],
  "expired": [
    "Preparation expired. Ask your teacher for a five-minute extension, then refresh.",
    "Время подготовки истекло. Попросите преподавателя продлить его на пять минут, затем обновите.",
    "Дайындық уақыты аяқталды. Оқытушыдан бес минутқа ұзартуды сұрап, жаңартыңыз."
  ],
  "fixed": [
    "Identity is fixed for this admitted attempt.",
    "Данные закреплены за допущенной попыткой.",
    "Деректер осы рұқсат етілген әрекетке бекітілген."
  ],
  "multiple": [
    "Select all correct options. One point requires the exact set.",
    "Выберите все верные варианты. Балл начисляется только за точный набор.",
    "Барлық дұрыс нұсқаны таңдаңыз. Бір ұпай үшін дәл жиын қажет."
  ],
  "unanswered": [
    "Unanswered questions",
    "Вопросов без ответа",
    "Жауап берілмеген сұрақтар"
  ],
  "invalid_server": [
    "Use an HTTPS server origin. HTTP is allowed only for explicitly configured local development.",
    "Укажите HTTPS-адрес сервера. HTTP разрешён только в явно включённом локальном режиме разработки.",
    "Сервердің HTTPS мекенжайын енгізіңіз. HTTP тек арнайы қосылған жергілікті әзірлеу режимінде рұқсат."
  ],
  "connection_failed": [
    "Connection failed. Check the server address, trusted certificate and network, then retry.",
    "Соединение не удалось. Проверьте адрес, доверенный сертификат и сеть, затем повторите.",
    "Қосылу сәтсіз. Мекенжайды, сенімді сертификатты және желіні тексеріп, қайталаңыз."
  ],
  "protection_policy_mismatch": [
    "This exam requires a different protection mode. This safe launch cannot enable blocking. Ask the operator.",
    "Экзамен требует другого режима защиты. Безопасный запуск не включает блокировку. Обратитесь к оператору.",
    "Емтихан басқа қорғау режимін талап етеді. Қауіпсіз іске қосу бұғаттауды қоспайды. Операторға хабарласыңыз."
  ],
  "preparation_expired": [
    "Preparation expired; ask your teacher for an extension.",
    "Подготовка истекла; попросите преподавателя о продлении.",
    "Дайындық мерзімі аяқталды; оқытушыдан ұзартуды сұраңыз."
  ],
  "request_rejected": [
    "The teacher server rejected the request. Check the code, admission window and existing attempt with your teacher.",
    "Сервер отклонил запрос. Уточните код, время допуска и существующую попытку у преподавателя.",
    "Сервер сұрауды қабылдамады. Кодты, рұқсат уақытын және бар әрекетті оқытушымен тексеріңіз."
  ],
  "invalid_policy": [
    "The received exam policy is unsupported. Setup remains blocked.",
    "Полученные настройки экзамена не поддерживаются. Подготовка заблокирована.",
    "Алынған емтихан саясаты қолдау таппайды. Дайындық бұғатталған."
  ],
  "readiness_changed": [
    "Local readiness changed during server approval. Restore the required checks and retry Start.",
    "Готовность изменилась во время ответа сервера. Восстановите проверки и повторите запуск.",
    "Сервер растауы кезінде дайындық өзгерді. Қажетті тексерулерді қалпына келтіріп, бастауды қайталаңыз."
  ]
} as const;
export function useC() { const locale = useContext(LocaleContext); return (key: string) => (messages[key as keyof typeof messages] ?? messages.request_rejected)[locale === 'ru' ? 1 : locale === 'kk' ? 2 : 0]; }
