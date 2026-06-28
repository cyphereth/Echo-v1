# Intel Feed v2 — Multi-Column Live Direction Feed — Design

**Date:** 2026-06-28
**Status:** Approved (brainstorm) — pending implementation plan
**Owner contour:** closed / military-intelligence (`intel` domain)
**Base branch:** `feat/intel-closed-contour` (screen lives inside `IntelApp`)

## 1. Context & Product Vision

The closed «Разведка» contour already has three screens — Situational Center (home), Stories, Operational Board. The Situational Center exposes a single unified event stream: all sources mixed in one feed.

Operators watching a specific area (a Russian border region, a Ukrainian oblast, a city) currently cannot isolate the relevant signal: they must visually scan the unified stream for the area they care about.

**Feed v2** closes that gap. It is a **fourth screen** of the contour — a TweetDeck-style multi-column live feed where **each column is one direction** (oblast / city / custom), and posts land in a column when their **source is subscribed to that direction** *or* the **post text mentions the area's geo-terms**. Operators pick up to ~8 columns to watch simultaneously; new posts arrive over a single multiplexed SSE connection and slide in at the top of the matching column with a brief highlight.

## 2. Scope & Non-Goals

**In scope:**
- New `IntelFeed` screen mounted as the 4th item in `IntelApp`'s sidebar (`screen === 'feed'`).
- Data model: many-to-many between `IntelMention` and `IntelDirection` (a post may belong to several directions); extended `IntelDirection` with `kind`, `region_key`, `geo_terms`.
- A seeded geo-dictionary covering the regions/cities already discovered (RF border oblasts, all 26 Ukrainian oblasts, DNR/LNR, plus major cities) — derived from the chat-collection spreadsheets produced earlier in this project.
- Geo-text matching performed **at collection time** (collector writes m2m rows), with lowercase boundary-aware matching against cached `geo_terms`.
- One multiplexed SSE endpoint `/intel/feed/stream` tagged with direction, plus REST endpoints for column initial history, column CRUD, and layout persistence.
- Frontend: topbar with global window/side filters, column bar (active column chips with ✕, a "+ колонки ▾" multi-select with search), narrow (~280–320px) tweet-deck columns of post cards, new-post highlight animation.
- Layout persistence: backend "боевой дефолт" (admin-saved) + `localStorage` personal override.

**Non-goals (explicitly deferred):**
- Audio/popup notifications (only in-column highlight for now).
- Drag-and-drop column reordering (only add via "+", remove via "✕").
- Per-column filters (window and side are global only).
- A real geocoded map.
- Free-text search across posts (already exists in Situational Center).
- Access-control provisioning for who may set the "боевой дефолт" — handled by the contour's existing auth; the layout PUT endpoint is admin-gated at the API level.

## 3. Information Architecture

```
[Closed contour · Разведка]
 ├── 🛰  Ситуационный центр   (home)        hotkey 1
 ├── 📰  Сюжеты               (stories)     hotkey 2
 ├── 🎯  Оперативная доска    (board)       hotkey 3
 └── 📡  Лента событий v2     (feed)        hotkey 4   ← NEW
```

The screen renders full-workspace (no right-hand detail panel).

## 4. Data Model

### 4.1. Extended `IntelDirection`

Existing columns (`id`, `key`, `name`, `created_at`) are preserved. Add:

| column       | type     | notes                                                                 |
|--------------|----------|-----------------------------------------------------------------------|
| `kind`       | Text     | `'region'` \| `'city'` \| `'custom'`. Default `'region'`.             |
| `region_key` | Text NULL| For cities: `key` of the parent region direction. NULL for regions/custom. |
| `geo_terms`  | Text     | Newline- or JSON-encoded list of lowercase match terms (`брянск`, `брянская`, `клинцы`, …). Empty for directions that match by source subscription only. |

`kind`, `region_key`, `geo_terms` are added via the `_MIGRATIONS` DDL pattern in `core/db.py` (same approach used for `news_probes.linked_chat_id`).

### 4.2. New m2m table `intel_mention_directions`

A post may match multiple directions. The existing `IntelMention.direction_id` is **kept as the primary direction** (backward-compatible with current aggregate/story code) and is *also* mirrored as one m2m row.

