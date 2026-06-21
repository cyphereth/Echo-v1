# Intel (Closed Military-Intelligence) Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend `intel` domain that serves the closed military-intelligence contour's `/intel/*` API contract.

**Architecture:** A new `radar/intel/` domain, parallel to `radar/news/` and `radar/brand/`, reusing `radar/core/` (clustering engine, anomaly stats, embeddings, providers, db, auth). It mirrors the `news` domain almost 1:1, with two military additions: the clustering **owner is a "direction"** (sector) instead of a topic, and **mentions carry a `side`**. Adds aggregation endpoints (`/intel/overview`, `/intel/directions`) that roll up stories/points into the situational center and operational board.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, pytest. Run backend from `backend/` with `python3 -m uvicorn radar.app:app --port 8000`. Tests: `cd backend && python3 -m pytest -q`.

**Spec:** `backend/docs/superpowers/specs/2026-06-21-intel-closed-contour-design.md` (the `/intel/*` contract in §6 is the single source of truth).

**Reference template:** the `news` domain is the living template. For mechanical files (collector, stories wiring, credibility, router plumbing), read the matching `radar/news/<file>.py` and mirror it, applying the transform: `Topic→Direction`, `topic_id→direction_id`, `News*→Intel*`, and add the `side` field on mentions. Do NOT modify `radar/news/` or `radar/brand/`.

## Global Constraints

- All radar modules use relative imports; intra-package refs are single-dot (`from .models import ...`), core refs are double-dot (`from ..core.db import ...`).
- New models share the single `radar.models.Base` metadata; import `Base, _now` from `..models`. No duplicate `__tablename__` across the shared Base — all intel tables are `intel_*` (new names, no collision).
- Tests live in `backend/tests/`, start with `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))`, use an in-memory SQLite engine + `Base.metadata.create_all`.
- Domain isolation: `radar/intel/` imports only from `.` (itself), `..core.*`, and `..models` (Base/_now/User). NO imports from `radar.news` / `radar.brand`. No `Scope`.
- The clustering engine `core.clustering.cluster_owner(session, owner_id, models, embed, *, sim_threshold=0.78, now=None)` and `core.domain.DomainModels(owner_field, Mention, Incident, Story, StoryPoint)` are reused as-is. `owner_field="direction_id"`.
- `core.anomalies.detect_anomaly(session, story_id, story_model, point_model)` — pass `IntelStory, IntelStoryPoint`.
- Full suite must stay green at every commit (current baseline: 207 passed). Only the pre-existing FastAPI on_event-free app; no new warnings.
- Run all git from repo ROOT `/Users/vovolypsi/Echo-v1/Echo-v1`; never `git init`.
- Credibility values: `"verified" | "likely" | "unverified" | "fake" | "unrated"`. Verification threshold reuses `STORY_VERIFY_MIN_SOURCES` (env, default 3), same as news.

## File Structure

- `radar/intel/__init__.py` — package marker.
- `radar/intel/models.py` — `IntelDirection, IntelProbe, IntelMention, IntelIncident, IntelStory, IntelStoryPoint`. Owner = `IntelDirection`; mentions add `side`.
- `radar/intel/collector.py` — `collect_probe(session, probe, provider) -> int` writing `IntelMention` (mirror `news/collector.py`, + `side`).
- `radar/intel/stories.py` — `update_stories(session, direction_id, embed=None)` (cluster + verification + anomaly) (mirror `news/stories.py`).
- `radar/intel/credibility.py` — `assess_credibility(session, story)`, `summarize_story(session, story)` on `IntelStory` (mirror `news/credibility.py`).
- `radar/intel/aggregate.py` — NEW: serializers + rollups (`story_summary`, `story_detail`, `event`, `direction_card`, `overview`, spike computation).
- `radar/intel/api.py` — `router` with the `/intel/*` endpoints.
- `radar/intel/seed.py` — `ensure_default_directions(session)` seeding a starter direction list.
- `radar/app.py` — mount `intel` router; call `intel.seed.ensure_default_directions` in lifespan.
- Tests: `tests/test_intel_models.py`, `tests/test_intel_collector.py`, `tests/test_intel_stories.py`, `tests/test_intel_aggregate.py`, `tests/test_intel_api.py`.

