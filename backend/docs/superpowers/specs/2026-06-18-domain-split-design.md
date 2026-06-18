# Domain Split: News and Brand — Design

**Date:** 2026-06-18
**Status:** Approved (design); pending implementation plan
**Goal:** Separate the two equal first-class products — independent CIS news intelligence and brand monitoring — into clean, isolated domains (code **and** data), removing the `Scope` polymorphism that currently smears both products across every file and causes task-level confusion.

## Problem

Brand and news currently share almost everything:

- One set of models (`Mention`, `Incident`, `Story`, `StoryPoint`, `Probe`, `Report`) with nullable `brand_id` / `topic_id` owner FKs.
- One `collector.py` (660 lines, ~65 brand / ~67 topic references) and `pipeline.py` that branch internally on `Scope`.
- One monolithic `api.py` (1620 lines) mixing `/brands`, `/topics`, `/news`, `/stories`, `/mentions`, `/comments`, `/onboarding`, `/analytics`, `/opportunities`, `/explore`.
- One frontend `AppPage` with a mode toggle and shared components (`Feed`, `Stories`, `Sources`, `Digests`) that do double duty via props like `lanes={mode==='brand'}` and `scope`-aware API calls.

The `Scope` abstraction was a band-aid letting one pipeline serve both owners. The cost: every change requires deciding "is this row/branch brand or news?", and the shared nullable-owner tables are the deepest knot. Both products stay first-class; they must be physically separated.

## Decisions (locked)

