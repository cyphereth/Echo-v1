# City Explorer — Design Spec

**Date:** 2026-06-10
**Status:** Approved (pending spec review)
**Branch:** `feat/city-explorer` (depends on `feat/socialcrawl-provider`)

## Goal

A standalone "City Explorer" tool: enter any city, get an LLM-generated summary of
what people there are interested in — top themes, what they want/seek, mood, and
emerging trends. Aggregated insight, **not** a post feed. Data comes from TikTok
and Instagram via the SocialCrawl provider.

## Why / Context

Echo monitors brands. This feature is orthogonal: ad-hoc audience research for any
city, to understand local interests and demand. It reuses two existing building
blocks — `SocialCrawlProvider.search` (data) and the Claude LLM via `LLM_API_KEY`
(summarization) — and adds a thin pipeline plus a cached report store.

**Constraint:** SocialCrawl has no true city-level geo search. "By city" is
implemented as keyword/hashtag search for city terms (posts mentioning/about the
city), which is the achievable proxy for local interests — not a precise geo-filter.

## Non-Goals (YAGNI)

- No post feed UI (output is the summary only).
- No per-user report ownership (the report cache is global — it's a research tool;
  this also maximizes credit savings on repeat lookups).
- No topic/niche focus input in v1 (city name only).
- No scheduled/automatic city refresh.

## Architecture

Flow for `POST /explore/city {city}`:

```
city → normalize → cache lookup (CityReport)
  ├─ fresh hit (< 7 days, no refresh) → return stored summary
  └─ miss / stale / refresh:true:
       build_city_queries(city)            # ~4 queries across TikTok + IG
       → SocialCrawlProvider.search(...)   # per query (≈4 credits)
       → aggregate_posts(...)              # dedupe, rank, take top ~40
       → summarize_city(city, posts)       # LLM → structured JSON
       → upsert CityReport → return
```

### Components

**`backend/radar/explore.py`** (new) — pure-ish pipeline, no FastAPI:
- `normalize_city(city) -> tuple[str, str]` — returns `(key, hashtag)`.
  - `key`: `city.strip().lower()` (cache key + display source).
  - `hashtag`: `key` with spaces/hyphens removed (e.g. `санкт-петербург` → `санктпетербург`).
- `build_city_queries(city) -> list[tuple[str, str, str]]` — list of
  `(platform, kind, query)`:
  - `("tiktok", "keyword", city)`
  - `("tiktok", "keyword", f"куда сходить {city}")`
  - `("tiktok", "keyword", f"что попробовать {city}")`
  - `("instagram", "hashtag", hashtag)`
- `aggregate_posts(posts) -> list[dict]` — dedupe by `post_id`, sort by
  `(likes + views//100)` desc, take top 40, return compact dicts
  `{text, likes, views, hashtags}` (text truncated to 280 chars).
- `summarize_city(city, agg_posts) -> dict` — LLM call (mirrors `drafts.py`:
  `LLM_API_KEY`, `LLM_API_URL`, `x-api-key`/`anthropic-version` headers, model
  `claude-haiku-4-5-20251001`). Returns the JSON below, or `{}` on no-key/error.