---

### Task 1: Intel domain models

**Files:**
- Create: `backend/radar/intel/__init__.py`
- Create: `backend/radar/intel/models.py`
- Test: `backend/tests/test_intel_models.py`

**Interfaces:**
- Produces: ORM classes `IntelDirection(id, key, name, created_at)`, `IntelProbe(id, direction_id→intel_directions.id NOT NULL, platform, kind, query, side, watermark, next_run_at, interval_sec)`, `IntelMention(id, direction_id NOT NULL, platform, post_id, author, side, text, url, views, created_at, verified, incident_id→intel_incidents.id, first_seen)` with `UniqueConstraint(platform, post_id)`, `IntelIncident(id, direction_id NOT NULL, story_id→intel_stories.id, title, post_count, first_seen_at, last_seen_at, created_at)`, `IntelStory(id, direction_id NOT NULL, title, status, is_anomaly[server_default "0"], post_count, source_count, verified, credibility, credibility_note, summary, first_seen_at, last_seen_at, created_at)`, `IntelStoryPoint(id, story_id→intel_stories.id, bucket_start, mention_count, source_count)` with `UniqueConstraint(story_id, bucket_start)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_models.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def _mem():
    from sqlalchemy import create_engine
    from radar.models import Base
    import radar.intel.models  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng

def test_intel_mention_has_side_and_direction():
    _mem()
    from radar.intel.models import IntelMention
    cols = set(IntelMention.__table__.columns.keys())
    assert "side" in cols and "direction_id" in cols
    for gone in ("competitor", "opportunity", "draft", "lane", "topic_id", "brand_id"):
        assert gone not in cols, f"{gone} must not be on IntelMention"

def test_intel_story_has_credibility_and_no_brandfields():
    _mem()
    from radar.intel.models import IntelStory
    cols = set(IntelStory.__table__.columns.keys())
    for need in ("source_count", "verified", "credibility", "credibility_note", "summary", "is_anomaly", "direction_id"):
        assert need in cols
    for gone in ("topic_id", "brand_id"):
        assert gone not in cols

def test_intel_schema_builds_clean():
    # no duplicate tablename / FK resolution errors on the shared Base
    _mem()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_models.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'radar.intel'`.

- [ ] **Step 3: Create the package + models**

Create `backend/radar/intel/__init__.py` (empty). Create `backend/radar/intel/models.py`. Read `backend/radar/news/models.py` and mirror it, applying: drop the `keywords/niche_keywords/kind/market/auto_collect` topic fields → `IntelDirection` instead carries `key` (Text, unique) and `name` (Text). Rename every `News*`→`Intel*`, `topic_id`→`direction_id`, `news_*` tables→`intel_*`. Add `side: Mapped[Optional[str]] = mapped_column(Text)` to `IntelProbe` and `IntelMention`. Add `url: Mapped[Optional[str]]` and `views: Mapped[int] = mapped_column(Integer, default=0)` to `IntelMention`. Put `server_default="0"` on `IntelStory.is_anomaly` (mirror news). Skip `NewsReport` (no digests in the contract). Example of the two anchor classes:

```python
class IntelDirection(Base):
    __tablename__ = "intel_directions"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    key:        Mapped[str]      = mapped_column(Text, unique=True, nullable=False)   # "kursk"
    name:       Mapped[str]      = mapped_column(Text, nullable=False)                # "Курское"
    created_at: Mapped[datetime] = mapped_column(default=_now)

class IntelMention(Base):
    __tablename__ = "intel_mentions"
    __table_args__ = (UniqueConstraint("platform", "post_id"),)
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction_id: Mapped[int]      = mapped_column(ForeignKey("intel_directions.id"), nullable=False)
    platform:     Mapped[str]      = mapped_column(Text)
    post_id:      Mapped[str]      = mapped_column(Text)
    author:       Mapped[str]      = mapped_column(Text)
    side:         Mapped[Optional[str]] = mapped_column(Text)          # "ru" | "ua" | None
    text:         Mapped[str]      = mapped_column(Text, default="")
    url:          Mapped[Optional[str]] = mapped_column(Text)
    views:        Mapped[int]      = mapped_column(Integer, default=0)
    created_at:   Mapped[datetime] = mapped_column(nullable=False)
    incident_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("intel_incidents.id"))
    verified:     Mapped[bool]     = mapped_column(Boolean, default=False)
    first_seen:   Mapped[datetime] = mapped_column(default=_now)
```

