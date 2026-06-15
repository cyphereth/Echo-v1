# Story Timeline & Dynamics — design

> Новый аналитический слой поверх Echo-v1 (по образцу ochi-analytics.com).
> Источник требований: `/Users/vovolypsi/Downloads/analytics-platform-spec.md`.
> Дата: 2026-06-15. Ветка: `feat/story-timeline`.

## 1. Цель и границы

Echo сейчас собирает посты как **упоминания** (`Mention`) с тональностью, но не
ведёт тему во времени. Главный дифференциатор продукта по спеку — показывать
**не «что произошло», а «как, почему и в какой динамике развивается тема»**.

Этот слой добавляет иерархию `mention → incident → story` и **график динамики
сюжета** (объём упоминаний, тональность, число источников во времени).

**Решения, зафиксированные при брейншторме:**

- **Слой поверх Echo-v1** — переиспользуем существующий Telegram-коллектор, БД и
  планировщик. Не отдельный продукт.
- **Хранилище: SQLite + sqlite-vec** — остаёмся на текущей БД, добавляем
  расширение для векторного поиска. Без Postgres/Redis/ARQ.
- **Эмбеддинги: локальная модель** `intfloat/multilingual-e5-small` (384-мерные)
  через `sentence-transformers`. Без ключей и пооточной платы. Хорошо знает
  русский.
- **LLM: Claude Haiku 4.5** — только для дайджестов/отчётов. **Вне MVP.**
- **MVP-срез: сюжет + график динамики на дашборде.** LLM-дайджесты и детект
  аномалий — позже, на том же фундаменте.

**Соответствие спеку:** в Echo `Mention` играет роль `raw_post` из спека (есть
`text`, `created_at`, `tone`, `platform`, `author`). Поверх него строим
`incidents`, `stories`, точки таймлайна.

## 2. Данные

Все сущности **scoped по бренду** (multi-tenant): дедуп и связывание идут только
в пределах одного `brand_id`.

### Новые таблицы

| Таблица | Назначение | Ключевые поля |
|---|---|---|
| `mention_vec` (sqlite-vec `vec0`) | эмбеддинг упоминания | rowid = mention_id, `embedding float[384]` |
| `incidents` | уникальное событие = группа схлопнутых дублей | `brand_id`, `story_id?`, `title`, `sentiment REAL`, `post_count`, `first_seen_at`, `last_seen_at`, `created_at` |
| `incident_vec` (`vec0`) | центроид инцидента | rowid = incident_id, `embedding float[384]` |
| `stories` | продолжающаяся тема = цепочка инцидентов | `brand_id`, `title`, `status` (active/dormant), `is_anomaly BOOLEAN` (задел), `first_seen_at`, `last_seen_at`, `created_at` |
| `story_vec` (`vec0`) | центроид сюжета | rowid = story_id, `embedding float[384]` |
| `story_points` | точки графика динамики | `story_id`, `bucket_start`, `mention_count`, `avg_sentiment REAL`, `source_count`, UNIQUE(story_id, bucket_start) |

### Изменение существующей таблицы

- `mentions`: добавить колонку `incident_id INTEGER` (nullable) через механизм
  `_MIGRATIONS` в `db.py`. Сырьё **не переписываем** — только проставляем ссылку.

### Заметки

- ORM-таблицы (`incidents`, `stories`, `story_points`) — обычные SQLAlchemy
  модели, создаются `Base.metadata.create_all`.
- `vec0`-таблицы (`mention_vec`, `incident_vec`, `story_vec`) — виртуальные
  таблицы sqlite-vec, создаются отдельным `CREATE VIRTUAL TABLE IF NOT EXISTS`
  при инициализации БД.
- Размерность 384 соответствует `multilingual-e5-small`.

## 3. Эмбеддинги — модуль `embeddings.py`

- Ленивый синглтон модели `intfloat/multilingual-e5-small` через
  `sentence-transformers`.
- `embed(texts: list[str]) -> np.ndarray` — пачкой; e5 требует префикс
  `"query: "` / `"passage: "` (использовать `passage:` для постов).
- Новые зависимости в `requirements.txt`: `sentence-transformers`, `sqlite-vec`,
  `numpy`.
- sqlite-vec подгружается в `db.py` в том же connect-listener, где включается WAL
  (`conn.enable_load_extension(True)` → `sqlite_vec.load(conn)`).

## 4. Обработка — модуль `stories.py`

Функция `update_stories(session, brand_id) -> dict` (счётчики для логов):

1. **Эмбеддинг.** Берём упоминания бренда без `incident_id` и не спам → считаем
   эмбеддинги пачкой → пишем в `mention_vec`.
