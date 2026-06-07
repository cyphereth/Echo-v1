# Brand disambiguation + intent reach

**Date:** 2026-06-07
**Status:** approved

## Problem

Two issues surfaced after the sphere-aware noise filter shipped, both about *relevance
to the brand's sphere*:

1. **Homonym noise in the brand lane.** Brand-name keywords can be homonyms — "тануки"
   is also a video-game character / folklore animal, not just the sushi chain. The
   recent change made brand-lane mentions (`source="brand"`) bypass the noise judge
   entirely (to stop it hiding real, promotional-toned brand mentions). The side effect:
   an off-topic game post tagged `#tanuki` matched the brand keyword and is shown as a
   brand mention. The blanket bypass swung too far.

2. **Reach is too literal.** Monitoring only catches posts that name the brand or its
   narrow niche. For a food/общепит brand it is valuable to also reach people with
   *intent* — "где поесть", "куда сходить на выходных", "посоветуйте ресторан" — i.e.
   audience the brand could engage natively. (General principle for all spheres; food is
   the current example. See memory `echo-keyword-niche-strategy`.)

## Goal

Keep real brand mentions (any tone) while dropping off-topic homonyms, and widen niche
reach with sphere-appropriate intent phrases that surface as engagement opportunities.

## Part 1 — Brand-lane disambiguation (replaces the blanket bypass)

- New in `backend/radar/spam.py`: `disambiguate_brand_batch(texts, brand_name, sphere)`
  → `list[bool]` where `True` = off-topic homonym (hide). Plus a testable
  `_build_disambiguate_payload(texts, brand_name, sphere)`.
  - Prompt framing (default-keep): "Каждый текст упоминает «{brand_name}». Это про бренд
    в сфере «{sphere}» — или ДРУГОЕ значение слова (игра, животное, имя, оффтоп)? Помечай
    off-topic ТОЛЬКО при явной уверенности; при сомнении — оставляй." JSON key
    `is_offtopic`.
  - Fail-open: no API key / error / parse failure → all `False` (keep everything).
- `backend/radar/pipeline.py` `classify_and_draft`: remove the `m.source != "brand"`
  blanket skip. Instead:
  - brand-lane mentions → `disambiguate_brand_batch(...)`; `is_offtopic` → `is_spam=True`.
  - niche/competitor mentions → existing `classify_ads_batch(texts, sphere)` noise judge.
  - Both run per-brand, so `brand.name` and `brand.sphere` are in scope.

## Part 2 — Intent reach

- **Generation.** Add an instruction to the niche portion of both suggest prompts
  (`_build_suggest_payload` and `_profile_with_claude` in `backend/radar/api.py`): include
  sphere-appropriate **intent phrases** in `niche_keywords` — recommendation-seeking and
  "where to go" phrasing for the sphere (food → «где поесть», «куда сходить на выходных»,
  «посоветуйте ресторан», «где поужинать»). No schema change — they are niche terms and
  become niche probes.
- **Opportunity labelling.** A niche mention that reads as a recommendation-seeking /
  intent post gets a stronger opportunity hint so it stands out in the feed. No new field
  — it upgrades the existing `opportunity` text.
  - New cheap helper `_looks_like_intent(text)` in `backend/radar/pipeline.py`: True when
    the text is recommendation-seeking — contains a "?" AND any cue from
    {«куда», «где», «посовет», «подскажите», «что попробовать», «что выбрать», «стоит ли»,
    «который лучше»}. Sphere-agnostic.
  - `opportunity_for(m)`: for `source == "niche"` when `_looks_like_intent(m.text)` →
    "Человек ищет, куда пойти / что выбрать — отличный момент предложить бренд нативно."
    Otherwise the existing niche hint. brand/competitor hints unchanged.

## Out of scope (unchanged)

- The slim cheap layer (`looks_like_ad_cheap`), `_ensure_name_in_keywords`, scoring, geo,
  collect loop, frontend.
- No new DB columns. Intent terms ride the existing niche lane; intent posts ride the
  existing `opportunity` field.

## Testing

- `_build_disambiguate_payload`: payload `system`/`user` includes the brand name and the
  sphere; texts are numbered in.
- `disambiguate_brand_batch`: no API key → returns all `False` (fail-open, keep).
- `_looks_like_intent`: "посоветуйте, где вкусно поесть?" → True; "купил роллы вчера,
  вкусно" → False; "куда сходить на выходных?" → True.
- `opportunity_for`: a niche intent mention → the stronger hint; a plain niche mention →
  the existing hint; a competitor mention → unchanged.

## Trade-off

The brand lane goes through the LLM again (disambiguation), so a few more batched Haiku
calls. Mitigated by: batching, fail-open, and **default-keep** framing — the judge only
hides on confident off-topic, so it will not re-introduce the "hides real mentions"
regression that motivated the original bypass.