```python
class IntelMentionDirection(Base):
    __tablename__ = "intel_mention_directions"
    __table_args__ = (UniqueConstraint("mention_id", "direction_id"),)
    id:           Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id:   Mapped[int] = mapped_column(ForeignKey("intel_mentions.id"), nullable=False)
    direction_id: Mapped[int] = mapped_column(ForeignKey("intel_directions.id"), nullable=False)
    match_type:   Mapped[str] = mapped_column(Text)   # 'source' | 'geo' | 'manual'
    created_at:   Mapped[datetime] = mapped_column(default=_now)
```

Created via `_MIGRATIONS` (new table). Indexed on `direction_id` for column queries.

### 4.3. Seed: `geo_dict.py` + `ensure_default_directions` expansion

`backend/radar/intel/geo_dict.py` defines the regions and major cities with their match terms. The data is sourced from the chat-collection spreadsheets already produced (`border_chats_found.xlsx`, `border_chats_ukraine.xlsx`, `border_chats_dnr_lnr.xlsx`): each oblast + its principal cities become a `DEFAULT_DIRECTIONS` entry. `ensure_default_directions` is extended to write the new `kind`, `region_key`, and `geo_terms` columns when seeding.

Custom directions created via the UI get `kind='custom'` and whatever `geo_terms` the operator enters.

## 5. Matching (in collector)

In `intel/collector.py`, when persisting an `IntelMention`:

