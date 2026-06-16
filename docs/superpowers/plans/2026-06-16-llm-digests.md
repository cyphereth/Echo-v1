# LLM Digests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a daily LLM digest of a brand's top stories (Claude Haiku via the existing proxy) and surface it on a new "Дайджесты" screen in echo-app.

**Architecture:** A thin `llm.complete()` helper mirrors the existing `drafts.py` call pattern (httpx → `LLM_API_URL`, Anthropic wire format, `LLM_API_KEY`). `digests.build_daily_digest()` selects top stories, builds a compact aggregate, calls the LLM once, and stores a `Report`. Two brand-scoped endpoints (generate + list) feed a React screen. No new key, no new dependency, no scheduler (manual-only this iteration). Degrades to a clean 503 without `LLM_API_KEY`.

**Tech Stack:** Python 3.x, FastAPI, SQLAlchemy, SQLite, `httpx` (already a dep); React (echo-app). Use `python3` for commands.

Spec: `docs/superpowers/specs/2026-06-16-llm-digests-design.md`

---

## File Structure

**Backend (create):** `backend/radar/llm.py`, `backend/radar/digests.py`, `backend/tests/test_llm.py`, `backend/tests/test_digests.py`, `backend/tests/test_digests_api.py`
**Backend (modify):** `backend/radar/models.py` (add `Report`), `backend/radar/api.py` (2 routes + schema)
**Frontend (modify, echo-app):** `src/services/api.js`, `src/components/app/Shell.jsx`, `src/pages/AppPage.jsx`; **create** `src/components/app/Digests.jsx`, `src/components/app/digests.module.css`

---

### Task 1: `llm.complete()` helper

**Files:** Create `backend/radar/llm.py`; create `backend/tests/test_llm.py`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_llm.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest


def test_complete_raises_without_key(monkeypatch):
    import radar.llm as L
    monkeypatch.setattr(L, "LLM_API_KEY", "")
    with pytest.raises(L.LLMNotConfigured):
        L.complete("sys", "user")


def test_complete_parses_text_block(monkeypatch):
    import radar.llm as L
    monkeypatch.setattr(L, "LLM_API_KEY", "sk-test")

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"content": [{"type": "text", "text": "  hello  "}]}

    captured = {}
    def _post(url, headers, json, timeout):
        captured["url"] = url; captured["json"] = json; captured["headers"] = headers
        return _Resp()
    monkeypatch.setattr(L.httpx, "post", _post)

    out = L.complete("SYS", "USER", max_tokens=99)
    assert out == "hello"
    assert captured["json"]["system"] == "SYS"
    assert captured["json"]["messages"] == [{"role": "user", "content": "USER"}]
    assert captured["json"]["max_tokens"] == 99
    assert captured["headers"]["x-api-key"] == "sk-test"
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: radar.llm`)

Run: `cd backend && python3 -m pytest tests/test_llm.py -v`

- [ ] **Step 3: Implement `backend/radar/llm.py`**

```python
from __future__ import annotations
import os
import httpx

# Reuse the existing proxy integration (same as drafts.py).
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")
MODEL_DIGEST = os.getenv("LLM_MODEL_DIGEST", "claude-haiku-4-5-20251001")


class LLMNotConfigured(RuntimeError):
    """Raised when LLM_API_KEY is absent — callers should degrade gracefully."""