Define `IntelProbe, IntelIncident, IntelStory, IntelStoryPoint` by mirroring the corresponding `News*` classes with the renames above. Imports at top: `from ..models import Base, _now` plus the needed sqlalchemy symbols.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_models.py -q`
Expected: 3 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 210 passed: 207 + 3).
```bash
git add backend/radar/intel/__init__.py backend/radar/intel/models.py backend/tests/test_intel_models.py
git commit -m "feat(intel): domain models (direction-owned, side-tagged mentions)"
```

---

### Task 2: Intel collector

**Files:**
- Create: `backend/radar/intel/collector.py`
- Test: `backend/tests/test_intel_collector.py`

**Interfaces:**
- Consumes: `IntelDirection, IntelProbe, IntelMention` (Task 1); `..core.spam` helpers as news uses them.
- Produces: `collect_probe(session, probe, provider) -> int` — resolves `probe.direction_id`, iterates `provider.search(probe.query, probe.kind, cursor).posts`, length-filters, writes `IntelMention(direction_id=..., side=probe.side, url=getattr(post,"url",None), views=getattr(post,"likes",0) or 0)`, dedups on `(platform, post_id)` via per-row `session.begin_nested()` savepoint (mirror news), advances watermark.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_collector.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from types import SimpleNamespace

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_collect_probe_writes_intel_mention_with_side():
    from radar.intel.models import IntelDirection, IntelProbe, IntelMention
    from radar.intel import collector
    s = _sess()
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    p = IntelProbe(direction_id=d.id, platform="telegram", kind="channel", query="@mil", side="ru")
    s.add(p); s.commit()
    posts = [SimpleNamespace(post_id="@mil/1", author="@mil", text="удар по складу под Суджей сегодня",
                             followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=12)]
    prov = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, prov)
    assert n == 1
    m = s.query(IntelMention).one()
    assert m.side == "ru" and m.direction_id == d.id

def test_collect_probe_dedups_on_platform_post_id():
    from radar.intel.models import IntelDirection, IntelProbe, IntelMention
    from radar.intel import collector
    s = _sess()
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    p = IntelProbe(direction_id=d.id, platform="telegram", kind="channel", query="@mil", side="ru")
    s.add(p); s.commit()
    post = SimpleNamespace(post_id="@mil/1", author="@mil", text="удар по складу под Суджей сегодня",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)
    prov = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=[post], cursor=None))
    collector.collect_probe(s, p, prov)
    p.watermark = None
    n2 = collector.collect_probe(s, p, prov)
    assert n2 == 0
    assert s.query(IntelMention).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_collector.py -q`
Expected: FAIL (`No module named 'radar.intel.collector'`).

- [ ] **Step 3: Implement collector**

