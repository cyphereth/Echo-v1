# Story Timeline & Dynamics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `mention → incident → story` layer with a per-story timeline of volume, sentiment, and source count, surfaced as a "Сюжеты" dashboard screen.

**Architecture:** A new backend module clusters brand mentions into deduplicated incidents and links incidents into ongoing stories using local embeddings + sqlite-vec nearest-neighbour search. Per-story hourly timeline points are recomputed on each scheduler tick. New REST endpoints feed a new echo-app screen with a recharts dynamics graph. No new infra — runs inside the existing synchronous scheduler tick on SQLite.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, SQLite + `sqlite-vec`, `sentence-transformers` (`intfloat/multilingual-e5-small`, 384-dim), React (echo-app) + `recharts`.

Spec: `docs/superpowers/specs/2026-06-15-story-timeline-design.md`

---

## File Structure

**Backend (create):**
- `backend/radar/embeddings.py` — local embedding model wrapper (`embed()`).
- `backend/radar/stories.py` — clustering pipeline (`update_stories()`) + helpers.
- `backend/radar/vec.py` — sqlite-vec helpers (serialize, store, KNN, table DDL).
- `backend/tests/test_embeddings.py`
- `backend/tests/test_stories.py`
- `backend/tests/test_stories_api.py`

**Backend (modify):**
- `backend/radar/models.py` — add `Incident`, `Story`, `StoryPoint`; add `Mention.incident_id`.
- `backend/radar/db.py` — load sqlite-vec in connect listener; create vec0 tables; migrate `mentions.incident_id`.
- `backend/radar/scheduler.py` — call `update_stories()` after `classify_and_draft()` (two sites).
- `backend/radar/api.py` — three `/stories` endpoints + Pydantic schemas.
- `backend/requirements.txt` — add deps.

**Frontend (modify, echo-app):**
- `echo-app/package.json` — add `recharts`.
- `echo-app/vite.config.*` — proxy `/stories`.
- `echo-app/src/services/api.js` — `getStories`, `getStory`.
- `echo-app/src/components/app/Shell.jsx` — sidebar "Сюжеты" item.
- `echo-app/src/pages/AppPage.jsx` — wire `screen === 'stories'`.
- `echo-app/src/components/app/Stories.jsx` (create) — list + detail with chart.
- `echo-app/src/components/app/stories.module.css` (create).

---

# PHASE 1 — Foundation (embeddings, sqlite-vec, schema)

### Task 1: Embeddings module

**Files:**
- Create: `backend/radar/embeddings.py`
- Test: `backend/tests/test_embeddings.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_embeddings.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np


def test_embed_returns_normalized_matrix(monkeypatch):
    import radar.embeddings as E

    class _FakeModel:
        def encode(self, texts, normalize_embeddings, convert_to_numpy):
            # one row per input, deterministic, already unit-ish
            return np.array([[float(len(t)), 0.0, 0.0] for t in texts], dtype=np.float32)

    monkeypatch.setattr(E, "_model", lambda: _FakeModel())
    out = E.embed(["a", "bb"])
    assert out.shape == (2, 3)
    assert out.dtype == np.float32


def test_embed_empty_returns_zero_rows():
    import radar.embeddings as E
    out = E.embed([])
    assert out.shape == (0, E.EMBED_DIM)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.embeddings'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/radar/embeddings.py
from __future__ import annotations
from functools import lru_cache
import numpy as np

_MODEL_NAME = "intfloat/multilingual-e5-small"
EMBED_DIM = 384


@lru_cache(maxsize=1)
def _model():
    # Imported lazily so tests can monkeypatch _model without importing torch.
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(_MODEL_NAME)


def embed(texts: list[str]) -> np.ndarray:
    """(len(texts), EMBED_DIM) float32, L2-normalized.

    e5 expects a task prefix; we treat posts as 'passage'.
    """
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    prefixed = [f"passage: {t or ''}" for t in texts]
    vecs = _model().encode(
        prefixed, normalize_embeddings=True, convert_to_numpy=True
    )
    return np.asarray(vecs, dtype=np.float32)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_embeddings.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Add dependencies and commit**

Add to `backend/requirements.txt`:
```
sentence-transformers>=3.0
sqlite-vec>=0.1.6
numpy>=1.26
```

```bash
git add backend/radar/embeddings.py backend/tests/test_embeddings.py backend/requirements.txt
git commit -m "feat: local embeddings module (multilingual-e5-small)"
```

---

### Task 2: sqlite-vec helpers + table DDL

**Files:**
- Create: `backend/radar/vec.py`
- Test: `backend/tests/test_stories.py` (shared fixtures land here; first vec tests added now)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_stories.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta
import numpy as np
import pytest


def _engine_with_vec():
    """In-memory engine with sqlite-vec loaded and all tables created."""
    import sqlite_vec
    from sqlalchemy import create_engine, event
    from radar.models import Base
    from radar import vec

    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _load(dbapi_conn, _rec):
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)

    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        vec.create_vec_tables(conn)
    return eng


def _session():
    from sqlalchemy.orm import Session as _S
    return _S(_engine_with_vec())


def test_store_and_knn_roundtrip():
    from radar import vec
    s = _session()
    conn = s.connection().connection  # raw DBAPI conn
    a = np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32)
    b = np.array([0.0, 1.0] + [0.0] * 382, dtype=np.float32)
    vec.store(conn, "incident_vec", 1, a)
    vec.store(conn, "incident_vec", 2, b)
    hits = vec.knn(conn, "incident_vec", a, k=2)
    assert hits[0][0] == 1            # nearest id is the identical vector
    assert hits[0][1] == pytest.approx(0.0, abs=1e-4)  # cosine distance ~0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stories.py::test_store_and_knn_roundtrip -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.vec'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/radar/vec.py
from __future__ import annotations
import numpy as np
import sqlite_vec

from .embeddings import EMBED_DIM

# vec0 virtual tables. Cosine distance so distance = 1 - cosine_similarity.
_TABLES = ("mention_vec", "incident_vec", "story_vec")


def create_vec_tables(conn) -> None:
    """Create vec0 tables. `conn` is a SQLAlchemy Connection or raw DBAPI conn."""
    exec_ = conn.exec_driver_sql if hasattr(conn, "exec_driver_sql") else conn.execute
    for t in _TABLES:
        exec_(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {t} USING vec0("
            f"id INTEGER PRIMARY KEY, "
            f"embedding float[{EMBED_DIM}] distance_metric=cosine)"
        )


def _ser(v: np.ndarray) -> bytes:
    return sqlite_vec.serialize_float32(np.asarray(v, dtype=np.float32).tolist())


def store(conn, table: str, row_id: int, v: np.ndarray) -> None:
    """Insert-or-replace one vector. `conn` is a raw DBAPI connection."""
    conn.execute(
        f"INSERT OR REPLACE INTO {table}(id, embedding) VALUES (?, ?)",
        (row_id, _ser(v)),
    )


def knn(conn, table: str, q: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
    """Return [(id, cosine_distance), ...] nearest to q, closest first."""
    rows = conn.execute(
        f"SELECT id, distance FROM {table} "
        f"WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (_ser(q), k),
    ).fetchall()
    return [(int(r[0]), float(r[1])) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_stories.py::test_store_and_knn_roundtrip -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/radar/vec.py backend/tests/test_stories.py
git commit -m "feat: sqlite-vec helpers (store, knn, table DDL)"
```

