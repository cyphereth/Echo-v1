# Echo — технический хендофф и история работы

> Самодостаточная карта проекта: что это, что построено, как работает, как запускать,
> и куда движемся (news-intelligence). Сделано, чтобы можно было продолжать
> самостоятельно. Дата: 2026-06-16.

---

## 0. Что за продукт

**Было:** Echo — мониторинг бренда. Собирает упоминания бренда из Telegram (и соцсетей),
классифицирует, считает тональность/серьёзность, предлагает черновики ответов.

**Стало (эта сессия):** поверх добавлен **аналитический слой по образцу ochi-analytics**:
упоминания → инциденты → сюжеты → таймлайн динамики → детект аномалий → LLM-дайджесты,
плюс **веб-источник** (Tavily) как ещё один топик-канал.

**Куда идём (следующий этап, ещё не начат):** разворот в сторону **независимой
новостной разведки** — два режима продукта: **«Новости»** (по теме, не по бренду) и
**«Бренд»** (текущий мониторинг). См. §7.

---

## 1. Архитектура и стек

- **Backend:** `backend/` — FastAPI + SQLAlchemy + **SQLite** (`echo_radar.db`).
  Пакет `radar` (импорт `radar.xxx` при CWD=`backend/`). Запуск: `uvicorn radar.api:app`.
  Конфиг через env (`backend/.env`, gitignored, грузится `load_dotenv()` в `api.py`).
- **Frontend:** `echo-app/` — активный фронт (Vite + React, react-router). Старый
  `echo-radar/` — не используется. Vite слушает `localhost` (IPv6 `[::1]`), прокси на
  `http://127.0.0.1:8000` (см. `echo-app/vite.config.js`).
- **Тесты:** `backend/tests/` (pytest, in-memory SQLite, мок внешних вызовов).
- **Python:** на хосте python.org framework build **3.14** — у него **отключён
  `enable_load_extension`** (важно, см. §4 numpy).
- Команды запускать как `python3` (не `python`).

---

## 2. Что построено этой сессией (по файлам, с механикой)

Всё смержено в `main` (кроме багфикса свежести — см. §6). Ветка работы `feat/story-timeline`.

### Бэкенд (`backend/radar/`)
- **`embeddings.py`** — `embed(texts)->np.ndarray` через локальную `intfloat/multilingual-e5-small`
  (sentence-transformers, ленивый синглтон `_model()`). 384-мерные, L2-норм.
- **`vec.py`** — векторное хранилище **на numpy** (не sqlite-vec!): таблицы
  `mention_vec/incident_vec/story_vec` (id + BLOB), `store()`, `knn()` (косинус в Python),
  `create_vec_tables()`. Причина numpy — см. §4.
- **`models.py`** — добавлены `Incident`, `Story`, `StoryPoint`, `Report` + колонка
  `Mention.incident_id`. (Story: brand_id, title, status, **is_anomaly**, post_count,
  first/last_seen. StoryPoint: story_id, bucket_start, mention_count, avg_sentiment,
  source_count. Report: brand_id, story_id?, kind, body, created_at.)
- **`stories.py`** — `update_stories(session, brand_id)`: новые упоминания → эмбеддинг →
  **дедуп в инциденты** (косинус ≥ `STORY_INCIDENT_SIM`, окно `STORY_INCIDENT_WINDOW_H`) →
  **связывание в сюжеты** (мягче: `STORY_STORY_SIM`, `STORY_STORY_WINDOW_D`) →
  `_recompute_points` (почасовые бакеты) → `anomalies.detect_anomaly`. Центроиды —
  бегущее среднее в vec-таблицах.
- **`anomalies.py`** — `detect_anomaly(session, story_id)->bool`: по `story_points`
  сравнивает последний бакет с базовой линией. Триггер = **всплеск объёма (обязателен)
  И (резкий негатив ИЛИ приток источников)**. Нужна история ≥ `ANOMALY_MIN_BUCKETS`.
  Пороги в env (`ANOMALY_*`). Идемпотентно, ставит `story.is_anomaly`.
