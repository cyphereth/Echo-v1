# Intel — пакет фиксов: реплаи, soft-hide спама, тосты-сигналы, порядок ленты

Дата: 2026-06-26

Четыре независимые проблемы в контуре «Разведка». Каждая с подтверждённой
корневой причиной. Изменения изолированы — можно ревьюить по отдельности.

## Fix 1 — Реплаи не отображаются (нет кнопки просмотра)

**Корневая причина.** Кнопка `ThreadContext` в ленте сюжета рендерится только при
`e.is_reply === true`. `is_reply` в `aggregate.event()` = `bool(m.reply_to_tg_id)`.
Основной живой путь ingestion'а — `realtime.store_realtime_post()` — создаёт
`IntelMention` **без** `reply_to_tg_id` (поллер `collector.py` его проставляет,
realtime — нет). Поэтому realtime-сообщения никогда не считаются реплаями.

**Решение.**
1. В `realtime.store_realtime_post()` добавить в конструктор `IntelMention`:
   `reply_to_tg_id=getattr(post, "reply_to_tg_id", None)`.
   Парсеры `_parse_tg_message` / `_parse_tg_chat_message` уже отдают это поле в `Post`.
2. Проверить, что `context_pass.enrich_context` (вызывается из `passes.py`) реально
   запускается планировщиком — иначе `IntelThreadContext` пуст и `/context` отдаёт
   пустую цепочку даже при корректном `is_reply`. Если не запланирован — добавить
   в тик `ticker`.

**Проверка.** Реплай-сообщение из чата → `is_reply=true` → кнопка появляется →
`GET /intel/mention/{id}/context` возвращает `reply_chain`.

## Fix 2 — Удаление в спам не убирает пост из сюжетов (soft-hide)

**Решение — мягкое скрытие.** Помеченный пост остаётся в БД, но исключается из всех
витринных выдач (лента, сюжеты, агрегаты). Обратимо.

1. **Схема.** Колонка `hidden BOOLEAN NOT NULL DEFAULT 0` в `intel_mentions`.
   Таблица существует → запись в `_MIGRATIONS` (`core/db.py`):
   `ALTER TABLE intel_mentions ADD COLUMN hidden BOOLEAN NOT NULL DEFAULT 0`.
2. **Эндпоинт.** `POST /intel/mention/{id}/hide` — ставит `hidden=true`; если у
   упоминания есть `incident_id` → находит owning `IntelStory` и уменьшает
   `post_count` на 1 (не ниже 0), best-effort. Идемпотентно (повторный вызов на
   уже скрытом не декрементит).
3. **Фильтр `hidden == False`** во всех read-путях упоминаний:
   - `api.intel_stream` (лента, оба ветвления from_dt/window)
   - `api.intel_stream_live` (SSE-лента)
   - `aggregate.story_detail` (список упоминаний сюжета)
   - `aggregate.direction_card`
   - `api.intel_direction_detail`
   - `aggregate.compute_overview` и `compute_overview_range` (счётчик событий)
   - `aggregate._sides`
4. **Фронт.** `IntelHome.handleSpam` уже знает `e.id` (id упоминания): после
   `addSpam({kind:'example'})` дополнительно вызвать `intelApi.hideMention(e.id)`.
   В `api.js` добавить `hideMention: (id) => request('/intel/mention/'+id+'/hide', {method:'POST'})`.

**Проверка.** ✕ на посте → пост исчезает из ленты И из детального вида сюжета;
`post_count` сюжета уменьшается; пример попадает в Антиспам.

## Fix 3 — Спам старыми сигналами при перезаходе

**Корневая причина.** `/intel/stream/live` при `after_alert_id=0` шлёт **все** алерты
`id>0` как новые (сброс на «только новые» в `event_gen` срабатывает лишь при
`after_alert_id < 0`). `IntelApp` вызывает `streamLiveEvents` без `afterAlertId` → 0
→ при каждом монтировании/переподключении все исторические алерты летят в `onAlert`
→ тосты дневной давности.

**Решение.** В `IntelApp` передать `streamLiveEvents({ afterAlertId: -1, onEvent, onAlert })`.
Сервер уже поддерживает: `last_alert_id < 0` → `max(IntelAlert.id)` → шлются только
алерты, появившиеся ПОСЛЕ подключения. Колокол по-прежнему наполняется отдельным
`intelApi.alerts({unread:true})` и фильтруется окном 2ч.

**Проверка.** Перезаход в «Разведку» при наличии старых алертов → тостов нет;
новый алерт во время сессии → тост появляется.

## Fix 4 — Новый пост появляется в конце ленты, а не в начале

**Корневая причина.** Лента отдаётся newest-first (`created_at.desc()`), но живые
события в `IntelHome` дописываются в **конец** массива (`[...prev, ...add]`) и
`slice(-200)`. Рендер идёт по порядку → новый пост уходит вниз.

**Решение.** В merge-эффекте `IntelHome`: новые события (newest-first) добавлять
в **начало**: `return [...addNewestFirst, ...prev].slice(0, 200)`, где
`addNewestFirst = [...add].reverse()` (`add` приходит oldest→newest). `slice(0,200)`
вместо `slice(-200)`, чтобы кап обрезал старые снизу, а не новые сверху.

**Проверка.** При открытой ленте новый пост появляется сверху; прокрутка к старым
постам не «прыгает».

## Тестирование

- **Backend, pytest:** новый тест `store_realtime_post` проставляет `reply_to_tg_id`;
  тест эндпоинта `/mention/{id}/hide` (hidden=true + декремент post_count, идемпотентность);
  тест, что `intel_stream`/`story_detail` не отдают `hidden` упоминания.
- **Frontend:** ручная проверка четырёх сценариев выше (Vite HMR, рестарт бэка делает ассистент).

## Вне области

- Ретро-чистка уже собранного мусора в старых сюжетах (только через ручной ✕).
- UI «корзины» скрытых постов / восстановление — задел на будущее (поле `hidden`
  обратимо, но эндпоинта unhide пока нет).
