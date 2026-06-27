# Intel Alerts & Anomaly Push — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect activity bursts at the story and direction level, persist them as deduplicated `IntelAlert` rows, push them over the existing SSE live stream, and surface them as a toast + notification bell in the intel UI.

**Architecture:** A new `IntelAlert` table is the single source of truth. A new `radar/intel/alerts.py` module runs inside the existing ticker (`run_intel_tick`, ~180s) after clustering/anomaly detection: it emits story-level alerts from `story.is_anomaly` and computes direction-level bursts, deduping by a per-scope cooldown. The existing `/intel/stream/live` SSE endpoint gains a second DB tail over `IntelAlert` (emitted as a named `event: alert` frame). The frontend opens a single stream in `IntelApp`, owns alert state, and renders a toast + bell.

**Tech Stack:** Python 3.14, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), FastAPI (SSE via `StreamingResponse`), pytest (backend). React (Vite) frontend with a fetch-based SSE reader; CSS modules. No frontend test runner exists — frontend tasks verify manually.

## Global Constraints

- Backend models use SQLAlchemy 2.0 `Mapped[...]` + `mapped_column`, importing `Base, _now` from `radar.models`. Match the existing `radar/intel/models.py` column style.
- Datetimes are timezone-aware UTC; use `_now` for defaults and `datetime.now(timezone.utc)` in logic. Wrap stored naive datetimes with the existing `_aware()` helper before `.isoformat()`.
- No new third-party dependencies (backend or frontend).
- New table is created by the existing `init_db()` → `Base.metadata.create_all(engine)` path (it builds missing tables on existing DBs); no manual migration code.
- Anomaly tunables are reused from `radar/core/anomalies.py`: `VOLUME_FACTOR` (3.0), `MIN_VOLUME` (3), `MIN_BUCKETS` (3). New env knob: `ALERT_COOLDOWN_H` (default `6`).
- Tests run from `backend/`: `python -m pytest tests/<file> -v`. Frontend dev server: `npm run dev` in `echo-app/`.
- Commit after each task with the message shown in its final step.

---

## File Structure

**Backend (`backend/radar/intel/`)**
- `models.py` — add `IntelAlert` (modify).
- `alerts.py` — detection + dedup + scan entrypoint (create).
- `passes.py` — call `alerts.scan(session)` at the end of `run_intel_tick` (modify).
- `aggregate.py` — `compute_overview` reads alerts from `IntelAlert`; add `alert_payload()` (modify).
- `api.py` — alert REST endpoints + SSE alert tail (modify).

**Backend tests (`backend/tests/`)**
- `test_intel_alerts.py` — model, dedup, story scan, direction burst, REST, overview (create).
- `test_intel_alerts_sse.py` — SSE delivers a named `alert` frame (create).

**Frontend (`echo-app/src/features/intel/`)**
- `api.js` — alert API methods + extend `streamLiveEvents` (modify).
- `IntelApp.jsx` — own the unified stream, alert state, render bell + toast (modify).
- `components/IntelHome.jsx` — consume live events via prop instead of opening its own stream (modify).
- `components/AlertBell.jsx` — header bell + dropdown (create).
- `components/AlertToast.jsx` — corner toast stack (create).
- `intel.module.css` — bell + toast styles (modify).

---

## Task 1: `IntelAlert` model

**Files:**
- Modify: `backend/radar/intel/models.py`
- Test: `backend/tests/test_intel_alerts.py`

**Interfaces:**
- Consumes: `Base`, `_now` from `radar.models`; `IntelDirection`, `IntelStory` tables (FKs).
- Produces: `IntelAlert` with columns `id:int, scope:str, direction_id:int|None, story_id:int|None, kind:str, magnitude:float, title:str, message:str, fired_at:datetime, acknowledged_at:datetime|None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_intel_alerts.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    import radar.intel.models  # register intel tables
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_intel_alert_roundtrip():
    from radar.intel.models import IntelAlert
    s = _mem()
    a = IntelAlert(scope="direction", direction_id=1, kind="direction_burst",
                   magnitude=320.0, title="Курское", message="Всплеск ×4")
    s.add(a); s.commit()
    got = s.query(IntelAlert).one()
    assert got.scope == "direction"
    assert got.kind == "direction_burst"
    assert got.acknowledged_at is None
    assert got.fired_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py::test_intel_alert_roundtrip -v`
Expected: FAIL with `ImportError: cannot import name 'IntelAlert'`.

- [ ] **Step 3: Add the model**

Append to `backend/radar/intel/models.py` (the imports already include `Boolean, ForeignKey, Integer, Text`, `Mapped, mapped_column`, `Optional`, `datetime`, `Base`, `_now`):

```python
class IntelAlert(Base):
    __tablename__ = "intel_alerts"
    id:              Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope:           Mapped[str]      = mapped_column(Text, nullable=False)   # "story" | "direction"
    direction_id:    Mapped[Optional[int]] = mapped_column(ForeignKey("intel_directions.id"))
    story_id:        Mapped[Optional[int]] = mapped_column(ForeignKey("intel_stories.id"))
    kind:            Mapped[str]      = mapped_column(Text, nullable=False)   # spike|sentiment|source_influx|direction_burst
    magnitude:       Mapped[float]    = mapped_column(default=0.0)            # SQLAlchemy infers Float from Mapped[float]
    title:           Mapped[str]      = mapped_column(Text, default="")
    message:         Mapped[str]      = mapped_column(Text, default="")
    fired_at:        Mapped[datetime] = mapped_column(default=_now)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py::test_intel_alert_roundtrip -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/radar/intel/models.py backend/tests/test_intel_alerts.py
git commit -m "feat(intel): IntelAlert model"
```

---

## Task 2: Cooldown dedup helper (`alerts._emit`)

**Files:**
- Create: `backend/radar/intel/alerts.py`
- Test: `backend/tests/test_intel_alerts.py`

**Interfaces:**
- Consumes: `IntelAlert` (Task 1); `_now` from `radar.models`.
- Produces:
  - `ALERT_COOLDOWN_H: int`
  - `_recent_exists(session, scope, kind, *, direction_id=None, story_id=None) -> bool`
  - `_emit(session, scope, kind, *, title, message, magnitude, direction_id=None, story_id=None) -> IntelAlert | None` — inserts and returns the new row, or returns `None` if a same-scope/ref/kind alert fired within the cooldown.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_intel_alerts.py`:

```python
def test_emit_inserts_then_dedups_within_cooldown():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()

    first = alerts._emit(s, "direction", "direction_burst",
                         title="Курское", message="Всплеск ×4",
                         magnitude=300.0, direction_id=1)
    s.commit()
    assert first is not None
    assert s.query(IntelAlert).count() == 1

    # Same scope/ref/kind again → suppressed by cooldown.
    again = alerts._emit(s, "direction", "direction_burst",
                         title="Курское", message="Всплеск ×5",
                         magnitude=350.0, direction_id=1)
    s.commit()
    assert again is None
    assert s.query(IntelAlert).count() == 1