---

### Task 3: ORM models for incidents / stories / story points

**Files:**
- Modify: `backend/radar/models.py`
- Test: `backend/tests/test_stories.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_stories.py
def test_models_create_and_relate():
    from radar.models import Story, Incident, StoryPoint, Mention
    s = _session()
    st = Story(brand_id=1, title="t",
               first_seen_at=datetime.now(timezone.utc),
               last_seen_at=datetime.now(timezone.utc))
    s.add(st); s.flush()
    inc = Incident(brand_id=1, story_id=st.id, title="i",
                   first_seen_at=datetime.now(timezone.utc),
                   last_seen_at=datetime.now(timezone.utc))
    s.add(inc); s.flush()
    m = Mention(brand_id=1, platform="telegram", post_id="p", author="@a",
                text="x", source="niche", incident_id=inc.id,
                created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    pt = StoryPoint(story_id=st.id, bucket_start=datetime.now(timezone.utc),
                    mention_count=3, avg_sentiment=0.5, source_count=2)
    s.add(pt); s.commit()
    assert st.id and inc.story_id == st.id and m.incident_id == inc.id
    assert st.is_anomaly is False and st.status == "active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stories.py::test_models_create_and_relate -v`
Expected: FAIL — `ImportError: cannot import name 'Story'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/radar/models.py` (after `CityReport`):

```python
class Incident(Base):
    __tablename__ = "incidents"
    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:      Mapped[int]           = mapped_column(ForeignKey("brands.id"))
    story_id:      Mapped[Optional[int]] = mapped_column(ForeignKey("stories.id"))
    title:         Mapped[str]           = mapped_column(Text, default="")
    summary:       Mapped[Optional[str]] = mapped_column(Text)   # filled by LLM later
    sentiment:     Mapped[float]         = mapped_column(Float, default=0.0)  # -1..1
    post_count:    Mapped[int]           = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime]      = mapped_column(nullable=False)
    last_seen_at:  Mapped[datetime]      = mapped_column(nullable=False)
    created_at:    Mapped[datetime]      = mapped_column(default=_now)


class Story(Base):
    __tablename__ = "stories"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:      Mapped[int]      = mapped_column(ForeignKey("brands.id"))
    title:         Mapped[str]      = mapped_column(Text, default="")
    status:        Mapped[str]      = mapped_column(Text, default="active")   # active | dormant
    is_anomaly:    Mapped[bool]     = mapped_column(Boolean, default=False)   # set by detector later
    post_count:    Mapped[int]      = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at:  Mapped[datetime] = mapped_column(nullable=False)
    created_at:    Mapped[datetime] = mapped_column(default=_now)


class StoryPoint(Base):
    __tablename__ = "story_points"
    __table_args__ = (UniqueConstraint("story_id", "bucket_start"),)
    id:            Mapped[int]              = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id:      Mapped[int]              = mapped_column(ForeignKey("stories.id"))
    bucket_start:  Mapped[datetime]         = mapped_column(nullable=False)
    mention_count: Mapped[int]              = mapped_column(Integer, default=0)
    avg_sentiment: Mapped[Optional[float]]  = mapped_column(Float)
    source_count:  Mapped[int]              = mapped_column(Integer, default=0)
```

