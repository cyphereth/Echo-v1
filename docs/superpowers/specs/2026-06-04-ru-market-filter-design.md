# RU/CIS Market Filter — Design

**Date:** 2026-06-04
**Status:** Approved

## Overview

Для русскоязычных/СНГ брендов: Claude при регистрации определяет рынок автоматически, предлагает только русскоязычных конкурентов, а сбор отфильтровывает иностранные посты — кроме вирусных (по факту просмотров).

## Decisions

- Рынок определяет Claude автоматически (`suggest_brand` / `_profile_with_claude`) — поле `market`: `"ru"` или `"global"`. Без ручного флага.
- Конкуренты-иностранцы не предлагаются русским брендам (инструкция в промпте Claude).
- Иностранные посты дропаются для `ru`-брендов, ЕСЛИ не вирусные. Вирусность = факт по метрикам TikHub (`views >= 500_000`). Внешний API виральности не используется — он недоступен для автономного бэкенда и оценивает pre-publish потенциал, а не факт.

## Backend

### Brand model
Новое поле `market: str = "global"`. Миграция в `db.py` `_MIGRATIONS["brands"]["market"] = "TEXT DEFAULT 'global'"`. Геттер не нужен (плоское поле).

### Claude prompts
В `suggest_brand` и `_profile_with_claude` добавить в промпт:
> Определи рынок бренда. Если бренд русскоязычный или ориентирован на СНГ — верни "market":"ru" и предлагай ТОЛЬКО русскоязычных конкурентов из СНГ (без иностранных). Иначе "market":"global".

JSON-схема в промптах получает поле `"market":""`. Ответы эндпоинтов возвращают `market` (дефолт `"global"`).

### collector.py
```python
import re
VIRAL_VIEWS = 500_000

def _passes_language(post: Post, brand: Brand) -> bool:
    if getattr(brand, "market", "global") != "ru":
        return True
    if post.views >= VIRAL_VIEWS:
        return True
    clean = " ".join(w for w in post.text.split() if not w.startswith("#"))
    return bool(re.search(r"[а-яёА-ЯЁ]", clean))
```
Вызывается в `_matches` после exclusions, до keyword-матчинга: `if not _passes_language(post, brand): return False`.

### onboarding / config
- `OnboardingBody` + `market: str = "global"` → сохраняется в `Brand.market`.
- `BrandConfigBody` + `market: Optional[str] = None` → обновляется если передан.
- `_brand_card` отдаёт `market`.

## Frontend

- `api.js createBrand(..., market = "global")` — добавить параметр в тело.
- `AIWizard`: `setMarket` из ответа suggest/scan; передать в `createBrand`; в Шаге 1 плашка «Рынок: 🇷🇺 Русскоязычный / СНГ» или «🌍 Глобальный».

## Error handling
- Claude не вернул market → `"global"` (фильтр не применяется).
- Старые бренды → миграция ставит `"global"`.

## Testing
- `_passes_language`: русский → True; чистый английский для ru-бренда → False; английский 600k просмотров → True; global-бренд английский → True.
- e2e onboarding с market через mock.

## Files
| Файл | Изменение |
|------|-----------|
| `backend/radar/models.py` | поле `market` |
| `backend/radar/db.py` | миграция market |
| `backend/radar/collector.py` | `_passes_language`, VIRAL_VIEWS, вызов в `_matches` |
| `backend/radar/api.py` | market в промптах, onboarding/config/brand_card |
| `backend/tests/test_profile_scan.py` | тесты `_passes_language` |
| `echo-app/src/services/api.js` | createBrand market |
| `echo-app/src/components/app/AIWizard.jsx` | market state + плашка |
