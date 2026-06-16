# Web Source (topic-driven) — design (APPROVED)

> **Status: approved (2026-06-16).** Добавляет веб как ещё один топик-источник
> мониторинга, дополняя уже существующий Telegram (глобальный поиск + дискавери
> каналов + чтение каналов + чаты — всё уже работает по ключевым словам бренда).
> Модель «тема → ищем везде» (как ochi-analytics): Telegram-сторона готова, эта
> спека закрывает веб. Дата: 2026-06-16. Ветка: `feat/story-timeline`.

## 1. Цель

Пользователь задаёт тему (= ключевые слова/нишу/имя бренда — уже есть в конфиге).
Система ищет по этой теме **в вебе** (через поисковый API) и кладёт находки в тот
же конвейер упоминаний, что и Telegram. Дальше всё построенное работает без правок:
релевантность → эмбеддинги → инциденты → сюжеты → таймлайн → аномалии → дайджесты.

## 2. Что уже есть (не трогаем)

- **Telegram целиком**: `TelegramProvider._global_search` (глобальный поиск по
  запросу), `discover_channels(query)`, чтение каналов, мониторинг чатов
  (`collect_chats`). Коллектор/планировщик уже гоняют это по теме бренда.
- Конвейер `Mention → incident → story → story_points → digest` + аномалии.
- Хелперы хранения/релевантности ниши в `collector.py` (`_store_niche_post`,
  `_word_in`/`_term_hit`) — **переиспользуем** для веб-находок.

Новое в этой спеке — только **веб-источник**.

## 3. Провайдер `backend/radar/providers/web.py`

`WebSearchProvider` (Tavily по умолчанию):
- `search(query: str, max_results=10) -> list[dict]` → `[{title, url, content, published}]`.
- Конфиг env: `WEB_SEARCH_API_KEY`, `WEB_SEARCH_URL` (default `https://api.tavily.com/search`),
  `WEB_MAX_RESULTS` (default 10).
- httpx POST `{api_key, query, search_depth:"basic", topic:"news", max_results}`,
  парсит `results[]`. Без ключа → `[]` (no-op, ноль затрат). Сетевые ошибки → `[]`.
- Tavily возвращает уже извлечённый релевантный текст (`content`), отдельный
  скрейпинг не нужен.

## 4. Коллектор `collect_web(session, brand, provider) -> int` (в `collector.py`)

- Запрос = тема бренда: имя + ключевые слова + нишевые термины (как уже строится
  для Telegram-проб; переиспользуем существующую логику сбора терминов).
- Для каждой находки: `post_id = sha1(url)[:16]`, дедуп через
  `UniqueConstraint(platform, post_id)` (платформа `"web"`). Уже виденные — пропуск.
- `text = title + ". " + content`; релевантность — существующая проверка терминов
  (`_word_in`/морфология), как для ниши. Прошедшие — сохраняем через
  `_store_niche_post(...)` с `platform="web"`, `author=домен(url)`,
  `created_at=published|now`, `source="niche"`.
- Возвращает число новых упоминаний.

## 5. Планировщик (`scheduler.py`)

- Веб-проход `_run_web_pass(session, provider)` — module-level, по образцу
  `_run_digest_pass`: для брендов с `auto_collect`, зовёт `collect_web`, при новых
  упоминаниях → `_run_brand_pipeline` (он уже гонит classify/draft/stories).
- Каденция `INTERVAL_WEB` (env, default 3600), gated по наличию `WEB_SEARCH_API_KEY`
  (нет ключа → не активничает). Best-effort (как остальные проходы).
- Провайдер веба создаётся в `api.on_startup` (как tg/основной), передаётся в Scheduler.

## 6. Фронт

Отдельного экрана НЕ добавляем. Веб-упоминания и сюжеты появятся в существующих
«Сюжетах»/ленте с `platform="web"`. (Опц. позже: фильтр по источнику.)

## 7. Тесты

- `providers/web.py`: мок `httpx.post` → парсинг results; пустой ключ → `[]`.
- `collect_web`: мок провайдера → проверяем создание `Mention(platform="web")`,
  дедуп по url, фильтр нерелевантного. Без реальной сети.
- `_run_web_pass`: мок `collect_web` → вызывается для auto_collect брендов.

## 8. Риски / границы

- **Стоимость search API** — Tavily платный сверх бесплатного тира; degrade-to-noop
  без ключа; каденция в конфиге. Бесплатный тир для проверки.
- **Качество/релевантность веба** — те же фильтры релевантности, что и для ниши;
  калибровать на реальных брендах ([[echo-testing-real-brands]]).
- **Провайдер сменяемый** — Tavily по умолчанию, но `WEB_SEARCH_URL` + формат
  изолированы в `web.py`; смена на Brave/др. — правка одного модуля.
- **Вне объёма:** UI-поле тем, фильтр источника на фронте, скрейпинг закрытых сайтов,
  не-новостной режим Tavily.
