# Таймфрейм — архив за период

**Дата:** 2026-07-02
**Статус:** реализовано

## Проблема

В `DateRangePicker` уже можно выбрать произвольный период (`from_dt/to_dt`), но
он влиял только на «Ситуационный центр» и «Сюжеты». «Сюжеты» кластеризуют посты,
плоского списка «все сообщения за период» не было. Нужна страница-архив: выбрал
период → все посты/смс за него, сгруппированные и с разворачиваемыми тредами.

## Решение

Подход: server-side группировка, тонкий клиент (выбран пользователем).

### Backend — `GET /intel/timeframe`

Параметры: `from_dt`, `to_dt` (ISO; иначе fallback на `window`), `side` (ru/ua),
`directions` (csv ключей-колонок, опц.), `include_radar` (default false),
`limit_per_source` (default 200).

Один оконный запрос `IntelMention` ⨝ `intel_mention_directions`, `hidden==False`,
фильтры side/radar. Группировка в Python: **направление → источник(author) → посты**.

Ответ:
```json
{ "from_dt","to_dt","total",
  "columns": [ { "direction": {"key","name"}, "count",
                 "sources": [ {"handle","side","count","last_at","posts":[<feed_event>]} ] } ] }
```
Сортировка: колонки по `count` desc; источники по `last_at` desc; посты новее сверху.
Формат поста — `aggregate.feed_event` (переиспользован).

### Frontend

- `api.js`: `timeframe(params)` → `/intel/timeframe`.
- `IntelTimeframe.jsx` (новый экран): колонки по направлению, внутри — под-группы
  по источнику-чату (`SourceGroup`). Топбар: side, 📡 Радар, 🧵 Треды. Без SSE —
  статичный снимок; перезапрос при смене периода/side/radar.
- `ThreadContext.jsx`: новый проп `forceOpen` — поднимает тред без клика (ленивая
  загрузка контекста один раз). Снятие сворачивает.
- `PostCard.jsx`: проброс `expandThreads` → `ThreadContext.forceOpen`.
- `IntelApp.jsx`: пункт сайдбара «Таймфрейм» (hotkey 6); `onTimeRange` — кастомный
  диапазон (from/to) авто-открывает экран `timeframe`, пресеты не трогают экран.

## Проверено

`/intel/timeframe`: 24ч → 10028 сообщений / 37 колонок; `limit_per_source`
соблюдён; кастомный диапазон + `side=ua` изолирует сторону; плохая дата → 400.
