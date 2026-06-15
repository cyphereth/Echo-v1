# Anomaly / Info-Attack Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag a story as anomalous when its latest hourly bucket shows a volume spike plus either a sharp negative sentiment shift or a source influx, and surface anomalous stories first (with a ⚠ badge) on the «Сюжеты» screen.

**Architecture:** A new rule-based module reads a story's `story_points` (hourly timeline) and sets `stories.is_anomaly`. It runs inside the existing `update_stories` pass right after `_recompute_points`. The `/stories` list sorts anomalous first; the React list shows a ⚠ marker. No new infra, no LLM.

**Tech Stack:** Python 3.x, SQLAlchemy, SQLite; React (echo-app). Use `python3` for all commands (host has no `python`).

Spec: `docs/superpowers/specs/2026-06-16-anomaly-detection-design.md`

---

## File Structure

**Backend (create):**
- `backend/radar/anomalies.py` — `detect_anomaly(session, story_id) -> bool`.
- `backend/tests/test_anomalies.py` — unit tests for the rule.

**Backend (modify):**
- `backend/radar/stories.py` — call `detect_anomaly` after `_recompute_points`.
- `backend/radar/api.py` — sort `/stories` anomalous-first.
- `backend/tests/test_stories.py` — integration test (update_stories flags anomaly).
- `backend/tests/test_stories_api.py` — sort-order test.

**Frontend (modify, echo-app):**
- `echo-app/src/components/app/Stories.jsx` — ⚠ marker on anomalous list items.
- `echo-app/src/components/app/stories.module.css` — marker style.

---

### Task 1: Anomaly detection rule

**Files:**
- Create: `backend/radar/anomalies.py`
- Test: `backend/tests/test_anomalies.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_anomalies.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def _story(s, points):
    """points: list of (mention_count, avg_sentiment, source_count), oldest first."""
    from radar.models import Story, StoryPoint
    base = datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc)
    st = Story(brand_id=1, title="t", first_seen_at=base, last_seen_at=base)
    s.add(st); s.flush()
    for i, (mc, sent, src) in enumerate(points):
        s.add(StoryPoint(story_id=st.id, bucket_start=base + timedelta(hours=i),
                         mention_count=mc, avg_sentiment=sent, source_count=src))
    s.flush()
    return st


def test_fires_on_spike_and_negative():
    from radar.anomalies import detect_anomaly
    s = _mem()
    st = _story(s, [(2, 0.5, 2), (2, 0.5, 2), (2, 0.5, 2), (10, -0.5, 2)])
    assert detect_anomaly(s, st.id) is True
    assert st.is_anomaly is True


def test_fires_on_spike_and_source_influx():
    from radar.anomalies import detect_anomaly
    s = _mem()
    st = _story(s, [(2, 0.0, 1), (2, 0.0, 1), (2, 0.0, 1), (10, 0.0, 5)])
    assert detect_anomaly(s, st.id) is True


def test_no_fire_spike_only():
    from radar.anomalies import detect_anomaly
    s = _mem()
    st = _story(s, [(2, 0.0, 2), (2, 0.0, 2), (2, 0.0, 2), (10, 0.0, 2)])
    assert detect_anomaly(s, st.id) is False
    assert st.is_anomaly is False


def test_no_fire_insufficient_history():
    from radar.anomalies import detect_anomaly
    s = _mem()
    st = _story(s, [(2, 0.5, 2), (10, -0.9, 9)])  # only 2 buckets
    assert detect_anomaly(s, st.id) is False


def test_clears_when_normal():
    from radar.anomalies import detect_anomaly
    from radar.models import Story
    s = _mem()
    st = _story(s, [(2, 0.5, 2), (2, 0.5, 2), (2, 0.5, 2), (2, 0.5, 2)])
    st.is_anomaly = True; s.flush()         # pretend a prior run flagged it
    assert detect_anomaly(s, st.id) is False
    assert s.get(Story, st.id).is_anomaly is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_anomalies.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.anomalies'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/radar/anomalies.py
from __future__ import annotations
import os

from sqlalchemy.orm import Session

from .models import Story, StoryPoint

# Tunables (env, calibrate on real brands).
MIN_BUCKETS   = int(os.getenv("ANOMALY_MIN_BUCKETS", "3"))      # baseline buckets required
VOLUME_FACTOR = float(os.getenv("ANOMALY_VOLUME_FACTOR", "3.0"))
MIN_VOLUME    = int(os.getenv("ANOMALY_MIN_VOLUME", "3"))       # absolute floor for a spike
SENT_DROP     = float(os.getenv("ANOMALY_SENT_DROP", "0.4"))    # drop toward negative
SOURCE_FACTOR = float(os.getenv("ANOMALY_SOURCE_FACTOR", "2.0"))


def _mean(xs) -> float:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else 0.0


def detect_anomaly(session: Session, story_id: int) -> bool:
    """Set story.is_anomaly from its timeline points. Idempotent.

    Trigger = volume spike (required) AND (sentiment drop OR source influx),
    evaluated on the latest bucket vs the mean of all prior buckets. Needs at
    least MIN_BUCKETS prior buckets, else False (no baseline yet).
    """
    story = session.get(Story, story_id)
    if story is None:
        return False
    points = (session.query(StoryPoint)
              .filter(StoryPoint.story_id == story_id)
              .order_by(StoryPoint.bucket_start).all())
    result = False
    if len(points) > MIN_BUCKETS:            # need MIN_BUCKETS baseline + 1 current
        last = points[-1]
        base = points[:-1]
        base_vol = _mean([p.mention_count for p in base])
        base_sent = _mean([p.avg_sentiment for p in base])
        base_src = _mean([p.source_count for p in base])

        spike = (last.mention_count >= MIN_VOLUME and
                 last.mention_count >= base_vol * VOLUME_FACTOR)
        sent_shift = (last.avg_sentiment is not None and
                      base_sent - last.avg_sentiment >= SENT_DROP)
        src_influx = (base_src > 0 and
                      last.source_count >= base_src * SOURCE_FACTOR)
        result = spike and (sent_shift or src_influx)

    story.is_anomaly = result
    session.flush()
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_anomalies.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/radar/anomalies.py backend/tests/test_anomalies.py
git commit -m "feat: rule-based story anomaly detection"
```

