# Follower Filter + Brand DNA (sphere) — Design

**Date:** 2026-06-05
**Status:** Approved

## Overview

1. **Follower filter** — посты/комменты от аккаунтов с <100 подписчиков прячутся (store-but-hide), кроме вирусных.
2. **Brand DNA (sphere)** — Claude при регистрации определяет сферу бренда и интересы его аудитории, хранит как `Brand.sphere`, и генерит ШИРОКИЕ niche_keywords (тема + индустрия + смежные интересы ЦА). Контент сферы наполняет существующую вкладку «Ниша» (без новой вкладки).

## Feature 1 — Follower filter

`collector.py`:
```python
MIN_FOLLOWERS = 100
```
- В `collect_probe`: `spam = looks_like_ad_cheap(...) or (0 < (post.followers or 0) < MIN_FOLLOWERS and not _is_viral(post))`. Мелкий аккаунт → `is_spam=True`, кроме вирусных. `followers == 0` (нет данных) НЕ режем.
- В `_fetch_and_store_comments` (api.py): аналогично для комментов — `0 < fc.followers < MIN_FOLLOWERS` → `is_spam`. Комменты с `followers in (0, None)` не режем по этому правилу (у комментов счётчик часто отсутствует).

## Feature 2 — Brand DNA / sphere

### Model / migration
- `Brand.sphere: Mapped[str] = mapped_column(Text, default="")`
- `db.py` `_MIGRATIONS["brands"]["sphere"] = "TEXT DEFAULT ''"`

### Claude prompts (suggest_brand + _profile_with_claude)
Добавить инструкцию:
> Определи ДНК бренда — его сферу и интересы аудитории 1-2 фразами (поле "sphere"). niche_keywords подбери ШИРОКО: узкая тематика + темы индустрии + смежные интересы ЦА (для косметологии: уход за кожей, бьюти-процедуры, тренды красоты, макияж, велнес, селф-кер).

JSON-схема в обоих промптах получает `"sphere":""`. Возвраты `suggest_brand` и `profile_scan` отдают `sphere` (дефолт "").

### API plumbing
- `OnboardingBody` + `sphere: str = ""` → сохраняется в `Brand.sphere`.
- `BrandConfigBody` + `sphere: Optional[str] = None` → обновляется если передан.
- `_brand_card` отдаёт `sphere`.

### Frontend
- `api.js`: `createBrand(..., sphere="")`; (`updateBrandConfig` принимает config-объект — фронт кладёт sphere туда).
- `AIWizard`: state `sphere`, заполняется из ответа suggest/scan; Шаг 1 — блок «ДНК бренда» (текст sphere, редактируемый textarea/inline); передаётся в createBrand / config.
- `Settings.jsx`: поле «Сфера / ДНК» рядом с нишей (опционально, если время — иначе только визард).
- Контент сферы идёт в существующую «Нишу» через расширенные niche-пробы (`_rebuild_probes` не меняется — просто niche_keywords шире).

## Error handling
- Claude не вернул sphere → "" (ничего не ломается).
- Старые бренды → миграция ставит "".
- followers отсутствует (0/None) → правило не применяется.

## Testing (test_profile_scan.py)
- followers filter via collect path helper: small (50) non-viral → spam; small + viral (likes 1500) → not spam; followers 0 → not spam by this rule.
  - Реализуем как чистую функцию `_below_follower_floor(post)` в collector для тестируемости:
    ```python
    def _below_follower_floor(post) -> bool:
        f = post.followers or 0
        return 0 < f < MIN_FOLLOWERS and not _is_viral(post)
    ```
- sphere migration present.

## Files
| Файл | Изменение |
|------|-----------|
| `backend/radar/collector.py` | MIN_FOLLOWERS, `_below_follower_floor`, в collect_probe spam-флаг |
| `backend/radar/api.py` | follower-фильтр комментов, sphere в onboarding/config/brand_card + промпты |
| `backend/radar/models.py` | Brand.sphere |
| `backend/radar/db.py` | миграция sphere |
| `backend/tests/test_profile_scan.py` | тесты follower floor |
| `echo-app/src/services/api.js` | createBrand sphere |
| `echo-app/src/components/app/AIWizard.jsx` | блок ДНК (sphere) + проброс |