def complete(system: str, user: str, max_tokens: int = 1024,
             model: str | None = None) -> str:
    """One completion via the Anthropic-format proxy at LLM_API_URL.

    Mirrors drafts.py: x-api-key + anthropic-version headers, {model, max_tokens,
    system, messages} payload. Returns the first text block, stripped.
    """
    if not LLM_API_KEY:
        raise LLMNotConfigured("LLM_API_KEY not configured")
    resp = httpx.post(
        LLM_API_URL,
        headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model or MODEL_DIGEST, "max_tokens": max_tokens,
              "system": system, "messages": [{"role": "user", "content": user}]},
        timeout=120,
    )
    resp.raise_for_status()
    blocks = resp.json().get("content", [])
    return next((b["text"] for b in blocks if b.get("type") == "text"), "").strip()
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd backend && python3 -m pytest tests/test_llm.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/radar/llm.py backend/tests/test_llm.py
git commit -m "feat: llm.complete() helper reusing the existing LLM proxy"
```

---

### Task 2: `Report` model

**Files:** Modify `backend/radar/models.py`; append a test to `backend/tests/test_digests.py`.

`models.py` uses `Integer, Text, ForeignKey, Mapped, mapped_column, Optional, _now, datetime` (all already imported). New table → `Base.metadata.create_all` builds it; no `_MIGRATIONS` entry needed.

- [ ] **Step 1: Write the failing test** (creates the shared test file)

```python
# backend/tests/test_digests.py
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


def test_report_model_persists():
    from radar.models import Report
    s = _mem()
    r = Report(brand_id=1, kind="digest", body="hello")
    s.add(r); s.commit()
    got = s.query(Report).one()
    assert got.kind == "digest" and got.body == "hello" and got.story_id is None
    assert got.created_at is not None
```

- [ ] **Step 2: Run — expect FAIL** (`ImportError: cannot import name 'Report'`)

Run: `cd backend && python3 -m pytest tests/test_digests.py::test_report_model_persists -v`

- [ ] **Step 3: Add `Report` to `backend/radar/models.py`** (after the `StoryPoint` class)

```python
class Report(Base):
    __tablename__ = "reports"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:   Mapped[int]           = mapped_column(ForeignKey("brands.id"))
    story_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("stories.id"))
    kind:       Mapped[str]           = mapped_column(Text, default="digest")  # digest | story | alert
    body:       Mapped[str]           = mapped_column(Text, default="")
    created_at: Mapped[datetime]      = mapped_column(default=_now)
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd backend && python3 -m pytest tests/test_digests.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/radar/models.py backend/tests/test_digests.py
git commit -m "feat: Report model for stored digests"
```

---

### Task 3: `digests.build_daily_digest()`

**Files:** Create `backend/radar/digests.py`; append a test to `backend/tests/test_digests.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_digests.py
def _mk_story(s, title, post_count, anomaly=False, sent=0.0):
    from radar.models import Story, StoryPoint
    base = datetime(2026, 6, 16, 9, 0, tzinfo=timezone.utc)
    st = Story(brand_id=1, title=title, status="active", is_anomaly=anomaly,
               post_count=post_count, first_seen_at=base, last_seen_at=base)
    s.add(st); s.flush()
    s.add(StoryPoint(story_id=st.id, bucket_start=base, mention_count=post_count,
                     avg_sentiment=sent, source_count=2))
    s.flush()
    return st


def test_build_daily_digest_creates_report(monkeypatch):
    import radar.digests as D
    from radar.models import Report
    s = _mem()
    _mk_story(s, "кризис", 10, anomaly=True, sent=-0.6)
    _mk_story(s, "акция", 4, sent=0.3)
    s.commit()
    seen = {}
    def _fake_complete(system, user, max_tokens=1024, model=None):
        seen["user"] = user
        return "СВОДКА: всё под контролем."
    monkeypatch.setattr(D.llm, "complete", _fake_complete)

    report = D.build_daily_digest(s, brand_id=1)
    assert report is not None
    assert report.kind == "digest"
    assert report.body == "СВОДКА: всё под контролем."
    assert s.query(Report).count() == 1
    # the aggregate handed to the LLM mentions both stories + flags the anomaly
    assert "кризис" in seen["user"] and "акция" in seen["user"]
    assert "АНОМАЛИЯ" in seen["user"]