1. Resolve the **primary** `direction_id` as today (from the probe's `direction_id`).
2. Run **geo-text matching** against `mention.text` for all directions' `geo_terms`:
   - Lowercase both text and terms.
   - Boundary-aware matching (word boundaries, not substring): `брянск` matches `брянск` / `брянская` / `б під Брянском`, but **not** `брянсковый` / `рязанский`. Use a regex `\b`-equivalent that respects Cyrillic word boundaries.
3. Build the set of matched direction ids (primary ∪ geo matches).
4. Insert one `IntelMentionDirection` row per matched direction with the appropriate `match_type`:
   - primary → `'source'`
   - any geo-only match → `'geo'`
   - dedupe on `(mention_id, direction_id)` via the unique constraint (insert-or-ignore).
5. `geo_terms` are cached in the collector process (refreshed every N minutes / on direction CRUD) to avoid a DB hit per post.

The matcher is a standalone, pure function in `intel/geo_match.py` so it can be unit-tested without a DB.

## 6. API (`/intel/*`)

All endpoints reuse the existing `current_user` dependency and the `_hours(window)` helper.

### 6.1. Column initial history
```
GET /intel/feed?direction=kursk&side=&window=24h&limit=50
```
Returns the most recent events for a single direction, filtered by m2m membership + optional side + window. Same `event` shape as the existing `/intel/stream`.

### 6.2. Live multiplexed SSE
```
GET /intel/feed/stream?directions=kursk,bryansk,lnr&side=ru&window=24h
```
- One SSE connection for all visible columns.
- Server polls the DB every 2s (same pattern as `/news/feed/stream`) for new mentions matching the m2m of any requested direction, side, and window, since the last-sent id.
- Each line is tagged: `data: {"direction": "bryansk", "event": {…}}`.
- Sync generator inside `StreamingResponse`, same approach as the news feed.

### 6.3. Directions catalog
```
GET  /intel/directions            # all available directions (for the "+ колонки" selector)
POST /intel/directions            # create custom: {key, name, kind:'custom', geo_terms:[...]}
```

### 6.4. Layout persistence
```
GET /intel/feed/layout            # боевой дефолт: {direction_ids: [...], updated_at}
PUT /intel/feed/layout            # admin-only: set боевой дефолт
```
Admin gate: 403 unless `current_user.is_admin`. If the `User` model does not yet have an `is_admin` flag, this task adds it (Boolean, default `False`) via `_MIGRATIONS`, and seeds `is_admin=True` for the first user / a bootstrap admin. No hardcoded allow-lists.

The personal override never touches the backend — it lives in `localStorage` under `echo.intel.feed.columns`.

## 7. Frontend

New module: `echo-app/src/features/intel/components/IntelFeed.jsx` (+ `api.js` additions).

### 7.1. Layout
```
┌─ Topbar ─────────────────────────────────────────────────────┐
│ 📡 Лента событий v2      [1h][24h][7d]   [🇷🇺][🇺🇦][оба]      │
├─ Column bar ─────────────────────────────────────────────────┤
│ [Брянск ✕][Белгород ✕][Харьков ✕]...   [+ колонки ▾]        │
├─ Columns workspace (horizontal scroll) ──────────────────────┤
│ ┌Брянск·24┐ ┌Белгород·18┐ ┌Харьков·42┐ ┌Курск·11┐ ...        │
│ │ cards   │ │ cards      │ │ cards     │ │ cards   │           │
│ └─────────┘ └────────────┘ └───────────┘ └─────────┘           │
└───────────────────────────────────────────────────────────────┘
```

### 7.2. Topbar
- Window segmented control (`1h` / `24h` / `7d`) — applies to all columns.
- Side segmented control (`ru` / `ua` / `both`) — applies to all columns.
- Both trigger a refetch of column history + a reconnect of the SSE stream with new params.

### 7.3. Column bar
- Active columns rendered as chips: `▶ {name} ✕`. Click ✕ removes the column.
- `+ колонки ▾` opens a dropdown with a search input and a checkbox list of all directions from `GET /intel/directions`. Selecting adds a column; the dropdown stays open for multi-add.
- Columns are ordered by add-order (left to right).

### 7.4. Column
- Header: direction name + count badge (events in window).
- Body: scrollable list of post cards.
- On SSE event for this direction → prepend card to top, trigger 1s highlight animation (`.postCard.new`), increment count.

### 7.5. Post card
- Side flag (🇷🇺/🇺🇦/–), author handle, time (`agoStr`).
- Text clamped to 3 lines.
- Credibility dot: `verified` green, `likely` blue, `unverified` grey, `fake` red, `unrated` grey.
- Match-type indicator (small): `S` for source-subscribed, `G` for geo-matched (so the operator understands why a post is in this column).

### 7.6. SSE subscription
- `useEffect` opens one `EventSource` on `/intel/feed/stream?directions=…&side=…&window=…`.
- `onmessage` parses `direction` tag, dispatches to the right column's state.
- Reconnect on params change or on close (native `EventSource` auto-reconnect).

### 7.7. Layout persistence
- On mount: read `localStorage["echo.intel.feed.columns"]`; if absent, `GET /intel/feed/layout` for боевой дефолт.
- On column add/remove: update state + write-through to `localStorage`.
- "Сбросить к боевому" button clears localStorage and reloads from API.
- "Сохранить как боевой" button (admin only) `PUT`s current selection.

## 8. Design system / CSS

Extends `intel.module.css` (dark theme, coordinate grid). New classes:
- `.feed`, `.feedTopbar`, `.feedColumnBar`, `.feedColumns` (horizontal scroll container)
- `.feedColumn`, `.feedColumnHead`, `.feedColumnCount`
- `.postCard`, `.postCard.new` (pulse animation)
- `.colChip`, `.colChip ✕`, `.colPicker` (dropdown)

Column width: `~280–320px`, fixed; post text 13px, meta 11px mono.

## 9. Testing

- `test_intel_geo_match.py` — pure matcher: `прилет в Брянске` → `{bryansk}`; `брянсковый` → `{}`; multi-region text; Ukrainian/Cyrillic boundary handling.
- `test_intel_collector.py` (extend) — persisting a mention writes the expected m2m rows (source + each geo match), dedupes.
- `test_intel_api.py` (extend):
  - `GET /intel/feed?direction=kursk` returns only kursk-tagged events, respects side/window.
  - `GET /intel/feed/stream` generator yields events tagged with the right direction (tested via `asyncio.wait_for` on the generator, same pattern as `/news/feed/stream`).
  - `POST /intel/directions` creates a custom direction.
  - `GET/PUT /intel/feed/layout` round-trips; PUT is 403 for non-admin.
- Frontend: manual smoke against mock data, then a live run with the real collector.

## 10. Risks & Notes

- **Geo-dictionary maintenance**: the seeded dictionary is a starting point; operators will refine via custom directions. The dictionary must not silently drift — version it (a `geo_dict_version` constant) and re-seed on version bump.
- **Cyrillic word boundaries**: Python `\b` does not always behave for Cyrillic under all locales; the matcher will use an explicit `(?<![А-Яа-яA-Za-z])term(?![А-Яа-яA-Za-z])` pattern to be locale-independent.
- **SSE load**: a single connection polling every 2s is cheap; if the contour scales to many operators, switch to a single global poller that fans out to connections (out of scope here).
- **Admin gate**: this task adds `is_admin` to `User` (Boolean, default `False`) and bootstraps the first user as admin. No hardcoded allow-lists.
