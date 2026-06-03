# AI Onboarding & Real Data Design

**Date:** 2026-06-03  
**Status:** Approved

## Overview

Убрать все мок-данные (PapaPizza, фейковые упоминания). Один пользователь = один бренд. Claude API генерирует настройки бренда (ключевые слова, конкуренты, ниша). TikHub показывает реальный превью постов до сохранения.

## Constraints

- Один аккаунт = один бренд. Мультибренд убирается.
- `seed.py` создаёт только демо-аккаунт (`demo@echo.app` / `demo12345`), без брендов.
- Все мок-упоминания и хардкод PapaPizza удаляются.

## Backend Changes

### seed.py
Удалить всё кроме `ensure_demo_user()`. Никаких брендов, никаких упоминаний, никаких проб при старте.

### POST /brands/suggest
```
Auth: Bearer token required
Body: { "name": "Ozon" }
Response: {
  "keywords": ["озон", "ozon", ...],       // 5-7 слов
  "hashtags": ["#озон", "#ozon", ...],     // 3-5 хэштегов
  "competitors": ["Wildberries", ...],     // 3-5 конкурентов
  "niche_keywords": ["маркетплейс", ...]   // 3-5 нишевых терминов
}
```

Реализация: вызов `claude-haiku-4-5-20251001` через `drafts.LLM_API_KEY/URL`. Системный промпт фиксирован на бэке. Claude отвечает JSON — парсить через `json.loads()`, при ошибке — retry 1 раз с явным указанием формата. Timeout 60s.

Промпт системный:
> Ты эксперт по SMM и мониторингу брендов в русскоязычных соцсетях (TikTok, Instagram). Отвечай ТОЛЬКО валидным JSON, без пояснений.

Промпт пользователя:
> Для бренда "{name}" подбери для мониторинга в TikTok и Instagram: 5-7 ключевых слов (на русском и латинице, вариации написания), 3-5 хэштегов, 3-5 прямых конкурентов (только названия), 3-5 нишевых терминов. JSON: {"keywords":[],"hashtags":[],"competitors":[],"niche_keywords":[]}

### POST /brands/preview
```
Auth: Bearer token required
Body: { "keywords": ["ozon", "озон"], "platforms": ["tiktok", "instagram"] }
Response: {
  "posts": [
    { "post_id": "...", "platform": "tiktok", "author": "...", "views": 0, "text": "...(80 chars)" }
  ]
}
```

Берёт первые 2 ключевых слова, 1 страница TikHub каждый. Возвращает до 5 постов. Ничего не пишет в БД. Timeout 25s. Ошибка TikHub → `{ "posts": [], "error": "preview_unavailable" }`.

### POST /onboarding — добавить ограничение
Если у пользователя уже есть бренд → `HTTP 409 { "detail": "Brand already exists" }`.

### Удалить
- Переключатель брендов в API (`/brands` теперь возвращает всегда один бренд для пользователя)

## Frontend Changes

### AppPage.jsx
- Если `brands.length === 0` → рендерить `<AIWizard mode="create" />` вместо основного интерфейса
- Если `brands.length > 0` → обычный интерфейс (Feed/Queue/Analytics/Settings)

### Shell.jsx
- Убрать переключатель брендов / `2 бренда` бейдж
- Показывать только название текущего бренда (без клика)

### Settings.jsx
- Убрать хардкод `PapaPizza`, `papapizza`, `DoDo Pizza` и прочие дефолты
- Поля заполняются только из `brand`-объекта с бэка
- Добавить кнопку **«✨ AI-заполнение»** рядом с заголовком → открывает `<AIWizard mode="edit" brand={brand} />`

### AIWizard.jsx (новый компонент)

**Режим `create`** (онбординг нового пользователя):
- Шаг 1: поле «Название бренда» + кнопка «Подобрать» → `POST /brands/suggest` → показать теги с ✕
- Шаг 2: `POST /brands/preview` → карточки реальных постов (или «Превью недоступно») → кнопка «Создать бренд»
- «Создать бренд» → `POST /onboarding` → `POST /brands/{id}/collect` (фоновый) → закрыть визард

**Режим `edit`** (существующий бренд в Settings):
- Шаг 1: название предзаполнено, можно изменить → «Подобрать» → показать предложения
- Шаг 2: превью постов → «Применить»
- «Применить» → `POST /brands/{id}/config` → `_rebuild_probes` на бэке → закрыть

**Обработка ошибок в визарде:**
- Claude недоступен → тост «AI недоступен — заполните вручную», поля разблокированы
- TikHub preview error → пропустить шаг 2, показать «Превью недоступно» + кнопка «Сохранить без превью»
- Пустые массивы от Claude → «Не удалось подобрать автоматически», дать редактировать вручную

### aiwizard.module.css (новый)
Модал поверх основного интерфейса. Два экрана: теги + превью карточки.

## Data Flow

### Новый пользователь
```
Логин → AppPage (нет бренда) → AIWizard[create]
  → POST /brands/suggest        (Claude, 60s)
  → Пользователь редактирует теги
  → POST /brands/preview        (TikHub, 25s)
  → POST /onboarding            (создать бренд)
  → POST /brands/{id}/collect   (фоновый сбор)
  → Основной интерфейс
```

### Существующий пользователь, перезаполнение
```
Settings → «AI-заполнение» → AIWizard[edit]
  → POST /brands/suggest        (Claude, 60s)
  → Пользователь редактирует теги
  → POST /brands/preview        (TikHub, 25s)
  → POST /brands/{id}/config    (сохранить + rebuild_probes)
  → Закрыть модал
```

## What Gets Deleted

| Файл | Что удаляется |
|------|---------------|
| `backend/radar/seed.py` | Весь `_SEED`, `seed_mentions()`, все бренды PapaPizza/Ozon/CafeBlanche |
| `echo-app/src/components/app/Settings.jsx` | Хардкод: `PapaPizza`, `папапицца`, `DoDo Pizza`, дефолтные конкуренты/ключи |
| `echo-app/src/components/app/Shell.jsx` | Переключатель брендов, бейдж `N брендов` |
| `echo-app/src/pages/AppPage.jsx` | Логика мультибренда, brand switcher state |