Add `incident_id` to the `Mention` class (after the `lane` column, near line 91):

```python
    incident_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_stories.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add backend/radar/models.py backend/tests/test_stories.py
git commit -m "feat: Incident/Story/StoryPoint models + Mention.incident_id"
```

---

### Task 4: Wire sqlite-vec + vec tables + migration into db.py

**Files:**
- Modify: `backend/radar/db.py`
- Test: `backend/tests/test_stories.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_stories.py
def test_init_db_loads_vec_and_migrates(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    import importlib, radar.db as db
    importlib.reload(db)            # pick up env + re-register listeners
    db.init_db()
    with db.engine.connect() as c:
        # vec table usable
        c.exec_driver_sql("SELECT count(*) FROM mention_vec")
        # incident_id column added to mentions
        cols = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(mentions)")}
        assert "incident_id" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stories.py::test_init_db_loads_vec_and_migrates -v`
Expected: FAIL — `no such table: mention_vec` (vec not loaded / tables not created)

- [ ] **Step 3: Write minimal implementation**

In `backend/radar/db.py`, extend the connect listener to also load sqlite-vec:

```python
def _enable_wal(connection, _record):
    if _DATABASE_URL.startswith("sqlite"):
        # sqlite-vec must be loaded per-connection before any vec0 query.
        import sqlite_vec
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
```

Add `incident_id` to the `mentions` migration block:

```python
    "mentions": {
        "source":      "TEXT DEFAULT 'brand'",
        "competitor":  "TEXT",
        "opportunity": "TEXT",
        "is_spam":     "BOOLEAN DEFAULT 0",
        "incident_id": "INTEGER",
    },
```

Create vec tables inside `init_db`:

```python
def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()
    from .vec import create_vec_tables
    with engine.begin() as conn:
        create_vec_tables(conn)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_stories.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/radar/db.py backend/tests/test_stories.py
git commit -m "feat: load sqlite-vec, create vec tables, migrate mentions.incident_id"
```

---

# PHASE 2 — Clustering pipeline

### Task 5: `update_stories` — dedup into incidents

**Files:**
- Create: `backend/radar/stories.py`
- Test: `backend/tests/test_stories.py`

Helper for tests — add a mention factory at the top of `test_stories.py` (below `_session`):

```python
def _mk(s, **kw):
    from radar.models import Mention
    d = dict(brand_id=1, platform="telegram", post_id="p", author="@a",
             text="t", source="niche", is_spam=False,
             created_at=datetime.now(timezone.utc))
    d.update(kw)
    m = Mention(**d); s.add(m); s.flush(); return m


def _fake_embed(mapping):
    """Return an embed() stub mapping text -> 384-vec (first dims set)."""
    import numpy as np
    def _e(texts):
        out = np.zeros((len(texts), 384), dtype=np.float32)
        for i, t in enumerate(texts):
            for j, val in enumerate(mapping[t]):
                out[i, j] = val
        return out
    return _e
```

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_stories.py
def test_dedup_collapses_near_duplicates(monkeypatch):
    import radar.stories as S
    s = _session()
    now = datetime.now(timezone.utc)
    m1 = _mk(s, post_id="a", text="пожар на заводе", created_at=now)
    m2 = _mk(s, post_id="b", text="пожар завод дубль", created_at=now + timedelta(minutes=5))
    m3 = _mk(s, post_id="c", text="концерт в парке", created_at=now + timedelta(minutes=6))
    s.commit()
    monkeypatch.setattr(S.embeddings, "embed", _fake_embed({
        "пожар на заводе":   [1.0, 0.0, 0.0],
        "пожар завод дубль": [0.99, 0.01, 0.0],   # near-duplicate of m1
        "концерт в парке":   [0.0, 1.0, 0.0],     # different
    }))
    S.update_stories(s, brand_id=1)
    s.refresh(m1); s.refresh(m2); s.refresh(m3)
    assert m1.incident_id == m2.incident_id          # collapsed
    assert m3.incident_id != m1.incident_id          # separate incident
    from radar.models import Incident
    assert s.query(Incident).count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stories.py::test_dedup_collapses_near_duplicates -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.stories'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/radar/stories.py
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy.orm import Session

from . import embeddings, vec
from .models import Mention, Incident, Story, StoryPoint

# Tunables (cosine SIMILARITY thresholds; distance = 1 - sim). Calibrate on real brands.
INCIDENT_SIM    = float(os.getenv("STORY_INCIDENT_SIM", "0.90"))
STORY_SIM       = float(os.getenv("STORY_STORY_SIM", "0.78"))
INCIDENT_WINDOW = timedelta(hours=int(os.getenv("STORY_INCIDENT_WINDOW_H", "48")))
STORY_WINDOW    = timedelta(days=int(os.getenv("STORY_STORY_WINDOW_D", "14")))
BUCKET          = timedelta(hours=1)


def _tone_score(tone: str) -> float:
    return {"positive": 1.0, "negative": -1.0}.get(tone or "", 0.0)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _raw(session: Session):
    return session.connection().connection  # DBAPI conn for vec ops


