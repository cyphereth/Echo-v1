# Intel Live Collection (Phase 1) — Design

**Date:** 2026-06-22
**Status:** Approved (brainstorm) — pending implementation plan
**Contour:** closed / military-intelligence (`intel` domain)

## 1. Context & Goal

The closed `intel` contour (situational center / stories / operational board) is built and serves the `/intel/*` contract, but on test data only. This feature makes **real data flow**: the operator curates Telegram channels and chats, the system collects from them via the existing Telethon infrastructure, tags each post by **side** (from the operator's file) and **direction** (auto, per post), and feeds the existing stories/board/center.

**Goal:** Live Telegram collection (channels + chats) into `IntelMention`, with side from a curated source file and per-post direction tagging (geo-keywords + LLM), so the intel screens show real conflict intelligence.

## 2. Scope & Non-Goals

**In scope (Phase 1):**
- Source intake from an operator-maintained file (channels + chats, each with side).
- Collection pass over those sources via the existing Telethon provider, wired into the scheduler.
- Hard noise filtering for chat-groups.
- Per-post direction tagging: inline geo-keyword pass + LLM enrichment pass.
- A military-slang lexicon (operator-maintained) used by the noise filter and as LLM context.
- Targeted `intel` model adjustments to support source-centric collection.

**Non-goals (deferred):**
- **Phase 2 — auto-suggestion of channels** (detect reposted/mentioned channels → approval queue). Separate spec.
- Geocoded map; broadening beyond military; in-UI slang decoder/tooltips (data model leaves room, UI later).
- Side inference (side is always operator-provided per source; never guessed).

## 3. Source Intake & Model Adjustments

The current `intel` models assume "everything belongs to a direction" (`IntelProbe.direction_id` and `IntelMention.direction_id` NOT NULL). Reality: a **source is a channel/chat with a side**; direction is determined **per post**. Targeted adjustments:

- **`IntelProbe` becomes "a source":** make `direction_id` **nullable** (a source is not tied to a direction). Fields used: `side` ("ru"|"ua", from the file), `kind` ("channel"|"chat"), `query` (the `@username` / `t.me/...` link), `title`/label, plus the existing `watermark`, `next_run_at`, `interval_sec`.
- **File intake (idempotent):** the operator sends a file; an ingest command upserts `IntelProbe` rows keyed by the source link. One source per line, e.g.:
  ```
  @rybar           | ru | channel
  https://t.me/xxx | ua | chat
  ```
  Side and kind come from the file — nothing is guessed. Re-ingesting updates side/kind without duplicating.
- **`IntelMention.direction_id`:** assigned by tagging (§5). A seeded special direction `key="unassigned"` ("Без направления") is the bucket for posts with no detected direction, so `direction_id` is always populated and clustering/board never break.
- **Military lexicon (`§6`):** stored so the noise filter and LLM can use it; operator-maintained file, idempotent ingest (same pattern as sources).

## 4. Collection Pass (channels + chats + noise filter)

Reuse the existing Telethon provider from the news TG infrastructure (operator's session already configured). New module `radar/intel/passes.py`:

- `run_intel_collect(session, tg_provider)`: rotate due `IntelProbe` sources by `next_run_at`; for each, read new messages since `watermark`; write `IntelMention` (`side` from the source); dedup on `(platform, post_id)` via per-row savepoint; advance `watermark`; preserve the **flood-wait circuit breaker**, per-tick cap, and adaptive interval (mirroring the news TG worker).
- **Channels** (`kind="channel"`): read channel posts — clean signal, light filter (length + spam).
- **Chats** (`kind="chat"`): read group messages — **hard noise filter**: drop stickers / one-word / link-only / spam (via `core.spam`); admit a message only if it contains a **geo-key OR a military-lexicon term** (the conflict-relevance gate). Without this, chat flood drowns the signal.

## 5. Direction Tagging (per post)

- **Inline geo pass (in the collector):** a geo-keyword dictionary per direction → set `direction_id` at write time; no match → `unassigned`. Guarantees `direction_id` is always set.
- **LLM enrichment pass** `radar/intel/tagging.py::retag_unassigned(session, limit)`: take recent `unassigned`/ambiguous mentions, ask the LLM "which direction (or none)", update `direction_id`. Batched (token control). **Skipped when no LLM key is configured.** Receives the military lexicon as glossary context so it understands slang.
- **Geo dictionary:** seeded starter set per direction (kursk: Курск/Суджа/Глушково/Коренево; zaporizhzhia: Орехов/Работино/Каменское; …), operator-extensible.
- **Tick order:** collect → inline geo-tag → LLM retag → cluster per direction (incl. `unassigned` as its own bucket) → existing stories/credibility/anomaly/board/center.

## 6. Military Lexicon

An operator-maintained slang/jargon glossary (e.g. `прилёт`=strike, `200`=KIA, `300`=wounded, `панцирь`=Pantsir SAM, `ёлка`=…). Ingested from a file like the sources file (idempotent). Used:
1. **Noise filter:** a chat message passes the conflict-relevance gate if it contains a geo-key OR a lexicon term.
2. **LLM context:** passed as a glossary so direction (and later credibility) classification understands slang.
3. **Future (data model only):** in-UI decode/tooltip ("300" → "раненые").

Stored as `term → meaning` (+ optional category) so it doubles as a decoder later.

## 7. What's Reused vs New

**Reused:** Telethon session + provider (TG read), `core.spam`, morphology matching, the scheduler, the whole downstream (`intel` clustering/stories/credibility/anomaly/aggregate/api/board/center).

**New:** `radar/intel/passes.py` (collect pass), `radar/intel/tagging.py` (geo dict + inline tag + LLM retag), source-file ingest command, military-lexicon model + ingest, `IntelProbe.direction_id` nullable + `unassigned` seed direction, scheduler wiring of the intel pass.

## 8. Data Flow

```
operator file (channels/chats + side)  ──ingest──▶  IntelProbe (source, side, kind)
operator file (military lexicon)        ──ingest──▶  Lexicon table
                                                         │
scheduler tick ─▶ run_intel_collect ─(Telethon)─▶ read channel posts / chat msgs
                                          │  chat: noise filter (geo-key OR lexicon, drop spam)
                                          ▼
                                   IntelMention (side from source, direction via inline geo-tag → unassigned)
                                          │
                          retag_unassigned (LLM + lexicon context) ─▶ fills direction_id
                                          ▼
                          cluster per direction ─▶ stories / credibility / anomaly
                                          ▼
                          /intel/overview · /intel/directions · /intel/stories  (already built)
```

## 9. Open Questions (deferred)
- Geo-dictionary and lexicon: seed-in-code vs DB table the operator edits in-UI (Phase 1 = file ingest into a table; in-UI editing later).
- LLM retag cadence/budget (every tick vs periodic; batch size) — tune during implementation.
- Chat back-read depth and per-source rate limits — tune against flood limits during implementation.