Read `backend/radar/news/collector.py`. Copy it to `backend/radar/intel/collector.py` and apply: `NewsTopic→IntelDirection`, `NewsProbe→IntelProbe`, `NewsMention→IntelMention`, `topic`/`topic_id`→`direction`/`direction_id`. Drop the news "global niche-keyword gating" branch (intel probes are channel reads of curated sources; keep a simple length filter + dedup + watermark). On write, set `side=probe.side`, `url=getattr(post, "url", None)`, `views=getattr(post, "likes", 0) or 0`. Keep the `session.begin_nested()` savepoint dedup and the `MIN_TEXT_LEN` length filter. Copy `_term_hit`/`_word_in` helpers if referenced. No `Scope`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_collector.py -q`
Expected: 2 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 212 passed).
```bash
git add backend/radar/intel/collector.py backend/tests/test_intel_collector.py
git commit -m "feat(intel): collector writing side-tagged IntelMention per direction"
```

---

### Task 3: Intel stories (clustering + verification + anomaly) + credibility

**Files:**
- Create: `backend/radar/intel/stories.py`
- Create: `backend/radar/intel/credibility.py`
- Test: `backend/tests/test_intel_stories.py`

**Interfaces:**
- Consumes: `core.clustering.cluster_owner`, `core.domain.DomainModels`, `core.anomalies.detect_anomaly`, `core.embeddings.embed`, Task 1 models.
- Produces: `stories.update_stories(session, direction_id, embed=None) -> None` (clusters unprocessed `IntelMention` for the direction, recomputes `source_count`/`verified`, flags `is_anomaly`); `credibility.assess_credibility(session, story)`, `credibility.summarize_story(session, story)` operating on `IntelStory`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_stories.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_update_stories_clusters_and_verifies():
    from radar.intel.models import IntelDirection, IntelMention, IntelStory
    from radar.intel import stories
    s = _sess()
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    now = datetime.now(timezone.utc)
    for i, author in enumerate(["@a", "@b", "@c"]):
        s.add(IntelMention(direction_id=d.id, platform="tg", post_id=f"p{i}", author=author,
                           side="ru", text="удар по складу под Суджей сегодня", created_at=now))
    s.commit()
    stories.update_stories(s, d.id, embed=lambda txt: [float(len(txt))])
    st = s.query(IntelStory).first()
    assert st is not None
    assert st.source_count == 3
    assert st.verified is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_stories.py -q`
Expected: FAIL (`No module named 'radar.intel.stories'`).

- [ ] **Step 3: Implement stories + credibility**

`stories.py`: mirror `backend/radar/news/stories.py`, changing models to intel and `owner_field="direction_id"`, `update_stories(session, direction_id, embed=None)`. Build `DomainModels(owner_field="direction_id", Mention=IntelMention, Incident=IntelIncident, Story=IntelStory, StoryPoint=IntelStoryPoint)`. After `cluster_owner`, run `_recompute_verification(session, direction_id)` (distinct non-blank authors via `(a or "").strip()`, `verified = count >= STORY_VERIFY_MIN_SOURCES`, `session.flush()`) and a `_detect_anomalies` loop calling `anomalies.detect_anomaly(session, st.id, IntelStory, IntelStoryPoint)` per touched story (wrap in try/except, mirror news). Embeddings via `from ..core.embeddings import embed as _batch_embed` with `_default_embed = lambda t: _batch_embed([t])[0]`.

`credibility.py`: mirror `backend/radar/news/credibility.py`, rebinding to `IntelStory`/`IntelMention`/`IntelIncident` and `..core.llm`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_stories.py -q`
Expected: 1 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 213 passed).
```bash
git add backend/radar/intel/stories.py backend/radar/intel/credibility.py backend/tests/test_intel_stories.py
git commit -m "feat(intel): story clustering + verification + anomaly + credibility"
```

---

### Task 4: Aggregation & serializers (`aggregate.py`)

**Files:**
- Create: `backend/radar/intel/aggregate.py`
- Test: `backend/tests/test_intel_aggregate.py`

**Interfaces:**
- Consumes: Task 1 models.
- Produces (exact signatures — the API in Task 5 depends on these):
  - `story_summary(session, story) -> dict` → contract `StorySummary` (`id, title, direction, sides, source_count, post_count, verified, credibility, credibility_note, spike_pct, sparkline, last_seen_at`).
  - `story_detail(session, story) -> dict` → `StorySummary` + `{summary_text, points, sources, events}`.
  - `event(m) -> dict` → contract `Event` (`id, platform, author, side, text, url, created_at, verified, direction`).
  - `direction_card(session, direction, window_h) -> dict` → contract `Direction`.
  - `compute_overview(session, window_h) -> dict` → `{kpis, hot, alerts, top_stories}`.
  - `_spike_pct(points) -> float`, `_sparkline(points) -> list[int]` helpers.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_aggregate.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_story_summary_shape_and_sides():
    from radar.intel.models import IntelDirection, IntelStory, IntelIncident, IntelMention
    from radar.intel import aggregate
    s = _sess()
    now = datetime.now(timezone.utc)
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    st = IntelStory(direction_id=d.id, title="Удар по складу", credibility="likely", verified=True,
                    source_count=3, post_count=5, first_seen_at=now, last_seen_at=now, summary="свод")
    s.add(st); s.flush()
    inc = IntelIncident(direction_id=d.id, story_id=st.id, title="i", post_count=5,
                        first_seen_at=now, last_seen_at=now); s.add(inc); s.flush()
    s.add(IntelMention(direction_id=d.id, platform="tg", post_id="p1", author="@a", side="ru",
                       text="x", created_at=now, incident_id=inc.id))
    s.add(IntelMention(direction_id=d.id, platform="tg", post_id="p2", author="@b", side="ua",
                       text="y", created_at=now, incident_id=inc.id))
    s.commit()
    out = aggregate.story_summary(s, st)
    assert out["id"] == st.id and out["direction"] == "kursk"
    assert set(out["sides"]) == {"ru", "ua"}
    for k in ("title","source_count","post_count","verified","credibility","spike_pct","sparkline","last_seen_at"):
        assert k in out

def test_compute_overview_keys():
    from radar.intel import aggregate
    s = _sess()
    out = aggregate.compute_overview(s, window_h=24)
    assert set(out.keys()) == {"kpis", "hot", "alerts", "top_stories"}
    assert set(out["kpis"].keys()) == {"events", "active_stories", "spiking_dirs"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_aggregate.py -q`
