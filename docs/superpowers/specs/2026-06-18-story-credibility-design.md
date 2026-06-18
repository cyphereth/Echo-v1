# Story Credibility — Design

**Date:** 2026-06-18
**Status:** Approved (design)
**Depends on:** stories pipeline + news-mode (in `main`).

## Goal

Give each story a trust signal, the core of the "independent news, only facts"
positioning:

1. **Cross-verification** (deterministic) — a story is *verified* when it's
   backed by ≥N independent sources.
2. **Fake-detection** (LLM, opt-in) — flag stories that show signs of
   fabrication / propaganda / manipulation.

## Non-Goals

- Source-reputation scoring / allow-lists (later).
- Auto-running fake-detection on every story (cost) — manual trigger + a gated
  scheduler pass only.

## Data model — Story (new columns, all nullable/defaulted; migrated in db.py)

- `source_count: int = 0` — distinct independent sources behind the story.
- `verified: bool = False` — `source_count >= VERIFY_MIN_SOURCES` (default 3).
- `credibility: str = "unrated"` — LLM verdict: `unrated | credible | suspect`.
- `credibility_note: str = ""` — short LLM rationale (Russian).

## Cross-verification — `stories._recompute_verification(session, story_id)`

- Distinct sources = distinct `Mention.author` over mentions whose
  `incident.story_id == story_id` (web author = domain, telegram = @channel),
  ignoring blank authors.
- Set `story.source_count` and `story.verified = count >= VERIFY_MIN_SOURCES`.
- Called inside `update_stories` for each touched story, next to
  `_recompute_points` + `detect_anomaly`. Deterministic, no network.

## Fake-detection — `credibility.assess_credibility(session, story)`

- Gather representative text: the story's incident titles + up to N mention
  excerpts.
- `llm.complete(system, user)` with a verification-analyst system prompt; expect
  a JSON object `{"verdict": "credible"|"suspect", "note": "<short ru>"}`.
- Parse leniently (find first `{...}`); on unparseable output default to
  `unrated` with the raw text trimmed into the note.
- Set `story.credibility` + `story.credibility_note`. Raises
  `llm.LLMNotConfigured` when no key (caller maps to 503).
- Opt-in: never called automatically except via a gated scheduler pass
  (`ENABLE_FAKE_DETECTION`, default off) targeting anomalous/unverified stories.

## API

- `StoryOut` += `source_count`, `verified`, `credibility`, `credibility_note`.
- **Fix:** `GET /stories/{id}` currently calls `_owned_brand(st.brand_id)` and
  404s for topic stories (brand_id NULL). Branch on owner (topic vs brand),
  mirroring `list_stories`.
- `POST /stories/{id}/assess` → `assess_credibility`, returns updated `StoryOut`;
  503 when LLM not configured. Ownership-checked.

## Frontend (Stories.jsx)

- Story list item + detail header show badges:
  - verified: `✓ N источников` (green) vs `± N` (muted) when below threshold.
  - credibility: `⚠ требует проверки` when `suspect`.
- Detail pane adds an "Оценить достоверность" button calling
  `POST /stories/{id}/assess` (mirrors the digest button), then re-renders.

## Error Handling

- Verification is pure-DB, best-effort inside `update_stories` (wrapped like
  the anomaly step).
- `assess_credibility` failures: `LLMNotConfigured` → 503; malformed LLM output
  → `unrated` + note, never crash.

## Testing

- `_recompute_verification`: distinct-source count, `verified` flips at the
  threshold, blanks ignored.
- `update_stories` populates `source_count`/`verified`.
- `assess_credibility`: monkeypatched `llm.complete` → parses verdict + note;
  malformed output → `unrated`; no key → raises.
- API: `StoryOut` carries the new fields; `POST /stories/{id}/assess` updates;
  `GET /stories/{id}` works for a **topic** story (regression for the ownership
  fix).
