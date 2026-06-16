# Web Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a topic-driven web source (Tavily) that ingests search results as `Mention(platform="web")` into the existing pipeline, so brands are monitored across the web in addition to the already-built Telegram surfaces.

**Architecture:** A `WebSearchProvider` queries Tavily; `collect_web()` maps results into the existing niche-mention storage (reusing `_store_niche_post`, `_term_hit`, `_brand_terms`, `Post`); a scheduler pass runs it per auto-collect brand and feeds classify/draft + stories. Degrades to a clean no-op without `WEB_SEARCH_API_KEY`. No frontend changes — web stories appear in the existing «Сюжеты»/feed.

**Tech Stack:** Python 3.x, SQLAlchemy, SQLite, `httpx` (already a dep). Use `python3`.

Spec: `docs/superpowers/specs/2026-06-16-web-source-design.md`

---

## File Structure
- **Create:** `backend/radar/providers/web.py`, `backend/tests/test_web.py`
- **Modify:** `backend/radar/collector.py` (add `collect_web`), `backend/radar/scheduler.py` (web pass + wiring), `backend/radar/api.py` (build web provider in `on_startup`, pass to Scheduler)

---

### Task 1: `WebSearchProvider` (Tavily)

**Files:** Create `backend/radar/providers/web.py`; create `backend/tests/test_web.py`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_web.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_web_search_noop_without_key(monkeypatch):
    import radar.providers.web as W
    monkeypatch.setattr(W, "WEB_SEARCH_API_KEY", "")
    assert W.WebSearchProvider().search("любая тема") == []


def test_web_search_parses_results(monkeypatch):
    import radar.providers.web as W
    monkeypatch.setattr(W, "WEB_SEARCH_API_KEY", "tvly-test")

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                {"title": "T1", "url": "https://a.example/x", "content": "body1",
                 "published_date": "2026-06-15"},
                {"title": "T2", "url": "https://b.example/y", "content": "body2"},
            ]}

    captured = {}
    def _post(url, json, timeout):
        captured["url"] = url; captured["json"] = json
        return _Resp()
    monkeypatch.setattr(W.httpx, "post", _post)

    out = W.WebSearchProvider().search("пожар", max_results=7)
    assert len(out) == 2
    assert out[0]["url"] == "https://a.example/x"
    assert out[0]["content"] == "body1"
    assert out[0]["published"] == "2026-06-15"
    assert out[1]["published"] is None
    assert captured["json"]["query"] == "пожар"
    assert captured["json"]["max_results"] == 7
    assert captured["json"]["api_key"] == "tvly-test"


def test_web_search_empty_on_http_error(monkeypatch):
    import radar.providers.web as W
    monkeypatch.setattr(W, "WEB_SEARCH_API_KEY", "tvly-test")
    def _boom(*a, **k): raise RuntimeError("network down")
    monkeypatch.setattr(W.httpx, "post", _boom)
    assert W.WebSearchProvider().search("x") == []
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: radar.providers.web`)

Run: `cd backend && python3 -m pytest tests/test_web.py -v`

- [ ] **Step 3: Implement `backend/radar/providers/web.py`**

```python
from __future__ import annotations
import logging
import os
import httpx

log = logging.getLogger(__name__)

WEB_SEARCH_API_KEY = os.getenv("WEB_SEARCH_API_KEY", "")
WEB_SEARCH_URL = os.getenv("WEB_SEARCH_URL", "https://api.tavily.com/search")
WEB_MAX_RESULTS = int(os.getenv("WEB_MAX_RESULTS", "10"))


class WebSearchProvider:
    """Topic web search via Tavily. Returns [{title, url, content, published}].

    No-op (returns []) when WEB_SEARCH_API_KEY is unset or on any network error,
    so the source degrades cleanly and never crashes a scheduler pass.
    """

    def search(self, query: str, max_results: int | None = None) -> list[dict]:
        if not WEB_SEARCH_API_KEY:
            return []
        try:
            resp = httpx.post(
                WEB_SEARCH_URL,
                json={"api_key": WEB_SEARCH_API_KEY, "query": query,
                      "search_depth": "basic", "topic": "news",
                      "max_results": max_results or WEB_MAX_RESULTS},
                timeout=60,
            )
            resp.raise_for_status()
            rows = resp.json().get("results", [])
        except Exception as e:
            log.warning("web search failed: %s", type(e).__name__)
            return []
        return [{"title": r.get("title", ""), "url": r.get("url", ""),
                 "content": r.get("content", ""), "published": r.get("published_date")}
                for r in rows if r.get("url")]