def test_emit_not_deduped_for_different_kind():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()
    alerts._emit(s, "story", "spike", title="t", message="m", magnitude=1.0, story_id=7)
    alerts._emit(s, "story", "source_influx", title="t", message="m", magnitude=1.0, story_id=7)
    s.commit()
    assert s.query(IntelAlert).count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k emit -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'radar.intel.alerts'`.

- [ ] **Step 3: Create the module + helper**

Create `backend/radar/intel/alerts.py`:

```python
"""Intel alerts: detect story/direction bursts and persist deduplicated IntelAlert rows.

Runs inside the ticker (passes.run_intel_tick) after clustering + anomaly detection.
A per-(scope, ref, kind) cooldown collapses one sustained burst into a single alert.
"""
from __future__ import annotations
import os
import logging
from datetime import datetime, timezone, timedelta

from ..models import _now
from .models import IntelAlert

log = logging.getLogger("radar.intel.alerts")

ALERT_COOLDOWN_H = int(os.getenv("ALERT_COOLDOWN_H", "6"))


def _recent_exists(session, scope, kind, *, direction_id=None, story_id=None) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_H)
    q = (session.query(IntelAlert)
         .filter(IntelAlert.scope == scope, IntelAlert.kind == kind,
                 IntelAlert.fired_at >= cutoff))
    if scope == "story":
        q = q.filter(IntelAlert.story_id == story_id)
    else:
        q = q.filter(IntelAlert.direction_id == direction_id)
    return session.query(q.exists()).scalar()


def _emit(session, scope, kind, *, title, message, magnitude,
          direction_id=None, story_id=None):
    """Insert an alert unless one of the same (scope, ref, kind) fired within the
    cooldown. Returns the new IntelAlert or None when suppressed."""
    if _recent_exists(session, scope, kind, direction_id=direction_id, story_id=story_id):
        return None
    alert = IntelAlert(scope=scope, kind=kind, title=title or "", message=message or "",
                       magnitude=float(magnitude or 0.0),
                       direction_id=direction_id, story_id=story_id, fired_at=_now())
    session.add(alert)
    session.flush()
    return alert
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k emit -v`
Expected: PASS (both emit tests).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/intel/alerts.py backend/tests/test_intel_alerts.py
git commit -m "feat(intel): alert cooldown dedup helper"
```

---

## Task 3: Story-level alert scan (`scan_story_alerts`)

**Files:**
- Modify: `backend/radar/intel/alerts.py`
- Test: `backend/tests/test_intel_alerts.py`

**Interfaces:**
- Consumes: `IntelStory`, `IntelStoryPoint` from `radar.intel.models`; `IntelDirection`; aggregate `_spike_pct`/`_points`; core tunables `VOLUME_FACTOR`, `SOURCE_FACTOR`, `MIN_VOLUME`, `MIN_BUCKETS`; `_emit` (Task 2).
- Produces:
  - `_classify_story(points) -> tuple[str, float]` — returns `(kind, magnitude)` where kind ∈ `{"source_influx","spike"}`.
  - `scan_story_alerts(session) -> list[IntelAlert]` — emits one alert per currently-anomalous story past the cooldown.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_intel_alerts.py`:

```python
def _direction(s, key="kursk", name="Курское"):
    from radar.intel.models import IntelDirection
    d = IntelDirection(key=key, name=name)
    s.add(d); s.flush()
    return d


def _anomalous_story(s, direction_id):
    """A story flagged is_anomaly with a spiking source-influx timeline."""
    from radar.intel.models import IntelStory, IntelStoryPoint
    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    st = IntelStory(direction_id=direction_id, title="Прорыв обороны",
                    is_anomaly=True, post_count=12, source_count=5,
                    first_seen_at=base, last_seen_at=base)
    s.add(st); s.flush()
    pts = [(2, 1), (2, 1), (2, 1), (10, 5)]  # (mention_count, source_count) oldest first
    for i, (mc, sc) in enumerate(pts):
        s.add(IntelStoryPoint(story_id=st.id, bucket_start=base + timedelta(hours=i),
                              mention_count=mc, source_count=sc))
    s.flush()
    return st


def test_scan_story_alerts_emits_for_anomalous_story():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()
    d = _direction(s)
    st = _anomalous_story(s, d.id)

    out = alerts.scan_story_alerts(s)
    s.commit()
    assert len(out) == 1
    row = s.query(IntelAlert).one()
    assert row.scope == "story"
    assert row.story_id == st.id
    assert row.direction_id == d.id          # copied from the story
    assert row.kind in ("spike", "source_influx")

    # Second scan within cooldown → no duplicate.
    out2 = alerts.scan_story_alerts(s)
    s.commit()
    assert out2 == []
    assert s.query(IntelAlert).count() == 1


def test_scan_story_alerts_skips_non_anomalous():
    from radar.intel import alerts
    from radar.intel.models import IntelStory
    s = _mem()
    d = _direction(s)
    base = datetime(2026, 6, 20, tzinfo=timezone.utc)
    s.add(IntelStory(direction_id=d.id, title="спокойно", is_anomaly=False,
                     first_seen_at=base, last_seen_at=base))
    s.flush()
    assert alerts.scan_story_alerts(s) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k scan_story -v`
Expected: FAIL with `AttributeError: module 'radar.intel.alerts' has no attribute 'scan_story_alerts'`.

- [ ] **Step 3: Implement classification + scan**

Add to `backend/radar/intel/alerts.py` (extend imports at top with the lines shown, then append the functions):

```python
# add to the imports block
from ..core.anomalies import VOLUME_FACTOR, SOURCE_FACTOR, MIN_VOLUME, MIN_BUCKETS
from . import aggregate
from .models import IntelDirection, IntelStory, IntelStoryPoint, IntelMention
```

```python
def _classify_story(points) -> tuple[str, float]:
    """Decide the kind + magnitude for an anomalous story from its timeline points.

    points: IntelStoryPoint list. Mirrors core.anomalies.detect_anomaly's branches:
    a source influx (last source_count >= base mean * SOURCE_FACTOR) is reported as
    'source_influx', otherwise 'spike'. Magnitude is the volume spike percentage.
    """
    pts = sorted(points, key=lambda p: p.bucket_start)
    magnitude = aggregate._spike_pct(pts)
    kind = "spike"
    if len(pts) > MIN_BUCKETS:
        base = pts[:-1]
        last = pts[-1]
        base_src = sum((getattr(p, "source_count", 0) or 0) for p in base) / max(1, len(base))
        last_src = getattr(last, "source_count", 0) or 0
        if base_src > 0 and last_src >= base_src * SOURCE_FACTOR:
            kind = "source_influx"
    return kind, magnitude


