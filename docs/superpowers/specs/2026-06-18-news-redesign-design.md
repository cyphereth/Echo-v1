# News-Mode Redesign — Design

**Date:** 2026-06-18
**Status:** Approved (design)
**Depends on:** news-mode + topic TG ingestion + story credibility (all in `main`).

## Problem

News mode reuses brand-mode machinery, which leaks and undermines the
"independent news, only facts" promise:

1. **Junk sources.** Topic channel discovery searches a single generic keyword,
   pulling homonyms/noise: `инфляция` → "инфляция счастья" (psychology),
   `переговоры` → negotiation-skills/psychology/leasing channels, plus FX-rate
   bot channels and promo/scam. The product's core (good first-hand news) fails
   at source selection.
2. **Brand UI leaks.** The news feed shows brand tabs **Мой бренд / Конкуренты /
   Ниша** and defaults to the (always-empty) brand tab.
3. **Meaningless metrics.** Story view shows **sentiment ("тональность")**, a
   brand concept; topic mentions aren't tone-classified so it's ~0 noise.

## Goal

Make news mode genuinely about news: vetted sources (hybrid curation), an
events-first UI with no brand concepts, transparent + editable source lists, and
a story view built around corroboration and spike — not sentiment.

## Decisions (from brainstorming)

- Sources: **hybrid** — curated seed + "similar channels" graph + LLM gate for
  newcomers.
- News mode lands on **Сюжеты** (events), the post feed is secondary.
- Story view: **event summary + spike + source growth + source list**, drop
  sentiment.
- **Editable** per-topic sources panel (see list with volume, remove junk, add
  own channel).

---

## Block 1 — Source quality (hybrid) `[backend]`

**Files:** `radar/seed.py`, `radar/collector.py`, `radar/llm.py` (reuse).

- `seed.py`: `TOPIC_SEED_CHANNELS: dict[str, list[str]]` — vetted news channels
  per default topic name (Экономика / Геополитика / Военное). Best-effort
  handles; each is validated at add time, so wrong guesses are skipped, not
  fatal.
- `collector.ensure_topic_channels_discovered` rewrite:
  1. **Seed:** add seed handles for the topic that aren't already probes.
  2. **Graph (trusted):** when seeds exist, expand via `channel_recommendations`
     off the seed handles only, bounded by `TOPIC_RECS_PER_SEED` (default 5).
     Recommendations of a vetted news channel are news-adjacent, and the API
     returns only handles (no title to gate on), so these are added directly —
     the small bound keeps it flood-safe.
  3. **Keyword discovery (gated):** only when the topic has **zero seeds** (user
     search-topics), run `discover_channels` per keyword; each result has a
     title, so pass it through the **LLM gate** `classify_source(title, topic)`
     to kill homonyms/junk ("инфляция счастья", psychology "переговоры",
     FX-bots, promo). Seeds skip the gate (already vetted).
- New helper `collector.classify_source(title, topic) -> bool` calling
  `llm.complete` with a strict YES/NO system prompt; on `LLMNotConfigured`
  degrade to the title term-hit filter (current behavior) so it still runs
  without a key.
- Anti-flood from the prior sprint stays (cap + rotation + circuit breaker).

**Data flow:** seed handles + (recommendations off seeds, LLM-gated) →
`Probe(topic_id, kind="channel")` → existing `collect_probe` → mentions →
stories.

**Testing:** seed channels added without LLM gate; graph newcomers kept only
when `classify_source`→True (monkeypatched); without LLM key falls back to
title filter; idempotent (no dup probes); existing channel probes untouched.

## Block 2 — Junk cleanup `[backend, one-off + ongoing]`

**Files:** `radar/maintenance.py` (new), one-off invocation.

- `purge_topic_sources(session, topic_id=None, only_unvetted=True)`: delete
  `kind="channel"` telegram probes that are **not** in the topic's seed list
  (and optionally their orphaned mentions/incidents), so the garbage set is
  reset. Re-seeding (Block 1) repopulates from vetted seeds.