Expected: FAIL (`No module named 'radar.intel.aggregate'`).

- [ ] **Step 3: Implement aggregate.py**

```python
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from .models import IntelDirection, IntelMention, IntelIncident, IntelStory, IntelStoryPoint

def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def _sparkline(points) -> list:
    return [int(p.mention_count) for p in sorted(points, key=lambda p: p.bucket_start)][-12:]

def _spike_pct(points) -> float:
    series = [p.mention_count for p in sorted(points, key=lambda p: p.bucket_start)]
    if len(series) < 2:
        return 0.0
    base = sum(series[:-1]) / max(1, len(series) - 1)
    last = series[-1]
    return round((last - base) / base * 100, 1) if base > 0 else (100.0 if last else 0.0)

def _sides(session, story_id) -> list:
    rows = (session.query(IntelMention.side)
            .join(IntelIncident, IntelMention.incident_id == IntelIncident.id)
            .filter(IntelIncident.story_id == story_id).distinct().all())
    return sorted({(r[0] or "").strip() for r in rows if (r[0] or "").strip()})

def _points(session, story_id):
    return session.query(IntelStoryPoint).filter_by(story_id=story_id).all()

def story_summary(session, story) -> dict:
    d = session.get(IntelDirection, story.direction_id)
    pts = _points(session, story.id)
    return {
        "id": story.id, "title": story.title, "direction": d.key if d else None,
        "sides": _sides(session, story.id),
        "source_count": story.source_count, "post_count": story.post_count,
        "verified": bool(story.verified), "credibility": story.credibility,
        "credibility_note": story.credibility_note or "",
        "spike_pct": _spike_pct(pts), "sparkline": _sparkline(pts),
        "last_seen_at": _aware(story.last_seen_at).isoformat() if story.last_seen_at else None,
    }

def event(m) -> dict:
    return {"id": m.id, "platform": m.platform, "author": m.author, "side": m.side,
            "text": m.text, "url": m.url, "created_at": _aware(m.created_at).isoformat(),
            "verified": bool(m.verified), "direction": m.direction_id}

def story_detail(session, story) -> dict:
    base = story_summary(session, story)
    pts = _points(session, story.id)
    src = {}
    rows = (session.query(IntelMention)
            .join(IntelIncident, IntelMention.incident_id == IntelIncident.id)
            .filter(IntelIncident.story_id == story.id).all())
    for m in rows:
        key = m.author or "—"
        e = src.setdefault(key, {"name": key, "side": m.side, "count": 0, "last_at": None, "url": m.url})
        e["count"] += 1
        at = _aware(m.created_at)
        if e["last_at"] is None or at.isoformat() > e["last_at"]:
            e["last_at"] = at.isoformat()
    base.update({
        "summary_text": story.summary or "",
        "points": [{"bucket_start": _aware(p.bucket_start).isoformat(),
                    "mention_count": p.mention_count, "source_count": p.source_count} for p in pts],
        "sources": list(src.values()),
        "events": [event(m) for m in sorted(rows, key=lambda m: m.created_at, reverse=True)[:50]],
    })
    return base

def direction_card(session, direction, window_h=24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
    q = (session.query(IntelMention)
         .filter(IntelMention.direction_id == direction.id, IntelMention.created_at >= since))
    events_count = q.count()
    stories = session.query(IntelStory).filter_by(direction_id=direction.id).all()
    spike = max([_spike_pct(_points(session, st.id)) for st in stories], default=0.0)
    last = q.order_by(IntelMention.created_at.desc()).first()
    creds = [st.credibility for st in stories if st.credibility and st.credibility != "unrated"]
    dominant = max(set(creds), key=creds.count) if creds else "unrated"
    activity = min(100, events_count * 5)
    return {"key": direction.key, "name": direction.name, "activity_level": activity,
            "spike_pct": spike, "events_count": events_count, "dominant_credibility": dominant,
            "last_event": ({"text": last.text, "at": _aware(last.created_at).isoformat(),
                            "source": last.author} if last else None)}

def compute_overview(session, window_h=24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
    events = session.query(func.count(IntelMention.id)).filter(IntelMention.created_at >= since).scalar() or 0
    stories = session.query(IntelStory).filter_by(status="active").all()
    summaries = [story_summary(session, st) for st in stories]
    hot = sorted(summaries, key=lambda x: x["spike_pct"], reverse=True)[:8]
    top = sorted(summaries, key=lambda x: x["post_count"], reverse=True)[:8]
    alerts = [{"id": st.id, "story_id": st.id, "direction": story_summary(session, st)["direction"],
               "kind": "spike", "magnitude": story_summary(session, st)["spike_pct"],
               "message": st.title, "at": _aware(st.last_seen_at).isoformat() if st.last_seen_at else None}
              for st in stories if st.is_anomaly][:20]
    spiking_dirs = len({s["direction"] for s in summaries if s["spike_pct"] >= 50})
    return {"kpis": {"events": events, "active_stories": len(stories), "spiking_dirs": spiking_dirs},
            "hot": hot, "alerts": alerts, "top_stories": top}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_aggregate.py -q`
