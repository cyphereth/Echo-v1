# News/Brand Domain Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the entangled news and brand products into two isolated domains (code + data), removing the `Scope` polymorphism and the shared nullable-owner tables.

**Architecture:** `radar/core/` holds infrastructure (db, auth, providers, llm, embeddings, a generic clustering engine, anomaly stats, the scheduler core). `radar/news/` and `radar/brand/` each own their models, collectors, story logic, digests, scheduler passes, and an API router. `radar/app.py` assembles the FastAPI app from both routers. Each domain gets its own tables; a one-shot idempotent migration copies existing rows into the new tables by owner. Work proceeds in 7 phases (`core → data → news → brand → teardown → frontend → drop`), keeping the test suite green and the app runnable at every commit.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, pytest (backend); Vite + React + react-router (frontend). Run backend from `backend/` with `python3 -m uvicorn radar.app:app --port 8000 --log-level warning` (note: entrypoint becomes `radar.app` after Phase 5). Tests: `python3 -m pytest`.

**Spec:** `backend/docs/superpowers/specs/2026-06-18-domain-split-design.md`

**Branch:** `refactor/domain-split` (already created; spec committed at `1d8685c`).

**Conventions used throughout:**
- All radar modules use relative imports (`from .db import ...`). After moving a module into `core/`, `news/`, or `brand/`, intra-package references become `from ..core.db import ...` etc.
- Tests live in `backend/tests/` and start with `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))` then `from radar.<module> import ...`.
- Run the full suite after every task: `cd backend && python3 -m pytest -q`. "Green" = the phase did not regress. Record the baseline count first (Task 0).

---

## Phase 0 — Baseline

### Task 0: Capture the green baseline

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite and record the count**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3`
Expected: a line like `N passed` (record N — this is the regression baseline; spec says ~225). If anything fails on a clean checkout, STOP and fix or report before refactoring.

- [ ] **Step 2: Confirm the app boots**

Run: `cd backend && python3 -c "import radar.api; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Note the current entrypoint**

The app is `radar.api:app`. It becomes `radar.app:app` in Phase 5. Until then, keep using `radar.api`.

---

## Phase 1 — Extract `core` (no behavior change)

The goal of this phase is purely mechanical relocation. No logic changes. The suite must stay green after every task.

### Task 1.1: Create the `core` package and move pure-infrastructure modules

**Files:**
- Create: `backend/radar/core/__init__.py`
- Move: `backend/radar/db.py` → `backend/radar/core/db.py`
- Move: `backend/radar/auth.py` → `backend/radar/core/auth.py`
- Move: `backend/radar/llm.py` → `backend/radar/core/llm.py`
- Move: `backend/radar/vec.py` → `backend/radar/core/vec.py`
- Move: `backend/radar/embeddings.py` → `backend/radar/core/embeddings.py`
- Move: `backend/radar/spam.py` → `backend/radar/core/spam.py`
- Move: `backend/radar/providers/` → `backend/radar/core/providers/`

- [ ] **Step 1: Create the package and move files with git**

```bash
cd backend
mkdir -p radar/core
touch radar/core/__init__.py
git mv radar/db.py radar/core/db.py
git mv radar/auth.py radar/core/auth.py
git mv radar/llm.py radar/core/llm.py
git mv radar/vec.py radar/core/vec.py
git mv radar/embeddings.py radar/core/embeddings.py
git mv radar/spam.py radar/core/spam.py
git mv radar/providers radar/core/providers
```

- [ ] **Step 2: Fix imports *inside* the moved modules**

These modules import siblings that are now also in `core/`, so relative imports still resolve (`from .vec import` etc. — same package). But any moved module that imports a module still at `radar/` top level (e.g. `from .models import`) now needs `from ..models import`. Find them:

```bash
cd backend
grep -rnE "from \.(models|collector|stories|pipeline|scope|drafts|digests|scoring|classifier_rules|anomalies|hotwatch|engagement|explore|maintenance|credibility|api|seed) " radar/core/
```

For each hit, change the single dot to double dot (`from .models` → `from ..models`). Providers import `from .base` (sibling, fine) and may import `from ..spam`/`..models` — verify with the grep above against `radar/core/providers/`.

- [ ] **Step 3: Fix imports *of* the moved modules across the rest of the package**

Every other file under `radar/` that did `from .db import` / `from .auth import` / `from .llm import` / `from .vec import` / `from .embeddings import` / `from .spam import` / `from .providers...` must now point at `core`. From `radar/` top-level modules that is `from .core.db import`:

```bash
cd backend
grep -rln --include=*.py -E "from \.(db|auth|llm|vec|embeddings|spam|providers) import|from \.providers" radar | grep -v "radar/core/"
```

For each top-level `radar/*.py` file in that list, rewrite `from .db ` → `from .core.db `, `from .auth ` → `from .core.auth `, `from .llm ` → `from .core.llm `, `from .vec ` → `from .core.vec `, `from .embeddings ` → `from .core.embeddings `, `from .spam ` → `from .core.spam `, `from .providers` → `from .core.providers`.

- [ ] **Step 4: Fix test imports of moved modules**

```bash
cd backend
grep -rln -E "from radar\.(db|auth|llm|vec|embeddings|spam|providers)|radar\.providers" tests
```

For each, rewrite `radar.db` → `radar.core.db`, `radar.auth` → `radar.core.auth`, `radar.llm` → `radar.core.llm`, `radar.vec` → `radar.core.vec`, `radar.embeddings` → `radar.core.embeddings`, `radar.spam` → `radar.core.spam`, `radar.providers` → `radar.core.providers`.