- **`llm.py`** — `complete(system, user, max_tokens, model)->str` поверх существующего
  LLM-прокси (`LLM_API_KEY`/`LLM_API_URL`, Anthropic-формат, как в `drafts.py`). Модель
  по умолчанию `claude-haiku-4-5-20251001`. Без ключа → `LLMNotConfigured`.
- **`digests.py`** — `build_daily_digest(session, brand_id)->Report|None`: топ-сюжеты за
  24ч (аномальные вперёд) → компактный агрегат → один вызов `llm.complete` → `Report(kind=digest)`.
  Промпт: «тема → динамика → источники → риски → рекомендация».
- **`providers/web.py`** — `WebSearchProvider.search(query)` через **Tavily**
  (`WEB_SEARCH_API_KEY`/`WEB_SEARCH_URL`, `topic="general"`+`search_depth="advanced"` =
  весь веб, не только новости). Без ключа/ошибка → `[]`.
- **`collector.py`** — добавлен `collect_web(session, brand, provider)`: тема = имя+ключевые
  слова бренда → находки → `Mention(platform="web")` → `_store_niche_post`. Дедуп по
  `sha1(url)`. **Свежесть:** `_store_niche_post` теперь не хранит нишевые посты старше
  `NICHE_FRESH_HOURS` (24ч) — багфикс §6.
- **`scheduler.py`** — module-level `_run_brand_pipeline` (classify+draft+fetch+stories,
  story-слой best-effort), `_run_digest_pass` (флаг `ENABLE_DIGESTS`, default OFF),
  `_run_web_pass` (`INTERVAL_WEB`, gated по `WEB_SEARCH_API_KEY`). Веб/дайджест/чаты —
  каждый на своей каденции в `_run_once`.
- **`api.py`** — эндпоинты: `GET /stories?brand_id=`, `GET /stories/{id}`,
  `POST /stories/recompute`, `POST /brands/{id}/digest`, `GET /brands/{id}/digests`.
  Все brand-scoped через `_owned_brand`. `/inbox` теперь прячет нишевые посты старше
  `NICHE_FRESH_HOURS` (§6). Веб-провайдер строится в `on_startup` при наличии ключа.

### Фронтенд (`echo-app/src/`)
- **`components/app/Stories.jsx`** + `stories.module.css` — экран «Сюжеты»: список (аномальные
  вверху, ⚠), деталь с графиком динамики (объём + тональность) на **recharts**.
- **`components/app/Digests.jsx`** + `digests.module.css` — экран «Дайджесты»: кнопка
  «Сгенерировать» + список сводок.
- **`components/app/Shell.jsx`** — пункты сайдбара «Сюжеты» (icon `activity`), «Дайджесты»
  (icon `zap`). Лента/Очередь/Аналитика/Города/Настройки — были раньше.
- **`pages/AppPage.jsx`** — ветки рендера `screen==='stories'|'digests'`, тайтлы TopBar.
  **Важно:** вкладка ленты определяется по **`source`** (`lane = m.source`), а не по
  бэкенд-`lane`. Ниша = `source==='niche'`.
- **`services/api.js`** — `getStories/getStory`, `getDigests/createDigest` (стиль `request()`).

---

## 3. Поток данных (pipeline)

```
Источники по теме бренда:
  • Telegram: _global_search (глобальный поиск) + discover_channels + чтение каналов + чаты (collect_chats)
  • Веб: collect_web → Tavily
        │
        ▼  (Mention, source=brand|competitor|niche, platform=telegram|web|…)
classify_and_draft  → тональность/серьёзность/lane + черновики
        │
        ▼
update_stories: эмбеддинг → дедуп→инцидент → связывание→сюжет → точки таймлайна → детект аномалии
        │
        ▼
Доставка: /stories (экран «Сюжеты» + график), build_daily_digest → /digests (экран «Дайджесты»)
```
Telegram-сторона (глоб.поиск+каналы+чаты) уже была построена ДО этой сессии и гоняется
коллектором/планировщиком по ключевым словам бренда.

---

## 4. Ключевое архитектурное решение: numpy вместо sqlite-vec