---

### Task 2: Run detection inside update_stories

**Files:**
- Modify: `backend/radar/stories.py` (the recompute loop in `update_stories`)
- Test: `backend/tests/test_stories.py`

`update_stories` currently ends with:
```python
    session.flush()
    for sid in stories_touched:
        _recompute_points(session, sid)
    session.commit()
    return {"mentions": len(new), "incidents": len(incidents_touched),
            "stories": len(stories_touched)}
```

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_stories.py` (uses existing `_session`, `_mk`, `_fake_embed`):

```python
def test_update_stories_flags_anomaly(monkeypatch):
    import radar.stories as S
    from radar.models import Story
    s = _session()
    base = datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc)
    # 3 baseline hours: one positive mention each (low volume, positive tone)
    for h in range(3):
        _mk(s, post_id=f"b{h}", text="тема", author=f"@u{h}", tone="positive",
            created_at=base + timedelta(hours=h, minutes=1))
    # spike hour: 6 negative mentions (volume spike + sentiment drop)
    for j in range(6):
        _mk(s, post_id=f"s{j}", text="тема", author=f"@x{j}", tone="negative",
            created_at=base + timedelta(hours=3, minutes=j))
    s.commit()
    # identical text -> identical vector -> one incident -> one story
    monkeypatch.setattr(S.embeddings, "embed", _fake_embed({"тема": [1.0, 0.0, 0.0]}))
    S.update_stories(s, brand_id=1)
    st = s.query(Story).one()
    assert st.is_anomaly is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_stories.py::test_update_stories_flags_anomaly -v`
Expected: FAIL — `assert False is True` (anomaly not evaluated yet; `is_anomaly` defaults False).

- [ ] **Step 3: Add the call**

In `backend/radar/stories.py`, change the recompute loop in `update_stories` to also run detection:

```python
    session.flush()
    from . import anomalies
    for sid in stories_touched:
        _recompute_points(session, sid)
        anomalies.detect_anomaly(session, sid)
    session.commit()
    return {"mentions": len(new), "incidents": len(incidents_touched),
            "stories": len(stories_touched)}
```

(Import `anomalies` inside the function as shown to avoid any import-order concerns.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_stories.py -v`
Expected: PASS (all, including the new test)

- [ ] **Step 5: Commit**

```bash
git add backend/radar/stories.py backend/tests/test_stories.py
git commit -m "feat: evaluate anomaly detection after recomputing story points"
```

---

### Task 3: Sort anomalous stories first in the API

