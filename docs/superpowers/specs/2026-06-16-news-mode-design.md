# News Mode — каркас 2 режимов + сущность Topic — design (APPROVED)

> Этап 1 разворота в news-intelligence (см. `docs/HANDOFF.md` §7). Делает продукт
> двухрежимным: **«Новости»** (по теме, независимо от бренда) и **«Бренд»** (текущий
> мониторинг). «Тема» — отдельная сущность `Topic`; движок обобщается с `brand_id` на
> владельца brand|topic. Дата: 2026-06-16. Ветка: `feat/story-timeline` (или новая).

## 1. Решения (приняты пользователем)
- **Сущность Topic** (не системный бренд) — чистая модель, движок обобщаем.
- **Поиск-темы — приватные** (привязаны к создавшему юзеру).
- **Дефолт-темы (глобальные, user_id=NULL):** Экономика / Геополитика / Военное.
- Два режима, выбор на входе; новостной режим не требует создавать бренд.

## 2. Данные

### Новая таблица `Topic`
```
id          PK
name        TEXT
keywords    TEXT (json list) — поисковые/релевантные термины темы
kind        TEXT 'default' | 'search'
user_id     FK users (NULL = глобальная дефолт-тема; задан = приватная поиск-тема)
auto_collect BOOL default True
market      TEXT default 'ru'
created_at  TIMESTAMPTZ
```
Сид 3 дефолтов (`user_id=NULL`, `kind='default'`) с наборами ключевых слов:
- Экономика, Геополитика, Военное (term-наборы — в сиде).

### Обобщение владельца
Добавить nullable `topic_id` (FK topics) в: `Mention`, `Incident`, `Story`, `Report`, `Probe`.
Инвариант: **ровно одно** из `brand_id`/`topic_id` заполнено. (Миграция через `_MIGRATIONS`
в `db.py` — добавление колонок идемпотентно.)

## 3. Scope-абстракция (ядро обобщения)

Маленький неймтапл/объект, описывающий «владельца сбора»:
```
Scope(kind: 'brand'|'topic', id: int, keywords: list[str], niche_terms: list[str], market: str, ...)
```
Хелпер `scope_for_brand(brand)` / `scope_for_topic(topic)` строит Scope. Функции, которые
сейчас берут `brand`/`brand_id`, принимают Scope (или `(brand_id=None, topic_id=None)`),
читают ключи из Scope и пишут FK по `scope.kind`. Затрагиваемое:
- `collector.collect_web` (запрос/релевантность по scope; Mention.topic_id|brand_id)
- `collector._store_niche_post` / `_upsert_mention` (проставлять нужный FK)
- `collector.collect_probe` / `collect_chats` / `ensure_chats_discovered` (для topic — позже;
  на каркасе достаточно web + global TG search по ключам темы)
- `stories.update_stories(scope)` (выборка новых упоминаний по scope; Story/Incident FK)
- `anomalies.detect_anomaly` (без изменений — работает по story_id)
- `digests.build_daily_digest(scope)` (топ-сюжетов скоупа; Report FK)

**Принцип:** дедуп/сюжеты/таймлайн/аномалии/дайджесты не меняются — меняется только
источник ключей и FK-владелец. Brand-путь сохраняет текущее поведение.

## 4. API
- `GET /news/topics` — дефолтные (все видят) + приватные текущего юзера. Со свежей активностью.
- `POST /news/topics {name, keywords[]}` (или `{query}`) — создать приватную поиск-тему,
  запустить сбор (web + TG global search по ключам).
- Существующие аналитические эндпоинты принимают `topic_id` как альтернативу `brand_id`:
  `GET /stories?topic_id=`, `GET /stories/{id}` (уже по story), `GET /inbox?topic_id=`,
  `POST /topics/{id}/digest`, `GET /topics/{id}/digests`.
- Авторизация: дефолт-темы (`user_id=NULL`) читают все авторизованные; приватные — только владелец
  (хелпер `_owned_topic`, по образцу `_owned_brand`).

## 5. Фронтенд (echo-app)
- **Переключатель режима** «Новости» / «Бренд» (верхний уровень; напр. в Shell или над сайдбаром).
- **Режим «Новости»:** список тем (дефолтные + мои) + строка поиска (создать тему) → выбор темы →
  существующие экраны **Лента / Сюжеты / Дайджесты**, скоупленные на `topic_id` вместо `brand_id`.
- **Режим «Бренд»:** текущий флоу без изменений.
- `services/api.js`: `getNewsTopics`, `createNewsTopic`, и параметризация существующих вызовов
  на `topic_id`.

## 6. Сбор для тем (каркас)
На каркасе достаточно переиспользовать: **web (Tavily)** по ключам темы + **TG global search**
(`provider.search(query, kind!='channel')`) по ключам темы. Агрессивный дискавери/вступление в
каналы/чаты — **следующий этап** (HANDOFF §7.2), здесь вне объёма. Планировщик: веб/стори-проход
по темам с `auto_collect=True` (аналогично `_run_web_pass`, но по Topic).

## 7. Тесты
- Topic-модель + миграция `topic_id`.
- Scope: `collect_web` по topic создаёт `Mention(topic_id=...)`, дедуп; `update_stories(scope)`
  строит сюжеты по topic; `build_daily_digest(scope)` → Report(topic_id).
- API: `/news/topics` (дефолт виден всем; приватная — только владельцу, 403 чужому);
  `/stories?topic_id=` и `/inbox?topic_id=` отдают данные темы.
- Brand-путь не сломан (существующие тесты зелёные).

## 8. Вне объёма (следующие этапы, HANDOFF §7)
Агрессивный TG-дискавери+вступление (7.2), кросс-сверка источников (7.3), фейк-детект (7.4),
военная гео/таймлайн-витрина (7.5).

## 9. Риски
- **Двойной FK (brand|topic)** — следить за инвариантом «ровно одно»; покрыть тестами,
  не плодить ветвлений (через Scope-хелпер).
- **Объём:** 5 задач; brand-путь не регрессировать (прогон полного suite после каждой).
- Приватные темы → дублирование сбора по одинаковым темам у разных юзеров (принято; оптимизация позже).