Изначально планировали sqlite-vec для векторного поиска. Но хостовый Python (python.org
framework, и 3.14, и 3.12) собран с **`enable_load_extension=False`**, а `pysqlite3-binary`
не имеет колеса под 3.14 → расширения SQLite не грузятся. Решение: эмбеддинги хранить как
BLOB, косинус считать в numpy (`vec.py`). KNN идёт только по центроидам (incident/story —
небольшие наборы), не по сырью. Возврат к sqlite-vec возможен на Homebrew/conda-Python.

---

## 5. Конфиг (env, `backend/.env`)

| Переменная | Назначение | Default |
|---|---|---|
| `LLM_API_KEY` / `LLM_API_URL` | LLM-прокси (Anthropic-формат, aiprimetech.io) — дайджесты, черновики | — / api.anthropic.com |
| `WEB_SEARCH_API_KEY` / `WEB_SEARCH_URL` | Tavily веб-поиск | — / api.tavily.com/search |
| `WEB_MAX_RESULTS` | результатов на запрос | 10 |
| `INTERVAL_WEB` | каденция веб-прохода, сек | 3600 |
| `ENABLE_DIGESTS` | авто-дайджесты по расписанию (1=вкл) | 0 (OFF) |
| `NICHE_FRESH_HOURS` | окно свежести нишевых постов | 24 |
| `STORY_INCIDENT_SIM` / `STORY_STORY_SIM` | пороги дедупа/связывания (косинус) | 0.90 / 0.78 |
| `STORY_INCIDENT_WINDOW_H` / `STORY_STORY_WINDOW_D` | временные окна | 48 / 14 |
| `ANOMALY_MIN_BUCKETS` / `ANOMALY_VOLUME_FACTOR` / `ANOMALY_MIN_VOLUME` / `ANOMALY_SENT_DROP` / `ANOMALY_SOURCE_FACTOR` | пороги аномалий | 3 / 3.0 / 3 / 0.4 / 2.0 |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_PHONE` | Telethon | — |
| `TIKHUB_TOKEN` / `SOCIALCRAWL_TOKEN` | соц-провайдеры | — |
| `ENABLE_SCHEDULER` | фоновый сбор (0=выкл для контроля) | 1 |
| `DATABASE_URL` | БД | sqlite:///echo_radar.db |

`sentence-transformers` нужно установить (`pip3 install sentence-transformers`) — он в
`requirements.txt`, но тяжёлый (torch); тесты его мокают.

---

## 6. Багфикс свежести ниши (коммит на ветке `feat/story-timeline`)

**Симптом:** в ленте раздел «Ниша» показывал одни и те же каналы со всей их историей
постов с ключевыми словами, включая 2-недельные/годовалые.
**Корень:** правило свежести было только в `collect_probe` (>7 дней — пропуск), а нишевый
путь (`_store_niche_post`: chats/web/geo) его не имел → засасывал всю историю канала; плюс
`/inbox` не фильтровал по свежести.
**Фикс:** `_store_niche_post` не хранит ниш-посты старше `NICHE_FRESH_HOURS` (24ч);
`/inbox` прячет ниш-посты старше окна (бренд/конкуренты не трогаем). Тесты:
`backend/tests/test_niche_freshness.py`. Проверено вживую: 9 старых скрыто, осталось свежее.

---

## 7. Следующий этап: news-intelligence (СПРОЕКТИРОВАТЬ, не начато)

**Видение (со слов пользователя):** независимый продукт, который по теме (или дефолтным
темам экономика/геополитика/военное) сам ищет по всем TG-каналам/чатам/группам + вебу,
ловит всплеск **раньше** новостных каналов, **сверяет** по независимым источникам,
**проверяет на фейк**, выдаёт факты. Не привязано к бренду.

**Референс:** ochi-analytics военная витрина `https://1314june.online` — «РЕПЛЕЙ НОЧІ»:
таймлайн-реплей с перемоткой (1×/4×/16×/40×), карта (области краснеют), счётчики по типам
(небезпека/БПЛА/вибухи/ППО/радар), лента типизированных фиксаций. По сути — парсер по
куче TG обеих сторон → типизированные события (что/где/когда) → лента + гео-временной реплей.