- `run_city_search(provider, city) -> tuple[list[dict], int, list[str]]` — runs
  `build_city_queries`, calls `provider.search` per query (per-query try/except so
  one failure doesn't abort), aggregates, returns `(agg_posts, post_count, platforms_used)`.

**LLM output JSON schema** (validated defensively; missing keys default to empty):
```json
{
  "overview": "1-2 sentence mood of the city",
  "themes": [{"title": "Еда и кафе", "description": "what specifically people discuss"}],
  "wants": ["what people seek/ask for — where to go, what to try…"],
  "trends": ["what is gaining momentum now"],
  "sentiment": {"overall": "positive|neutral|negative", "note": "why"},
  "top_hashtags": ["#…"]
}
```

**`backend/radar/models.py`** — add `CityReport`:
```python
class CityReport(Base):
    __tablename__ = "city_reports"
    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    city:        Mapped[str]      = mapped_column(Text)        # normalized key (unique-ish lookup)
    display_city:Mapped[str]      = mapped_column(Text, default="")  # original user input
    summary:     Mapped[str]      = mapped_column(Text, default="{}") # JSON string of the schema above
    post_count:  Mapped[int]      = mapped_column(Integer, default=0)
    platforms:   Mapped[str]      = mapped_column(Text, default="")  # comma-joined, e.g. "tiktok,instagram"
    created_at:  Mapped[datetime] = mapped_column(default=_now)
```
Auto-created by `Base.metadata.create_all` (new table — no `_MIGRATIONS` row, same as
`EngagementLog`). Cache freshness: a report is reusable if `created_at` is within
`CITY_REPORT_TTL_DAYS` (default 7). On refresh, insert a new row (history is the set
of rows per city, newest wins).

**`backend/radar/api.py`** — two endpoints, `current_user` auth:
- `POST /explore/city` body `{city: str, refresh: bool = False}`:
  1. `key, _ = normalize_city(city)`; reject empty city → 400.
  2. Unless `refresh`, look up newest `CityReport` for `key`; if within TTL, return it
     with `{cached: true, created_at}`.
  3. Else: `provider = _get_provider()`; `agg, n, platforms = run_city_search(provider, city)`.
     If `n == 0` → 502 "no posts found / provider unavailable".
  4. `summary = summarize_city(city, agg)`; if `{}` → 503 "LLM unavailable (set LLM_API_KEY)".
  5. Insert `CityReport`, return `{city, display_city, summary, post_count, platforms, created_at, cached: false}`.
- `GET /explore/cities` → recent reports (latest per city, limit ~30):
  `[{city, display_city, created_at, post_count}]` for the history sidebar.

**Frontend** — `echo-app/src/components/app/CityExplorer.jsx` (+ `cityexplorer.module.css`):
- City text input + "Исследовать" button → `POST /explore/city`.
- Renders summary: overview banner, theme cards (title + description), "Что хотят"
  list, "Тренды" list, sentiment chip, top-hashtags row.
- "Сводка от {date} · Обновить" affordance (Обновить re-posts with `refresh:true`).
- History sidebar from `GET /explore/cities`; clicking a city loads its cached report.
- Wire a nav entry in `Shell.jsx`; add `exploreCity(city, refresh)` and
  `getCityReports()` to `services/api.js`.

## Data Flow Summary

1. User types city → frontend `POST /explore/city`.
2. Backend cache check → hit returns instantly (free).
3. Miss → SocialCrawl searches (TikTok×3 + IG×1 ≈ 4 credits) → aggregate → LLM summary.
4. Store `CityReport` → return to frontend → render cards.
5. History sidebar lists prior cities; refresh forces a new live run.

## Error Handling

- Empty/blank city → 400.
- Provider returns 0 posts (or 402 no credits) → per-query failures are caught;
  if total posts == 0 → 502 with a clear message.
- LLM no key or parse failure → `summarize_city` returns `{}` → endpoint 503 with
  guidance to set `LLM_API_KEY`. No partial/garbage report is stored.
- LLM JSON parse: defensive — unknown/missing keys default to empty lists/strings;
  retry once on `JSONDecodeError` (mirrors `evaluate_opportunity`).

## Testing (no network / no credits)

`backend/tests/test_explore.py`:
- `normalize_city`: lowercasing, trim, hashtag strips spaces/hyphens
  (`"Санкт-Петербург"` → `("санкт-петербург", "санктпетербург")`).
- `build_city_queries`: returns the 4 expected (platform, kind, query) tuples with the
  city interpolated.
- `aggregate_posts`: dedupes by post_id, ranks by engagement, caps at 40, truncates text.
- `run_city_search`: with a fake provider (returns canned `Post`s), verifies aggregation
  and that a failing platform query is skipped without aborting.
- `summarize_city`: monkeypatch `httpx.post` to return a canned envelope; verify JSON
  parsed into the schema; verify `{}` on no-key and on parse error.
- Cache logic (endpoint-level, in-memory session): fresh report returns `cached:true`
  without calling the provider; stale/refresh triggers a live run (provider monkeypatched).

## Credit / Cost Notes

- ~4 SocialCrawl credits per **new** city report; cached views are free.
- Requires a funded SocialCrawl key (currently 0 credits) to run live; LLM key verified working.

## File Manifest

- Create: `backend/radar/explore.py`
- Modify: `backend/radar/models.py` (+`CityReport`)
- Modify: `backend/radar/api.py` (+`POST /explore/city`, +`GET /explore/cities`)
- Create: `echo-app/src/components/app/CityExplorer.jsx`, `cityexplorer.module.css`
- Modify: `echo-app/src/components/app/Shell.jsx` (nav entry), `echo-app/src/services/api.js`
- Create: `backend/tests/test_explore.py`