- [ ] **Step 5: Run the suite**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3`
Expected: same N passed as Task 0. If imports are missed you'll see `ModuleNotFoundError` / `ImportError` — fix the named module's import and re-run.

- [ ] **Step 6: Confirm the app still boots**

Run: `cd backend && python3 -c "import radar.api; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
cd backend && git add -A && git commit -m "refactor(core): extract infrastructure modules into radar.core"
```

### Task 1.2: Move the scheduler core and anomalies into `core`

**Files:**
- Move: `backend/radar/scheduler.py` → `backend/radar/core/scheduler.py`
- Move: `backend/radar/anomalies.py` → `backend/radar/core/anomalies.py`

> Note: `scheduler.py` currently imports domain code (`collector`, `pipeline`, `stories`, `digests`) and defines the domain passes inline. We move the *file* now and fix its internal imports to `..collector` etc.; the pass functions are extracted to `news/passes.py` and `brand/passes.py` in Phases 3–4. This task only relocates and re-points imports — no logic change.

- [ ] **Step 1: Move with git**

```bash
cd backend
git mv radar/scheduler.py radar/core/scheduler.py
git mv radar/anomalies.py radar/core/anomalies.py
```

- [ ] **Step 2: Fix internal imports in the moved files**

```bash
cd backend
grep -nE "from \.(collector|pipeline|stories|digests|models|scope|hotwatch|maintenance|credibility|sources) import" radar/core/scheduler.py radar/core/anomalies.py
```
Rewrite each single-dot domain import to double-dot (`from .collector` → `from ..collector`). Core siblings already moved (`from .db` resolves within `core`). If `scheduler.py` used `from .db import` it is now a `core` sibling — change `from .core.db` back to `from .db` only if the grep shows it; simplest: ensure `from .db import get_session` (sibling in core) — verify it resolves by the import test in Step 4.

- [ ] **Step 3: Fix references to the moved modules elsewhere**

```bash
cd backend
grep -rln -E "from \.scheduler import|from \.anomalies import|import radar\.scheduler|radar\.anomalies|radar\.scheduler" radar tests | grep -v "radar/core/"
```
In `radar/*.py`: `from .scheduler` → `from .core.scheduler`, `from .anomalies` → `from .core.anomalies`. In tests: `radar.scheduler` → `radar.core.scheduler`, `radar.anomalies` → `radar.core.anomalies`.

- [ ] **Step 4: Run suite + boot check**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3 && python3 -c "import radar.api; print('ok')"`
Expected: N passed, then `ok`.

- [ ] **Step 5: Commit**

```bash
cd backend && git add -A && git commit -m "refactor(core): move scheduler core and anomaly stats into radar.core"
```

### Task 1.3: Extract the generic clustering engine

The current `radar/stories.py` clusters mentions into incidents/stories using `Scope` + hardcoded `Mention`/`Incident`/`Story`/`StoryPoint`. Extract the algorithm into `core/clustering.py`, parameterized by a `DomainModels` bundle so each domain passes its own model classes. `stories.py` stays put for now as a thin caller; it is split per-domain in Phases 3–4.

**Files:**
- Create: `backend/radar/core/clustering.py`
- Create: `backend/radar/core/domain.py`
- Test: `backend/tests/test_clustering_engine.py`
- Modify: `backend/radar/stories.py` (delegate to the engine)

- [ ] **Step 1: Write the `DomainModels` bundle**

Create `backend/radar/core/domain.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Type


@dataclass(frozen=True)
class DomainModels:
    """Bundle of a domain's ORM classes + its owner FK column name, so the
    generic clustering engine can read/write the right tables without Scope."""
    owner_field: str            # "brand_id" or "topic_id"
    Mention: Type
    Incident: Type
    Story: Type
    StoryPoint: Type

    def owner_kwargs(self, owner_id: int) -> dict:
        return {self.owner_field: owner_id}
```

- [ ] **Step 2: Write a failing test for the engine against throwaway models**

Create `backend/tests/test_clustering_engine.py`. It builds a tiny in-memory schema with generic-shaped models and asserts the engine groups two near-identical mentions into one story.

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def _setup():
    from sqlalchemy import create_engine, Integer, Text, Float, Boolean, ForeignKey
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

    class Base(DeclarativeBase):
        pass

    class M(Base):
        __tablename__ = "m"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        topic_id: Mapped[int] = mapped_column(Integer)
        text: Mapped[str] = mapped_column(Text, default="")
        author: Mapped[str] = mapped_column(Text, default="")
        created_at: Mapped[datetime] = mapped_column()
        incident_id: Mapped[int] = mapped_column(ForeignKey("inc.id"), nullable=True)

    class Inc(Base):
        __tablename__ = "inc"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        topic_id: Mapped[int] = mapped_column(Integer)
        story_id: Mapped[int] = mapped_column(ForeignKey("st.id"), nullable=True)
        title: Mapped[str] = mapped_column(Text, default="")
        post_count: Mapped[int] = mapped_column(Integer, default=1)
        first_seen_at: Mapped[datetime] = mapped_column()
        last_seen_at: Mapped[datetime] = mapped_column()

    class St(Base):
        __tablename__ = "st"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        topic_id: Mapped[int] = mapped_column(Integer)
        title: Mapped[str] = mapped_column(Text, default="")
        status: Mapped[str] = mapped_column(Text, default="active")
        is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
        post_count: Mapped[int] = mapped_column(Integer, default=0)
        first_seen_at: Mapped[datetime] = mapped_column()
        last_seen_at: Mapped[datetime] = mapped_column()

    class SP(Base):
        __tablename__ = "sp"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        story_id: Mapped[int] = mapped_column(ForeignKey("st.id"))
        bucket_start: Mapped[datetime] = mapped_column()
        mention_count: Mapped[int] = mapped_column(Integer, default=0)

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng), M, Inc, St, SP


def test_engine_clusters_similar_mentions_into_one_story():
    from radar.core.clustering import cluster_owner
    from radar.core.domain import DomainModels
    s, M, Inc, St, SP = _setup()
    now = datetime.now(timezone.utc)
    s.add_all([
        M(topic_id=1, text="взрыв на нефтебазе под Брянском", author="a", created_at=now),
        M(topic_id=1, text="взрыв нефтебаза Брянск область", author="b", created_at=now),
    ])
    s.commit()
    models = DomainModels(owner_field="topic_id", Mention=M, Incident=Inc, Story=St, StoryPoint=SP)
    cluster_owner(s, owner_id=1, models=models, embed=lambda txt: [float(len(txt))])
    assert s.query(St).count() >= 1
    assert all(m.incident_id is not None for m in s.query(M).all())
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_clustering_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'radar.core.clustering'`.

- [ ] **Step 4: Implement `core/clustering.py` by parameterizing the current stories logic**

Open `backend/radar/stories.py`. Copy its clustering functions into `backend/radar/core/clustering.py` and apply this exact mechanical transformation:
- Replace every hardcoded `Mention` → `models.Mention`, `Incident` → `models.Incident`, `Story` → `models.Story`, `StoryPoint` → `models.StoryPoint`.
- Replace `scope.owner_kwargs()` → `models.owner_kwargs(owner_id)` and any `scope.id` used as the owner → `owner_id`.
- Replace the filter `.filter_by(**scope.owner_kwargs())` → `.filter_by(**models.owner_kwargs(owner_id))`.
- Replace the embedding call (currently `from .embeddings import embed` or similar) with an injected `embed` callable parameter, so the engine has no provider dependency.
- The public entrypoint is:

```python
def cluster_owner(session, owner_id: int, models, embed, *,
                  sim_threshold: float = 0.78, now=None) -> None:
    """Generic story/incident clustering for one owner (brand or topic).
    Reads models.Mention rows for owner_id with incident_id IS NULL, embeds via
    `embed(text)->vector`, attaches to the nearest incident/story above
    sim_threshold or creates new ones, and refreshes story_points + counts.
    All table access goes through the `models` bundle — no Scope, no globals."""
```

Keep the similarity/cosine and bucketing helpers private (`_cos`, `_bucket_hour`, etc.) inside this module. Do NOT include credibility or source-count logic here — that is news-specific and stays in `news/credibility.py`.

- [ ] **Step 5: Run the engine test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_clustering_engine.py -q`
Expected: PASS.

- [ ] **Step 6: Make `stories.py` delegate to the engine (keep behavior identical)**

In `backend/radar/stories.py`, replace the clustering body of `update_stories(session, scope, ...)` with a call into the engine, building the bundle from the current global models:

```python
from .core.clustering import cluster_owner
from .core.domain import DomainModels
from .models import Mention, Incident, Story, StoryPoint
from .embeddings import embed  # existing embedding fn

def update_stories(session, scope, **kwargs):
    models = DomainModels(owner_field=f"{scope.kind}_id",
                          Mention=Mention, Incident=Incident,
                          Story=Story, StoryPoint=StoryPoint)
    cluster_owner(session, owner_id=scope.id, models=models, embed=embed)
    # keep the existing post-clustering steps (verification recompute, anomaly
    # flagging) exactly as they were below this point
```

Preserve every non-clustering line that already followed (e.g. `_recompute_verification`, anomaly flag). Only the clustering core is delegated.

- [ ] **Step 7: Run the full suite**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3`
Expected: N passed (the existing story tests now exercise the engine via `stories.py`).

- [ ] **Step 8: Commit**

```bash
cd backend && git add -A && git commit -m "refactor(core): extract generic clustering engine parameterized by DomainModels"
```

---

## Phase 2 — New domain models + migration (additive)

New tables are created alongside the old ones. Old code still reads the old tables. A guarded, idempotent migration copies rows by owner. Nothing is switched yet.

### Task 2.1: Define news + brand model modules

**Files:**
- Create: `backend/radar/news/__init__.py`
- Create: `backend/radar/news/models.py`
- Create: `backend/radar/brand/__init__.py`
- Create: `backend/radar/brand/models.py`
- Test: `backend/tests/test_domain_models.py`

> All new models share `radar.models.Base` (single metadata) so `create_all` builds them together and FKs to `users` resolve. Import `Base` and `_now` from `..models`.

- [ ] **Step 1: Write a failing test that the new tables exist and are lean/rich as specified**

Create `backend/tests/test_domain_models.py`:

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mem():
    from sqlalchemy import create_engine
    from radar.models import Base
    import radar.news.models  # noqa: F401  (register tables)
    import radar.brand.models  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_news_mention_is_lean():
    _mem()
    from radar.news.models import NewsMention
    cols = set(NewsMention.__table__.columns.keys())
    assert "topic_id" in cols
    # brand-only fields must NOT leak into news
    for gone in ("competitor", "opportunity", "draft", "lane", "tone", "phase", "is_hot", "status"):
        assert gone not in cols, f"{gone} should not be on NewsMention"


def test_news_story_has_credibility():
    _mem()
    from radar.news.models import NewsStory
    cols = set(NewsStory.__table__.columns.keys())
    for need in ("source_count", "verified", "credibility", "credibility_note", "summary"):
        assert need in cols


def test_brand_story_has_no_credibility():
    _mem()
    from radar.brand.models import BrandStory
    cols = set(BrandStory.__table__.columns.keys())
    assert "credibility" not in cols
    assert "verified" not in cols
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_domain_models.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'radar.news.models'`.

- [ ] **Step 3: Write `news/models.py`**

```python
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..models import Base, _now
import json


class NewsTopic(Base):
    __tablename__ = "news_topics"
    id:             Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:        Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    name:           Mapped[str]           = mapped_column(Text, nullable=False)
    keywords:       Mapped[str]           = mapped_column(Text, default="[]")
    niche_keywords: Mapped[str]           = mapped_column(Text, default="[]")
    kind:           Mapped[str]           = mapped_column(Text, default="search")
    market:         Mapped[str]           = mapped_column(Text, default="ru")
    auto_collect:   Mapped[bool]          = mapped_column(Boolean, default=True)
    created_at:     Mapped[datetime]      = mapped_column(default=_now)

    def keywords_list(self):       return json.loads(self.keywords or "[]")
    def niche_keywords_list(self): return json.loads(self.niche_keywords or "[]")


class NewsProbe(Base):
    __tablename__ = "news_probes"
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:     Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    platform:     Mapped[str]      = mapped_column(Text)
    kind:         Mapped[str]      = mapped_column(Text)              # channel | global
    query:        Mapped[str]      = mapped_column(Text)
    label:        Mapped[Optional[str]] = mapped_column(Text)
    watermark:    Mapped[Optional[str]] = mapped_column(Text)
    next_run_at:  Mapped[datetime] = mapped_column(default=_now)
    interval_sec: Mapped[int]      = mapped_column(Integer, default=3600)


class NewsMention(Base):
    __tablename__ = "news_mentions"
    __table_args__ = (UniqueConstraint("platform", "post_id"),)
    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:    Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    platform:    Mapped[str]      = mapped_column(Text)
    post_id:     Mapped[str]      = mapped_column(Text)
    author:      Mapped[str]      = mapped_column(Text)
    followers:   Mapped[int]      = mapped_column(Integer, default=0)
    text:        Mapped[str]      = mapped_column(Text, default="")
    hashtags:    Mapped[str]      = mapped_column(Text, default="[]")
    created_at:  Mapped[datetime] = mapped_column(nullable=False)
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("news_incidents.id"))
    source:      Mapped[str]      = mapped_column(Text, default="channel")  # channel | global
    first_seen:  Mapped[datetime] = mapped_column(default=_now)


class NewsIncident(Base):
    __tablename__ = "news_incidents"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:      Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    story_id:      Mapped[Optional[int]] = mapped_column(ForeignKey("news_stories.id"))
    title:         Mapped[str]      = mapped_column(Text, default="")
    summary:       Mapped[Optional[str]] = mapped_column(Text)
    post_count:    Mapped[int]      = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at:  Mapped[datetime] = mapped_column(nullable=False)
    created_at:    Mapped[datetime] = mapped_column(default=_now)


class NewsStory(Base):
    __tablename__ = "news_stories"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:      Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    title:         Mapped[str]      = mapped_column(Text, default="")
    status:        Mapped[str]      = mapped_column(Text, default="active")
    is_anomaly:    Mapped[bool]     = mapped_column(Boolean, default=False)
    post_count:    Mapped[int]      = mapped_column(Integer, default=0)
    source_count:  Mapped[int]      = mapped_column(Integer, default=0)
    verified:      Mapped[bool]     = mapped_column(Boolean, default=False)
    credibility:   Mapped[str]      = mapped_column(Text, default="unrated")
    credibility_note: Mapped[str]   = mapped_column(Text, default="")
    summary:       Mapped[str]      = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at:  Mapped[datetime] = mapped_column(nullable=False)
    created_at:    Mapped[datetime] = mapped_column(default=_now)


class NewsStoryPoint(Base):
    __tablename__ = "news_story_points"
    __table_args__ = (UniqueConstraint("story_id", "bucket_start"),)
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id:      Mapped[int]      = mapped_column(ForeignKey("news_stories.id"))
    bucket_start:  Mapped[datetime] = mapped_column(nullable=False)
    mention_count: Mapped[int]      = mapped_column(Integer, default=0)
    source_count:  Mapped[int]      = mapped_column(Integer, default=0)


class NewsReport(Base):
    __tablename__ = "news_reports"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:   Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    story_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("news_stories.id"))
    kind:       Mapped[str]      = mapped_column(Text, default="digest")
    body:       Mapped[str]      = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
```

- [ ] **Step 4: Write `brand/models.py`**

Copy the current `Brand`, `Probe`, `Mention` (full field set), `MentionSnapshot`, `Comment`, `DraftEdit`, `EngagementLog`, `CityReport`, `Incident`, `Story`, `StoryPoint`, `Report` classes from `radar/models.py` into `backend/radar/brand/models.py`, renaming tables and classes to the brand-prefixed names and dropping the now-unused `topic_id` column from the owner tables. Concretely:
- `Brand` → `__tablename__ = "brands"` (unchanged), class `Brand`.
- `Probe` → class `BrandProbe`, `__tablename__ = "brand_probes"`, FK `brand_id` NOT NULL (drop `topic_id`).
- `Mention` → class `BrandMention`, `__tablename__ = "brand_mentions"`, FK `brand_id` NOT NULL (drop `topic_id`), keep ALL reply fields (`lane, source, competitor, opportunity, draft, draft_flag, status, tone, phase, is_hot, severity, category, confidence`), and re-point `incident_id` FK to `brand_incidents.id`.
- `Incident` → `BrandIncident` / `brand_incidents`, `brand_id` NOT NULL (drop `topic_id`), `story_id` → `brand_stories.id`.
- `Story` → `BrandStory` / `brand_stories`, `brand_id` NOT NULL (drop `topic_id`), **drop** `source_count, verified, credibility, credibility_note` (keep `summary`, `is_anomaly`).
- `StoryPoint` → `BrandStoryPoint` / `brand_story_points`, `story_id` → `brand_stories.id`.
- `Report` → `BrandReport` / `brand_reports`, `brand_id` NOT NULL (drop `topic_id`), `story_id` → `brand_stories.id`.
- `MentionSnapshot`/`Comment`/`DraftEdit`/`EngagementLog` → re-point their `mention_id` FK to `brand_mentions.id` (and `brand_id` FKs stay), keep table names `mention_snapshots`, `comments`, `draft_edits`, `engagement_log`.
- `CityReport` → unchanged (`city_reports`), moved verbatim.

Import `Base`, `_now` from `..models`; keep the `*_list()` JSON helpers on `Brand`.

- [ ] **Step 5: Run the model test**

Run: `cd backend && python3 -m pytest tests/test_domain_models.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full suite (old models still present and used)**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3`
Expected: N passed (no regression — new models are additive and not yet wired).

- [ ] **Step 7: Commit**

```bash
cd backend && git add -A && git commit -m "feat(models): add isolated news.* and brand.* domain models (additive)"
```

### Task 2.2: Write the routed copy migration

**Files:**
- Create: `backend/radar/core/migrate_split.py`
- Modify: `backend/radar/core/db.py:130-138` (call migration in `init_db`)
- Test: `backend/tests/test_migrate_split.py`

- [ ] **Step 1: Write a failing test that seeds old-schema rows and asserts routed copy**

Create `backend/tests/test_migrate_split.py`:

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def _engine_with_old_and_new():
    from sqlalchemy import create_engine
    from radar.models import Base
    import radar.news.models, radar.brand.models  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)  # builds old (mentions/...) AND new (news_*/brand_*) tables
    return eng


