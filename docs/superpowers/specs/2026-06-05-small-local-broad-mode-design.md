# Small Local Brands — Broad City-Audience Mode — Design

**Date:** 2026-06-05
**Status:** Approved

## Problem

Строгий «ниша + город» даёт мало для маленьких локальных бизнесов (волюм). Для них (≤1000 подписчиков + один город) надо показывать весь городской контент, близкий к аудитории/сфере (салон красоты → любой женский/лайфстайл-контент города).

## Decisions

- **Detect small-local**: авто — `followers ≤ 1000` (из `fetch_profile` при скане) И `geo` задан → `local_mode=True`. Плюс ручной тумблер (override; новый аккаунт с 0 подписчиков).
- **audience_terms**: Claude генерит широкий портрет ЦА (8-12 тем: женское, лайфстайл, мода, уют, дети, отношения, готовка, шопинг).
- **broad matching**: гибрид — аудиторные темы как сеть (объём) + Claude батч-трим явного оффтопа (точность).
- **<100 follower floor смягчается** в local_mode (горожане = аудитория). Реклама/дропшиппер фильтр остаётся.
- Не-локальные бренды без изменений.

## Models / migration

- `Brand.followers: Mapped[int] = mapped_column(Integer, default=0)`
- `Brand.local_mode: Mapped[bool] = mapped_column(Boolean, default=False)`
- `Brand.audience_terms: Mapped[str] = mapped_column(Text, default="[]")` + `audience_terms_list()`
- `db.py` `_MIGRATIONS["brands"]`: followers INTEGER DEFAULT 0, local_mode BOOLEAN DEFAULT 0, audience_terms TEXT DEFAULT '[]'

## Claude (suggest_brand + _profile_with_claude)

Промпт += «Сгенерируй audience_terms — 8-12 широких тем целевой аудитории бренда (для салона красоты: женское, лайфстайл, мода, уют, дети, отношения, готовка, шопинг, фитнес). Для глобальных/нетематических — []». JSON += `"audience_terms":[]`.
`profile_scan`: `followers` берём из собранного профиля (max по платформам, как name/bio). suggest-по-названию: followers неизвестны → не возвращаем (фронт оставит 0).
Возвраты suggest/scan отдают `audience_terms` (+ scan отдаёт `followers`).

## _rebuild_probes

Если `brand.local_mode` и `geo`:
```python
for term in brand.audience_terms_list():
    add Probe(source="niche", label=term, query=f"{term} {geo}")  # both platforms
```
Обычные brand/competitor/category/niche пробы — как сейчас. (Строгая гео-релевантность term+city в `_matches` уже есть, применяется и к аудиторным.)

## collector.py

- `_below_follower_floor(post, local_mode=False)`: если `local_mode` → всегда False (не режем мелких).
  - Вызовы в collect_probe и comments передают `brand.local_mode`.
- `collect_geo`: топик-фильтр расширяется в local_mode — включает `audience_terms` помимо niche/category/sphere.

## pipeline.py

`classify_and_draft`: в local_mode прогон `classify_ads_batch` остаётся; off-audience трим — расширяем промпт батча, чтобы помечать `is_ad=true` также для контента, явно НЕ относящегося к ЦА (для краткости: переиспользуем classify_ads_batch, передаём флаг/контекст ЦА). Минимально: оставляем ad-фильтр; off-audience — best-effort через тот же батч с добавленным критерием. (Если усложнит — отдельный проход later.)

## API plumbing

- `OnboardingBody` += `followers:int=0`, `local_mode:bool=False`, `audience_terms:list[str]=[]`.
- `BrandConfigBody` += `followers`, `local_mode`, `audience_terms` (Optional).
- onboarding: авто `local_mode = body.local_mode or (0 < followers <= 1000 and bool(geo))`.
- config: обновляет поля; rebuild_probes если изменились audience_terms/local_mode/geo/...
- `_brand_card` += followers, local_mode, audience_terms.

## Frontend

- `api.js createBrand(..., followers=0, local_mode=false, audience_terms=[])`.
- `AIWizard` Шаг 1: тумблер «Локальный бизнес — широкая выдача по городу» (чекбокс; авто-вкл если followers≤1000 && geo), и если включён — TagGroup «Темы аудитории». Передаются в createBrand/config.
- `Settings`: тот же тумблер (если время).

## Error handling
- Claude без audience_terms → []; local_mode работает на нише+категориях.
- followers неизвестны (0) → авто local_mode НЕ включается, тумблер доступен.
- Старые бренды → миграции дефолтят (local_mode False).

## Tests
- авто local_mode: followers=500+geo→True; 5000→False; 0→False.
- `_below_follower_floor(post, local_mode=True)` → False для 50 подп.
- `_rebuild_probes` local_mode → аудиторные гео-пробы присутствуют (source niche, query содержит город).

## Files
| Файл | Изменение |
|------|-----------|
| `backend/radar/models.py` | followers, local_mode, audience_terms + геттер |
| `backend/radar/db.py` | миграции |
| `backend/radar/api.py` | Claude промпты, _rebuild_probes аудиторные пробы, onboarding/config авто local_mode, brand_card, scan followers |
| `backend/radar/collector.py` | follower-floor с local_mode, collect_geo topic расширение |
| `backend/tests/test_profile_scan.py` | тесты local_mode |
| `echo-app/src/services/api.js` | createBrand новые поля |
| `echo-app/src/components/app/AIWizard.jsx` | тумблер + темы аудитории |
