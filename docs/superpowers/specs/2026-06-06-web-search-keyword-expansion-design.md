# Web-search keyword expansion

**Date:** 2026-06-06
**Status:** approved

## Problem

A brand's monitoring coverage is only as wide as its term lists (keywords / niche /
competitors / audience). Today `/brands/suggest` generates very few terms (5–7
keywords, 3–5 competitors, 5–8 niche) from model knowledge alone, with
`max_tokens=300` and no web access. Few terms → few probes → few videos in the feed.

## Goal

Generate substantially more, relevant terms per brand using **real web search**, so
collection produces more data and more videos. Two deliverables:

1. **Feature** — rewrite `/brands/suggest` to use Anthropic's `web_search` server
   tool and emit large, relevance-validated term lists. Works automatically for any
   future brand.
2. **One-off** — enrich the user's existing real brands (Ozon, CafeBlanche) now via
   web research, written to the DB.

## Part A — `/brands/suggest` rewrite (backend)

File: `backend/radar/api.py` (`suggest_brand`, ~line 405).

- **Attach the web_search server tool** to the Claude request:
  `tools: [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]`.
  Anthropic runs the search loop server-side and returns the final answer in a single
  HTTP request — no client-side tool loop needed.
- **Raise `max_tokens` to ~4000.** Search reasoning + a large JSON payload do not fit
  in 300.
- **Expand the prompt.** Instruct the model to first search for the brand and its
  sphere (what it is, what it sells, real competitors, how people talk about it
  online), then return:
  - `keywords`: 20–30 (RU + Latin name variants, products, branded terms)
  - `niche_keywords`: 15–25
  - `competitors`: 10–15 — **only real, search-verified companies**
  - `audience_terms`: 15–20
  - `sphere`, `geo`, `category_terms`, `market` — unchanged semantics
  - Instruct the model to **rank by relevance and drop clearly irrelevant terms**
    (homonyms, noise).
- **Parse the response from the LAST text block** (after searching, the model writes
  its final JSON at the end), not the first. Keep the existing markdown-strip +
  `json.loads` + single-retry-on-parse-failure logic.
- Response shape returned to the frontend is unchanged (same keys); only the volume
  and quality of values change.

## Part B — enrich existing brands now (one-off)

For Ozon and CafeBlanche: research each brand and its sphere via web search, assemble
expanded term lists, and write them via `POST /brands/{id}/config` (which triggers
`_rebuild_probes`). Then run a collect pass to confirm the feed fills up.

## Out of scope (unchanged)

- Filters (spam / geo relevance / follower floor), `scoring.py`, the collect loop.
- Frontend: `AIWizard.jsx` renders terms with `TagGroup` (`list.map`) with no caps —
  larger lists just render taller. No change needed.

## Accepted trade-off

Each term becomes one probe per platform, and `collect_probe`
(`backend/radar/collector.py:112`) paginates to the watermark with **no per-run page
cap**. ~90 terms → ~180 probes → many more TikHub calls per collection run (slower
collection, faster quota burn). Decision: **keep collection as-is** (variant "a") to
maximize coverage. A soft per-probe page cap is a known future safeguard if
collection becomes too heavy, but is not part of this work.

## Notes / risks

- `LLM_API_KEY` is present in `backend/.env`, so the live call is testable.
- web_search billing is per-search + tokens; accepted by the user.
- Haiku 4.5 (`claude-haiku-4-5-20251001`) is the model already in use; confirm it
  accepts the `web_search_20250305` tool during implementation.