def _story_message(kind: str, magnitude: float, title: str) -> str:
    head = "Приток источников" if kind == "source_influx" else f"Всплеск +{int(magnitude)}%"
    return f"{head}: {title}" if title else head


def scan_story_alerts(session) -> list:
    """Emit an alert for every currently-anomalous active story (cooldown-deduped)."""
    out = []
    stories = (session.query(IntelStory)
               .filter(IntelStory.is_anomaly.is_(True), IntelStory.status == "active").all())
    for st in stories:
        pts = aggregate._points(session, st.id)
        kind, magnitude = _classify_story(pts)
        alert = _emit(session, "story", kind,
                      title=st.title or "", message=_story_message(kind, magnitude, st.title or ""),
                      magnitude=magnitude, direction_id=st.direction_id, story_id=st.id)
        if alert is not None:
            out.append(alert)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k scan_story -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/intel/alerts.py backend/tests/test_intel_alerts.py
git commit -m "feat(intel): story-level alert scan"
```

---

## Task 4: Direction-level burst detection (`detect_direction_burst`, `scan_direction_alerts`)

**Files:**
- Modify: `backend/radar/intel/alerts.py`
- Test: `backend/tests/test_intel_alerts.py`

**Interfaces:**
- Consumes: `IntelMention`, `IntelDirection`; core tunables (already imported in Task 3).
- Produces:
  - `_direction_hourly_counts(session, direction_id) -> list[int]` — mention counts per UTC hour bucket, oldest first.
  - `detect_direction_burst(session, direction_id) -> float | None` — spike pct if the latest hour bursts, else `None`.
  - `scan_direction_alerts(session) -> list[IntelAlert]`.
  - `scan(session) -> list[IntelAlert]` — tick entrypoint: `scan_story_alerts + scan_direction_alerts`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_intel_alerts.py`:

```python
def _mention(s, direction_id, when, post_id):
    from radar.intel.models import IntelMention
    s.add(IntelMention(direction_id=direction_id, platform="tg", post_id=post_id,
                       author="@x", text="t", created_at=when, first_seen=when))


def test_detect_direction_burst_fires_on_latest_hour_spike():
    from radar.intel import alerts
    s = _mem()
    d = _direction(s)
    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    # 3 baseline hours with 1 mention each, then a 9-mention spike in hour 3.
    n = 0
    for h in range(3):
        _mention(s, d.id, base + timedelta(hours=h, minutes=1), f"b{n}"); n += 1
    for i in range(9):
        _mention(s, d.id, base + timedelta(hours=3, minutes=i), f"s{n}"); n += 1
    s.flush()
    mag = alerts.detect_direction_burst(s, d.id)
    assert mag is not None and mag > 0


def test_detect_direction_burst_none_without_baseline():
    from radar.intel import alerts
    s = _mem()
    d = _direction(s)
    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    _mention(s, d.id, base, "a"); _mention(s, d.id, base + timedelta(hours=1), "b")
    s.flush()
    assert alerts.detect_direction_burst(s, d.id) is None  # < MIN_BUCKETS baseline


def test_scan_direction_alerts_emits_and_dedups():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()
    d = _direction(s)
    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    n = 0
    for h in range(3):
        _mention(s, d.id, base + timedelta(hours=h, minutes=1), f"b{n}"); n += 1
    for i in range(9):
        _mention(s, d.id, base + timedelta(hours=3, minutes=i), f"s{n}"); n += 1
    s.flush()
    out = alerts.scan_direction_alerts(s); s.commit()
    assert len(out) == 1
    assert s.query(IntelAlert).filter_by(scope="direction", kind="direction_burst").count() == 1
    assert alerts.scan_direction_alerts(s) == []  # cooldown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k direction -v`
Expected: FAIL with `AttributeError: ... has no attribute 'detect_direction_burst'`.

- [ ] **Step 3: Implement burst detection + scan + entrypoint**

Append to `backend/radar/intel/alerts.py`:

```python
def _direction_hourly_counts(session, direction_id) -> list[int]:
    """Mention counts per UTC hour for a direction, oldest first (no gap-filling —
    matches how aggregate builds story sparklines)."""
    rows = (session.query(IntelMention.created_at)
            .filter(IntelMention.direction_id == direction_id).all())
    buckets: dict = {}
    for (created_at,) in rows:
        if created_at is None:
            continue
        ts = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        key = ts.replace(minute=0, second=0, microsecond=0)
        buckets[key] = buckets.get(key, 0) + 1
    return [buckets[k] for k in sorted(buckets)]


def detect_direction_burst(session, direction_id):
    """Spike pct if the latest hour bursts vs the mean of prior hours, else None.
    Requires > MIN_BUCKETS baseline hours; latest >= MIN_VOLUME and >= base*VOLUME_FACTOR."""
    series = _direction_hourly_counts(session, direction_id)
    if len(series) <= MIN_BUCKETS:
        return None
    base = series[:-1]
    last = series[-1]
    base_mean = sum(base) / max(1, len(base))
    spike = last >= MIN_VOLUME and (last >= base_mean * VOLUME_FACTOR if base_mean > 0 else True)
    if not spike:
        return None
    return round((last - base_mean) / base_mean * 100, 1) if base_mean > 0 else 100.0


def scan_direction_alerts(session) -> list:
    out = []
    for d in session.query(IntelDirection).all():
        if d.key == "unassigned":
            continue  # the catch-all bucket is not a real direction
        magnitude = detect_direction_burst(session, d.id)
        if magnitude is None:
            continue
        alert = _emit(session, "direction", "direction_burst",
                      title=d.name or d.key,
                      message=f"Всплеск активности +{int(magnitude)}% по направлению {d.name or d.key}",
                      magnitude=magnitude, direction_id=d.id)
        if alert is not None:
            out.append(alert)
    return out


def scan(session) -> list:
    """Tick entrypoint: emit story + direction alerts. Never raises — logs and
    continues so a detection bug can't break the ticker."""
    out = []
    try:
        out += scan_story_alerts(session)
    except Exception:
        log.exception("intel story alert scan failed")
    try:
        out += scan_direction_alerts(session)
    except Exception:
        log.exception("intel direction alert scan failed")
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/intel/alerts.py backend/tests/test_intel_alerts.py
git commit -m "feat(intel): direction-level burst detection + scan entrypoint"
```