def test_migration_routes_rows_by_owner():
    from sqlalchemy.orm import Session
    from radar.models import Brand, Topic, Mention
    from radar.news.models import NewsMention
    from radar.brand.models import BrandMention
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(Brand(id=1, name="B"))
        s.add(Topic(id=1, name="T"))
        s.add(Mention(id=10, brand_id=1, platform="tg", post_id="p1", author="a", text="x", created_at=now))
        s.add(Mention(id=11, topic_id=1, platform="tg", post_id="p2", author="b", text="y", created_at=now))
        s.commit()
    migrate_split(eng)
    with Session(eng) as s:
        assert s.query(BrandMention).count() == 1
        assert s.query(NewsMention).count() == 1
        assert s.get(BrandMention, 10).post_id == "p1"   # PK preserved
        assert s.get(NewsMention, 11).post_id == "p2"


def test_migration_is_idempotent():
    from sqlalchemy.orm import Session
    from radar.models import Topic, Mention
    from radar.news.models import NewsMention
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(Topic(id=1, name="T"))
        s.add(Mention(id=11, topic_id=1, platform="tg", post_id="p2", author="b", text="y", created_at=now))
        s.commit()
    migrate_split(eng)
    migrate_split(eng)  # second run must not duplicate
    with Session(eng) as s:
        assert s.query(NewsMention).count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_migrate_split.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'radar.core.migrate_split'`.

- [ ] **Step 3: Implement `core/migrate_split.py`**

```python
"""One-shot, idempotent migration: copy rows from the legacy shared tables
into the per-domain tables, routed by owner. Guarded so it only runs when the
old tables exist and the new ones are still empty. PKs and internal FKs are
preserved (an owner's whole subtree routes to one domain)."""
from __future__ import annotations
import logging
from sqlalchemy import inspect, text