def _attach_to_incident(session, conn, brand_id, m, v) -> Incident:
    created = _aware(m.created_at)
    for inc_id, dist in vec.knn(conn, "incident_vec", v, k=5):
        if (1.0 - dist) < INCIDENT_SIM:
            break  # sorted by distance; nothing closer qualifies
        inc = session.get(Incident, inc_id)
        if inc is None or inc.brand_id != brand_id:
            continue
        if abs(_aware(inc.last_seen_at) - created) > INCIDENT_WINDOW:
            continue
        # merge: incremental centroid + running stats
        old = _centroid(conn, "incident_vec", inc_id)
        n = inc.post_count
        merged = _normalize((old * n + v) / (n + 1))
        vec.store(conn, "incident_vec", inc_id, merged)
        inc.post_count = n + 1
        inc.sentiment = (inc.sentiment * n + _tone_score(m.tone)) / (n + 1)
        inc.first_seen_at = min(_aware(inc.first_seen_at), created)
        inc.last_seen_at = max(_aware(inc.last_seen_at), created)
        session.flush()
        return inc
    inc = Incident(brand_id=brand_id, title=_title(m.text),
                   sentiment=_tone_score(m.tone), post_count=1,
                   first_seen_at=created, last_seen_at=created)
    session.add(inc); session.flush()
    vec.store(conn, "incident_vec", inc.id, v)
    return inc


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v if n == 0 else (v / n).astype(np.float32)


def _centroid(conn, table, row_id) -> np.ndarray:
    row = conn.execute(
        f"SELECT embedding FROM {table} WHERE id = ?", (row_id,)
    ).fetchone()
    return np.frombuffer(row[0], dtype=np.float32).copy()


def _title(text: str) -> str:
    t = (text or "").strip().replace("\n", " ")
    return (t[:80] + "…") if len(t) > 80 else (t or "(без текста)")