Expected: 2 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 215 passed).
```bash
git add backend/radar/intel/aggregate.py backend/tests/test_intel_aggregate.py
git commit -m "feat(intel): aggregation + contract serializers (overview, directions, story shapes)"
```

---

### Task 5: Intel API router (`/intel/*`)

**Files:**
- Create: `backend/radar/intel/api.py`
- Test: `backend/tests/test_intel_api.py`

**Interfaces:**
- Consumes: `..core.auth` (the `current_user` dependency — read how `radar/news/api.py` imports/uses it), `..core.db` session dependency, Task 1 models, Task 3 `credibility`, Task 4 `aggregate`.
- Produces: `router = APIRouter(tags=["intel"])` mounting the §6 endpoints.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_api.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_intel_router_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path/'i.db'}")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from radar.intel.api import router
    app = FastAPI(); app.include_router(router)
    c = TestClient(app)
    assert c.get("/intel/overview").status_code in (401, 403)
    assert c.get("/intel/directions").status_code in (401, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_api.py -q`
Expected: FAIL (`No module named 'radar.intel.api'`).

- [ ] **Step 3: Implement the router**

Read `backend/radar/news/api.py` for the exact auth dependency (`current_user`) and session-`Depends` pattern; mirror them. Implement endpoints, delegating serialization to `aggregate`:
- `GET /intel/overview?window=24h` → `aggregate.compute_overview(session, _hours(window))`.
- `GET /intel/stream?window=&direction=&limit=50` → query `IntelMention` (optional `direction` key→id), `created_at >= since`, order desc, `[aggregate.event(m) for m in rows]`.
- `GET /intel/stories?direction=&side=&verified=&sort=&limit=50` → filter `IntelStory` (join mentions for `side`), `verified` flag, sort `activity` (spike) or `recency` (last_seen_at desc), `[aggregate.story_summary(...)]`.
- `GET /intel/stories/{id}` → `aggregate.story_detail(session, story)` or 404.
- `POST /intel/stories/{id}/assess` → `credibility.assess_credibility(session, story)`; `POST /intel/stories/{id}/summarize` → `credibility.summarize_story(session, story)`; 503 on `LLMNotConfigured` (mirror news).
- `GET /intel/directions?window=24h` → `[aggregate.direction_card(session, d, _hours(window)) for d in session.query(IntelDirection).all()]`.
- `GET /intel/directions/{key}?window=24h` → resolve direction by key (404 if none) → `{direction: direction_card(...), stories: [story_summary...], stream: [event...]}`.
- `GET /intel/search?q=` → `IntelStory.title ILIKE %q%` → `[story_summary...]`.

Add a `_hours(window: str) -> int` helper parsing `"1h"|"24h"|"7d"` → hours.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_api.py -q`
Expected: 1 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 216 passed).
```bash
git add backend/radar/intel/api.py backend/tests/test_intel_api.py
git commit -m "feat(intel): /intel/* API router on the closed-contour contract"
```