log = logging.getLogger("radar.migrate")

# old table -> (news table, brand table, owner discriminator columns)
# columns to copy are intersected with the destination table's columns.
_PLAN = [
    ("probes",       "news_probes",       "brand_probes"),
    ("incidents",    "news_incidents",    "brand_incidents"),
    ("stories",      "news_stories",      "brand_stories"),
    ("mentions",     "news_mentions",     "brand_mentions"),
    ("reports",      "news_reports",      "brand_reports"),
]


def _cols(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def _copy(conn, src: str, dst: str, where: str):
    src_cols = _cols(conn, src)
    dst_cols = _cols(conn, dst)
    shared = [c for c in src_cols if c in dst_cols]
    cols = ", ".join(shared)
    conn.execute(text(f"INSERT INTO {dst} ({cols}) SELECT {cols} FROM {src} WHERE {where}"))


def migrate_split(engine) -> None:
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    if "mentions" not in existing or "news_mentions" not in existing:
        return  # nothing to migrate (fresh DB built straight from new models)
    with engine.begin() as conn:
        # idempotency guard: if any destination already has rows, assume done.
        already = conn.execute(text("SELECT COUNT(*) FROM news_mentions")).scalar() \
            or conn.execute(text("SELECT COUNT(*) FROM brand_mentions")).scalar()
        if already:
            return
        for src, news_dst, brand_dst in _PLAN:
            if src not in existing:
                continue
            _copy(conn, src, news_dst, "topic_id IS NOT NULL")
            _copy(conn, src, brand_dst, "brand_id IS NOT NULL")
        # story_points route by their story's domain
        if "story_points" in existing:
            _copy(conn, "story_points", "news_story_points",
                  "story_id IN (SELECT id FROM stories WHERE topic_id IS NOT NULL)")
            _copy(conn, "story_points", "brand_story_points",
                  "story_id IN (SELECT id FROM stories WHERE brand_id IS NOT NULL)")
        # brand-only tables move verbatim (all rows)
        for tbl in ("mention_snapshots", "comments", "draft_edits", "engagement_log"):
            if tbl in existing:
                pass  # same table name reused by brand models; no copy needed
        # verify counts
        for src, news_dst, brand_dst in _PLAN:
            if src not in existing:
                continue
            old_n = conn.execute(text(f"SELECT COUNT(*) FROM {src} WHERE topic_id IS NOT NULL")).scalar()
            old_b = conn.execute(text(f"SELECT COUNT(*) FROM {src} WHERE brand_id IS NOT NULL")).scalar()
            new_n = conn.execute(text(f"SELECT COUNT(*) FROM {news_dst}")).scalar()
            new_b = conn.execute(text(f"SELECT COUNT(*) FROM {brand_dst}")).scalar()
            if (old_n, old_b) != (new_n, new_b):
                raise RuntimeError(
                    f"migrate_split count mismatch for {src}: "
                    f"old(news={old_n},brand={old_b}) new(news={new_n},brand={new_b})")
        log.info("migrate_split: domain tables populated from legacy tables")
```

> Note on `mention_snapshots`/`comments`/`draft_edits`/`engagement_log`: brand models reuse the same table names, so the rows are already in place — no copy. They are listed for documentation. `city_reports` likewise unchanged.

- [ ] **Step 4: Run the migration test**

Run: `cd backend && python3 -m pytest tests/test_migrate_split.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Wire migration into `init_db` (after `create_all`, before old relax)**

In `backend/radar/core/db.py`, inside `init_db()` add, after the new models are imported and `create_all` runs:

```python
    import radar.news.models, radar.brand.models  # noqa: F401  register new tables
    Base.metadata.create_all(engine)
    from .migrate_split import migrate_split
    migrate_split(engine)
```

Keep `_migrate()` and (for now) `_relax_brand_id_not_null()` — they still serve the legacy tables until Phase 5.

- [ ] **Step 6: Run the full suite**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3`
Expected: N + 5 passed (3 model tests from 2.1 + 2 migration tests). No prior test regresses.

- [ ] **Step 7: Commit**

```bash
cd backend && git add -A && git commit -m "feat(db): routed idempotent migration from legacy tables to domain tables"
```

---

## Phase 3 — Build the `news` domain

Move news logic onto the new models and switch `/news/*` + the news scheduler pass. After this phase, news no longer touches `Scope` or legacy tables.

### Task 3.1: News collector + sources on new models

**Files:**
- Create: `backend/radar/news/collector.py` (topic path lifted from `radar/collector.py`)
- Create: `backend/radar/news/sources.py` (from `ensure_topic_channels_discovered`, `ensure_topic_global_probe`, `classify_source`, plus `radar/maintenance.py`)
- Test: `backend/tests/test_news_collector.py`

- [ ] **Step 1: Write a failing test for topic collection writing NewsMention**

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from types import SimpleNamespace


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.news.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_collect_channel_probe_writes_news_mention():
    from radar.news.models import NewsTopic, NewsProbe
    from radar.news import collector
    s = _mem()
    t = NewsTopic(name="Экономика", keywords='["инфляция"]', niche_keywords='["инфляция","рубль"]')
    s.add(t); s.flush()
    p = NewsProbe(topic_id=t.id, platform="telegram", kind="channel", query="@rbc_news")
    s.add(p); s.commit()
    posts = [SimpleNamespace(post_id="@rbc_news/1", author="@rbc_news",
                             text="инфляция в РФ ускорилась", followers=1000,
                             created_at=datetime.now(timezone.utc), hashtags=[])]
    provider = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, provider)
    from radar.news.models import NewsMention
    assert n == 1
    assert s.query(NewsMention).count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_news_collector.py -q`
Expected: FAIL (`No module named 'radar.news.collector'`).

- [ ] **Step 3: Implement `news/collector.py`**

Lift the topic branch of `radar/collector.py::collect_probe` into a standalone `collect_probe(session, probe, provider) -> int` that:
- reads `NewsProbe`, resolves its `NewsTopic`;
- iterates `provider.search(probe.query, probe.kind, cursor).posts`;
- skips posts shorter than `MIN_TEXT_LEN` after stripping `#`-tokens;
- for `kind == "global"` only, keeps a post only if `_term_hit(text, topic.niche_keywords_list())` (reuse the existing `_term_hit`/`_word_in` helpers — copy them into `news/collector.py` or into `core/spam.py` if shared; copy into news for isolation);
- writes a `NewsMention(topic_id=..., source=("global" if kind=="global" else "channel"))`, dedup on `(platform, post_id)`;
- advances the probe watermark.
Remove every brand-only concept (follower-floor, competitor, lane, draft). No `Scope`.

- [ ] **Step 4: Implement `news/sources.py`**

Move `ensure_topic_channels_discovered`, `ensure_topic_global_probe`, `classify_source` from `radar/collector.py` and `purge_topic_sources` from `radar/maintenance.py`, rewritten to use `NewsTopic`/`NewsProbe` and `seed.TOPIC_SEED_CHANNELS`. Keep the hybrid seed→recs→gated-keyword behavior identical.

- [ ] **Step 5: Run the news collector test + full suite**

Run: `cd backend && python3 -m pytest tests/test_news_collector.py -q && python3 -m pytest -q 2>&1 | tail -3`
Expected: news test PASS; full suite still N+5 passed.

- [ ] **Step 6: Commit**

```bash
cd backend && git add -A && git commit -m "feat(news): collector + sources on NewsTopic/NewsProbe/NewsMention"
```

### Task 3.2: News stories + credibility + digests on new models

**Files:**
- Create: `backend/radar/news/stories.py`
- Move: `backend/radar/credibility.py` → `backend/radar/news/credibility.py`
- Create: `backend/radar/news/digests.py`
- Test: `backend/tests/test_news_stories.py`

- [ ] **Step 1: Write a failing test that news stories cluster + recompute verification**

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.news.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_news_update_stories_clusters_and_verifies():
    from radar.news.models import NewsTopic, NewsMention, NewsStory
    from radar.news import stories
    s = _mem()
    t = NewsTopic(name="Военное"); s.add(t); s.flush()
    now = datetime.now(timezone.utc)
    for i, author in enumerate(["@a", "@b", "@c"]):
        s.add(NewsMention(topic_id=t.id, platform="tg", post_id=f"p{i}", author=author,
                          text="взрыв на нефтебазе под Брянском", created_at=now))
    s.commit()
    stories.update_stories(s, t.id, embed=lambda txt: [float(len(txt))])
    st = s.query(NewsStory).first()
    assert st is not None
    assert st.source_count == 3   # 3 distinct authors
    assert st.verified is True    # >= STORY_VERIFY_MIN_SOURCES (3)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_news_stories.py -q`
Expected: FAIL (`No module named 'radar.news.stories'`).

- [ ] **Step 3: Implement `news/stories.py`**

```python
from __future__ import annotations
from ..core.clustering import cluster_owner
from ..core.domain import DomainModels
from ..embeddings import embed as default_embed
from .models import NewsMention, NewsIncident, NewsStory, NewsStoryPoint

_MODELS = DomainModels(owner_field="topic_id", Mention=NewsMention,
                       Incident=NewsIncident, Story=NewsStory, StoryPoint=NewsStoryPoint)

STORY_VERIFY_MIN_SOURCES = 3


def update_stories(session, topic_id: int, embed=None) -> None:
    cluster_owner(session, owner_id=topic_id, models=_MODELS, embed=embed or default_embed)
    _recompute_verification(session, topic_id)


def _recompute_verification(session, topic_id: int) -> None:
    stories = session.query(NewsStory).filter_by(topic_id=topic_id).all()
    for st in stories:
        authors = {m.author for m in session.query(NewsMention)
                   .join(NewsIncident, NewsMention.incident_id == NewsIncident.id)
                   .filter(NewsIncident.story_id == st.id).all() if m.author}
        st.source_count = len(authors)
        st.verified = len(authors) >= STORY_VERIFY_MIN_SOURCES
    session.commit()
```

> Port the exact verification query shape from the legacy `radar/stories.py::_recompute_verification` if it differs (e.g. counts via story_points). The behavior must match the legacy one.

- [ ] **Step 4: Move credibility and re-point its model imports**

```bash
cd backend && git mv radar/credibility.py radar/news/credibility.py
```
In `radar/news/credibility.py`, change model imports to `from .models import NewsStory, NewsMention, NewsIncident` and `from ..core.llm import complete` (and `LLMNotConfigured`). Functions `assess_credibility(session, story_id)` and `summarize_story(session, story_id)` now take a `NewsStory`.

- [ ] **Step 5: Implement `news/digests.py`**

Port the topic branch of `radar/digests.py::build_daily_digest` to operate on `NewsStory`/`NewsReport` for one `topic_id`, returning a `NewsReport`. Keep the LLM prompt and window logic identical.

- [ ] **Step 6: Run the news stories test + full suite**

Run: `cd backend && python3 -m pytest tests/test_news_stories.py -q && python3 -m pytest -q 2>&1 | tail -3`
Expected: news test PASS; full suite no regression.

- [ ] **Step 7: Commit**

```bash
cd backend && git add -A && git commit -m "feat(news): stories engine wiring, credibility, digests on news models"
```

### Task 3.3: News passes + router; switch the app to them

**Files:**
- Create: `backend/radar/news/passes.py` (`run_topic_tg_pass`, `run_topic_web_pass`)
- Create: `backend/radar/news/api.py` (router with `/news/*` endpoints)
- Modify: `backend/radar/core/scheduler.py` (call `news.passes` instead of inline `_run_topic_*`)
- Modify: `backend/radar/api.py` (mount `news.api.router`; remove old `/news`, `/topics`, news `/stories` endpoints)
- Test: `backend/tests/test_news_passes.py` (port from `test_topic_tg.py`)

- [ ] **Step 1: Write a failing test that the news router lists topics**

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_news_router_lists_topics(monkeypatch, tmp_path):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path/'t.db'}")
    from fastapi.testclient import TestClient
    from radar.app import app   # app.py assembles routers (created in Phase 5)
    # If Phase 5 not yet done, import the router directly instead:
    # from fastapi import FastAPI; from radar.news.api import router
    # app = FastAPI(); app.include_router(router)
    c = TestClient(app)
    r = c.get("/news/topics")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

> Until `radar/app.py` exists (Phase 5), use the inline `FastAPI()+include_router` variant noted in the comment.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_news_passes.py -q`
Expected: FAIL (`No module named 'radar.news.api'`).

- [ ] **Step 3: Implement `news/passes.py`**

Move `_run_topic_tg_pass` and `_run_topic_web_pass` from `core/scheduler.py` into `news/passes.py` as `run_topic_tg_pass(session, tg_provider)` and `run_topic_web_pass(session, web_provider)`, using `NewsTopic`/`NewsProbe`, `news.collector`, `news.sources`, `news.stories`. Keep `MAX_TOPIC_CHANNELS_PER_RUN`, rotation by `next_run_at`, and the `TelegramFloodWait` circuit breaker.

- [ ] **Step 4: Implement `news/api.py`**

Create `router = APIRouter(tags=["news"])` and port these endpoints from `radar/api.py`, converting `@app.` → `@router.`: `GET/POST /news/topics`, `GET /stories?topic_id=`, `GET /stories/{id}` (news ownership), `POST /stories/{id}/assess`, `POST /stories/{id}/summarize`, `GET /inbox?topic_id=` (flat news feed), `GET/POST /topics/{id}/digests`+`/digest`, `GET/POST/DELETE /topics/{id}/sources`. Use `radar.news.*` modules and `NewsStory`/`NewsMention`. Use `Depends` session from `core.db`.

> Stories endpoints are owned by news now. The brand domain keeps its own `/brands/{id}/stories` if it had any; per the spec, brand stories exist but had no dedicated endpoint — leave brand stories internal unless an endpoint already exists (grep `@app.*stories` to confirm; the 4 `/stories` routes are all news/topic scoped).

- [ ] **Step 5: Switch scheduler + remove old news endpoints**

In `core/scheduler.py`, replace the inline `_maybe_collect_topic_tg` body to call `radar.news.passes.run_topic_tg_pass` and the web pass to call `run_topic_web_pass`. In `radar/api.py`, delete the now-moved news/topics/stories endpoints and add `app.include_router(news_router)` (import at top: `from .news.api import router as news_router`).

- [ ] **Step 6: Port the TG-first pass test**

Adapt `tests/test_topic_tg.py` into `tests/test_news_passes.py` against the new models/passes; delete the old file once green. Adapt `tests/test_news_sources.py` to `radar.news.sources` similarly.

- [ ] **Step 7: Run suite + smoke**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3`
Expected: no regression. Then smoke (run skill): start `python3 -m uvicorn radar.api:app --port 8000 --log-level warning` in background, `python3 -c "import httpx; print(httpx.get('http://127.0.0.1:8000/news/topics').status_code)"` → `200`. Stop the server.

- [ ] **Step 8: Commit**

```bash
cd backend && git add -A && git commit -m "feat(news): scheduler passes + /news router on news domain; drop legacy news endpoints"
```

---

## Phase 4 — Build the `brand` domain

Mirror Phase 3 for brand. After this, brand no longer touches `Scope` or legacy tables.

### Task 4.1: Brand collector + pipeline + drafts + scoring on new models

**Files:**
- Create: `backend/radar/brand/collector.py` (brand path from `radar/collector.py`)
- Move: `backend/radar/pipeline.py` → `backend/radar/brand/pipeline.py`
- Move: `backend/radar/drafts.py` → `backend/radar/brand/drafts.py`
- Move: `backend/radar/scoring.py` → `backend/radar/brand/scoring.py`
- Move: `backend/radar/classifier_rules.py` → `backend/radar/brand/classifier_rules.py`
- Move: `backend/radar/engagement.py` → `backend/radar/brand/engagement.py`
- Move: `backend/radar/hotwatch.py` → `backend/radar/brand/hotwatch.py`
- Move: `backend/radar/explore.py` → `backend/radar/brand/explore.py`
- Test: `backend/tests/test_brand_collector.py`

- [ ] **Step 1: Write a failing test for brand collection writing BrandMention**

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from types import SimpleNamespace


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.brand.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_collect_brand_probe_writes_brand_mention():
    from radar.brand.models import Brand, BrandProbe, BrandMention
    from radar.brand import collector
    s = _mem()
    b = Brand(name="PapaPizza", keywords='["папа пицца"]')
    s.add(b); s.flush()
    p = BrandProbe(brand_id=b.id, platform="tiktok", kind="keyword", query="папа пицца", source="brand")
    s.add(p); s.commit()
    posts = [SimpleNamespace(post_id="1", author="u", text="заказал папа пицца сегодня",
                             followers=10, created_at=datetime.now(timezone.utc), hashtags=[],
                             likes=0, views=0, comments=0, shares=0)]
    provider = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, provider)
    assert n == 1
    assert s.query(BrandMention).count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_brand_collector.py -q`
Expected: FAIL (`No module named 'radar.brand.collector'`).

- [ ] **Step 3: Implement `brand/collector.py`**

Lift the brand branch of `radar/collector.py::collect_probe` (brand/competitor/niche relevance, follower-floor, `_matches`, lane/source assignment) into `collect_probe(session, probe, provider) -> int` on `BrandProbe`/`BrandMention`. No `Scope`, no topic path.

- [ ] **Step 4: Move the brand-only modules and fix imports**

```bash
cd backend
git mv radar/pipeline.py radar/brand/pipeline.py
git mv radar/drafts.py radar/brand/drafts.py
git mv radar/scoring.py radar/brand/scoring.py
git mv radar/classifier_rules.py radar/brand/classifier_rules.py
git mv radar/engagement.py radar/brand/engagement.py
git mv radar/hotwatch.py radar/brand/hotwatch.py
git mv radar/explore.py radar/brand/explore.py
```
In each moved file: model imports → `from .models import Brand, BrandMention, ...`; core imports → `from ..core.llm import ...`, `from ..core.db import ...`, `from ..core.providers...`, `from ..core.spam import ...`. Run the grep pattern from Task 1.1 Step 2 scoped to `radar/brand/` to catch every single-dot import.

- [ ] **Step 5: Run brand collector test + full suite**

Run: `cd backend && python3 -m pytest tests/test_brand_collector.py -q && python3 -m pytest -q 2>&1 | tail -3`
Expected: brand test PASS; full suite no regression (legacy `collector.py` still present for any not-yet-switched caller).

- [ ] **Step 6: Commit**

```bash
cd backend && git add -A && git commit -m "feat(brand): collector + brand-only modules on brand domain models"
```

### Task 4.2: Brand stories + digests + passes + router

**Files:**
- Create: `backend/radar/brand/stories.py`
- Create: `backend/radar/brand/digests.py`
- Create: `backend/radar/brand/passes.py` (`run_brand_pipeline`, `run_web_pass`, `run_chat_monitor`, `run_hotwatch`)
- Create: `backend/radar/brand/api.py` (router: `/brands/*`, `/mentions/*`, `/comments/*`, `/analytics`, `/opportunities`, `/onboarding`, `/explore`, `/search`)
- Modify: `backend/radar/core/scheduler.py` (call `brand.passes`)
- Modify: `backend/radar/api.py` (mount `brand.api.router`; remove moved endpoints)
- Test: `backend/tests/test_brand_passes.py`

- [ ] **Step 1: Write a failing test that the brand router lists brands (auth-scoped)**

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_brand_router_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path/'b.db'}")
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from radar.brand.api import router
    app = FastAPI(); app.include_router(router)
    c = TestClient(app)
    r = c.get("/brands")           # no token
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_brand_passes.py -q`
Expected: FAIL (`No module named 'radar.brand.api'`).

- [ ] **Step 3: Implement `brand/stories.py`** (mirror `news/stories.py` but with `BrandStory` models and no credibility/source recompute — brand stories are lean):

```python
from __future__ import annotations
from ..core.clustering import cluster_owner
from ..core.domain import DomainModels
from ..embeddings import embed as default_embed
from .models import BrandMention, BrandIncident, BrandStory, BrandStoryPoint

_MODELS = DomainModels(owner_field="brand_id", Mention=BrandMention,
                       Incident=BrandIncident, Story=BrandStory, StoryPoint=BrandStoryPoint)


def update_stories(session, brand_id: int, embed=None) -> None:
    cluster_owner(session, owner_id=brand_id, models=_MODELS, embed=embed or default_embed)
```

- [ ] **Step 4: Implement `brand/digests.py`** — port the brand branch of `radar/digests.py::build_daily_digest` to `BrandStory`/`BrandReport` for one `brand_id`.

- [ ] **Step 5: Implement `brand/passes.py`** — move `_run_brand_pipeline`, `_run_web_pass`, the chat-monitor worker body, and `_maybe_hotwatch` logic from `core/scheduler.py` into named functions on brand models/modules.

- [ ] **Step 6: Implement `brand/api.py`** — `router = APIRouter()`; port all remaining `@app.` endpoints (brands, mentions, comments, analytics, opportunities, onboarding, explore, search, profile-scan, preview, suggest, autocollect, config, digests) converting to `@router.`, using `radar.brand.*` and `core.auth`/`core.db`.

- [ ] **Step 7: Switch scheduler + remove moved endpoints from `radar/api.py`**

In `core/scheduler.py`, point the brand passes at `radar.brand.passes`. In `radar/api.py`, delete the moved endpoints and add `from .brand.api import router as brand_router; app.include_router(brand_router)`.

- [ ] **Step 8: Port brand pipeline tests**

Adapt existing brand-pipeline/collector/draft tests to `radar.brand.*` and the new models. Delete superseded legacy-model tests.

- [ ] **Step 9: Run suite + smoke**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3`
Expected: no regression. Smoke: boot `radar.api:app`, `GET /brands` → 401/403 without token, `GET /news/topics` → 200.

- [ ] **Step 10: Commit**

```bash
cd backend && git add -A && git commit -m "feat(brand): stories/digests/passes + /brands router on brand domain"
```

---

## Phase 5 — Teardown

Remove the legacy scaffolding now that both domains are switched.

### Task 5.1: Create `radar/app.py` and slim `radar/api.py` away

**Files:**
- Create: `backend/radar/app.py`
- Delete: `backend/radar/api.py` (after moving startup wiring)
- Delete: `backend/radar/scope.py`, `backend/radar/collector.py`, `backend/radar/stories.py`, `backend/radar/digests.py`, `backend/radar/maintenance.py`
- Modify: legacy `radar/models.py` (remove the now-unused shared owner models)
- Modify: `backend/radar/core/db.py` (drop `_relax_brand_id_not_null`; keep `_migrate` only if any new table still needs ADD COLUMN)
- Modify: `backend/radar/seed.py`

- [ ] **Step 1: Write `radar/app.py`**

```python
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.db import init_db, get_session
from .core.auth import router as auth_router   # if auth endpoints live in core
from .news.api import router as news_router
from .brand.api import router as brand_router

app = FastAPI(title="Echo API", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_router)
app.include_router(news_router)
app.include_router(brand_router)

_scheduler = None


@app.on_event("startup")
def on_startup():
    init_db()
    from . import seed
    with get_session() as s:
        seed.run(s)
    global _scheduler
    if os.getenv("ENABLE_SCHEDULER", "1") == "1" and _scheduler is None:
        from .core.scheduler import Scheduler
        # provider wiring identical to legacy api.py on_startup
        ...
        _scheduler.start()


@app.get("/health")
def health():
    return {"status": "ok"}
```

> Copy the exact provider-wiring block (`_get_provider`, `_get_tg_provider`, `_get_web_provider`, Scheduler construction args) verbatim from the legacy `radar/api.py` `on_startup`. Move `auth` endpoints into `core/auth.py`'s router if they were inline in `api.py`; otherwise create `core/auth_api.py` with the 3 `/auth/*` routes and import that.

- [ ] **Step 2: Delete legacy modules and the monolith**

```bash
cd backend
git rm radar/scope.py radar/collector.py radar/stories.py radar/digests.py radar/maintenance.py radar/api.py
```

- [ ] **Step 3: Remove unused shared owner models from `radar/models.py`**

Delete `Brand`, `Topic`, `Probe`, `Mention`, `MentionSnapshot`, `Comment`, `DraftEdit`, `EngagementLog`, `CityReport`, `Incident`, `Story`, `StoryPoint`, `Report` from `radar/models.py`, leaving only `Base`, `_now`, and `User`. (The legacy *tables* remain in existing DBs as the one-release backup; they're simply no longer mapped.)

- [ ] **Step 4: Drop `_relax_brand_id_not_null` from `core/db.py`**

Remove the function and its call in `init_db`. The new tables have honest NOT NULL owner FKs from creation.

- [ ] **Step 5: Update `seed.py`** to seed only `User` (demo user) and call `news.sources.ensure_default_topics`/seed channels; remove any `Scope`/legacy-model references.

- [ ] **Step 6: Fix remaining imports + update uvicorn entrypoint references**

```bash
cd backend
grep -rln -E "radar\.api|from \.api|radar\.scope|radar\.collector|from \.scope|from \.collector|from \.stories|from \.digests|from \.maintenance" radar tests
```
Update each: tests that imported `radar.api` for `TestClient` → `radar.app`. Any lingering `from .stories`/`from .digests` in scheduler must already point at `news.*`/`brand.*` (verify). Update `README`/run docs to `radar.app:app`.

- [ ] **Step 7: Run the full suite + smoke on the new entrypoint**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3`
Expected: green (count will differ from N as legacy tests were ported/removed; the suite must pass). Smoke: `python3 -m uvicorn radar.app:app --port 8000 --log-level warning` → `GET /health` 200, `/news/topics` 200, `/brands` 401.

- [ ] **Step 8: Commit**

```bash
cd backend && git add -A && git commit -m "refactor: remove Scope, legacy monolith and shared owner models; app.py assembles domain routers"
```

---

## Phase 6 — Frontend split

Mirror the backend split. Each task keeps `npm run build` working.

> Run `cd echo-app && npm install` once if `node_modules` is absent. Verify each task with `npm run build` (Vite). There is no JS test suite; the build + a manual smoke is the gate.

### Task 6.1: Extract `core` (client + auth + primitives)

**Files:**
- Create: `echo-app/src/core/api/client.js`
- Create: `echo-app/src/core/auth/` (move `pages/LoginPage.jsx`, add `RequireAuth`)
- Create: `echo-app/src/core/components/` (move `components/shared/icons.jsx`; add `Badge`, `TimelineChart`, `EmptyState` extracted from `Stories.jsx`)
- Modify: `echo-app/src/services/api.js` → split

- [ ] **Step 1: Create `core/api/client.js`** with the `request`, `getToken/setToken/clearToken`, and 401-redirect logic from the top of `services/api.js` (lines 1–37). No `scopeQuery`.

- [ ] **Step 2: Move shared primitives** — `git mv src/components/shared/icons.jsx src/core/components/icons.jsx`; extract `Badge`/`VerifiedBadge`/`CredibilityBadge` chart-agnostic bits and the recharts `ComposedChart` wrapper into `core/components/TimelineChart.jsx`.

- [ ] **Step 3: Build check + commit**

Run: `cd echo-app && npm run build 2>&1 | tail -5`
Expected: build succeeds.
```bash
cd echo-app && git add -A && git commit -m "refactor(fe): extract core api client, auth, shared primitives"
```

### Task 6.2: News feature

**Files:**
- Create: `echo-app/src/features/news/NewsApp.jsx` (from the news half of `pages/AppPage.jsx` — TopicBar + screens)
- Create: `echo-app/src/features/news/api.js` (getTopics, createTopic, getNewsFeed, getNewsStories, getStory, assessStory, summarizeStory, getTopicSources, addTopicSource, deleteTopicSource — no `scope`)
- Move: `components/app/Stories.jsx`, `Sources.jsx` → `features/news/components/` (specialize: flat `Feed`, news `Digests`)

- [ ] **Step 1:** Move and re-point the news components/services; replace `getStoriesScoped(scope)` calls with `getNewsStories(topicId)` etc.
- [ ] **Step 2: Build check + commit**

Run: `cd echo-app && npm run build 2>&1 | tail -5`
```bash
cd echo-app && git add -A && git commit -m "feat(fe): isolated news feature (NewsApp, news api, specialized components)"
```

### Task 6.3: Brand feature + Shell

**Files:**
- Create: `echo-app/src/features/brand/BrandApp.jsx` (brand half of `AppPage.jsx`)
- Create: `echo-app/src/features/brand/api.js` (brand endpoints, no `scope`)
- Move: `Feed.jsx` (tabbed variant), `Detail.jsx`, `Queue.jsx`, `Analytics.jsx`, `CityExplorer.jsx`, `Settings.jsx`, `AIWizard.jsx`, `BrandGate.jsx`, brand `Digests.jsx` → `features/brand/components/`
- Modify: `components/app/Shell.jsx` → `app/Shell.jsx` (mode switch mounts `NewsApp`/`BrandApp`)
- Delete: `pages/AppPage.jsx`, `services/api.js`, `data/mock.js` (if unused)

- [ ] **Step 1:** Build `BrandApp` from the brand branch of `AppPage`; `Shell` keeps only the mode switch and mounts the active feature. Remove the `scope`/`mode===` conditionals and the `lanes` prop (brand Feed is always tabbed; news Feed always flat).
- [ ] **Step 2:** Delete `AppPage.jsx`, the old `services/api.js`, and `data/mock.js` if no longer imported (`grep -rn "services/api\|data/mock" src`).
- [ ] **Step 3: Build check + manual smoke + commit**

Run: `cd echo-app && npm run build 2>&1 | tail -5`
Manual smoke (run skill): `npm run dev`, open `http://localhost:5173/app`, confirm news mode renders stories and the mode switch flips to brand (login gate). Backend must be running on 8000.
```bash
cd echo-app && git add -A && git commit -m "feat(fe): isolated brand feature + Shell mounts features; remove AppPage/scope"
```

---

## Phase 7 — Drop legacy tables (separate, after one release)

### Task 7.1: Drop the legacy shared tables

**Files:**
- Create: `backend/radar/core/migrate_drop_legacy.py`
- Modify: `backend/radar/core/db.py` (call it in `init_db`, guarded)
- Test: `backend/tests/test_migrate_drop_legacy.py`

- [ ] **Step 1: Write a failing test** that, given populated domain tables and empty-or-copied legacy tables, dropping legacy leaves domain data intact and the legacy tables gone.

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_drop_legacy_removes_old_tables():
    from sqlalchemy import create_engine, text, inspect
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE mentions (id INTEGER PRIMARY KEY)"))
        c.execute(text("CREATE TABLE news_mentions (id INTEGER PRIMARY KEY)"))
    from radar.core.migrate_drop_legacy import drop_legacy
    drop_legacy(eng)
    assert "mentions" not in inspect(eng).get_table_names()
    assert "news_mentions" in inspect(eng).get_table_names()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_migrate_drop_legacy.py -q`
Expected: FAIL (`No module named 'radar.core.migrate_drop_legacy'`).

- [ ] **Step 3: Implement `drop_legacy(engine)`** — `DROP TABLE IF EXISTS` for `mentions, incidents, stories, story_points, probes, reports, topics, brands` only after confirming the matching domain tables exist and are non-empty (guard against dropping before migration ran).

- [ ] **Step 4: Run test + full suite**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -3`
Expected: green.

- [ ] **Step 5: Commit**

```bash
cd backend && git add -A && git commit -m "feat(db): drop legacy shared tables after domain migration (guarded)"
```

---

## Self-Review

**Spec coverage:**
- "Both domains equal" → all phases keep both; ✓.
- "Separation depth code + data" → Phases 1–5 (code) + Phase 2 (data/models/migration); ✓.
- "Clustering/anomalies in core, parameterized" → Task 1.2 (anomalies move), Task 1.3 (`core/clustering.py` + `DomainModels`); ✓.
- "Lean news_mentions, credibility on news_stories" → Task 2.1 models + `test_domain_models.py` asserting both; ✓.
- "Frontend specialized per feature" → Phase 6, Tasks 6.1–6.3; ✓.
- "Old tables kept one release, dropped later" → migration keeps them (Task 2.2), Phase 7 drops them; ✓.
- "Per-domain uniqueness, Scope removed, honest NOT NULL" → Task 2.1 (UniqueConstraint per table), Task 5.1 (delete Scope + relax); ✓.
- "Rollout order core→data→news→brand→teardown→frontend→drop" → Phases 1–7 in that order; ✓.
- "Testing: regression each phase, migration test, per-domain tests, smoke after 3&4" → Task 0 baseline, run-suite step in every task, `test_migrate_split.py`, ported domain tests, smoke in 3.3/4.2; ✓.

**Placeholder scan:** The `...` in `app.py` (Task 5.1 Step 1) is explicitly directed to copy the verbatim provider-wiring block from the legacy `api.py` on_startup — actionable, not a TBD. All new artifacts (DomainModels, migration, models, engine signature, tests) have complete code. Endpoint *moves* are specified as mechanical `@app.`→`@router.` ports with exact route lists rather than reproduced bodies, which is the correct action for a behavior-preserving move.

**Type consistency:** `cluster_owner(session, owner_id, models, embed, ...)` is used identically in Task 1.3, `news/stories.py` (3.2), and `brand/stories.py` (4.2). `DomainModels(owner_field, Mention, Incident, Story, StoryPoint)` consistent across all three. `migrate_split(engine)` / `drop_legacy(engine)` take an engine consistently. `update_stories(session, owner_id, embed=None)` signature matches in both domains.

**Known judgment calls flagged for the implementer:**
- The legacy `_recompute_verification` query shape (story_points vs join) must be matched exactly in `news/stories.py` Step 3 — port from the original if it differs.
- `auth` endpoints' current home (inline in `api.py`) determines whether they go to `core/auth.py` or a new `core/auth_api.py` (Task 5.1 Step 1).