**Решённое:** делаем **два режима** — на входе выбор «Новости» / «Бренд». Новостной режим
**не привязан к бренду** (убрать обязательность бренда). Так получаем 2 сектора в одном продукте.

**Декомпозиция (по порядку, каждый — отдельный спек→план→реализация):**
1. **[НАЧИНАЕМ С ЭТОГО] Каркас 2 режимов + независимый раздел «Новости».** Экран выбора
   режима; новостной режим по теме/поиску (без бренда), на готовом движке
   (инцидент→сюжет→таймлайн→аномалия→дайджест), скоуп по теме (TG глоб.поиск + веб).
   Дефолтные темы + строка поиска.
2. Агрессивный TG-дискавери + вступление в каналы/чаты по теме (ранние сигналы).
3. Кросс-сверка источников (одно событие из N независимых = выше доверие/раньше).
4. Фейк/дезинфо-детект.
5. Военная витрина (типизация событий + гео + таймлайн-реплей, как референс).

**Чего сейчас НЕТ (честно):** независимого новостного режима, строки поиска, дефолтных тем,
кросс-сверки, фейк-детекта; TG-дискавери есть, но консервативный (по нише бренда, throttled,
без активного вступления). Движок инцидент→сюжет→аномалия→дайджест — правильный фундамент,
но подключён к бренду.

---

## 8. Как запускать и проверять

```bash
# Бэкенд (из backend/), без фонового сбора для контроля:
cd backend && ENABLE_SCHEDULER=0 python3 -m uvicorn radar.api:app --port 8000
# Фронт:
cd echo-app && npm run dev          # http://localhost:5173
# Тесты:
cd backend && python3 -m pytest -q  # ~187 зелёных
```
**Тестовый аккаунт (бренд 11 «Дача Grill Park»):** `dacha.grillpark@echo.app` / `grillpark2026`.

Ручной прогон полного цикла для бренда (нужен `sentence-transformers` + ключи):
```python
from dotenv import load_dotenv; load_dotenv("backend/.env")
from radar.db import get_session
from radar import collector, stories, digests
from radar.providers.web import WebSearchProvider
s=get_session(); b=s.get(__import__("radar.models",fromlist=["Brand"]).Brand, 11)
collector.collect_web(s,b,WebSearchProvider()); stories.update_stories(s,11)
print(digests.build_daily_digest(s,11).body)
```

### Гочи
- Vite на `localhost`/IPv6 — `curl 127.0.0.1:5173` не коннектится, браузер открывает норм.
- Тесты делят on-disk `echo_radar.db`; при ошибке `mentions.incident_id` прогнать раз
  `python3 -c "import radar.db as db; db.init_db()"` (идемпотентная миграция).
- Первый `update_stories` качает модель e5 (~сотни МБ).
- `curl`/`wget` в этом окружении перехватываются хуком — для HTTP-проверок использовать httpx в python3.

---

## 9. Git / документы

- Всё (story-timeline + telegram-provider + аномалии + дайджесты + веб) смержено в **`main`**
  (PR #5, #6). Багфикс свежести — на ветке `feat/story-timeline` (нужно домержить в main).
- Спеки/планы: `docs/superpowers/specs/` и `docs/superpowers/plans/` —
  `2026-06-15-story-timeline-*`, `2026-06-16-anomaly-detection-*`, `2026-06-16-llm-digests-*`,
  `2026-06-16-web-source-*`. Этот файл — `docs/HANDOFF.md`.
- Процесс работы: каждая фича шла brainstorm → spec → plan → реализация субагентами (TDD,
  ревью спека + код-ревью), затем мерж. Память Claude: `~/.claude/projects/.../memory/echo-story-timeline.md`.

---

## 10. TODO / следующие шаги
- [ ] Домержить багфикс свежести (`feat/story-timeline`) в `main`.
- [ ] Спроектировать и сделать §7.1 — каркас 2 режимов + «Новости» (СЛЕДУЮЩЕЕ).
- [ ] Далее §7.2–7.5 по порядку.
- [ ] (Опц.) Установить `sentence-transformers` в проде; включить `ENABLE_DIGESTS` при желании.
- [ ] (Опц.) Подкрутить веб-релевантность под рус/локальные бренды (country/домены).