---

### Task 6: Seed directions + mount router + authed end-to-end test

**Files:**
- Create: `backend/radar/intel/seed.py`
- Modify: `backend/radar/app.py`
- Test: extend `backend/tests/test_intel_api.py`

**Interfaces:**
- Consumes: Task 1 models, Task 5 router, `radar/app.py` lifespan.
- Produces: `seed.ensure_default_directions(session)` (idempotent); `intel_router` mounted in `app.py`.

- [ ] **Step 1: Write the failing test (authed overview is 200 with seeded directions)**

```python
# append to backend/tests/test_intel_api.py
def test_intel_overview_authed_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path/'i2.db'}")
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as c:
        c.post("/auth/register", json={"email": "intel@test.local", "password": "secret123"})
        tok = c.post("/auth/login", json={"email": "intel@test.local", "password": "secret123"}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        ov = c.get("/intel/overview", headers=h)
        assert ov.status_code == 200
        assert set(ov.json().keys()) == {"kpis", "hot", "alerts", "top_stories"}
        dirs = c.get("/intel/directions", headers=h)
        assert dirs.status_code == 200 and isinstance(dirs.json(), list) and len(dirs.json()) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_api.py::test_intel_overview_authed_ok -q`
Expected: FAIL (router not mounted on `radar.app` / no directions).

- [ ] **Step 3: Implement seed + mount**

`backend/radar/intel/seed.py`:
```python
from .models import IntelDirection

DEFAULT_DIRECTIONS = [
    ("kursk", "Курское"), ("zaporizhzhia", "Запорожское"), ("kharkiv", "Харьковское"),
    ("donetsk", "Донецкое"), ("kherson", "Херсонское"),
]

def ensure_default_directions(session) -> None:
    existing = {k for (k,) in session.query(IntelDirection.key).all()}
    for key, name in DEFAULT_DIRECTIONS:
        if key not in existing:
            session.add(IntelDirection(key=key, name=name))
    session.commit()
```

In `backend/radar/app.py`: add `from .intel.api import router as intel_router` and `app.include_router(intel_router)` next to the other routers; inside the `lifespan` startup (after `init_db()` and the existing seed calls), add `import radar.intel.models  # noqa` (ensure tables registered before create_all already runs in init_db — verify init_db imports domain models or add intel there too) and `from .intel import seed as intel_seed; intel_seed.ensure_default_directions(session)` within the same session block.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_api.py -q`
Expected: all intel api tests pass.

- [ ] **Step 5: Full suite + boot smoke + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 217 passed).
Run: `cd backend && python3 -c "import radar.app; print('app ok')"` → `app ok`.
```bash
git add backend/radar/intel/seed.py backend/radar/app.py backend/tests/test_intel_api.py
git commit -m "feat(intel): seed default directions + mount /intel router in app"
```

---

## Notes / Deferred (per spec §2, §9)
- Collection wiring into the scheduler (an intel pass), both-sides source curation, and `side` inference are deferred technical features — not in this plan. The collector exists and is unit-tested; wiring a live pass comes when source lists are defined.
- No geocoded map, no digests endpoint (not in the contract).
- `init_db` must `create_all` the intel tables: confirm `radar/core/db.py::init_db` imports domain model modules (news/brand) and add `import radar.intel.models` there if that is how tables get registered; otherwise the lifespan import in Task 6 covers it. Verify during Task 6.
