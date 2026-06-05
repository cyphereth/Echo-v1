# Geo & Local Targeting for Service Businesses — Design

**Date:** 2026-06-05
**Status:** Approved

## Problem

Для локального сервисного бизнеса (салоны, клиники) мониторинг другой: конкуренты = ВСЕ салоны/клиники категории (даже мелкие), нужна вся ниша + аудитория города, и геопривязка к городу/региону.

## Decisions

- **geo locality**: гибрид — Claude определяет город, пользователь правит. `Brand.geo` (пусто = федеральный).
- **category competitors**: Claude для сервисного бизнеса генерит `category_terms` (салон красоты, маникюр, косметолог) → пробы source=competitor. Для не-сервисных пусто.
- **geo method**: keyword-append (город в запрос) + native IG location endpoints (best-effort, fail-open).
- **geo scope**: город добавляется только к категорийным и нишевым пробам (аудитория). Бренд и именованные конкуренты — глобально.

## Models / migration

- `Brand.geo: Mapped[str] = mapped_column(Text, default="")`
- `Brand.category_terms: Mapped[str] = mapped_column(Text, default="[]")` + `category_terms_list()`
- `db.py` `_MIGRATIONS["brands"]`: `geo = "TEXT DEFAULT ''"`, `category_terms = "TEXT DEFAULT '[]'"`

## Claude (suggest_brand + _profile_with_claude)

Промпт добавляет:
> Определи город (`geo`), если бизнес локальный (салон/клиника в конкретном городе) — иначе "". Если это сервисный локальный бизнес — сгенерируй `category_terms`: 4-6 категорий, по которым ищется вся ниша города (для салона: «салон красоты», «маникюр», «брови», «косметолог», «бьюти мастер»). Для федеральных/онлайн брендов category_terms = [].

JSON-схема += `"geo":"", "category_terms":[]`. Возвраты suggest/scan отдают `geo`, `category_terms`.

## Probe building (_rebuild_probes)

Для каждой платформы из MONITORED_PLATFORMS:
- brand keywords → source=brand, query=kw  (как сейчас, без гео)
- competitors → source=competitor, query=comp  (как сейчас, без гео)
- **category_terms → source=competitor**, query = `f"{term} {geo}"` if geo else term
- niche_keywords → source=niche, query = `f"{term} {geo}"` if geo else term

Гео добавляется только к category + niche. `_clean_list` чистит входы.

## Native IG location supplement (best-effort)

`providers/base.py`: `fetch_location_posts(city: str, platform: str, limit: int) -> list[Post]` (default []).
`tikhub.py` IG: `search_locations`(city)→location_id→`location_posts`. Fail-open (return [] on any error). TikTok/mock → [].
`collector.py`: новый `collect_geo(session, brand, provider)` — если `brand.geo`, тянет location_posts, прогоняет через те же фильтры (_matches с фиктивной niche-пробой / language / spam), сохраняет как source=niche. Вызывается из `_run_collect` и scheduler после обычных проб, best-effort (try/except, не валит сбор).

## API plumbing

- `OnboardingBody` += `geo: str = ""`, `category_terms: list[str] = []`.
- `BrandConfigBody` += `geo: Optional[str]`, `category_terms: Optional[list[str]]`.
- onboarding/config сохраняют (category_terms через `_clean_list`).
- `_brand_card` отдаёт `geo`, `category_terms`.

## Frontend

- `api.js createBrand(..., geo="", category_terms=[])`; config принимает их.
- `AIWizard`: state `geo`, `categoryTerms`; заполняются из suggest/scan; Шаг 1 — поле «Город» (input, редактируемое) + TagGroup «Категории конкурентов» (если непусто); передаются в createBrand/config.
- Settings: поле «Город» + категории (если время).
- Никаких новых вкладок: category → Конкуренты, niche(гео) → Ниша.

## Error handling
- Claude не вернул geo/category → "" / []. Не-сервисный бизнес → category пусто, гео-append не делается.
- Native location fail → []  (best-effort, основной keyword-поиск работает).
- Старые бренды → миграции дефолтят.

## Tests
- `_rebuild_probes` с geo: category/niche пробы содержат город в query; brand/competitor — нет.
- category_terms → source=competitor probes.
- geo пусто → query без города.

## Files
| Файл | Изменение |
|------|-----------|
| `backend/radar/models.py` | Brand.geo, category_terms + геттер |
| `backend/radar/db.py` | миграции geo, category_terms |
| `backend/radar/api.py` | Claude промпты, _rebuild_probes гео, onboarding/config/brand_card, collect_geo вызов |
| `backend/radar/collector.py` | collect_geo (best-effort location) |
| `backend/radar/providers/base.py` | fetch_location_posts default |
| `backend/radar/providers/tikhub.py` | IG location resolve+posts |
| `backend/radar/providers/mock.py` | fetch_location_posts → [] |
| `backend/tests/test_profile_scan.py` | probe geo tests |
| `echo-app/src/services/api.js` | createBrand geo/category |
| `echo-app/src/components/app/AIWizard.jsx` | город + категории |