---

## Task 5: Wire alert scan into the ticker

**Files:**
- Modify: `backend/radar/intel/passes.py`
- Test: `backend/tests/test_intel_alerts.py`

**Interfaces:**
- Consumes: `alerts.scan` (Task 4).
- Produces: `run_intel_tick` emits alerts after clustering. No signature change.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_intel_alerts.py`:

```python
def test_run_intel_tick_emits_alerts(monkeypatch):
    """The tick runs alert scanning after clustering; an anomalous story yields a row."""
    from radar.intel import passes
    from radar.intel.models import IntelAlert
    s = _mem()
    d = _direction(s)
    _anomalous_story(s, d.id)
    s.commit()
    # tg_provider=None → collect is a no-op; clustering finds no untagged mentions;
    # alert scan still runs over the pre-seeded anomalous story.
    passes.run_intel_tick(s, tg_provider=None)
    assert s.query(IntelAlert).filter_by(scope="story").count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k run_intel_tick -v`
Expected: FAIL — `IntelAlert` count is 0 (scan not wired yet).

- [ ] **Step 3: Call `alerts.scan` at the end of `run_intel_tick`**

In `backend/radar/intel/passes.py`, the current `run_intel_tick` ends with the `for did in dir_ids:` clustering loop. Add an alert scan after that loop (still inside the function), matching the existing try/except + commit style:

```python
    # Emit alerts from the freshly-updated stories + direction activity. Isolated so a
    # detection error can't abort the tick.
    from . import alerts
    try:
        alerts.scan(session)
        session.commit()
    except Exception:
        log.exception("intel alert scan failed")
        session.rollback()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k run_intel_tick -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/radar/intel/passes.py backend/tests/test_intel_alerts.py
git commit -m "feat(intel): run alert scan in the ticker"
```

---

## Task 6: Alert REST endpoints + serializer

**Files:**
- Modify: `backend/radar/intel/api.py`, `backend/radar/intel/aggregate.py`
- Test: `backend/tests/test_intel_alerts.py`

**Interfaces:**
- Consumes: `IntelAlert`, `IntelDirection`; `aggregate._aware`.
- Produces:
  - `aggregate.alert_payload(session, alert) -> dict` with keys `id, scope, story_id, direction (key|None), kind, magnitude, title, message, at, acknowledged` — the shared serializer.
  - `GET /intel/alerts?unread={bool}&limit={int}` → `list[dict]` (newest first).
  - `POST /intel/alerts/{id}/ack` → `{"ok": true}`.
  - `POST /intel/alerts/ack-all` → `{"ok": true, "count": N}`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_intel_alerts.py`:

```python
def _client(session):
    """A TestClient whose /intel router uses our in-memory session + a stub user."""
    from fastapi import FastAPI
    from radar.intel import api as intel_api
    from radar.models import User
    app = FastAPI()
    app.include_router(intel_api.router)
    app.dependency_overrides[intel_api.db] = lambda: session
    app.dependency_overrides[intel_api.current_user] = lambda: User(id=1, email="t@t", password_hash="x")
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_alerts_list_and_ack():
    from radar.intel import alerts
    s = _mem()
    d = _direction(s)
    alerts._emit(s, "direction", "direction_burst", title="Курское",
                 message="Всплеск", magnitude=300.0, direction_id=d.id)
    s.commit()
    c = _client(s)

    listed = c.get("/intel/alerts?unread=true").json()
    assert len(listed) == 1
    aid = listed[0]["id"]
    assert listed[0]["direction"] == "kursk"
    assert listed[0]["acknowledged"] is False

    assert c.post(f"/intel/alerts/{aid}/ack").json()["ok"] is True
    assert c.get("/intel/alerts?unread=true").json() == []

    # ack-all over a fresh unread row.
    alerts._emit(s, "story", "spike", title="t", message="m", magnitude=1.0, story_id=9)
    s.commit()
    assert c.post("/intel/alerts/ack-all").json()["count"] == 1
    assert c.get("/intel/alerts?unread=true").json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k "alerts_list" -v`
Expected: FAIL with 404 (routes not defined).

- [ ] **Step 3a: Add the shared serializer to `aggregate.py`**