def test_build_daily_digest_none_when_no_stories(monkeypatch):
    import radar.digests as D
    s = _mem()
    monkeypatch.setattr(D.llm, "complete", lambda *a, **k: "x")
    assert D.build_daily_digest(s, brand_id=1) is None
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: radar.digests`)

Run: `cd backend && python3 -m pytest tests/test_digests.py -v`

- [ ] **Step 3: Implement `backend/radar/digests.py`**

```python
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import llm
from .models import Story, StoryPoint, Report

TOP_N  = int(os.getenv("DIGEST_TOP_N", "5"))
WINDOW = timedelta(hours=int(os.getenv("DIGEST_WINDOW_H", "24")))

_SYSTEM = (
    "Ты — аналитик медиамониторинга бренда. По переданным агрегатам составь краткую "
    "утреннюю сводку на русском языке. Для каждого сюжета: тема → динамика → "
    "ключевые источники → риски → рекомендованное действие. Пиши по делу, без воды."
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _top_stories(session: Session, brand_id: int) -> list[Story]:
    since = datetime.now(timezone.utc) - WINDOW
    return (session.query(Story)
            .filter(Story.brand_id == brand_id, Story.status == "active",
                    Story.last_seen_at >= since)
            .order_by(Story.is_anomaly.desc(), Story.post_count.desc())
            .limit(TOP_N).all())


def _aggregate(session: Session, stories: list[Story]) -> str:
    lines = []
    for st in stories:
        pts = (session.query(StoryPoint)
               .filter(StoryPoint.story_id == st.id)
               .order_by(StoryPoint.bucket_start).all())
        sents = [p.avg_sentiment for p in pts if p.avg_sentiment is not None]
        avg = sum(sents) / len(sents) if sents else 0.0
        flag = " [АНОМАЛИЯ]" if st.is_anomaly else ""
        lines.append(
            f"- Сюжет «{st.title}»{flag}: {st.post_count} упоминаний, "
            f"средняя тональность {avg:.2f}, точек динамики {len(pts)}."
        )
    return "Топ-сюжеты за период:\n" + "\n".join(lines)


def build_daily_digest(session: Session, brand_id: int) -> Report | None:
    """Generate and store a digest Report for the brand's top stories.

    Returns the Report, or None if there are no active stories in the window.
    Raises llm.LLMNotConfigured if no key (caller maps to 503).
    """
    stories = _top_stories(session, brand_id)
    if not stories:
        return None
    body = llm.complete(_SYSTEM, _aggregate(session, stories), max_tokens=1024)
    report = Report(brand_id=brand_id, kind="digest", body=body)
    session.add(report)
    session.flush()
    return report
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd backend && python3 -m pytest tests/test_digests.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/radar/digests.py backend/tests/test_digests.py
git commit -m "feat: build_daily_digest over top stories"
```

---

### Task 4: `/brands/{id}/digest` endpoints

**Files:** Modify `backend/radar/api.py`; create `backend/tests/test_digests_api.py`.

> Mirror the established patterns: `current_user`, `db`, `_owned_brand`, `HTTPException(code, "msg")`. Extend the existing models import to include `Report`. `/brands` is already proxied on the frontend.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_digests_api.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def test_generate_and_list_digests(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'d.db'}")
    import importlib
    import radar.db as db; importlib.reload(db); db.init_db()
    import radar.digests as D; importlib.reload(D)
    import radar.api as api; importlib.reload(api)
    from fastapi.testclient import TestClient
    from radar.models import Story, StoryPoint, Brand, User

    # one active story so the digest has material
    s = db.get_session()
    u = User(email="d@d.d", password_hash="x"); s.add(u); s.flush()
    b = Brand(id=1, user_id=u.id, name="b"); s.add(b); s.flush()
    now = datetime.now(timezone.utc)
    st = Story(brand_id=1, title="t", status="active", post_count=5,
               first_seen_at=now, last_seen_at=now)
    s.add(st); s.flush()
    s.add(StoryPoint(story_id=st.id, bucket_start=now, mention_count=5,
                     avg_sentiment=-0.2, source_count=2))
    s.commit()

    # stub the LLM call (no network)
    monkeypatch.setattr(api, "build_daily_digest", None, raising=False)
    import radar.digests as D2
    monkeypatch.setattr(D2.llm, "complete", lambda *a, **k: "ГОТОВО")

    api.app.dependency_overrides[api.current_user] = lambda: u
    client = TestClient(api.app)

    r = client.post("/brands/1/digest")
    assert r.status_code == 200, r.text
    assert r.json()["body"] == "ГОТОВО"

    r2 = client.get("/brands/1/digests")
    assert r2.status_code == 200
    assert len(r2.json()) == 1 and r2.json()[0]["kind"] == "digest"
    api.app.dependency_overrides.clear()
```

> If `api.py` imports `build_daily_digest` at module top, the `monkeypatch.setattr(api, "build_daily_digest", None, ...)` line is unnecessary — remove it and rely on stubbing `radar.digests.llm.complete`. Keep whichever matches your import style; the LLM stub is the load-bearing part.

- [ ] **Step 2: Run — expect FAIL** (404 — routes absent)

Run: `cd backend && python3 -m pytest tests/test_digests_api.py -v`

- [ ] **Step 3: Add schema + routes to `backend/radar/api.py`**

Add `Report` to the existing `from .models import ...` line. Add the schema near the other Pydantic models:

```python
class ReportOut(BaseModel):
    id: int
    kind: str
    body: str
    created_at: datetime
    story_id: int | None = None
```

Add the routes near the other `@app` routes:

```python
@app.post("/brands/{brand_id}/digest", response_model=ReportOut)
def create_digest(brand_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_brand(session, brand_id, user)
    from .digests import build_daily_digest
    from .llm import LLMNotConfigured
    try:
        report = build_daily_digest(session, brand_id)
    except LLMNotConfigured:
        raise HTTPException(503, "Digest generation unavailable — set LLM_API_KEY in backend/.env")
    if report is None:
        raise HTTPException(404, "No active stories to summarize")
    session.commit()
    return ReportOut(id=report.id, kind=report.kind, body=report.body,
                     created_at=report.created_at, story_id=report.story_id)


@app.get("/brands/{brand_id}/digests", response_model=list[ReportOut])
def list_digests(brand_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_brand(session, brand_id, user)
    rows = (session.query(Report)
            .filter(Report.brand_id == brand_id, Report.kind == "digest")
            .order_by(Report.created_at.desc()).limit(50).all())
    return [ReportOut(id=r.id, kind=r.kind, body=r.body,
                      created_at=r.created_at, story_id=r.story_id) for r in rows]
```

- [ ] **Step 4: Run — expect PASS, then full suite**

Run: `cd backend && python3 -m pytest tests/test_digests_api.py -v && python3 -m pytest -q`
Expected: digest test passes; full suite green (if a pre-existing `mentions.incident_id` failure appears, the on-disk dev DB needs `python3 -c "import radar.db as db; db.init_db()"` once — that's the known test-isolation quirk, not a regression here).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/api.py backend/tests/test_digests_api.py
git commit -m "feat: /brands/{id}/digest generate + list endpoints"
```

---

### Task 5: "Дайджесты" screen (frontend)

**Files:** Modify `echo-app/src/services/api.js`, `Shell.jsx`, `AppPage.jsx`; create `Digests.jsx` + `digests.module.css`. Build-verified (`npm run build`). `/brands` is already proxied — no vite change.

- [ ] **Step 1: Add API functions** to `echo-app/src/services/api.js` (match the `request`-wrapper style):

```js
export const getDigests   = (brandId) => request(`/brands/${brandId}/digests`);
export const createDigest = (brandId) => request(`/brands/${brandId}/digest`, { method: 'POST' });
```

- [ ] **Step 2: Create `echo-app/src/components/app/Digests.jsx`**

```jsx
import { useEffect, useState } from 'react';
import * as api from '../../services/api';
import styles from './digests.module.css';

export function DigestsScreen({ brand }) {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () => {
    if (!brand?.id) return;
    api.getDigests(brand.id).then(setItems).catch(() => setItems([]));
  };
  useEffect(load, [brand?.id]);

  const generate = async () => {
    if (!brand?.id) return;
    setBusy(true); setError(null);
    try {
      await api.createDigest(brand.id);
      load();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.bar}>
        <button className={styles.btn} onClick={generate} disabled={busy}>
          {busy ? 'Генерация…' : 'Сгенерировать дайджест'}
        </button>
        {error && <span className={styles.err}>{error}</span>}
      </div>
      {items.length === 0 && <div className={styles.empty}>Пока нет дайджестов</div>}
      <ul className={styles.list}>
        {items.map((r) => (
          <li key={r.id} className={styles.item}>
            <div className={styles.meta}>{new Date(r.created_at).toLocaleString()}</div>
            <div className={styles.body}>{r.body}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: Create `echo-app/src/components/app/digests.module.css`**

```css
.wrap { height: 100%; overflow-y: auto; }
.bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.btn { padding: 8px 14px; border: 1px solid #6366f1; border-radius: 8px;
  background: #6366f1; color: #fff; cursor: pointer; font-size: 14px; }
.btn:disabled { opacity: 0.6; cursor: default; }
.err { color: #ef4444; font-size: 13px; }
.list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.item { border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; }
.meta { color: #6b7280; font-size: 12px; margin-bottom: 6px; }
.body { white-space: pre-wrap; font-size: 14px; line-height: 1.5; }
.empty { color: #9ca3af; padding: 24px; }
```

- [ ] **Step 4: Wire into navigation**

In `echo-app/src/components/app/Shell.jsx`, add a sidebar item after the "Сюжеты" one, matching its shape, label **"Дайджесты"**, screen key `'digests'`, reusing an existing icon name from `../shared/icons` (e.g. the same one used for analytics, or another that exists — do not invent a missing icon).

In `echo-app/src/pages/AppPage.jsx`:
- add `import { DigestsScreen } from '../components/app/Digests';`
- add a render branch beside the others: `) : screen === 'digests' ? (\n  <div className={styles.workspace}><DigestsScreen brand={brand} /></div>`
- add `screen === 'digests' ? 'Дайджесты' :` to the TopBar title ternary (next to the `'stories' ? 'Сюжеты'` entry).

- [ ] **Step 5: Verify build**

Run: `cd echo-app && npm run build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add echo-app/src/services/api.js echo-app/src/components/app/Digests.jsx echo-app/src/components/app/digests.module.css echo-app/src/components/app/Shell.jsx echo-app/src/pages/AppPage.jsx
git commit -m "feat: Дайджесты screen (generate + list)"
```

---

## Self-Review notes (resolved)

- **Spec §3 provider reuse (LLM_API_KEY, drafts pattern, no new dep, degrade-to-noop)** → Task 1 (`llm.py`) + Task 4 (503 on `LLMNotConfigured`). ✅
- **Spec §4 components (llm.py, digests.py, Report, API, UI)** → Tasks 1–5. ✅
- **Spec §5 report structure (тема→динамика→источники→риски→действие)** → `_SYSTEM` prompt in Task 3. ✅
- **Spec §7 decisions (UI delivery, reuse key, no schedule)** → UI screen (Task 5), no scheduler task, key reuse (Task 1). ✅
- **Type/name consistency:** `complete()`, `LLMNotConfigured`, `build_daily_digest()`, `Report`, `ReportOut`, `getDigests`/`createDigest`, `DigestsScreen` — consistent across tasks.
- **No real network in tests:** every test stubs `httpx.post` or `digests.llm.complete`. ✅
- **Open implementation detail:** the exact existing icon name for the nav item — implementer picks one that exists in `icons.jsx` (flagged in Task 5).
```
