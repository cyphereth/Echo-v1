# Intel — Closed (Military-Intelligence) Contour — Design

**Date:** 2026-06-21
**Status:** Approved (brainstorm) — pending implementation plan
**Owner contour:** closed / military-intelligence

## 1. Context & Product Vision

Echo is a **media-intelligence / monitoring platform**: the user's own ideas + **Ochi Analytics** (independent news intelligence) + **M13 «Катюша»** (professional media/social monitoring). It is split into two separately-deployed products that share only the backend core:

- **Commercial contour** — brands / marketing / AI reply models (the existing `brand` domain). *Out of scope for this spec.*
- **Closed contour** — gov / СМИ / military services only. News intelligence + operational conflict picture (Ochi + M13, military focus). **This spec.**

The user chose to build the **closed contour first** ("это очень важно"), and to make it **look good first, then add technical features**. The frontend will be built by the user in GLM 5.2 against the data contract in §6; the backend (`intel` domain) is built afterward against the same contract.

## 2. Scope & Non-Goals

**In scope:** the closed contour's product shape, information architecture, the three screens, and the `/intel/*` API data contract.

**Non-goals (explicitly deferred):**
- Commercial contour and any public "choose your product" entry/routing — separate, later (deployments are separate; a shared public landing may not exist).
- Broad intelligence (economy / geopolitics) — closed contour is **military-centric for now**; widen later.
- **Geocoded map** — the military view is a structured board for now; a real map is a later feature.
- **Access-control mechanism** (invite/credential provisioning, IP allowlist, etc.) — a "technical feature" for later; for the visual phase a simple login gate suffices.
- Source/channel curation (both-sides Telegram channel lists), realtime alert transport (websockets/SSE) — later technical features.

## 3. Product Form

- **Separate, non-public deployment** (e.g. `intel.echo.*` or invite-only); not linked from the commercial site.
- **Military-centric** intelligence contour.
- Shares only **`radar/core/`** (collection from Telegram + web, clustering into stories, credibility / fake-detection, anomaly stats). Military specifics live in a **dedicated `intel` backend domain**, parallel to `news` and `brand` — keeping the contours cleanly separated ("не путать задачи").

## 4. Information Architecture

Single product; **Situational Center is the home**, with drill-down into the two detail sections:

```
[Closed contour]
 ├── 🛰  Situational Center   (home — "what's hot now")
 │        ↓ drills into
 ├── 📰  Stories              (news intelligence on the conflict)
 └── 🎯  Operational Board    (directions grid — no map yet)
```

## 5. Screens

### 5.1 Situational Center (home)
- Top: title, live indicator, time-window selector (1h / 24h / 7d), global search.
- **"Now hot"** — stories with the largest activity spike in the window: title, direction tag, activity sparkline, source count, credibility badge, last-seen time.
- **"Alerts"** — compact list of anomalies / sharp spikes (spike detection feeds this).
- **"Top stories"** — the largest ongoing stories.
- **"Event stream"** — live feed of the latest verified messages (compact, scrolling).
- **KPI strip** — events (24h) · active stories · directions spiking.

### 5.2 Stories
- Left: story list with filters (direction, side, verified-only) and sort (activity / recency).
- Right: story detail — title, summary, credibility badge + fake-detection note, **activity timeline chart** (from points), **source list tagged by side**, constituent events/messages.

### 5.3 Operational Board
- Grid of **direction** cards; each: name, **activity level** (heat bar), **spike indicator** (↑ % vs baseline), verified-event count in the window, last-event snippet, dominant credibility.
- Click a direction → filtered view: its stories + event stream.

## 6. Data Contract (`/intel/*`)

Prefix `/intel/*`, JWT auth (closed credentials). The GLM frontend mocks exactly these shapes; the `intel` backend later serves them for real.

### Core objects
```jsonc
StorySummary = {
  id, title, direction,            // "kursk" | "zaporizhzhia" | ...
  sides: ["ru","ua"],              // sides whose sources appear in the story
  source_count, post_count,
  verified: true,
  credibility: "verified|likely|unverified|fake|unrated",
  credibility_note: "",            // fake-detection verdict
  spike_pct: 240,                  // activity rise vs baseline (powers "hot"/alerts)
  sparkline: [3,5,9,4],            // mini activity series
  last_seen_at
}
Event = { id, platform, author, side, text, url, created_at, verified, direction }
Direction = { key, name, activity_level: 0-100, spike_pct, events_count,
              dominant_credibility, last_event: { text, at, source } }
Alert = { id, story_id, direction, kind: "spike", magnitude, message, at }
```

### Endpoints
```
GET /intel/overview?window=24h        → { kpis: { events, active_stories, spiking_dirs },
                                          hot: [StorySummary], alerts: [Alert],
                                          top_stories: [StorySummary] }
GET /intel/stream?window&direction&limit      → [Event]            // live feed
GET /intel/stories?direction&side&verified&sort&limit → [StorySummary]
GET /intel/stories/{id}               → StorySummary + { summary_text,
                                          points: [{ bucket_start, mention_count, source_count }],
                                          sources: [{ name, side, count, last_at, url }],
                                          events: [Event] }
GET /intel/directions?window          → [Direction]                 // operational board
GET /intel/directions/{key}?window    → { direction: Direction, stories: [StorySummary], stream: [Event] }
GET /intel/search?q                   → [StorySummary]
```

## 7. Backend Approach (`intel` domain) — built after the visual phase

A new `radar/intel/` domain, parallel to `radar/news/` and `radar/brand/`, reusing `radar/core/` (clustering engine, credibility, anomaly stats) — no duplication of heavy logic.

- **Models** mirror the news domain's story/mention/incident/story-point shape, plus two military fields: **`direction`** (sector key) and **`side`** (source affiliation). Reuses `DomainModels` for the core clustering engine.
- **Collection** tuned for conflict sources (both-sides Telegram channels/chats + web), via `core` providers. Channel curation deferred.
- **Aggregation endpoints** (`/intel/overview`, `/intel/directions`) compute spikes (via `core` anomaly stats over story points) and per-direction rollups.
- The contract in §6 is the single source of truth shared by the GLM frontend and this backend.

## 8. Sequencing

1. **Visual-first (now):** user builds the closed-contour frontend in GLM 5.2 against §6 with realistic mock data; iterate until it looks good.
2. **Backend (`intel` domain):** implement §7 against the same contract; swap the frontend from mock to live `/intel/*`.
3. **Technical features (later):** access-control mechanism, both-sides source curation, realtime alert transport, geocoded map, broadening to economy/geopolitics.

## 9. Open Questions (deferred, tracked)
- Direction taxonomy: fixed list vs. configurable per deployment.
- "Side" inference: from a curated source→side mapping, or model-tagged.
- Access provisioning for the closed deploy (who issues credentials, audit).
- Alert delivery: in-app only vs. push (telegram/email) — and transport (polling vs. SSE/ws).