def update_stories(session: Session, brand_id: int) -> dict:
    conn = _raw(session)
    new = (session.query(Mention)
           .filter(Mention.brand_id == brand_id,
                   Mention.incident_id.is_(None),
                   Mention.is_spam.is_(False))
           .order_by(Mention.created_at).all())
    if not new:
        return {"mentions": 0, "incidents": 0}
    vecs = embeddings.embed([m.text or "" for m in new])
    incidents_touched = set()
    for m, v in zip(new, vecs):
        v = _normalize(v)
        vec.store(conn, "mention_vec", m.id, v)
        inc = _attach_to_incident(session, conn, brand_id, m, v)
        m.incident_id = inc.id
        incidents_touched.add(inc.id)
    session.commit()
    return {"mentions": len(new), "incidents": len(incidents_touched)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_stories.py::test_dedup_collapses_near_duplicates -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/radar/stories.py backend/tests/test_stories.py
git commit -m "feat: stories pipeline — dedup mentions into incidents"
```

---

### Task 6: Link incidents into stories

**Files:**
- Modify: `backend/radar/stories.py`
- Test: `backend/tests/test_stories.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_stories.py
def test_incidents_link_into_one_story(monkeypatch):
    import radar.stories as S
    from radar.models import Story
    s = _session()
    now = datetime.now(timezone.utc)
    # two NON-duplicate but topically-close incidents (sim ~0.8, below INCIDENT_SIM,
    # above STORY_SIM) → same story.
    _mk(s, post_id="a", text="скандал день1", created_at=now)
    _mk(s, post_id="b", text="скандал день2", created_at=now + timedelta(days=1))
    s.commit()
    monkeypatch.setattr(S.embeddings, "embed", _fake_embed({
        "скандал день1": [1.0, 0.0, 0.0],
        "скандал день2": [0.82, 0.57, 0.0],   # cos≈0.82: new incident, same story
    }))
    S.update_stories(s, brand_id=1)
    stories = s.query(Story).all()
    assert len(stories) == 1
    assert stories[0].post_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stories.py::test_incidents_link_into_one_story -v`
Expected: FAIL — two stories created (linking not implemented)

- [ ] **Step 3: Write minimal implementation**

Add to `backend/radar/stories.py`:

```python
def _attach_to_story(session, conn, brand_id, inc, centroid) -> Story:
    if inc.story_id is not None:
        st = session.get(Story, inc.story_id)
        _bump_story(conn, st, inc, centroid)
        return st
    for st_id, dist in vec.knn(conn, "story_vec", centroid, k=5):
        if (1.0 - dist) < STORY_SIM:
            break
        st = session.get(Story, st_id)
        if st is None or st.brand_id != brand_id:
            continue
        if abs(_aware(st.last_seen_at) - _aware(inc.last_seen_at)) > STORY_WINDOW:
            continue
        _bump_story(conn, st, inc, centroid)
        return st
    st = Story(brand_id=brand_id, title=inc.title,
               first_seen_at=inc.first_seen_at, last_seen_at=inc.last_seen_at,
               post_count=0)
    session.add(st); session.flush()
    vec.store(conn, "story_vec", st.id, centroid)
    _bump_story(conn, st, inc, centroid)
    return st


def _bump_story(conn, st, inc, centroid) -> None:
    # story centroid = running mean of member-incident centroids (approx by post_count)
    old = _centroid(conn, "story_vec", st.id)
    w = max(st.post_count, 1)
    merged = _normalize((old * w + centroid) / (w + 1))
    vec.store(conn, "story_vec", st.id, merged)
    st.first_seen_at = min(_aware(st.first_seen_at), _aware(inc.first_seen_at))
    st.last_seen_at = max(_aware(st.last_seen_at), _aware(inc.last_seen_at))
    st.post_count = (st.post_count or 0) + 1
```

Update `update_stories` to link + collect stories. Replace the loop body and return:

```python
    incidents_touched = set()
    stories_touched = set()
    for m, v in zip(new, vecs):
        v = _normalize(v)
        vec.store(conn, "mention_vec", m.id, v)
        inc = _attach_to_incident(session, conn, brand_id, m, v)
        m.incident_id = inc.id
        cen = _centroid(conn, "incident_vec", inc.id)
        st = _attach_to_story(session, conn, brand_id, inc, cen)
        inc.story_id = st.id
        incidents_touched.add(inc.id)
        stories_touched.add(st.id)
    session.flush()
    for sid in stories_touched:
        _recompute_points(session, sid)
    session.commit()
    return {"mentions": len(new), "incidents": len(incidents_touched),
            "stories": len(stories_touched)}
```

Add a placeholder `_recompute_points` so this task runs (real body in Task 7):

```python
def _recompute_points(session: Session, story_id: int) -> None:
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_stories.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add backend/radar/stories.py backend/tests/test_stories.py
git commit -m "feat: link incidents into stories"
```

---

### Task 7: Recompute story timeline points

**Files:**
- Modify: `backend/radar/stories.py`
- Test: `backend/tests/test_stories.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_stories.py
def test_recompute_points_buckets_by_hour(monkeypatch):
    import radar.stories as S
    from radar.models import StoryPoint
    s = _session()
    base = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
    # 2 mentions same hour (one + / one -), 1 next hour; all same topic → 1 story
    _mk(s, post_id="a", text="тема x", author="@u1", tone="positive", created_at=base + timedelta(minutes=2))
    _mk(s, post_id="b", text="тема x две", author="@u2", tone="negative", created_at=base + timedelta(minutes=40))
    _mk(s, post_id="c", text="тема x три", author="@u1", tone="neutral", created_at=base + timedelta(hours=1, minutes=5))
    s.commit()
    monkeypatch.setattr(S.embeddings, "embed", _fake_embed({
        "тема x":     [1.0, 0.0, 0.0],
        "тема x две": [0.999, 0.01, 0.0],
        "тема x три": [0.999, 0.0, 0.01],
    }))
    S.update_stories(s, brand_id=1)
    pts = s.query(StoryPoint).order_by(StoryPoint.bucket_start).all()
    assert len(pts) == 2
    assert pts[0].mention_count == 2
    assert pts[0].avg_sentiment == 0.0      # (+1 + -1)/2
    assert pts[0].source_count == 2         # @u1, @u2
    assert pts[1].mention_count == 1
    assert pts[1].source_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stories.py::test_recompute_points_buckets_by_hour -v`
Expected: FAIL — `assert 0 == 2` (placeholder writes nothing)

- [ ] **Step 3: Write minimal implementation**

Replace the placeholder `_recompute_points` in `backend/radar/stories.py`:

```python
def _bucket(dt: datetime) -> datetime:
    dt = _aware(dt)
    return dt.replace(minute=0, second=0, microsecond=0)


def _recompute_points(session: Session, story_id: int) -> None:
    # All mentions whose incident belongs to this story.
    rows = (session.query(Mention)
            .join(Incident, Mention.incident_id == Incident.id)
            .filter(Incident.story_id == story_id).all())
    buckets: dict[datetime, dict] = {}
    for m in rows:
        b = _bucket(m.created_at)
        agg = buckets.setdefault(b, {"n": 0, "sent": 0.0, "src": set()})
        agg["n"] += 1
        agg["sent"] += _tone_score(m.tone)
        agg["src"].add(m.author or "")
    # Wipe + rewrite this story's points (idempotent on every recompute).
    session.query(StoryPoint).filter(StoryPoint.story_id == story_id).delete()
    for b, agg in buckets.items():
        session.add(StoryPoint(
            story_id=story_id, bucket_start=b,
            mention_count=agg["n"],
            avg_sentiment=(agg["sent"] / agg["n"]) if agg["n"] else None,
            source_count=len(agg["src"]),
        ))
    session.flush()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_stories.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add backend/radar/stories.py backend/tests/test_stories.py
git commit -m "feat: recompute hourly story timeline points"
```

---

### Task 8: Hook `update_stories` into the scheduler

**Files:**
- Modify: `backend/radar/scheduler.py:120-128` (main loop) and `:151-167` (chat worker)
- Test: `backend/tests/test_stories.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_stories.py
def test_scheduler_calls_update_stories(monkeypatch):
    import radar.scheduler as SCH
    calls = []
    monkeypatch.setattr("radar.stories.update_stories",
                        lambda sess, bid: calls.append(bid) or {})
    monkeypatch.setattr("radar.pipeline.classify_and_draft", lambda sess, bid: {})
    monkeypatch.setattr("radar.pipeline.fetch_new_comments",
                        lambda sess, bid, p, t: 0)
    # exercise the per-brand post-collect block in isolation
    SCH._run_brand_pipeline(session=object(), brand_id=7, provider=None, tg_provider=None)
    assert calls == [7]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stories.py::test_scheduler_calls_update_stories -v`
Expected: FAIL — `AttributeError: module 'radar.scheduler' has no attribute '_run_brand_pipeline'`

- [ ] **Step 3: Write minimal implementation**

In `backend/radar/scheduler.py`, extract the per-brand post-collect work into a module-level helper (DRY — both the main loop and the chat worker call it):

```python
def _run_brand_pipeline(session, brand_id, provider, tg_provider):
    from .pipeline import classify_and_draft, fetch_new_comments
    from .stories import update_stories
    classify_and_draft(session, brand_id)
    fetch_new_comments(session, brand_id, provider, tg_provider)
    update_stories(session, brand_id)
```

Replace the main-loop block (currently lines ~122-128):

```python
            for brand_id in touched:
                try:
                    _run_brand_pipeline(session, brand_id, self._provider, self._tg_provider)
                except Exception:
                    log.exception("Pipeline failed for brand %s", brand_id)
```

Replace the chat-worker block (currently lines ~157-163):

```python
            for b in brands:
                ensure_chats_discovered(session, b, self._tg_provider)
                n = collect_chats(session, b, self._tg_provider)
                if n:
                    _run_brand_pipeline(session, b.id, self._provider, self._tg_provider)
                    log.info("Chat monitor: %d new niche message(s) for brand %s", n, b.id)
```

Remove the now-unused `from .pipeline import classify_and_draft, fetch_new_comments` lines inside those two blocks (they live in `_run_brand_pipeline` now).

- [ ] **Step 4: Run test + full suite**

Run: `cd backend && python -m pytest tests/test_stories.py tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/radar/scheduler.py backend/tests/test_stories.py
git commit -m "feat: run update_stories after each brand collect pass"
```

---

# PHASE 3 — API

### Task 9: `/stories` endpoints

**Files:**
- Modify: `backend/radar/api.py` (add schemas + routes; follow existing brand-scoped/auth patterns in this file)
- Test: `backend/tests/test_stories_api.py`

> Before writing: read how an existing brand-scoped GET route and its auth dependency are declared in `api.py` (e.g. the `/mentions` route) and mirror that exact style (router, response_model, session dependency, auth).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_stories_api.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def test_list_and_detail(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'a.db'}")
    import importlib
    import radar.db as db; importlib.reload(db); db.init_db()
    import radar.api as api; importlib.reload(api)
    from fastapi.testclient import TestClient
    from radar.models import Story, Incident, StoryPoint, Mention

    s = db.get_session()
    st = Story(brand_id=1, title="кризис", first_seen_at=datetime.now(timezone.utc),
               last_seen_at=datetime.now(timezone.utc), post_count=2)
    s.add(st); s.flush()
    inc = Incident(brand_id=1, story_id=st.id, title="i",
                   first_seen_at=datetime.now(timezone.utc),
                   last_seen_at=datetime.now(timezone.utc))
    s.add(inc); s.flush()
    s.add(Mention(brand_id=1, platform="telegram", post_id="p", author="@a",
                  text="x", source="niche", incident_id=inc.id,
                  created_at=datetime.now(timezone.utc)))
    s.add(StoryPoint(story_id=st.id, bucket_start=datetime.now(timezone.utc),
                     mention_count=2, avg_sentiment=-0.5, source_count=1))
    s.commit()

    client = TestClient(api.app)
    # auth bypass: mirror how other api tests authenticate, or override the
    # auth dependency. Pattern: api.app.dependency_overrides[api.<auth_dep>] = lambda: <user>
    api.app.dependency_overrides[api.current_user] = lambda: type("U", (), {"id": 1})()

    r = client.get("/stories?brand_id=1")
    assert r.status_code == 200
    assert r.json()[0]["title"] == "кризис"
    sid = r.json()[0]["id"]

    r2 = client.get(f"/stories/{sid}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["title"] == "кризис"
    assert len(body["points"]) == 1
    assert body["points"][0]["mention_count"] == 2
```

> If `current_user` is not the actual dependency name in `api.py`, substitute the real one when implementing — keep the override pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stories_api.py -v`
Expected: FAIL — 404 (routes not defined)

- [ ] **Step 3: Write minimal implementation**

Add to `backend/radar/api.py` (Pydantic v2 style, matching existing schemas):

```python
from pydantic import BaseModel

class StoryOut(BaseModel):
    id: int
    title: str
    status: str
    is_anomaly: bool
    post_count: int
    last_seen_at: datetime
    avg_sentiment: float | None = None

class StoryPointOut(BaseModel):
    bucket_start: datetime
    mention_count: int
    avg_sentiment: float | None
    source_count: int

class IncidentOut(BaseModel):
    id: int
    title: str
    sentiment: float
    post_count: int
    last_seen_at: datetime

class StoryDetailOut(StoryOut):
    points: list[StoryPointOut]
    incidents: list[IncidentOut]
```

Add routes (use the file's existing router/session/auth idioms — `get_session`, the real auth dependency, and `func` from sqlalchemy):

```python
from sqlalchemy import func
from .models import Story, Incident, StoryPoint

@app.get("/stories", response_model=list[StoryOut])
def list_stories(brand_id: int, user=Depends(current_user)):
    s = get_session()
    try:
        rows = (s.query(Story)
                .filter(Story.brand_id == brand_id, Story.status == "active")
                .order_by(Story.last_seen_at.desc()).all())
        out = []
        for st in rows:
            avg = (s.query(func.avg(StoryPoint.avg_sentiment))
                   .filter(StoryPoint.story_id == st.id).scalar())
            out.append(StoryOut(
                id=st.id, title=st.title, status=st.status,
                is_anomaly=st.is_anomaly, post_count=st.post_count,
                last_seen_at=st.last_seen_at, avg_sentiment=avg))
        return out
    finally:
        s.close()


@app.get("/stories/{story_id}", response_model=StoryDetailOut)
def get_story(story_id: int, user=Depends(current_user)):
    s = get_session()
    try:
        st = s.get(Story, story_id)
        if st is None:
            raise HTTPException(status_code=404, detail="story not found")
        points = (s.query(StoryPoint)
                  .filter(StoryPoint.story_id == story_id)
                  .order_by(StoryPoint.bucket_start).all())
        incidents = (s.query(Incident)
                     .filter(Incident.story_id == story_id)
                     .order_by(Incident.last_seen_at.desc()).all())
        avg = (s.query(func.avg(StoryPoint.avg_sentiment))
               .filter(StoryPoint.story_id == story_id).scalar())
        return StoryDetailOut(
            id=st.id, title=st.title, status=st.status, is_anomaly=st.is_anomaly,
            post_count=st.post_count, last_seen_at=st.last_seen_at, avg_sentiment=avg,
            points=[StoryPointOut(bucket_start=p.bucket_start, mention_count=p.mention_count,
                                  avg_sentiment=p.avg_sentiment, source_count=p.source_count)
                    for p in points],
            incidents=[IncidentOut(id=i.id, title=i.title, sentiment=i.sentiment,
                                   post_count=i.post_count, last_seen_at=i.last_seen_at)
                       for i in incidents])
    finally:
        s.close()


@app.post("/stories/recompute")
def recompute_stories(brand_id: int, user=Depends(current_user)):
    from .stories import update_stories
    s = get_session()
    try:
        return update_stories(s, brand_id)
    finally:
        s.close()
```

> `Depends`, `HTTPException`, `current_user` (real name), and `datetime` are already imported in `api.py`; reuse them rather than re-importing. Confirm the auth dependency's real name before wiring.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_stories_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/radar/api.py backend/tests/test_stories_api.py
git commit -m "feat: /stories list, detail, recompute endpoints"
```

---

### Task 10: Full backend suite green

- [ ] **Step 1: Run everything**

Run: `cd backend && python -m pytest -q`
Expected: all pass. If the embedding model download is attempted in any non-monkeypatched path, that test is wrong — fix the test to monkeypatch `embeddings.embed` / `stories.embeddings.embed`.

- [ ] **Step 2: Commit (only if fixes were needed)**

```bash
git add -A && git commit -m "test: stabilize story suite"
```

---

# PHASE 4 — Frontend (echo-app)

### Task 11: API client + proxy + dependency

**Files:**
- Modify: `echo-app/package.json`, `echo-app/vite.config.*`, `echo-app/src/services/api.js`

- [ ] **Step 1: Add recharts**

Run: `cd echo-app && npm install recharts`

- [ ] **Step 2: Add proxy entry**

In `echo-app/vite.config.*`, add to the `proxy` object (match existing `127.0.0.1:8000` form):

```js
      '/stories':    'http://127.0.0.1:8000',
```

- [ ] **Step 3: Add API functions**

In `echo-app/src/services/api.js`, mirror the existing fetch helpers:

```js
export async function getStories(brandId) {
  const r = await fetch(`/stories?brand_id=${brandId}`, { headers: authHeaders() });
  if (!r.ok) throw new Error('stories failed');
  return r.json();
}

export async function getStory(id) {
  const r = await fetch(`/stories/${id}`, { headers: authHeaders() });
  if (!r.ok) throw new Error('story failed');
  return r.json();
}
```

> Use whatever auth-header / base helper the existing functions in this file use (e.g. `authHeaders()` or a shared wrapper) — match them exactly rather than inventing a new pattern.

- [ ] **Step 4: Verify build**

Run: `cd echo-app && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add echo-app/package.json echo-app/package-lock.json echo-app/vite.config.* echo-app/src/services/api.js
git commit -m "feat: stories API client + proxy + recharts dep"
```

---

### Task 12: Stories screen (list + detail with timeline chart)

**Files:**
- Create: `echo-app/src/components/app/Stories.jsx`, `echo-app/src/components/app/stories.module.css`

- [ ] **Step 1: Implement the screen**

```jsx
// echo-app/src/components/app/Stories.jsx
import { useEffect, useState } from 'react';
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import * as api from '../../services/api';
import styles from './stories.module.css';

function fmtHour(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:00`;
}