1. **Both domains remain equal first-class products.** Neither is dropped or frozen.
2. **Separation depth: code + data.** Each domain gets its own tables and its own code. `Scope` is removed entirely.
3. **Clustering and anomaly detection move to `core`** as a generic engine *parameterized by domain models* (it accepts the domain's `Mention/Incident/Story` classes; it never reaches into a shared table). Domain-specific concepts (what a "source" is, credibility) stay in `news`/`brand`.
4. **News tables are lean.** `news_mentions` drops ~15 brand-only fields rather than carrying them empty.
5. **Frontend components are specialized per feature.** Only truly generic primitives (chart wrapper, badge, empty state) live in `core/components`.
6. **Old tables are kept for one release** as a backup, then dropped by a separate follow-up migration.

## Backend Module Layout

```
radar/
  core/                  infrastructure, nothing domain-specific
    db.py  auth.py  llm.py  vec.py  embeddings.py  spam.py
    providers/           (web, telegram, socialcrawl, tikhub, mock, base)
    scheduler.py         thin tick core; domains register their passes
    clustering.py        NEW: generic story/incident clustering engine,
                         parameterized over a domain's models
    anomalies.py         generic spike statistics, called by both domains
  news/
    models.py            NewsTopic, NewsProbe, NewsMention, NewsIncident,
                         NewsStory, NewsStoryPoint, NewsReport
    collector.py         TG channel + global + web collection per topic
    stories.py           story update via core.clustering on news models
    sources.py           seed/hybrid discovery, classify_source, purge
    credibility.py       cross-verification + fake-detection
    digests.py           per-topic digest
    passes.py            topic-TG-pass, topic-web-pass (for scheduler)
    api.py               router: /news/*
  brand/
    models.py            Brand, BrandProbe, BrandMention, BrandIncident,
                         BrandStory, BrandStoryPoint, BrandReport,
                         MentionSnapshot, Comment, DraftEdit,
                         EngagementLog, CityReport
    collector.py         brand collection (niche/competitor/follower-floor)
    stories.py           story update via core.clustering on brand models
    pipeline.py  drafts.py  digests.py  engagement.py  hotwatch.py
    scoring.py  classifier_rules.py  explore.py
    passes.py            brand-pipeline, web-pass, chat-monitor, hotwatch
    api.py               router: /brands/*, /mentions/*, /comments/*,
                         /analytics, /opportunities, /onboarding, /explore
  app.py                 assembles FastAPI: core + news.router + brand.router,
                         registers passes (news-pass first → TG-first)
```

- **`Scope` is deleted.** Each domain calls its own `collector`/`stories` directly; no `if kind == 'brand'`.
- **`scheduler.py` becomes thin.** Domains register passes; the core only fires them on cadence. News-pass registers first, preserving the TG-first priority (`INTERVAL_TOPIC_TG`).

## Data Model Split

**`core` (shared):** `users` only — authentication is shared.

**Brand domain** (tables renamed with prefix, fields preserved):
`brands`, `brand_probes`, `brand_mentions` (keeps all reply fields: `lane, source, competitor, opportunity, draft, draft_flag, status, tone, phase, is_hot, severity, category, confidence`), `mention_snapshots`, `comments`, `draft_edits`, `engagement_log`, `city_reports`, `brand_incidents`, `brand_stories`, `brand_story_points`, `brand_reports`.

**News domain** (lean tables):
`news_topics`, `news_probes`, `news_mentions`, `news_incidents`, `news_stories`, `news_story_points`, `news_reports`.

- **`news_mentions` keeps only:** `platform, post_id, author, followers, text, hashtags, created_at, first_seen, incident_id, source` (channel/global). Dropped brand-only columns: `competitor, opportunity, draft, draft_flag, lane, tone, phase, is_hot, severity, category, status, confidence`.
- **`news_stories` keeps the credibility fields** (`source_count, verified, credibility, credibility_note, summary`) — they were always news-specific. `brand_stories` stays lean (no credibility columns).
- **`is_anomaly`, `summary`, `title`, `post_count`, timestamps** exist on both `*_stories`.

### Per-domain uniqueness

`UniqueConstraint(platform, post_id)` becomes per-domain (one constraint on `news_mentions`, one on `brand_mentions`). A single post may now exist once in each domain — intended: the same TG post can be both a news signal and a brand mention with different context.

## Migration (additive → copy → swap; idempotent)

Implemented in `core/db.py`, run at `init_db()`. Data is mostly fresh (CIS news + one demo brand), so risk is low.

1. **Create new tables** alongside old ones (`create_all` over new models).
2. **Copy with owner routing** (guard: old tables exist AND new tables empty):
   - `mentions` rows with `topic_id` → `news_mentions`; rows with `brand_id` → `brand_mentions`.
   - `incidents`, `stories`, `probes`, `reports`, `story_points` routed the same way (story_points follow their story's domain).
   - **Original PK values and internal references are preserved.** `incident_id` / `story_id` stay valid because a brand mention references a brand incident — an entire subtree routes to one domain, so no remapping is required.
   - Brand-only tables (`comments`, `mention_snapshots`, `draft_edits`, `engagement_log`, `city_reports`) move as `brand_*` unchanged.
3. **Verify:** per-domain new row counts equal the corresponding old counts. On mismatch, abort and leave old tables untouched.
4. **Switch code** to new models (phases 3–4 below).
5. **Keep old tables for one release.** A separate follow-up migration drops them.

`Scope` and `_relax_brand_id_not_null` are removed once the swap completes — owner FKs become honestly `NOT NULL`.

## Frontend Layout

```
src/
  app/
    App.jsx              router: /login, /app
    Shell.jsx            mode switch (Новости/Бренд) + nav; mounts active feature
  core/
    api/client.js        fetch wrapper, token, 401→/login (no scope)
    auth/                LoginPage, RequireAuth
    components/          icons, generic primitives: Badge, TimelineChart, EmptyState
  features/
    news/
      NewsApp.jsx        TopicBar + screens: Сюжеты/Лента/Дайджесты/Источники
      api.js             getTopics, getNewsFeed, getNewsStories, getTopicSources…
      components/        Stories, Sources, Feed (flat), Digests
    brand/
      BrandApp.jsx       BrandBar + screens: Очередь/Лента/Аналитика/Дайджесты/…
      api.js             getBrands, getInbox, collectBrand, postAction, getAnalytics…
      components/        Feed (lane tabs), Detail, Queue, Analytics, CityExplorer,
                         Settings, AIWizard, Digests, BrandGate
```

- **`api.js`** (single file with `scopeQuery` / `*Scoped`) splits into `core/api/client.js` (transport + auth) + `features/news/api.js` + `features/brand/api.js`. `scope` disappears from the frontend.
- **`AppPage.jsx`** (mode + scope state) splits into `NewsApp` + `BrandApp`. `Shell` holds only the mode switch and mounts the active feature.
- **Dual-use components are specialized per feature** (kills the `lanes` prop and `mode===` conditionals). `Feed` is flat in news, tabbed in brand. `Stories`/`Digests` have a per-feature version. Only small primitives (chart wrapper, badges, empty state) are shared in `core/components`.

## Rollout Phases

Each phase keeps the existing test suite green and the app runnable.

1. **Extract `core`** (no behavior change): move pure infrastructure modules, fix imports. The 225 existing tests are the safety net.
2. **New models + migration** (additive): new tables, routed copy, count verification. Old code still reads old tables. Add a migration test.
3. **Build `news` domain** on new models; switch `/news/*` and the news scheduler pass; remove news's `Scope` and shared-table use.
4. **Build `brand` domain** on new models; switch `/brands/*` and brand passes.
5. **Teardown:** delete `Scope`, the shared-collector branches, `_relax_brand_id_not_null`, and the `api.py` monolith. `app.py` assembles routers.
6. **Frontend** in the same order: `core` (client + auth) → `features/news` → `features/brand` → `Shell`.
7. **Drop old tables** — separate migration, after one release.

## Testing

- **Regression:** full current suite runs every phase; green means the domain is intact.
- **Migration:** seed old-schema rows → run migration → assert rows routed by domain, counts match, and `incident_id`/`story_id` references remain valid.
- **Per-domain unit tests** replace the Scope-based tests (`test_topic_tg`, `test_news_sources` → `news/`; brand pipeline → `brand/`).
- **Smoke (run skill):** after phases 3 and 4, launch the backend and hit `/news/stories` and `/brands` via httpx.

## Process Safety

- Branch `refactor/domain-split`; one commit per phase; the app runs at every commit.
- Migration is idempotent, guarded, and count-verified; old tables are never dropped in the same phase that creates new ones.
- The `core → data → news → brand → teardown` order guarantees exactly one layer is in motion at any commit.

## Out of Scope (YAGNI)

- Splitting into separate services/repos or separate deploys — both domains stay in one app.
- Auth/permission tiers (news-public vs brand-private) — unchanged by this refactor.
- New product features — this is a structural refactor only; behavior is preserved.
