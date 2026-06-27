# Смена типа источника (Канал ⇄ Чат)

**Дата:** 2026-06-26 · ветка `feat/intel-thread-context`

## Проблема
Реплаи/thread-context не работают для источников, ошибочно заведённых как `channel`.
Channel-ветка коллектора (`provider.search` → `_parse_tg_message`) даёт голый `post_id`
и никогда не ставит `reply_to_tg_id`, поэтому `context_pass` для них не срабатывает.
Групповые чаты (напр. `orel_chat57`) нужно собирать chat-веткой
(`search_chat` → `_parse_tg_chat_message`), которая namespace'ит `post_id` и пишет `reply_to_tg_id`.

## Решение
Дать в «Источниках» возможность переключать тип уже добавленного источника.

### Backend — `PATCH /intel/sources/{id}`
- Тело `{ "kind": "chat" }` (опц. `side`).
- Валидация `kind` через существующий `_VALID_KINDS`.
- Меняет `probe.kind`; **watermark не трогаем** — числовой watermark станет `min_id`
  в chat-ветке, сбор продолжится с той же точки уже с захватом реплаев,
  старые «голые» записи не пере-собираются (min_id отсекает).
- Возвращает обновлённый `_probe_dict`.

### API-клиент (`echo-app/src/features/intel/api.js`)
- `updateSource: (id, body) => request('/intel/sources/'+id, { method:'PATCH', ... })`.

### Frontend (`IntelSources.jsx`) — вариант A
- Бейдж типа `КАНАЛ`/`ЧАТ` делаем кликабельным тумблером (`cursor:pointer`, `title`).
- По клику → PATCH с противоположным kind → перезагрузка списка; локальный «updating» как у delete.

## Вне объёма
- Ретро-бэкфилл `reply_to_tg_id` для уже собранных голых записей.
- Проверка гипотезы, что chat-ветка тоже не пишет реплаи (502 записи с NULL).