Add to `backend/radar/intel/aggregate.py` (import `IntelDirection`, `IntelAlert` are in the module's model imports — add `IntelAlert` to that import line):

```python
def alert_payload(session, a) -> dict:
    d = session.get(IntelDirection, a.direction_id) if a.direction_id else None
    return {"id": a.id, "scope": a.scope, "story_id": a.story_id,
            "direction": d.key if d else None, "kind": a.kind,
            "magnitude": a.magnitude, "title": a.title, "message": a.message,
            "at": _aware(a.fired_at).isoformat() if a.fired_at else None,
            "acknowledged": a.acknowledged_at is not None}
```

- [ ] **Step 3b: Add the routes to `api.py`**

In `backend/radar/intel/api.py`, add `IntelAlert` to the model imports, ensure `_now` is imported from `..models` (add if missing), and add these routes (place near the other `/intel/*` routes):

```python
@router.get("/intel/alerts")
def intel_alerts(
    unread: bool = False,
    limit: int = 50,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    q = session.query(IntelAlert)
    if unread:
        q = q.filter(IntelAlert.acknowledged_at.is_(None))
    rows = q.order_by(IntelAlert.id.desc()).limit(limit).all()
    return [aggregate.alert_payload(session, a) for a in rows]


@router.post("/intel/alerts/{alert_id}/ack")
def intel_alert_ack(
    alert_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    a = session.get(IntelAlert, alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    if a.acknowledged_at is None:
        a.acknowledged_at = _now()
        session.commit()
    return {"ok": True}


@router.post("/intel/alerts/ack-all")
def intel_alert_ack_all(
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    rows = session.query(IntelAlert).filter(IntelAlert.acknowledged_at.is_(None)).all()
    for a in rows:
        a.acknowledged_at = _now()
    session.commit()
    return {"ok": True, "count": len(rows)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k "alerts_list" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/radar/intel/api.py backend/radar/intel/aggregate.py backend/tests/test_intel_alerts.py
git commit -m "feat(intel): alert REST endpoints + shared serializer"
```

---

## Task 7: SSE alert tail (named `alert` frame)

**Files:**
- Modify: `backend/radar/intel/api.py`
- Test: `backend/tests/test_intel_alerts_sse.py`

**Interfaces:**
- Consumes: `IntelAlert`; `aggregate.alert_payload`; existing `event_gen` in `intel_stream_live`.
- Produces: `/intel/stream/live` accepts `after_alert_id: int = 0`; new `IntelAlert` rows (id > after_alert_id) are emitted as `event: alert\ndata: {json}\n\n`. Mention frames are unchanged (`data: {json}\n\n`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_intel_alerts_sse.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import asyncio
from datetime import datetime, timezone


def _mem_engine():
    from sqlalchemy import create_engine
    from radar.models import Base
    import radar.intel.models
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_event_gen_emits_named_alert_frame(monkeypatch):
    """After after_alert_id, a new IntelAlert is delivered as an `event: alert` frame."""
    from sqlalchemy.orm import Session
    from radar.intel import api as intel_api
    from radar.intel import alerts
    from radar.intel.models import IntelDirection

    eng = _mem_engine()
    # Route get_session() (used inside event_gen) at our in-memory engine.
    monkeypatch.setattr(intel_api, "get_session", lambda: Session(eng))
    monkeypatch.setattr(intel_api, "_auth_user_from_header", lambda authorization: object())
    # Stop the infinite loop after the first cycle.
    async def _stop(_):
        raise asyncio.CancelledError()
    monkeypatch.setattr(intel_api.asyncio, "sleep", _stop)

    s = Session(eng)
    d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    alerts._emit(s, "direction", "direction_burst", title="Курское",
                 message="Всплеск", magnitude=300.0, direction_id=d.id)
    s.commit(); s.close()

    async def drain():
        resp = await intel_api.intel_stream_live(after_id=0, after_alert_id=0,
                                                 direction=None, authorization="Bearer x")
        chunks = []
        try:
            async for c in resp.body_iterator:
                chunks.append(c)
        except asyncio.CancelledError:
            pass
        return "".join(chunks)

    out = asyncio.get_event_loop().run_until_complete(drain())
    assert "event: alert" in out
    assert "Всплеск" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_alerts_sse.py -v`
Expected: FAIL — `intel_stream_live() got an unexpected keyword argument 'after_alert_id'`.

- [ ] **Step 3: Add the alert tail to `event_gen`**

In `backend/radar/intel/api.py`, modify `intel_stream_live`:

1. Add the query param to the signature (after `after_id: int = 0`):

```python
    after_alert_id: int = 0,
```

2. Inside `event_gen`, initialize the alert cursor next to `last_id` (mirror the "newest id" bootstrap):

```python
        last_alert_id = after_alert_id
        if last_alert_id <= 0:
            s = get_session()
            try:
                last_alert_id = s.query(func.max(IntelAlert.id)).scalar() or 0
            finally:
                s.close()
```

3. Inside the `while True:` loop, after the block that yields mention frames and before the `: ping` heartbeat, add the alert tail:

```python
            s = get_session()
            try:
                arows = (s.query(IntelAlert).filter(IntelAlert.id > last_alert_id)
                         .order_by(IntelAlert.id.asc()).limit(50).all())
                apayloads = [(a.id, json.dumps(aggregate.alert_payload(s, a), ensure_ascii=False))
                             for a in arows]
            finally:
                s.close()
            for aid, payload in apayloads:
                last_alert_id = aid
                yield f"event: alert\ndata: {payload}\n\n"
```

4. Ensure `IntelAlert` is imported in `api.py` (added in Task 6).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_alerts_sse.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full intel test suite (regression check)**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py tests/test_intel_alerts_sse.py tests/test_anomalies.py tests/test_intel_realtime.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/radar/intel/api.py backend/tests/test_intel_alerts_sse.py
git commit -m "feat(intel): push alerts over the live SSE stream as a named event"
```

---

## Task 8: Overview reads alerts from `IntelAlert`

**Files:**
- Modify: `backend/radar/intel/aggregate.py`
- Test: `backend/tests/test_intel_alerts.py`

**Interfaces:**
- Consumes: `IntelAlert`, `alert_payload` (Task 6).
- Produces: `compute_overview(session, window_h)["alerts"]` is sourced from unacknowledged `IntelAlert` rows (newest first, ≤20), each via `alert_payload`. KPIs/hot/top_stories unchanged.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_intel_alerts.py`:

```python
def test_compute_overview_alerts_come_from_intel_alert_table():
    from radar.intel import aggregate, alerts
    s = _mem()
    d = _direction(s)
    alerts._emit(s, "direction", "direction_burst", title="Курское",
                 message="Всплеск ×4", magnitude=300.0, direction_id=d.id)
    s.commit()
    ov = aggregate.compute_overview(s, 24)
    assert len(ov["alerts"]) == 1
    assert ov["alerts"][0]["message"] == "Всплеск ×4"
    assert ov["alerts"][0]["direction"] == "kursk"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k compute_overview -v`
Expected: FAIL — current overview builds `alerts` from `is_anomaly` stories, so a direction alert with no anomalous story yields `[]`.

- [ ] **Step 3: Replace the alerts block in `compute_overview`**

In `backend/radar/intel/aggregate.py::compute_overview`, replace the `alerts = [...]` list comprehension (the one iterating `stories` with `st.is_anomaly`) with a read from `IntelAlert`:

```python
    alert_rows = (session.query(IntelAlert)
                  .filter(IntelAlert.acknowledged_at.is_(None))
                  .order_by(IntelAlert.id.desc()).limit(20).all())
    alerts = [alert_payload(session, a) for a in alert_rows]
```

Leave the `return {...}` dict and all other computed values (`kpis`, `hot`, `top_stories`, `spiking_dirs`) unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_alerts.py -k compute_overview -v`
Expected: PASS.

- [ ] **Step 5: Run the intel API test suite (regression check)**

Run: `cd backend && python -m pytest tests/test_intel_aggregate.py tests/test_intel_api.py tests/test_intel_alerts.py -v`
Expected: PASS (if an existing overview test asserts the old anomaly-sourced shape, update it to seed an `IntelAlert` and assert the new source — note it in the commit).

- [ ] **Step 6: Commit**

```bash
git add backend/radar/intel/aggregate.py backend/tests/test_intel_alerts.py
git commit -m "feat(intel): overview alerts read from IntelAlert (single source of truth)"
```

---

## Task 9: Frontend — alert API methods + SSE parser supports named events

**Files:**
- Modify: `echo-app/src/features/intel/api.js`

**Interfaces:**
- Consumes: `request`, `getToken` (already imported); existing `streamLiveEvents`.
- Produces:
  - `intelApi.alerts({ unread, limit })`, `intelApi.ackAlert(id)`, `intelApi.ackAllAlerts()`.
  - `streamLiveEvents({ afterId, afterAlertId, direction, onEvent, onAlert })` — parser tracks each frame's `event:` line and routes `data:` to `onAlert` for `event: alert`, else `onEvent`; threads `after_alert_id` into the request and tracks `lastAlertId`.

- [ ] **Step 1: Add alert methods to `intelApi`**

In `echo-app/src/features/intel/api.js`, add to the `intelApi` object (after `deleteSource`):

```javascript
  alerts:    (params)         => INTEL_USE_MOCK ? Promise.resolve([]) : passthrough('alerts', params),
  ackAlert:  (id)             => request(`/intel/alerts/${id}/ack`, { method: 'POST' }),
  ackAllAlerts: ()            => request('/intel/alerts/ack-all', { method: 'POST' }),
```

- [ ] **Step 2: Extend `streamLiveEvents` signature + request params**

Change the signature and add an alert cursor + callback:

```javascript
export function streamLiveEvents({ afterId = 0, afterAlertId = 0, direction, onEvent, onAlert }) {
  if (INTEL_USE_MOCK) return () => {};
  let stopped = false;
  let lastId = afterId || 0;
  let lastAlertId = afterAlertId || 0;
  let currentCtrl = null;
```

In the block that builds `params` for the fetch, add the alert cursor:

```javascript
        const params = { after_id: String(lastId), after_alert_id: String(lastAlertId) };
        if (direction) params.direction = direction;
```

- [ ] **Step 3: Make the frame parser event-type aware**

Replace the inner frame loop (currently: `for (const line of frame.split('\n')) { if (!line.startsWith('data:')) continue; ... onEvent(ev) }`) with a version that reads the `event:` line first:

```javascript
          while ((sep = buf.indexOf('\n\n')) >= 0) {
            const frame = buf.slice(0, sep);
            buf = buf.slice(sep + 2);
            let eventType = 'message';
            let dataRaw = '';
            for (const line of frame.split('\n')) {
              if (line.startsWith('event:')) eventType = line.slice(6).trim();
              else if (line.startsWith('data:')) dataRaw += line.slice(5).trim();
              // ": ping" heartbeats and blank lines fall through (ignored)
            }
            if (!dataRaw) continue;
            try {
              const ev = JSON.parse(dataRaw);
              if (eventType === 'alert') {
                if (ev && ev.id) lastAlertId = Math.max(lastAlertId, ev.id);
                if (onAlert) onAlert(ev);
              } else {
                if (ev && ev.id) lastId = Math.max(lastId, ev.id);
                if (onEvent) onEvent(ev);
              }
            } catch { /* ignore malformed frame */ }
          }
```

- [ ] **Step 4: Verify build (no test runner)**

Run: `cd echo-app && npm run build`
Expected: build succeeds (no syntax errors). The behavioral check happens in Task 10.

- [ ] **Step 5: Commit**

```bash
git add echo-app/src/features/intel/api.js
git commit -m "feat(intel-ui): alert API + SSE parser handles named alert events"
```

---

## Task 10: Frontend — lift the live stream to `IntelApp`, own alert state

**Files:**
- Modify: `echo-app/src/features/intel/IntelApp.jsx`, `echo-app/src/features/intel/components/IntelHome.jsx`

**Interfaces:**
- Consumes: `streamLiveEvents`, `intelApi.alerts/ackAlert/ackAllAlerts` (Task 9); `AlertBell` (Task 11), `AlertToast` (Task 12) — imported but rendered here.
- Produces: `IntelApp` owns one `streamLiveEvents` connection (mentions + alerts), holds `liveEvents` (capped array, newest last) and `alerts`/`unreadCount` state, passes `liveEvents` to `IntelHome` via the `liveEvents` prop. `IntelHome` consumes `liveEvents` instead of opening its own stream.

- [ ] **Step 1: Add stream + alert state to `IntelApp`**

In `echo-app/src/features/intel/IntelApp.jsx`, change the `useState`-only import to include effects/refs and import the API + new components:

```javascript
import { useState, useEffect, useRef, useCallback } from 'react';
import { intelApi, streamLiveEvents } from './api';
import { AlertBell } from './components/AlertBell';
import { AlertToast } from './components/AlertToast';
```

Inside `IntelApp`, add state and the stream effect (after the existing `useState` calls):

```javascript
  const [liveEvents, setLiveEvents] = useState([]);
  const [alerts, setAlerts]         = useState([]);
  const [toasts, setToasts]         = useState([]);
  const seenAlert = useRef(new Set());

  useEffect(() => {
    let alive = true;
    // Initial unread alerts so the bell has history before the first live push.
    intelApi.alerts({ unread: true, limit: 50 }).then(rows => {
      if (!alive || !Array.isArray(rows)) return;
      rows.forEach(a => seenAlert.current.add(a.id));
      setAlerts(rows);
    }).catch(() => {});

    const stop = streamLiveEvents({
      onEvent: (e) => {
        if (!alive || !e || e.id == null) return;
        setLiveEvents(prev => [...prev, e].slice(-200));  // cap memory
      },
      onAlert: (a) => {
        if (!alive || !a || a.id == null || seenAlert.current.has(a.id)) return;
        seenAlert.current.add(a.id);
        setAlerts(prev => [a, ...prev]);
        setToasts(prev => [...prev, a]);
      },
    });
    return () => { alive = false; stop(); };
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const ackAlert = useCallback(async (id) => {
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, acknowledged: true } : a));
    try { await intelApi.ackAlert(id); } catch { /* optimistic */ }
  }, []);

  const ackAll = useCallback(async () => {
    setAlerts(prev => prev.map(a => ({ ...a, acknowledged: true })));
    try { await intelApi.ackAllAlerts(); } catch { /* optimistic */ }
  }, []);

  const unreadCount = alerts.filter(a => !a.acknowledged).length;
```

- [ ] **Step 2: Render the bell in the topbar + toast stack**

In the `<header className={styles.topbar}>`, after `<div className={styles.topgrow} />` and before the window selector, add:

```jsx
          <AlertBell alerts={alerts} unreadCount={unreadCount} onAck={ackAlert} onAckAll={ackAll}
                     onOpen={(a) => setScreen(a.scope === 'story' ? 'stories' : 'board')} />
```

At the end of the `<div className={styles.main}>` block (after the screen switch), add the toast stack:

```jsx
        <AlertToast toasts={toasts} onDismiss={dismissToast}
                    onOpen={(a) => { setScreen(a.scope === 'story' ? 'stories' : 'board'); dismissToast(a.id); }} />
```

Pass live events to `IntelHome`:

```jsx
          <IntelHome window={window} liveEvents={liveEvents} onOpenStory={() => setScreen('stories')} />
```

- [ ] **Step 3: Make `IntelHome` consume `liveEvents` instead of its own stream**

In `echo-app/src/features/intel/components/IntelHome.jsx`:

1. Accept the prop: `export function IntelHome({ window, liveEvents = [], onOpenStory }) {`
2. Remove the `streamLiveEvents` import from `'../api'` and delete the `streamLiveEvents({...})` call inside the effect (keep the `intelApi.overview` + `intelApi.stream` snapshot fetch and the `kpiTimer` poll).
3. Merge `liveEvents` into the displayed feed. Where it currently maintained `stream` state from the live callback, instead derive the feed from the snapshot + the `liveEvents` prop, deduped by id. Replace the stream-append effect with:

```javascript
  useEffect(() => {
    if (!liveEvents.length) return;
    setStream(prev => {
      const seen = new Set(prev.map(e => e.id));
      const add = liveEvents.filter(e => e && e.id != null && !seen.has(e.id));
      return add.length ? [...prev, ...add].slice(-200) : prev;
    });
  }, [liveEvents]);
```

(The existing `seenRef`-based dedup against the snapshot can be simplified to the id-set check above; keep the snapshot fetch that seeds `stream` initially.)

- [ ] **Step 4: Verify manually**

Run the app and confirm the live feed still updates and no console errors:

Run: `cd echo-app && npm run dev` (and ensure the backend is running per the project's run setup)
Expected: IntelHome feed still streams new mentions (regression check — the lifted stream feeds it via props). Bell renders in the topbar (empty until Task 11). Use the `verify` skill to drive this.

- [ ] **Step 5: Commit**

```bash
git add echo-app/src/features/intel/IntelApp.jsx echo-app/src/features/intel/components/IntelHome.jsx
git commit -m "feat(intel-ui): single live stream in IntelApp, feed events via props"
```

---

## Task 11: Frontend — `AlertBell`

**Files:**
- Create: `echo-app/src/features/intel/components/AlertBell.jsx`
- Modify: `echo-app/src/features/intel/intel.module.css`

**Interfaces:**
- Consumes props: `alerts: Alert[]`, `unreadCount: number`, `onAck(id)`, `onAckAll()`, `onOpen(alert)`. `Alert` shape from `alert_payload`: `{ id, scope, story_id, direction, kind, magnitude, title, message, at, acknowledged }`.
- Produces: a header bell button with an unread badge and a dropdown list. Uses the existing `Icon` component and `agoStrShort` from `../api`.

- [ ] **Step 1: Create the component**

Create `echo-app/src/features/intel/components/AlertBell.jsx`:

```jsx
// Header notification bell: unread badge + dropdown of recent alerts.
import { useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { agoStrShort } from '../api';
import styles from '../intel.module.css';

export function AlertBell({ alerts = [], unreadCount = 0, onAck, onAckAll, onOpen }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={styles.bellWrap}>
      <button className={styles.bellBtn} onClick={() => setOpen(o => !o)} title="Сигналы">
        <Icon name="radio" size={15} />
        {unreadCount > 0 && <span className={styles.bellBadge}>{unreadCount > 99 ? '99+' : unreadCount}</span>}
      </button>
      {open && (
        <div className={styles.bellMenu}>
          <div className={styles.bellHead}>
            <span>Сигналы</span>
            {unreadCount > 0 && (
              <button className={styles.bellAckAll} onClick={() => onAckAll && onAckAll()}>
                Прочитать все
              </button>
            )}
          </div>
          {alerts.length === 0 ? (
            <div className={styles.bellEmpty}>Нет сигналов</div>
          ) : (
            alerts.slice(0, 30).map(a => (
              <button key={a.id} className={styles.bellItem} data-unread={a.acknowledged ? '0' : '1'}
                      onClick={() => { onAck && onAck(a.id); onOpen && onOpen(a); setOpen(false); }}>
                <span className={styles.bellItemMsg}>{a.message || a.title}</span>
                <span className={styles.bellItemMeta}>{agoStrShort(a.at)}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add styles**

Append to `echo-app/src/features/intel/intel.module.css` (match the existing dark "военный диспетчер" palette — neutrals already used in this file; the accent `#FF4D5E` is the existing КРИТ color):

```css
.bellWrap { position: relative; }
.bellBtn { position: relative; display: flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: 8px; background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08); color: #9FB3C8; cursor: pointer; }
.bellBtn:hover { background: rgba(255,255,255,0.08); }
.bellBadge { position: absolute; top: -4px; right: -4px; min-width: 16px; height: 16px;
  padding: 0 4px; border-radius: 8px; background: #FF4D5E; color: #fff;
  font-size: 10px; line-height: 16px; text-align: center; font-weight: 700; }
.bellMenu { position: absolute; top: 40px; right: 0; width: 320px; max-height: 60vh; overflow-y: auto;
  background: #0E1622; border: 1px solid rgba(255,255,255,0.10); border-radius: 10px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.5); z-index: 50; }
.bellHead { display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.08);
  font-size: 12px; color: #C7D6E5; font-weight: 600; }
.bellAckAll { background: none; border: none; color: #57D2E2; font-size: 11px; cursor: pointer; }
.bellEmpty { padding: 18px 12px; color: #7E91A6; font-size: 12px; text-align: center; }
.bellItem { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left;
  padding: 9px 12px; background: none; border: none; border-bottom: 1px solid rgba(255,255,255,0.05);
  cursor: pointer; }
.bellItem:hover { background: rgba(255,255,255,0.05); }
.bellItem[data-unread="1"] { border-left: 2px solid #FF4D5E; }
.bellItemMsg { font-size: 12px; color: #DCE7F2; }
.bellItemMeta { font-size: 10px; color: #7E91A6; }
```

- [ ] **Step 3: Verify manually**

Run: `cd echo-app && npm run dev`
Expected: bell shows in the topbar; with seeded/real alerts the badge shows the unread count; clicking opens the dropdown; "Прочитать все" clears the badge; clicking an item navigates (stories/board) and marks it read. Use the `verify` skill.

- [ ] **Step 4: Commit**

```bash
git add echo-app/src/features/intel/components/AlertBell.jsx echo-app/src/features/intel/intel.module.css
git commit -m "feat(intel-ui): alert notification bell"
```

---

## Task 12: Frontend — `AlertToast`

**Files:**
- Create: `echo-app/src/features/intel/components/AlertToast.jsx`
- Modify: `echo-app/src/features/intel/intel.module.css`

**Interfaces:**
- Consumes props: `toasts: Alert[]`, `onDismiss(id)`, `onOpen(alert)`.
- Produces: a fixed corner stack; each toast auto-dismisses after 8s.

- [ ] **Step 1: Create the component**

Create `echo-app/src/features/intel/components/AlertToast.jsx`:

```jsx
// Corner toast stack for incoming alerts. Auto-dismisses each after 8s.
import { useEffect } from 'react';
import { Icon } from '../../../core/components/icons';
import styles from '../intel.module.css';

function Toast({ alert, onDismiss, onOpen }) {
  useEffect(() => {
    const t = setTimeout(() => onDismiss(alert.id), 8000);
    return () => clearTimeout(t);
  }, [alert.id, onDismiss]);
  return (
    <div className={styles.toast} onClick={() => onOpen(alert)}>
      <Icon name="radio" size={14} />
      <div className={styles.toastBody}>
        <div className={styles.toastTitle}>{alert.title || 'Сигнал'}</div>
        <div className={styles.toastMsg}>{alert.message}</div>
      </div>
      <button className={styles.toastClose} onClick={(e) => { e.stopPropagation(); onDismiss(alert.id); }}>
        <Icon name="x" size={12} />
      </button>
    </div>
  );
}

export function AlertToast({ toasts = [], onDismiss, onOpen }) {
  if (!toasts.length) return null;
  return (
    <div className={styles.toastStack}>
      {toasts.slice(-4).map(t => (
        <Toast key={t.id} alert={t} onDismiss={onDismiss} onOpen={onOpen} />
      ))}
    </div>
  );
}
```

> Note: if the `x` icon name does not exist in `core/components/icons`, use an existing close-like icon (check the `Icon` set) or a literal `×` span. Verify the available names before implementing.

- [ ] **Step 2: Add styles**

Append to `echo-app/src/features/intel/intel.module.css`:

```css
.toastStack { position: fixed; right: 18px; bottom: 18px; display: flex; flex-direction: column;
  gap: 8px; z-index: 60; }
.toast { display: flex; align-items: flex-start; gap: 8px; width: 320px; padding: 10px 12px;
  background: #14202E; border: 1px solid rgba(255,77,94,0.45); border-left: 3px solid #FF4D5E;
  border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); color: #DCE7F2; cursor: pointer;
  animation: toastIn 160ms ease-out; }
.toastBody { flex: 1; min-width: 0; }
.toastTitle { font-size: 12px; font-weight: 700; color: #FF8A95; }
.toastMsg { font-size: 12px; color: #C7D6E5; overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.toastClose { background: none; border: none; color: #7E91A6; cursor: pointer; padding: 0; }
@keyframes toastIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
```

- [ ] **Step 3: Verify manually (end-to-end)**

Run: `cd echo-app && npm run dev` with the backend running.
Expected: when a new `IntelAlert` is created (e.g. seed one in the DB, or lower `ANOMALY_VOLUME_FACTOR`/`ALERT_COOLDOWN_H` and let the ticker fire), a toast slides in at the bottom-right within ~1-2s, auto-dismisses after 8s, click navigates to the story/direction. The bell badge increments in lockstep. Use the `verify` skill to confirm.

- [ ] **Step 4: Commit**

```bash
git add echo-app/src/features/intel/components/AlertToast.jsx echo-app/src/features/intel/intel.module.css
git commit -m "feat(intel-ui): live alert toast stack"
```

---

## Task 13: Full regression + manual end-to-end

**Files:** none (verification only).

- [ ] **Step 1: Backend suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: all pass. Fix any regression introduced by the overview alert-source change (Task 8).

- [ ] **Step 2: Frontend build**

Run: `cd echo-app && npm run build`
Expected: clean build.

- [ ] **Step 3: Manual end-to-end via the `verify` skill**

Drive the running app: seed/trigger an alert, confirm (a) toast appears, (b) bell badge increments, (c) acknowledging clears unread in bell + IntelHome alerts block, (d) the live mention feed still updates (no regression from the lifted stream).

- [ ] **Step 4: Final commit (if any fixes were needed)**

```bash
git add -A
git commit -m "test(intel): alerts regression pass + fixes"
```

---

## Self-Review

**Spec coverage:**
- §3 model → Task 1. §4 detection (story + direction + cooldown) → Tasks 2,3,4. §4 tick wiring → Task 5. §5 SSE named-event delivery → Task 7 (backend) + Task 9 (frontend parser). §6 REST (list/ack/ack-all) + overview single-source → Tasks 6,8. §7 frontend (stream lift, toast, bell, mount load) → Tasks 9,10,11,12. §8 testing → tests in Tasks 1-8 + Task 13. §9 risks (latency/cooldown/overview shape) addressed by env knob + preserved payload shape.
- Gap check: spec says alerts carry a `magnitude` float used for ordering/text — present in model (Task 1), serializer (Task 6), and messages (Tasks 3,4). No uncovered requirement found.

**Placeholder scan:** No "TBD/TODO/handle edge cases" steps. The one conditional note (Task 12 `x` icon) instructs a concrete verify-and-substitute action, not a deferral.

**Type consistency:** `IntelAlert` columns (Task 1) match usage in `_emit` (Task 2), `_classify_story`/`scan_story_alerts` (Task 3), burst scan (Task 4), `alert_payload` (Task 6), SSE tail (Task 7), overview (Task 8). Frontend `Alert` shape (`{id, scope, story_id, direction, kind, magnitude, title, message, at, acknowledged}`) is produced by `alert_payload` and consumed identically in `AlertBell`/`AlertToast`/`IntelApp`. `streamLiveEvents` named params (`afterId, afterAlertId, onEvent, onAlert`) are consistent between definition (Task 9) and call site (Task 10). The tick entrypoint `alerts.scan` is defined in Task 4 and called in Task 5.