- Run once against the live DB after Block 1 lands. Ongoing junk is prevented by
  the LLM gate.

**Testing:** purge removes non-seed channel probes + their mentions, keeps seed
ones and keeps web/global probes; idempotent.

## Block 3 — Editable sources panel `[backend + frontend]`

**Files:** `radar/api.py`, `echo-app/src/services/api.js`,
`echo-app/src/components/app/Sources.jsx` (new) + nav.

- `GET /topics/{id}/sources` → list of `{id, kind, handle, title, mention_count}`
  for the topic's channel/global probes plus distinct web domains (read-only for
  web). Ownership-checked.
- `POST /topics/{id}/sources {handle}` → validate via provider (`linked_chat`/
  `get_entity` existence) and add a `kind="channel"` probe; 400 if invalid, 409
  if exists.
- `DELETE /topics/{id}/sources/{probe_id}` → delete the probe and its mentions
  for that author (best-effort), 404 if not owned.
- Frontend: **Источники** screen/panel in news mode — table of sources with
  mention volume, a remove (✕) per row, and an "add channel" input.

**Testing (API):** list returns probes + counts; add validates + dedups; delete
removes probe + its mentions; ownership enforced (403 for other user's private
topic).

## Block 4 — News UX: events-first, no brand lanes `[frontend]`

**Files:** `echo-app/src/pages/AppPage.jsx`, `components/app/Shell.jsx`,
`components/app/Feed.jsx`.

- When `mode === 'news'`: default `screen = 'stories'` (not `feed`); nav order
  puts Сюжеты first, then Лента (posts), Дайджесты, Источники.
- News feed: render posts as a single chronological list **without** the
  brand/competitor/niche tabs. Implement via a `lanes={false}` prop (or a
  dedicated `NewsFeed`) so brand Feed keeps its tabs unchanged.
- Remove the empty default brand tab in news mode.

**Testing:** brand mode Feed unchanged (tabs present); news Feed renders flat
list (no tabs) — covered by a light component check / manual run.

## Block 5 — News story view `[backend + frontend]`

**Files:** `radar/api.py` (StoryDetailOut), `radar/stories.py` or new
`radar/story_view.py`, `components/app/Stories.jsx`.

- **Drop** the sentiment line from the chart and the "тональность" meta.
- **Event summary:** reuse the `credibility`/`digests` LLM pattern —
  `summarize_story` produces a 1–2 sentence "what happened", stored on
  `Story.summary` (new column, default ""). Generated **on demand** via
  `POST /stories/{id}/summarize` (a button, like assess) so there is no
  surprise auto-LLM cost; `StoryDetailOut.summary` returns the stored value
  (empty until generated). Degrades on `LLMNotConfigured` (503).
- **Sources list:** per-story distinct sources with first-seen time
  (`min(created_at)` per author), earliest highlighted ("первым сообщил X").
  New `StoryDetailOut.sources: [{author, first_seen, count}]`.
- **Chart:** keep volume bars (spike); replace the sentiment line with a
  **source-count** line per bucket (corroboration growth) — `StoryPoint`
  already has `source_count`.
- Keep verified/credibility badges (Block done earlier).

**Testing:** StoryDetailOut includes `sources` (distinct authors, first_seen,
sorted); summary present when LLM monkeypatched, omitted on `LLMNotConfigured`;
points still serialize.

---

## Non-Goals

- Source reputation scoring beyond the LLM yes/no gate.
- Touching brand mode behavior (feed tabs, sentiment) — brand path unchanged.
- Auto-running summaries/fake-detection on every story (cost) — on-demand.

## Build Order

1. Block 1 (source quality) + Block 2 (cleanup) — the root fix.
2. Block 3 (sources panel).
3. Block 4 (events-first UX, drop lanes).
4. Block 5 (news story view).

Each block: TDD, its own commit, full suite green, brand path untouched.

## Error Handling

- Discovery/LLM gate fail-open (degrade to title filter; never crash the pass).
- Source add validates and returns 400/409; delete is best-effort.
- LLM features (gate, summary) degrade gracefully without `LLM_API_KEY`.