```

- [ ] **Step 4: Run — expect PASS** (3 passed)

Run: `cd backend && python3 -m pytest tests/test_web.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/radar/providers/web.py backend/tests/test_web.py
git commit -m "feat: WebSearchProvider (Tavily, no-op without key)"
```

---

### Task 2: `collect_web()` in collector.py

**Files:** Modify `backend/radar/collector.py`; append a test to `backend/tests/test_web.py`.

`collector.py` already imports `json, logging, os, re`, `datetime, timezone`, `Post`, `Brand/Mention`, and defines `_store_niche_post(session, brand_id, post, spam) -> bool`, `_term_hit(text, terms) -> bool`, `_brand_terms(brand) -> list[str]`, `_now()`. `Post` fields: `post_id, platform, author, followers, text, hashtags, created_at, likes, views, comments, shares, sound_id=None`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_web.py
from datetime import datetime, timezone


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


class _FakeWeb:
    def __init__(self, rows): self.rows = rows
    def search(self, query, max_results=None): return self.rows


def test_collect_web_stores_relevant_dedup(monkeypatch):
    import radar.collector as C
    from radar.models import Brand, Mention
    s = _mem()
    b = Brand(id=1, name="Бренд", keywords='["пожар"]', niche_keywords='["пожар"]')
    s.add(b); s.commit()
    prov = _FakeWeb([
        {"title": "Пожар на заводе", "url": "https://news.ru/a", "content": "сильный пожар", "published": "2026-06-15"},
        {"title": "Погода", "url": "https://news.ru/b", "content": "солнечно и тепло", "published": None},  # irrelevant → filtered
    ])
    n = C.collect_web(s, b, prov)
    assert n == 1
    rows = s.query(Mention).filter_by(platform="web").all()
    assert len(rows) == 1
    assert rows[0].author == "news.ru"     # domain
    assert rows[0].source == "niche"
    # second run = dedup (same URL) → no new rows
    n2 = C.collect_web(s, b, prov)
    assert s.query(Mention).filter_by(platform="web").count() == 1
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: module 'radar.collector' has no attribute 'collect_web'`)

Run: `cd backend && python3 -m pytest tests/test_web.py::test_collect_web_stores_relevant_dedup -v`

- [ ] **Step 3: Add `collect_web` to `backend/radar/collector.py`** (place it after `_store_niche_post`). Add `import hashlib` and `from urllib.parse import urlparse` to the top of the file (extend the existing import lines).

```python
def _web_query(brand: Brand) -> str:
    parts = [brand.name] + brand.keywords_list()[:5]
    return " ".join(p for p in parts if p).strip() or brand.name


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or "web"
    except Exception:
        return "web"


def _web_published(value) -> datetime:
    if value:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value[:len(fmt) + 2], fmt).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return _now()


def collect_web(session: Session, brand: Brand, provider) -> int:
    """Search the web for the brand's topic and store relevant results as web mentions.

    Reuses the niche-mention storage + relevance gate. Dedup is by (platform, post_id)
    where post_id = sha1(url). Returns the count of relevant results stored this pass.
    """
    results = provider.search(_web_query(brand))
    terms = _brand_terms(brand)
    n = 0
    for r in results:
        url = r.get("url")
        if not url:
            continue
        text = f"{r.get('title', '')}. {r.get('content', '')}".strip()
        if terms and not _term_hit(text, terms):
            continue  # off-topic — skip (no relevance terms → keep all)
        post = Post(
            post_id=hashlib.sha1(url.encode()).hexdigest()[:16],
            platform="web", author=_domain(url), followers=0,
            text=text, hashtags=[], created_at=_web_published(r.get("published")),
            likes=0, views=0, comments=0, shares=0,
        )
        if _store_niche_post(session, brand.id, post, spam=False):
            n += 1
    session.commit()
    return n
```

- [ ] **Step 4: Run — expect PASS** (whole file)

Run: `cd backend && python3 -m pytest tests/test_web.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/radar/collector.py backend/tests/test_web.py
git commit -m "feat: collect_web — ingest web search results as web mentions"
```

---

### Task 3: scheduler web pass + startup wiring

**Files:** Modify `backend/radar/scheduler.py`, `backend/radar/api.py`; append a test to `backend/tests/test_web.py`.