function StoryDetail({ id }) {
  const [data, setData] = useState(null);
  useEffect(() => { api.getStory(id).then(setData).catch(() => setData(null)); }, [id]);
  if (!data) return <div className={styles.empty}>Загрузка…</div>;
  const chart = data.points.map((p) => ({
    t: fmtHour(p.bucket_start),
    mentions: p.mention_count,
    sentiment: p.avg_sentiment,
  }));
  return (
    <div className={styles.detail}>
      <h2>{data.title}</h2>
      <div className={styles.meta}>
        {data.post_count} упоминаний · тональность {(data.avg_sentiment ?? 0).toFixed(2)}
        {data.is_anomaly && <span className={styles.anomaly}> ⚠ аномалия</span>}
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={chart}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="t" />
          <YAxis yAxisId="l" />
          <YAxis yAxisId="r" orientation="right" domain={[-1, 1]} />
          <Tooltip />
          <Bar yAxisId="l" dataKey="mentions" name="Упоминания" fill="#6366f1" />
          <Line yAxisId="r" dataKey="sentiment" name="Тональность" stroke="#ef4444" dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <h3>Инциденты</h3>
      <ul className={styles.incidents}>
        {data.incidents.map((i) => (
          <li key={i.id}>{i.title} <span>· {i.post_count}</span></li>
        ))}
      </ul>
    </div>
  );
}

