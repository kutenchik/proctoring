Local Proctoring — question import / импорт вопросов / сұрақтарды импорттау

EN
Download example files at /samples/questions.json and /samples/questions.xlsx.
Each question is worth 1 point. Single choice requires exactly one correct
option. Multiple choice requires the exact set; no partial credit.
JSON: {"title":"Title","questions":[{"id":"q1","type":"single_choice",
"prompt":"Question?","options":[{"id":"a","text":"First"},
{"id":"b","text":"Second"}],"correct_option_ids":["a"]}]}
Use single_choice or multiple_choice. Question IDs must be unique. Option IDs
must be unique within their question. Text must not be empty. Correct IDs must
refer to existing options. Imports support at most 200 questions and 2 MiB.
XLSX: exactly one sheet named Questions. Header (one option per row):
question_id | type | prompt | option_id | option_text | is_correct
Repeat the question ID, type and prompt for each option. IDs/text are strings.
is_correct is Excel TRUE/FALSE or 1/0. No formulas, macros or external links.
The filename becomes the set title. Preview validates; Save persists separately.

RU
Примеры: /samples/questions.json и /samples/questions.xlsx.
За вопрос даётся 1 балл. В single_choice нужен ровно один правильный ответ.
В multiple_choice нужен точный набор ответов, частичных баллов нет.
Формат JSON приведён выше. ID вопросов уникальны; ID ответов уникальны внутри
вопроса. Текст не может быть пустым. correct_option_ids содержит существующие
ID ответов. До 200 вопросов, файл до 2 МиБ.
XLSX: один лист Questions, заголовки как указано выше. Каждая строка — один
ответ; повторяйте question_id, type и prompt. ID и текст — строки.
is_correct: логическое TRUE/FALSE или число 1/0. Формулы, макросы и внешние
ссылки запрещены. Имя файла становится названием набора.
Предпросмотр проверяет файл; для сохранения нажмите отдельную кнопку.

KK
Мысалдар: /samples/questions.json және /samples/questions.xlsx.
Әр сұраққа 1 ұпай. single_choice түрінде дәл бір дұрыс жауап қажет.
multiple_choice түрінде дәл дұрыс жиынтық қажет, жартылай ұпай жоқ.
JSON пішімі жоғарыда көрсетілген. Сұрақ ID бірегей; жауап ID сол сұрақ ішінде
бірегей болуы керек. Мәтін бос болмауы керек. correct_option_ids бар жауап
ID-лерін қамтиды. Ең көбі 200 сұрақ, файл көлемі 2 МиБ-қа дейін.
XLSX: Questions атты бір парақ, баған атаулары жоғарыда. Әр жол — бір жауап.
question_id, type және prompt мәндерін қайталаңыз. ID мен мәтін — жолдар.
is_correct: TRUE/FALSE немесе 1/0. Формула, макрос, сыртқы сілтеме қолданбаңыз.
Файл атауы жинақ атауына айналады. Қарау тек тексереді, сақтау бөлек орындалады.