`scheduler.py` has module-level helpers (`_run_brand_pipeline`, `_run_digest_pass`), `INTERVAL_*` constants, `log`, and a `Scheduler` class whose `__init__(self, provider, tick_sec=60, tg_provider=None)` sets `self._last_chats`/`self._last_digest`, and whose `_run_once` calls `self._maybe_collect_chats(session)` / `self._maybe_daily_digest(session)` near the end. `os` and `time` are imported.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_web.py
def test_run_web_pass_collects_for_autocollect_brands(monkeypatch):
    import radar.scheduler as SCH
    from radar.models import Brand
    s = _mem()
    s.add(Brand(id=1, name="a", auto_collect=True))
    s.add(Brand(id=2, name="b", auto_collect=False))   # excluded
    s.commit()
    calls = []
    monkeypatch.setattr("radar.collector.collect_web",
                        lambda sess, brand, prov: calls.append(brand.id) or 0)
    SCH._run_web_pass(s, web_provider=object())
    assert calls == [1]
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: ... has no attribute '_run_web_pass'`)

Run: `cd backend && python3 -m pytest tests/test_web.py::test_run_web_pass_collects_for_autocollect_brands -v`

- [ ] **Step 3a: Edit `backend/radar/scheduler.py`**

Add a constant near the other `INTERVAL_*`:

```python
INTERVAL_WEB    = int(os.getenv("INTERVAL_WEB", "3600"))   # web-source cadence
```

Add a module-level helper near `_run_digest_pass` (uses module-attribute lookup so tests can monkeypatch `collect_web`):

```python
def _run_web_pass(session, web_provider):
    """Search the web per auto-collect brand and feed results into the pipeline."""
    import radar.collector as _collector
    import radar.pipeline as _pipeline
    import radar.stories as _stories
    from .models import Brand
    for b in session.query(Brand).filter(Brand.auto_collect.is_(True)).all():
        try:
            n = _collector.collect_web(session, b, web_provider)
        except Exception:
            log.exception("collect_web failed for brand %s", b.id)
            continue
        if n:
            try:
                _pipeline.classify_and_draft(session, b.id)
                _stories.update_stories(session, b.id)
            except Exception:
                log.exception("web pipeline failed for brand %s", b.id)
```

In `Scheduler.__init__`, add the `web_provider` param and a timer field:

```python
    def __init__(self, provider, tick_sec: int = 60, tg_provider=None, web_provider=None):
        ...
        self._tg_provider  = tg_provider
        self._web_provider = web_provider
        ...
        self._last_digest   = 0.0
        self._last_web      = 0.0
```

Add a method:

```python
    def _maybe_collect_web(self, session):
        if self._web_provider is None:
            return
        if time.monotonic() - self._last_web < INTERVAL_WEB:
            return
        self._last_web = time.monotonic()
        _run_web_pass(session, self._web_provider)
```

In `_run_once`, add after the existing `self._maybe_daily_digest(session)` line:

```python
            self._maybe_collect_web(session)
```

- [ ] **Step 3b: Edit `backend/radar/api.py`** — build the web provider in `on_startup` only when a key is set, and pass it to the Scheduler. In the scheduler-construction block inside `on_startup`:

```python
        from .scheduler import Scheduler
        web_provider = None
        if os.getenv("WEB_SEARCH_API_KEY"):
            from .providers.web import WebSearchProvider
            web_provider = WebSearchProvider()
        _scheduler = Scheduler(_get_provider(), tick_sec=int(os.getenv("SCHEDULER_TICK_SEC", "60")),
                               tg_provider=_get_tg_provider(), web_provider=web_provider)
        _scheduler.start()
```

(Match the existing `Scheduler(...)` call — add only the `web_provider=` argument; keep the rest.)

- [ ] **Step 4: Run — expect PASS, then full suite**

Run: `cd backend && python3 -m pytest tests/test_web.py -v && python3 -m pytest -q`
Expected: web tests pass; full suite green. (If `test_profile_scan` shows `mentions.incident_id` errors, run `python3 -c "import radar.db as db; db.init_db()"` once — known dev-DB quirk — and re-run.)

- [ ] **Step 5: Commit**

```bash
git add backend/radar/scheduler.py backend/radar/api.py backend/tests/test_web.py
git commit -m "feat: scheduler web-source pass + startup wiring (gated on WEB_SEARCH_API_KEY)"
```

---

## Self-Review notes (resolved)

- **Spec §3 provider (Tavily, no-op without key, sane parse)** → Task 1 + 3 tests. ✅
- **Spec §4 collect_web (topic query, dedup by url, relevance gate, reuse `_store_niche_post`)** → Task 2. ✅
- **Spec §5 scheduler pass (auto-collect brands, gated, best-effort, startup wiring)** → Task 3. ✅
- **Spec §6 no frontend** → no frontend task. ✅
- **Spec §7 tests (provider/collect_web/web_pass, no real network)** → all stub httpx/provider/collect_web. ✅
- **Type/name consistency:** `WebSearchProvider.search()`, `collect_web(session, brand, provider)`, `_run_web_pass(session, web_provider)`, `Scheduler(..., web_provider=)`, `Post` fields — consistent across tasks and match the existing collector helpers.
- **Telegram:** intentionally untouched — global search / channel discovery / chats already exist and run by topic.
```
