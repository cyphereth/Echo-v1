# Sphere-aware noise filtering

**Date:** 2026-06-06
**Status:** approved

## Problem

The spam/noise filter is global and tuned for **marketplaces / delivery / e-commerce**
(Ozon-style): `SALES_PHRASES` like "артикул", "промокод", "оптом", "в наличии";
`SELLER_NAME_HINTS` like `wb_`, `ozon_`, `_shop`; and `MAX_HASHTAGS=3`. Applied to a
brand in a different sphere it misfires badly.

Concrete failure (brand `tanuki.official`, id=10, a sushi restaurant chain): collect
found 66 posts and **all 66 were hidden as spam** → empty feed. Sampling shows food
content routinely trips `tags>3`, `len>150`, and "промокод" — all normal for food, all
treated as marketplace spam. (A second, related defect — the brand's `keywords` held
generic niche terms, not the brand name — is addressed in the implementation plan, see
"Related fix".)

## Goal

Make noise detection depend on the brand's **sphere**, so "промокод" and many hashtags
are normal for a restaurant while dropshipper spam is still caught for a marketplace —
without maintaining a hand-curated rule set per sphere.

## Approach: hybrid (universal cheap layer + sphere-aware AI judge)

Two layers, with the brand's `sphere` (free-text brand DNA, already stored) flowing into
the AI layer.

### Layer 1 — `looks_like_ad_cheap` (collect time, free, universal)

Keep only what is junk for **every** sphere:
- **Too-short text** (`len < MIN_LEN`, currently 20) — "огонь", "👍".
- **Dropshipper/seller handles** (`SELLER_NAME_HINTS`: `wb_`, `ozon_`, `_shop`, `_opt`,
  `artikul`, etc.) — junk regardless of sphere.

Remove from the cheap layer (these are sphere-specific judgments, delegated to Layer 2):
- `SALES_PHRASES` matching (marketplace vocabulary).
- The `MAX_HASHTAGS` rule.
- The upper length bound (`MAX_LEN`) — long captions are normal for food/lifestyle.

`_below_follower_floor` (tiny-account filter) is unchanged — it is about account size,
not sphere.

### Layer 2 — `classify_ads_batch` (pipeline, batched Haiku, sphere-aware)

Reframe from generic "ad vs human" to a sphere-aware noise call:

> For a brand in sphere "{sphere}", is each text NOISE (unrelated promo, a different
> seller, off-topic) or a RELEVANT mention/signal? Mark only noise.

- Add a `sphere: str` parameter. `classify_and_draft` already runs per-brand
  (`classify_and_draft(session, brand_id)` with `brand` in scope, pipeline.py:42), so it
  passes `brand.sphere`. Empty sphere → generic framing.
- Fail-open is unchanged: no API key or any error → returns all-`False` (nothing hidden).

**Effect on Ozon:** marketplace noise (dropshippers) is still caught — now via the
sphere-aware judge with `sphere="маркетплейс / e-commerce"`, plus the seller-handle
hints that stay in Layer 1. So marketplace brands do not regress; the hardcoded
marketplace phrases simply move into the AI's per-sphere judgment.

## Related fix (implementation plan, not this spec's core)

So the Тануки feed is actually relevant, the plan also includes:
1. `_profile_with_claude` prompt: instruct that `keywords` = brand-name variants
   (RU+Latin, incl. the scanned handle), mirroring `_build_suggest_payload`. Today the
   prompt describes niche/category/audience but never says what `keywords` should be.
2. Safety net on brand save: always ensure the brand name is present in `keywords`, so
   the brand lane always searches the name even if the AI omits it (defense in depth).
3. Retrofit brand id=10: set real name-variant keywords, re-collect, confirm the feed
   shows relevant Тануки mentions.

## Out of scope (unchanged)

- `_below_follower_floor`, scoring, geo-relevance, the collect loop, the frontend.
- The local-mode provider routing (`looks_like_provider_cheap` /
  `classify_providers_batch`) — already sphere-specific for beauty/services, left as-is.

## Testing

- `looks_like_ad_cheap` after changes: short text → spam; dropshipper handle → spam;
  food-style post with 6 hashtags + "промокод" → NOT spam; long (>150 char) post → NOT
  spam.
- `classify_ads_batch` / sphere payload: no API key → fail-open all-`False`; the request
  payload includes the brand's sphere text.

## Trade-off

The AI judge now sees more posts (Layer 1 pre-filters less) → more LLM calls. They are
batched on Haiku in the background pipeline — acceptable. If volume becomes a problem, a
cheap pre-cap is a future option, not part of this work.