**Files:**
- Modify: `backend/radar/api.py` (the `list_stories` route)
- Test: `backend/tests/test_stories_api.py`

The current route orders by `Story.last_seen_at.desc()`:
```python
    rows = (session.query(Story)
            .filter(Story.brand_id == brand_id, Story.status == "active")
            .order_by(Story.last_seen_at.desc()).all())
```

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_stories_api.py`:

```python
def test_list_sorts_anomalous_first(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'b.db'}")
    import importlib
    import radar.db as db; importlib.reload(db); db.init_db()
    import radar.api as api; importlib.reload(api)
    from fastapi.testclient import TestClient
    from radar.models import Story, Brand, User
    from datetime import datetime, timezone, timedelta

    s = db.get_session()
    u = User(email="t2@t.t", password_hash="x"); s.add(u); s.flush()
    b = Brand(id=1, user_id=u.id, name="b"); s.add(b); s.flush()
    now = datetime.now(timezone.utc)
    # "calm" is newer (would sort first by recency) but not anomalous;
    # "attack" is older but anomalous -> must come first.
    s.add(Story(brand_id=1, title="calm", is_anomaly=False,
                first_seen_at=now, last_seen_at=now))
    s.add(Story(brand_id=1, title="attack", is_anomaly=True,
                first_seen_at=now - timedelta(days=1), last_seen_at=now - timedelta(days=1)))
    s.commit()

    api.app.dependency_overrides[api.current_user] = lambda: u
    client = TestClient(api.app)
    titles = [row["title"] for row in client.get("/stories?brand_id=1").json()]
    api.app.dependency_overrides.clear()
    assert titles == ["attack", "calm"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_stories_api.py::test_list_sorts_anomalous_first -v`
Expected: FAIL — `assert ['calm', 'attack'] == ['attack', 'calm']` (currently sorted by recency only).

- [ ] **Step 3: Change the sort**

In `backend/radar/api.py`, in `list_stories`, change the `order_by` to put anomalous first:

```python
    rows = (session.query(Story)
            .filter(Story.brand_id == brand_id, Story.status == "active")
            .order_by(Story.is_anomaly.desc(), Story.last_seen_at.desc()).all())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python3 -m pytest tests/test_stories_api.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add backend/radar/api.py backend/tests/test_stories_api.py
git commit -m "feat: sort anomalous stories first in /stories"
```

---

### Task 4: ⚠ badge on anomalous list items (frontend)

**Files:**
- Modify: `echo-app/src/components/app/Stories.jsx`, `echo-app/src/components/app/stories.module.css`

This is build-verified (no unit tests). The `StoriesScreen` list maps `stories` and each item already shows `s.title`. Add a ⚠ marker when `s.is_anomaly`.

- [ ] **Step 1: Add the marker in the list item**

In `echo-app/src/components/app/Stories.jsx`, find the list item title line inside `StoriesScreen`:

```jsx
            <div className={styles.title}>{s.title}</div>
```

Replace it with:

```jsx
            <div className={styles.title}>
              {s.is_anomaly && <span className={styles.warn} title="Аномалия">⚠ </span>}
              {s.title}
            </div>
```

- [ ] **Step 2: Add the style**

Append to `echo-app/src/components/app/stories.module.css`:

```css
.warn { color: #ef4444; font-weight: 700; }
```

- [ ] **Step 3: Verify build**

Run: `cd echo-app && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add echo-app/src/components/app/Stories.jsx echo-app/src/components/app/stories.module.css
git commit -m "feat: ⚠ badge on anomalous stories in list"
```

---

## Self-Review notes (resolved)

- **Spec §2 rule (min history, spike required, sentiment drop, source influx, AND/OR combine)** → Task 1 (`detect_anomaly`) + its 5 tests cover each branch incl. zero-baseline behavior and clear-when-normal. ✅
- **Spec §3 integration (after `_recompute_points`)** → Task 2. ✅
- **Spec §4 API sort** → Task 3. ✅
- **Spec §5 frontend badge (sort from backend)** → Task 4. ✅
- **Spec §6 tests** → all enumerated cases mapped to Tasks 1–3 tests.
- **Out of scope (LLM alert, alert log, push)** → not in this plan. ✅
- **Type/name consistency:** `detect_anomaly(session, story_id) -> bool`, env constants `ANOMALY_*`, `is_anomaly` field, `_recompute_points` — consistent with the existing story-timeline code and across tasks.
```