export function StoriesScreen({ brand }) {
  const [stories, setStories] = useState([]);
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    if (!brand?.id) return;
    api.getStories(brand.id).then((rows) => {
      setStories(rows);
      setSelected(rows[0]?.id ?? null);
    }).catch(() => setStories([]));
  }, [brand?.id]);

  return (
    <div className={styles.wrap}>
      <div className={styles.list}>
        {stories.length === 0 && <div className={styles.empty}>Пока нет сюжетов</div>}
        {stories.map((s) => (
          <button
            key={s.id}
            className={s.id === selected ? styles.activeItem : styles.item}
            onClick={() => setSelected(s.id)}
          >
            <div className={styles.title}>{s.title}</div>
            <div className={styles.sub}>{s.post_count} · {(s.avg_sentiment ?? 0).toFixed(2)}</div>
          </button>
        ))}
      </div>
      <div className={styles.pane}>
        {selected ? <StoryDetail id={selected} /> : <div className={styles.empty}>Выберите сюжет</div>}
      </div>
    </div>
  );
}
```

```css
/* echo-app/src/components/app/stories.module.css */
.wrap { display: flex; gap: 16px; height: 100%; }
.list { width: 280px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.item, .activeItem { text-align: left; padding: 10px 12px; border: 1px solid #e5e7eb;
  border-radius: 8px; background: #fff; cursor: pointer; }
.activeItem { border-color: #6366f1; background: #eef2ff; }
.title { font-weight: 600; font-size: 14px; }
.sub { color: #6b7280; font-size: 12px; margin-top: 2px; }
.pane { flex: 1; overflow-y: auto; }
.detail h2 { margin: 0 0 4px; }
.meta { color: #6b7280; font-size: 13px; margin-bottom: 16px; }
.anomaly { color: #ef4444; font-weight: 600; }
.incidents { list-style: none; padding: 0; }
.incidents li { padding: 6px 0; border-bottom: 1px solid #f3f4f6; font-size: 14px; }
.incidents li span { color: #9ca3af; }
.empty { color: #9ca3af; padding: 24px; }
```

- [ ] **Step 2: Verify build**

Run: `cd echo-app && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add echo-app/src/components/app/Stories.jsx echo-app/src/components/app/stories.module.css
git commit -m "feat: Stories screen with timeline chart"
```

---

### Task 13: Wire screen into navigation

**Files:**
- Modify: `echo-app/src/components/app/Shell.jsx` (sidebar item), `echo-app/src/pages/AppPage.jsx` (render branch + import)

- [ ] **Step 1: Add sidebar nav item**

In `echo-app/src/components/app/Shell.jsx`, add a "Сюжеты" entry to the sidebar nav list, matching the existing items' shape (the same way `analytics` / `cityexplorer` items are declared), with screen key `'stories'`.

- [ ] **Step 2: Render the screen**

In `echo-app/src/pages/AppPage.jsx`:
- Add import: `import { StoriesScreen } from '../components/app/Stories';`
- Add a render branch alongside the existing `screen === '...'` branches:

```jsx
{screen === 'stories' && <StoriesScreen brand={brand} />}
```

- [ ] **Step 3: Verify build**

Run: `cd echo-app && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Manual smoke test**

Run backend (`cd backend && uvicorn radar.api:app --reload`) and frontend (`cd echo-app && npm run dev`). Log in with the test restaurant account, open "Сюжеты". With existing mentions, hit `POST /stories/recompute?brand_id=<id>` once (or wait a scheduler tick), then confirm stories list + chart render.

- [ ] **Step 4: Commit**

```bash
git add echo-app/src/components/app/Shell.jsx echo-app/src/pages/AppPage.jsx
git commit -m "feat: add Сюжеты screen to navigation"
```

---

## Self-Review notes (resolved)

- **Spec §2 tables** → Tasks 2–4 (vec tables, ORM models, migration). ✅
- **Spec §3 embeddings** → Task 1. ✅
- **Spec §4 pipeline (dedup→incident→story→points)** → Tasks 5–7. ✅
- **Spec §5 scheduler hook** → Task 8. ✅
- **Spec §6 API** → Task 9. ✅
- **Spec §7 frontend** → Tasks 11–13. ✅
- **Spec §9 out-of-MVP (LLM digests, anomaly detection, RSS)** → intentionally NOT in this plan; `is_anomaly` field + `summary` field are scaffolded for later.
- **Type consistency:** `embed()`, `vec.store/knn/create_vec_tables`, `update_stories`, `_recompute_points`, `StoryOut/StoryDetailOut/StoryPointOut/IncidentOut`, `_run_brand_pipeline`, `getStories/getStory` — names consistent across tasks.
- **Open implementation detail:** the real auth-dependency name in `api.py` and the real auth-header helper in `api.js` must be confirmed at implementation time (flagged in Tasks 9 & 11). Everything else is concrete.
```