2. **Дедуп → инцидент.** Для каждого нового упоминания ищем ближайший центроид
   инцидента бренда (`incident_vec`) в пределах порога косинуса
   `INCIDENT_SIM` И временного окна `INCIDENT_WINDOW`. Близко → присоединяем
   (обновляем `post_count`, `last_seen_at`, `sentiment`, центроид). Иначе →
   новый инцидент.
3. **Инцидент → сюжет.** Тем же приёмом для новых/обновлённых инцидентов, но с
   более мягким порогом `STORY_SIM` и большим окном `STORY_WINDOW`. Близко →
   присоединяем к сюжету; иначе → новый сюжет.
4. **Пересчёт `story_points`** по задетым сюжетам: бакеты по часам, для каждого —
   `mention_count`, `avg_sentiment` (positive=+1 / neutral=0 / negative=−1,
   среднее), `source_count` (уникальные `author`/канал). Upsert по
   (story_id, bucket_start).

**Конфиг (env, подбор эмпирически):** `INCIDENT_SIM`, `STORY_SIM`,
`INCIDENT_WINDOW`, `STORY_WINDOW`, размер бакета (час).

**Заголовки на MVP — эвристика, без LLM:** самое частое ключевое слово темы или
текст репрезентативного (ближайшего к центроиду) упоминания, обрезанный. Поле
оставляем перезаписываемым — позже заполнит LLM.

## 5. Точка интеграции

`Scheduler._run_once` и `_collect_chats_worker` (scheduler.py) уже вызывают
`classify_and_draft(session, brand_id)` для брендов с новыми упоминаниями.
**Сразу после него добавляем `update_stories(session, brand_id)`** в обоих местах.
Никакого нового воркера, очереди или Redis — работаем в существующем тике.

Плюс ручной триггер `POST /stories/recompute?brand_id=` для теста и бэкофилла.

## 6. API (api.py)

- `GET /stories?brand_id=` — список активных сюжетов: `id`, `title`,
  `post_count`, `last_seen_at`, текущая `avg_sentiment`, краткая динамика.
- `GET /stories/{id}` — детали сюжета: точки таймлайна (`story_points` для
  графика), список инцидентов, топ-источники.
- `POST /stories/recompute?brand_id=` — ручной пересчёт (тест/бэкофилл).

Ответы — Pydantic-схемы в стиле существующих эндпоинтов; авторизация — как у
остальных brand-scoped роутов.

## 7. Фронтенд (echo-app — активный фронтенд)

- Новый экран **«Сюжеты»** в Sidebar (`components/app/Shell.jsx`) + ветка в
  `pages/AppPage.jsx` (`screen === 'stories'`).
- `StoriesScreen` — список сюжетов (заголовок, объём, последняя активность,
  тональность, мини-спарклайн).
- `StoryDetail` — **график динамики**: объём упоминаний + средняя тональность во
  времени, ниже — инциденты и топ-источники.
- Новая зависимость: `recharts` (графиков в проекте сейчас нет).
- `vite.config`: добавить `/stories` в proxy на `http://127.0.0.1:8000`.
- API-вызовы — в `services/api.js` рядом с существующими.

## 8. Фазы реализации

1. **Фундамент:** `embeddings.py`, sqlite-vec в `db.py`, новые
   таблицы/`vec0`/миграция `incident_id`. Тесты на эмбеддинги и схему.
2. **Пайплайн:** `stories.py` (дедуп→инцидент→сюжет→точки) + хук в Scheduler.
   Тесты на дедуп, связывание, пересчёт точек.
3. **API:** три эндпоинта + Pydantic-схемы. Тесты на ответы.
4. **Фронтенд:** экран «Сюжеты» + график (recharts) + proxy + api.js.

## 9. Вне MVP (тот же фундамент, позже)

- **LLM-дайджесты** (Claude Haiku 4.5) по сюжетам/агрегатам, не по сырью.
- **Детект аномалий/инфо-атак** (`stories.is_anomaly`): всплеск объёма + сдвиг
  тональности + неестественный приток источников → алерт.
- **RSS/веб-коллекторы** как дополнительные источники.

## 10. Риски / на что смотреть

- **`sentence-transformers` тянет torch** (сотни МБ) — принято осознанно
  (локальные эмбеддинги без ключей и платы).
- **Пороги близости** — главная эмпирическая настройка; вынесены в конфиг,
  калибровать на реальных брендах (см. память: тестируем на реальных брендах).
- **Качество кластеризации — 80% сложности** (по спеку): строим до любого
  LLM-слоя; на MVP проверяем глазами на дашборде.
- **Заголовки без LLM** могут быть корявыми — это осознанный MVP-компромисс,
  поле перезаписываемо.
- **sqlite-vec на больших объёмах** — на MVP-объёмах достаточно; масштаб —
  отдельная история.
