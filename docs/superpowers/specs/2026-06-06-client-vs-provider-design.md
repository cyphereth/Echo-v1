# Local-Mode Audience: Client vs Provider — Design

**Date:** 2026-06-06
**Status:** Approved

## Problem

В local_mode салон хочет видеть потенциальных КЛИЕНТОВ (обычных горожан), а не других мастеров/салонов (конкурентов, которые уводят клиентов). Текущий фильтр резал и тех, и других, и литеральный топик-фильтр выкидывал обычных людей («когда лето чувствуется» не содержит «лайфстайл»).

## Decisions

- Провайдеры (мастера/салоны/бизнес) → уводить в «Конкуренты» (`source=competitor`), не прятать — их комменты = потенциальные клиенты для перехвата.
- Клиенты (обычные горожане) → остаются в нише/аудитории.
- Различение клиент/провайдер = гибрид: дешёвые правила + Claude батч.
- В local_mode снять литеральный топик-фильтр в collect_geo (релевантность по персоне, не по совпадению слова).
- «тгк:» НЕ является сигналом провайдера.

## spam.py additions

```python
PROVIDER_NAME_HINTS = ["nails", "nail", "brows", "brow", "makeup", "lash", "studio",
    "beauty", "salon", "мастер", "master", "stylist", "barber", "manicure", "permanent"]
PROVIDER_PHRASES = ["запись", "записаться", "по записи", "записывайтесь", "прайс",
    "услуги", "директ для записи", "запись в директ", "коррекция", "наращивание",
    "свободные окошки", "свободное время", "адрес студии"]

def looks_like_provider_cheap(text: str, author: str) -> bool:
    a = (author or "").lower()
    if any(h in a for h in PROVIDER_NAME_HINTS):
        return True
    t = (text or "").lower()
    return any(p in t for p in PROVIDER_PHRASES)

def classify_providers_batch(texts: list) -> list:
    """Claude: per text, is this a service PROVIDER (master/salon/business) vs a
    regular person (potential client)? Returns list[bool] is_provider. Fail-open
    = all False (treat as clients — better show a client than lose one)."""
```
`classify_providers_batch`: model claude-haiku-4-5-20251001, numbered batch, JSON `[{"i":0,"is_provider":false}]`, retry 1, no-key → all False.

## pipeline.classify_and_draft

After normal classification, if `brand.local_mode`:
- collect niche-source mentions (just classified, not spam)
- cheap: `looks_like_provider_cheap` per mention
- batch Claude `classify_providers_batch` on the non-cheap ones
- provider (cheap OR claude) → `m.source = "competitor"`, `m.competitor = m.author`
- client → stays niche
- commit

(Existing `classify_ads_batch` ad/off-topic trim stays — hides dropshipper/marketplace spam, not self-promo clients.)

## collector.collect_geo

In local_mode skip the literal `_on_topic` term filter (persona classification in pipeline handles relevance). Non-local: keep literal topic filter as-is.

## Non-local brands

No client/provider classification — niche stays niche.

## Tests
- `looks_like_provider_cheap`: author "aiva.nails" → True; "запись в директ, прайс" → True; "когда лето чувствуется" + author "lu_happy13" → False; "тгк: мойканал" alone → False.
- `classify_providers_batch` no key → all False.
- pipeline local_mode: niche provider → source becomes competitor; niche client stays niche. (mock Claude / no-key path)

## Files
| Файл | Изменение |
|------|-----------|
| `backend/radar/spam.py` | looks_like_provider_cheap, classify_providers_batch |
| `backend/radar/pipeline.py` | local_mode client/provider routing |
| `backend/radar/collector.py` | collect_geo: skip literal topic filter in local_mode |
| `backend/tests/test_profile_scan.py` | provider tests |
