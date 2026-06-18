# Topic TG Ingestion — Design

**Date:** 2026-06-18
**Status:** Approved (design)
**Depends on:** news-mode framework (Topic + Scope + topic web pass), already in `main`.

## Goal

News-mode topics ingest from Telegram, not just the web: global message search
(`_global_search`) over topic keywords plus reading discovered public channels
(`discover_channels` → `_read_channel`). Results flow into the existing
incident/story pipeline scoped by `topic_id`. **No account auto-join** this
sprint — only public, read-only access.

## Non-Goals

- Auto-joining private / discussion groups (FloodWait + account-ban risk).
- Cross-source verification, fake-detection (separate sub-projects).
- Per-topic digest scheduling (manual `POST /topics/{id}/digest` already works).

## Architecture

Reuse the `Probe` infrastructure (watermark, rotation, scheduler). `Probe`
already has a nullable `topic_id`; `brand_id` is now nullable too. Telegram
probes for a topic carry `topic_id` (brand_id NULL) and one of:

- `kind="global"` → `provider.search(query, "global")` → `_global_search` over the
  topic's top keywords.
- `kind="channel"` → `provider.search(handle, "channel")` → `_read_channel` of a
  discovered public channel.

The existing generic `_run_once` probe loop joins `Brand` and filters
`Brand.auto_collect`, so it will **not** pick up topic probes — the brand path
stays untouched. Topic probes are collected by a dedicated scheduler pass.

### Components

1. **`scope_for_probe(session, probe) -> Scope`** (in `scope.py`)
   Resolve a probe's owner: `topic_id` → `scope_for_topic`, else `brand_id` →
   `scope_for_brand`. Used by the generalized collector.

2. **Generalize `collect_probe(session, probe, provider)`** (`collector.py`)
   Replace the hard `session.get(Brand, probe.brand_id)` with
   `scope_for_probe`. Branch on `scope.kind`:
   - **brand**: unchanged — `_matches(post, brand, probe)`, competitor label,
     follower floor, `local_mode`. Brand behavior is byte-identical.
   - **topic**: relevance via `_term_hit(post.text, [t.lower() for t in
     scope.niche_keywords])` — the same morphology-aware gate `collect_web`
     uses; empty terms → keep all. No competitor label, no follower floor.
     `mention.source = probe.source` ("niche").
   Shared tail (age ≤ 7d, cheap ad/spam, `_upsert_mention(scope)`, snapshot,
   watermark) stays common.

3. **`ensure_topic_channels_discovered(session, topic, provider, min_chan=6, max_add=30)`**
   (`collector.py`)
   If the topic has fewer than `min_chan` `kind="channel"` telegram probes:
   run `discover_channels(q)` for each top topic keyword, keep channels whose
   title hits the topic's terms (`_term_hit`), optionally expand 1 hop via
   `channel_recommendations`, and store new `Probe(topic_id, platform="telegram",
   kind="channel", query=handle, source="niche", label=title)`. Fail-open per
   query; no-op once enough exist. Capability-guarded (`hasattr`).

4. **`ensure_topic_global_probe(session, topic)`** (`collector.py`)
   Idempotently ensure one `Probe(topic_id, platform="telegram", kind="global",
   query=<top keywords joined>, source="niche")` exists for the topic.

5. **`_run_topic_tg_pass(session, tg_provider)`** (`scheduler.py`)
   For each `Topic` with `auto_collect=True`: `ensure_topic_channels_discovered`
   + `ensure_topic_global_probe`, then collect that topic's telegram probes
   (`kind in ("global","channel")`) via the generalized `collect_probe`, then
   `update_stories(scope_for_topic(t))`. Best-effort per probe/topic.
   Wired into `_maybe_collect_topic_tg` on the chat worker-thread cadence
   (`INTERVAL_CHATS`), guarded by `tg_provider is not None`.

## Data Flow

topic keywords → `discover_channels` / `_global_search` → `Post`s →
`collect_probe` (topic relevance filter, spam, age) → `_upsert_mention(topic_id)`
→ `update_stories(scope_for_topic)` → stories / `/inbox?topic_id` /
`/topics/{id}/digest` (all already topic-aware).

## Ownership

Default global topics (`user_id=None`) own shared probes — one discovery serves
every user. Private search-topics own their own probes. This matches the
existing topic-ownership model; no new authz.

## Error Handling

- Fail-open per channel/probe (existing `collect_probe` / `collect_chats`
  pattern); watermark is **not** advanced on failure.
- Discovery wrapped in try/except per query.
- Provider-capability guards: skip if the provider lacks
  `discover_channels` / `channel_recommendations` / global search.

## Testing

- `scope_for_probe` resolves topic vs brand.
- `collect_probe` with a topic probe + fake provider: stores topic mentions,
  filters off-topic posts, respects watermark; **brand probe path unchanged**
  (existing tests stay green).
- `ensure_topic_channels_discovered`: creates channel probes from a fake
  `discover_channels`, filters by title term-hit, idempotent (no-op when full).
- `ensure_topic_global_probe`: idempotent single global probe.
- `_run_topic_tg_pass`: iterates `auto_collect` topics, collects + clusters
  (monkeypatched), skips when `tg_provider is None`.

## Risks

- Global search volume can be large → rely on topic term-match + age + spam
  filters (same gates as web/brand). Tunable via env if noisy.
- Telegram throttling → runs on the dedicated worker thread, watermarked,
  rotation via `next_run_at`.
