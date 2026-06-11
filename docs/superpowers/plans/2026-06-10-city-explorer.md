# City Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Standalone "City Explorer" — enter any city, get an LLM summary of local interests (themes, wants, trends, mood) from TikTok + Instagram via SocialCrawl, with cached reports.

**Architecture:** A thin pipeline (`explore.py`) builds city keyword/hashtag queries → `SocialCrawlProvider.search` → aggregates posts → Claude summarizes to structured JSON. A `CityReport` table caches results (7-day freshness). Two FastAPI endpoints serve report generation and history. A React screen renders the summary.

**Tech Stack:** Python/FastAPI/SQLAlchemy/SQLite, React+Vite, pytest. LLM = Claude via `LLM_API_KEY` (mirrors `drafts.py`).

**Spec:** `docs/superpowers/specs/2026-06-10-city-explorer-design.md`
**Test command:** `cd backend && python3 -m pytest tests/ -v`
**Branch:** `feat/city-explorer`

---

## Task 1: City query building (`explore.py`)

**Files:** Create `backend/radar/explore.py`; Test `backend/tests/test_explore.py`

- [ ] **Step 1: Failing test** — create `backend/tests/test_explore.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from radar.explore import normalize_city, build_city_queries


def test_normalize_city_lowercase_trim():
    assert normalize_city("  Москва ") == ("москва", "москва")


def test_normalize_city_hashtag_strips_space_and_hyphen():
    assert normalize_city("Санкт-Петербург") == ("санкт-петербург", "санктпетербург")


def test_build_city_queries_shape():
    qs = build_city_queries("Москва")
    assert ("tiktok", "keyword", "Москва") in qs
    assert ("tiktok", "keyword", "куда сходить Москва") in qs
    assert ("tiktok", "keyword", "что попробовать Москва") in qs
    assert ("instagram", "hashtag", "москва") in qs
    assert len(qs) == 4
```

- [ ] **Step 2: Run, expect fail** — `cd backend && python3 -m pytest tests/test_explore.py -v` → `ModuleNotFoundError: radar.explore`.

- [ ] **Step 3: Implement** — create `backend/radar/explore.py`:

```python
"""City Explorer pipeline: build city queries, aggregate posts, LLM-summarize.

Standalone audience research — no brand coupling. SocialCrawl has no native geo
search, so "by city" means keyword/hashtag search for city terms.
"""
import json, logging, os
from typing import Optional

log = logging.getLogger(__name__)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")


def normalize_city(city: str) -> tuple[str, str]:
    """Return (key, hashtag). key = trimmed lowercase; hashtag = key without
    spaces/hyphens (for IG hashtag search and cache key)."""
    key = (city or "").strip().lower()
    hashtag = key.replace(" ", "").replace("-", "")
    return key, hashtag


def build_city_queries(city: str) -> list[tuple[str, str, str]]:
    """(platform, kind, query) tuples — small set to bound credit cost (~4)."""
    _, hashtag = normalize_city(city)
    c = city.strip()
    return [
        ("tiktok", "keyword", c),
        ("tiktok", "keyword", f"куда сходить {c}"),
        ("tiktok", "keyword", f"что попробовать {c}"),
        ("instagram", "hashtag", hashtag),
    ]
```

- [ ] **Step 4: Run, expect pass** — `cd backend && python3 -m pytest tests/test_explore.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/radar/explore.py backend/tests/test_explore.py
git commit -m "feat: city query building for City Explorer"
```
Append trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## Task 2: Post aggregation + search runner (`explore.py`)

**Files:** Modify `backend/radar/explore.py`; Test append `backend/tests/test_explore.py`

- [ ] **Step 1: Failing test (append)**:

```python
from datetime import datetime, timezone
from radar.providers.base import Post


def _post(pid, text, likes=0, views=0, tags=None):
    return Post(post_id=pid, platform="tiktok", author="a", followers=0, text=text,
                hashtags=tags or [], created_at=datetime.now(timezone.utc),
                likes=likes, views=views, comments=0, shares=0)


def test_aggregate_posts_dedup_rank_cap_truncate():
    from radar.explore import aggregate_posts
    posts = [_post("1", "x"*400, likes=5), _post("1", "dup", likes=99),
             _post("2", "hi", likes=100, views=500, tags=["#a"])]
    out = aggregate_posts(posts)
    ids_texts = [(o["likes"], len(o["text"])) for o in out]
    # dedup by post_id keeps first occurrence; "2" ranks above "1"
    assert len(out) == 2
    assert out[0]["likes"] == 100              # highest engagement first
    assert all(len(o["text"]) <= 280 for o in out)
    assert out[0]["hashtags"] == ["#a"]


def test_run_city_search_skips_failing_platform():
    from radar.explore import run_city_search
    class FakeProvider:
        def search(self, query, kind, cursor, platform):
            if platform == "instagram":
                raise RuntimeError("ig down")
            from radar.providers.base import SearchPage
            return SearchPage(posts=[_post(query, "post "+query, likes=10)], next_cursor=None)
    agg, n, platforms = run_city_search(FakeProvider(), "Москва")
    assert n > 0
    assert "tiktok" in platforms and "instagram" not in platforms
```

- [ ] **Step 2: Run, expect fail** — `ImportError: aggregate_posts`.

- [ ] **Step 3: Implement (append to `explore.py`)**:

```python
def aggregate_posts(posts: list, limit: int = 40) -> list[dict]:
    """Dedupe by post_id, rank by engagement, cap, return compact dicts."""
    seen, uniq = set(), []
    for p in posts:
        if p.post_id in seen:
            continue
        seen.add(p.post_id)
        uniq.append(p)
    uniq.sort(key=lambda p: (p.likes or 0) + (p.views or 0) // 100, reverse=True)
    return [{
        "text": (p.text or "")[:280],
        "likes": p.likes or 0,
        "views": p.views or 0,
        "hashtags": p.hashtags or [],
    } for p in uniq[:limit]]


def run_city_search(provider, city: str) -> tuple[list[dict], int, list[str]]:
    """Run every city query; skip platforms that error. Returns
    (aggregated_posts, raw_post_count, platforms_with_results)."""
    all_posts, platforms = [], set()
    for platform, kind, query in build_city_queries(city):
        try:
            page = provider.search(query, kind, None, platform)
        except Exception as e:
            log.warning("city search failed (%s/%s %r): %s", platform, kind, query, e)
            continue
        if page.posts:
            platforms.add(platform)
            all_posts.extend(page.posts)
    return aggregate_posts(all_posts), len(all_posts), sorted(platforms)
```

- [ ] **Step 4: Run, expect pass**.

- [ ] **Step 5: Commit** — `git add` the two files; message `feat: city post aggregation + search runner`.

---

## Task 3: LLM summarization (`explore.py`)

**Files:** Modify `backend/radar/explore.py`; Test append

- [ ] **Step 1: Failing test (append)**:

```python
def _fake_llm_response(text):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"content": [{"type": "text", "text": text}]}
    return R()


def test_summarize_city_parses_json(monkeypatch):
    import radar.explore as ex
    monkeypatch.setattr(ex, "LLM_API_KEY", "k")
    payload = '{"overview":"ok","themes":[{"title":"Еда","description":"кафе"}],' \
              '"wants":["куда сходить"],"trends":["t"],' \
              '"sentiment":{"overall":"positive","note":"n"},"top_hashtags":["#м"]}'
    monkeypatch.setattr(ex.httpx, "post", lambda *a, **k: _fake_llm_response(payload))
    out = ex.summarize_city("Москва", [{"text": "x", "likes": 1, "views": 1, "hashtags": []}])
    assert out["overview"] == "ok"
    assert out["themes"][0]["title"] == "Еда"
    assert out["sentiment"]["overall"] == "positive"


def test_summarize_city_no_key_returns_empty(monkeypatch):
    import radar.explore as ex
    monkeypatch.setattr(ex, "LLM_API_KEY", "")
    assert ex.summarize_city("Москва", [{"text": "x"}]) == {}
```

- [ ] **Step 2: Run, expect fail** — `AttributeError: module has no attribute 'httpx'` / `summarize_city` missing.

- [ ] **Step 3: Implement (append to `explore.py`)** — add `import httpx` at top of file (with the other imports) and:

```python
_SUMMARY_SCHEMA = ('{"overview":"","themes":[{"title":"","description":""}],'
                   '"wants":[],"trends":[],"sentiment":{"overall":"neutral","note":""},'
                   '"top_hashtags":[]}')


def summarize_city(city: str, agg_posts: list[dict]) -> dict:
    """Claude summary of city interests. Returns the schema dict, or {} on no-key/error."""
    if not LLM_API_KEY:
        return {}
    sample = "\n".join(f"- {p['text']} (likes {p.get('likes',0)})" for p in agg_posts[:40])
    system = (
        "Ты аналитик соцсетей. По постам, упоминающим город, опиши интересы местной "
        "аудитории. Отвечай ТОЛЬКО валидным JSON без markdown."
    )
    user = (
        f"Город: {city}. Посты:\n{sample}\n\n"
        f"Сделай сводку интересов: о чём говорят, что хотят/ищут, тренды, общее настроение. "
        f"Строго JSON по форме: {_SUMMARY_SCHEMA}"
    )

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 900,
                  "system": system, "messages": [{"role": "user", "content": user}]},
            timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = json.loads(text)
        return {
            "overview":     data.get("overview", "") or "",
            "themes":       data.get("themes", []) or [],
            "wants":        data.get("wants", []) or [],
            "trends":       data.get("trends", []) or [],
            "sentiment":    data.get("sentiment", {}) or {},
            "top_hashtags": data.get("top_hashtags", []) or [],
        }

    try:
        return _call()
    except (json.JSONDecodeError, KeyError):
        try:
            return _call()
        except Exception as e:
            log.warning("summarize_city retry failed: %s", e); return {}
    except Exception as e:
        log.warning("summarize_city failed: %s", e); return {}
```

- [ ] **Step 4: Run, expect pass**.

- [ ] **Step 5: Commit** — message `feat: LLM city interest summarization`.

---

## Task 4: `CityReport` model

**Files:** Modify `backend/radar/models.py`; Test append `backend/tests/test_explore.py`

- [ ] **Step 1: Failing test (append)**:

```python
def _mem_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_city_report_roundtrip():
    from radar.models import CityReport
    s = _mem_session()
    s.add(CityReport(city="москва", display_city="Москва", summary='{"overview":"x"}',
                     post_count=12, platforms="tiktok,instagram"))
    s.commit()
    r = s.query(CityReport).filter_by(city="москва").one()
    assert r.display_city == "Москва" and r.post_count == 12
    assert r.created_at is not None
```

- [ ] **Step 2: Run, expect fail** — `ImportError: CityReport`.

- [ ] **Step 3: Implement** — append to `backend/radar/models.py` after the last class:

```python
class CityReport(Base):
    """Cached City Explorer summary. Global (not per-user). Newest row per city wins."""
    __tablename__ = "city_reports"
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    city:         Mapped[str]      = mapped_column(Text)                 # normalized key
    display_city: Mapped[str]      = mapped_column(Text, default="")     # original input
    summary:      Mapped[str]      = mapped_column(Text, default="{}")   # JSON string
    post_count:   Mapped[int]      = mapped_column(Integer, default=0)
    platforms:    Mapped[str]      = mapped_column(Text, default="")     # comma-joined
    created_at:   Mapped[datetime] = mapped_column(default=_now)
```

- [ ] **Step 4: Run, expect pass**.

- [ ] **Step 5: Commit** — message `feat: CityReport model for cached city summaries`.

---

## Task 5: Endpoints (`api.py`)

**Files:** Modify `backend/radar/api.py`; Test append `backend/tests/test_explore.py`

- [ ] **Step 1: Failing test (append)**:

```python
def test_explore_city_uses_cache(monkeypatch):
    from datetime import datetime, timezone
    from radar import api
    from radar.models import CityReport
    s = _mem_session()
    s.add(CityReport(city="москва", display_city="Москва",
                     summary='{"overview":"cached"}', post_count=5, platforms="tiktok",
                     created_at=datetime.now(timezone.utc)))
    s.commit()

    class U: id = 1; email = "u@x.com"
    def boom(*a, **k): raise AssertionError("provider must not be called on fresh cache")
    monkeypatch.setattr(api, "_get_provider", boom)
    body = api.ExploreCityBody(city="Москва")
    out = api.explore_city(body, user=U(), session=s)
    assert out["cached"] is True
    assert out["summary"]["overview"] == "cached"


def test_explore_city_live_when_missing(monkeypatch):
    from radar import api
    from radar.models import CityReport
    s = _mem_session()
    monkeypatch.setattr(api, "_get_provider", lambda: object())
    monkeypatch.setattr("radar.explore.run_city_search",
                        lambda provider, city: ([{"text": "p"}], 3, ["tiktok"]))
    monkeypatch.setattr("radar.explore.summarize_city",
                        lambda city, posts: {"overview": "fresh", "themes": []})
    class U: id = 1; email = "u@x.com"
    out = api.explore_city(api.ExploreCityBody(city="Казань"), user=U(), session=s)
    assert out["cached"] is False and out["summary"]["overview"] == "fresh"
    assert s.query(CityReport).filter_by(city="казань").count() == 1
```

- [ ] **Step 2: Run, expect fail** — `AttributeError: ExploreCityBody` / `explore_city`.

- [ ] **Step 3: Implement** — in `backend/radar/api.py`, add near the other route groups:

```python
# ── City Explorer ─────────────────────────────────────────────────────────────
CITY_REPORT_TTL_DAYS = int(os.getenv("CITY_REPORT_TTL_DAYS", "7"))


class ExploreCityBody(BaseModel):
    city:    str
    refresh: bool = False


def _city_report_card(r) -> dict:
    return {
        "city":         r.city,
        "display_city": r.display_city,
        "summary":      json.loads(r.summary or "{}"),
        "post_count":   r.post_count,
        "platforms":    r.platforms.split(",") if r.platforms else [],
        "created_at":   r.created_at.isoformat() if r.created_at else None,
    }


@app.post("/explore/city")
def explore_city(body: ExploreCityBody, user: User = Depends(current_user),
                 session: Session = Depends(db)):
    from .explore import normalize_city, run_city_search, summarize_city
    from .models import CityReport
    key, _ = normalize_city(body.city)
    if not key:
        raise HTTPException(400, "City is required")

    if not body.refresh:
        latest = (session.query(CityReport).filter_by(city=key)
                  .order_by(CityReport.created_at.desc()).first())
        if latest:
            age_days = (datetime.now(timezone.utc) -
                        latest.created_at.replace(tzinfo=timezone.utc)).days
            if age_days < CITY_REPORT_TTL_DAYS:
                return {**_city_report_card(latest), "cached": True}

    agg, n, platforms = run_city_search(_get_provider(), body.city)
    if n == 0:
        raise HTTPException(502, "No posts found (provider unavailable or out of credits)")
    summary = summarize_city(body.city, agg)
    if not summary:
        raise HTTPException(503, "Summary unavailable — set LLM_API_KEY in backend/.env")

    row = CityReport(city=key, display_city=body.city.strip(),
                     summary=json.dumps(summary, ensure_ascii=False),
                     post_count=n, platforms=",".join(platforms))
    session.add(row); session.commit()
    return {**_city_report_card(row), "cached": False}


@app.get("/explore/cities")
def explore_cities(user: User = Depends(current_user), session: Session = Depends(db)):
    from .models import CityReport
    rows = (session.query(CityReport).order_by(CityReport.created_at.desc()).all())
    seen, out = set(), []
    for r in rows:
        if r.city in seen:
            continue
        seen.add(r.city)
        out.append({"city": r.city, "display_city": r.display_city,
                    "post_count": r.post_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None})
        if len(out) >= 30:
            break
    return out
```

> Note: `os`, `json`, `datetime`, `timezone`, `BaseModel`, `HTTPException`, `Depends`, `User`, `Session`, `db`, `current_user`, `_get_provider`, `app` are all already imported/defined in `api.py`.

- [ ] **Step 4: Run, expect pass** — `cd backend && python3 -m pytest tests/test_explore.py -v`.

- [ ] **Step 5: Full suite** — `cd backend && python3 -m pytest tests/ -v` → PASS.

- [ ] **Step 6: Commit** — `git add backend/radar/api.py backend/tests/test_explore.py`; message `feat: City Explorer endpoints (report + history) with caching`.

---

## Task 6: Frontend City Explorer screen

**Files:** Create `echo-app/src/components/app/CityExplorer.jsx`, `cityexplorer.module.css`; Modify `echo-app/src/services/api.js`, `echo-app/src/components/app/Shell.jsx`. No automated frontend tests — verify with `npm run build` + manual.

- [ ] **Step 1: Add API client functions** — append to `echo-app/src/services/api.js`:

```javascript
export const exploreCity = (city, refresh = false) =>
  request('/explore/city', { method: 'POST', body: JSON.stringify({ city, refresh }) });

export const getCityReports = () => request('/explore/cities');
```

- [ ] **Step 2: Create `echo-app/src/components/app/CityExplorer.jsx`** — read an existing screen (e.g. `Analytics.jsx`) first to match imports (`Icon`, `styles`, `*  as api`) and visual conventions, then implement:

```jsx
import { useState, useEffect } from 'react';
import { Icon } from '../shared/icons';
import * as api from '../../services/api';
import styles from './cityexplorer.module.css';

export function CityExplorerScreen() {
  const [city, setCity]       = useState('');
  const [report, setReport]   = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');
  const [history, setHistory] = useState([]);

  const loadHistory = () => api.getCityReports().then(d => Array.isArray(d) && setHistory(d)).catch(() => {});
  useEffect(() => { loadHistory(); }, []);

  async function run(targetCity, refresh = false) {
    const c = (targetCity ?? city).trim();
    if (!c) return;
    setLoading(true); setError('');
    try {
      const r = await api.exploreCity(c, refresh);
      setReport(r); setCity(r.display_city || c); loadHistory();
    } catch (e) {
      setError('Не удалось собрать сводку — проверь баланс провайдера / LLM-ключ.');
    } finally { setLoading(false); }
  }

  const s = report?.summary || {};
  return (
    <div className={styles.page}>
      <div className={styles.searchBar}>
        <input className={styles.input} placeholder="Введите город — напр. Москва"
          value={city} onChange={e => setCity(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && run()} />
        <button className={styles.btnPrimary} onClick={() => run()} disabled={loading}>
          <Icon name="search" size={14} />{loading ? 'Собираю…' : 'Исследовать'}
        </button>
        {report && (
          <button className={styles.btnGhost} onClick={() => run(report.display_city, true)} disabled={loading}>
            <Icon name="refresh" size={14} />Обновить
          </button>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.body}>
        <div className={styles.main}>
          {report ? (
            <>
              <div className={styles.metaRow}>
                <span className={styles.cityName}>{report.display_city}</span>
                <span className={styles.meta}>{report.post_count} постов · {(report.platforms || []).join(', ')}
                  {report.cached ? ' · из кеша' : ''}{report.created_at ? ` · ${new Date(report.created_at).toLocaleDateString('ru-RU')}` : ''}</span>
              </div>
              {s.overview && <div className={styles.overview}>{s.overview}</div>}
              {s.sentiment?.overall && (
                <div className={styles.sentiment} data-tone={s.sentiment.overall}>
                  Настроение: {s.sentiment.overall}{s.sentiment.note ? ` — ${s.sentiment.note}` : ''}
                </div>
              )}
              {Array.isArray(s.themes) && s.themes.length > 0 && (
                <section className={styles.section}><h3>Темы</h3>
                  <div className={styles.themeGrid}>
                    {s.themes.map((t, i) => (
                      <div key={i} className={styles.themeCard}>
                        <div className={styles.themeTitle}>{t.title}</div>
                        <div className={styles.themeDesc}>{t.description}</div>
                      </div>
                    ))}
                  </div>
                </section>
              )}
              {Array.isArray(s.wants) && s.wants.length > 0 && (
                <section className={styles.section}><h3>Что хотят / ищут</h3>
                  <ul className={styles.list}>{s.wants.map((w, i) => <li key={i}>{w}</li>)}</ul>
                </section>
              )}
              {Array.isArray(s.trends) && s.trends.length > 0 && (
                <section className={styles.section}><h3>Тренды</h3>
                  <ul className={styles.list}>{s.trends.map((t, i) => <li key={i}>{t}</li>)}</ul>
                </section>
              )}
              {Array.isArray(s.top_hashtags) && s.top_hashtags.length > 0 && (
                <div className={styles.tags}>{s.top_hashtags.map((h, i) => <span key={i} className={styles.tag}>{h}</span>)}</div>
              )}
            </>
          ) : (
            <div className={styles.empty}>Введите город, чтобы увидеть интересы аудитории.</div>
          )}
        </div>

        <aside className={styles.history}>
          <div className={styles.historyTitle}>История</div>
          {history.map(h => (
            <button key={h.city} className={styles.historyItem} onClick={() => run(h.display_city)}>
              {h.display_city}<span className={styles.historyMeta}>{h.post_count}</span>
            </button>
          ))}
        </aside>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `echo-app/src/components/app/cityexplorer.module.css`** — match the visual language of `analytics.module.css` (CSS variables like `--surface-2`, `--line`, `--fg-1`, `--brand`, `--r-md`). Minimal but consistent:

```css
.page { display: flex; flex-direction: column; height: 100%; }
.searchBar { display: flex; gap: 8px; padding: 16px; border-bottom: 1px solid var(--line); flex-shrink: 0; }
.input { flex: 1; max-width: 420px; padding: 9px 12px; border-radius: var(--r-md); border: 1px solid var(--line-2); background: var(--surface-2); color: var(--fg-1); font-size: 14px; font-family: var(--font-sans); }
.btnPrimary, .btnGhost { display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; border-radius: var(--r-md); font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid var(--line-2); font-family: var(--font-sans); }
.btnPrimary { background: var(--brand); color: #fff; border-color: transparent; }
.btnGhost { background: var(--surface-2); color: var(--fg-2); }
.btnPrimary:disabled { opacity: .6; cursor: default; }
.error { margin: 12px 16px; padding: 10px 12px; border-radius: var(--r-md); background: var(--neg-dim); color: var(--neg); font-size: 13px; }
.body { display: flex; gap: 16px; padding: 16px; overflow-y: auto; flex: 1; min-height: 0; }
.main { flex: 1; min-width: 0; }
.metaRow { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.cityName { font-size: 20px; font-weight: 800; color: var(--fg-1); }
.meta { font-size: 12px; color: var(--fg-4); }
.overview { font-size: 14px; line-height: 1.6; color: var(--fg-1); background: var(--surface-2); padding: 12px 14px; border-radius: var(--r-md); margin-bottom: 12px; }
.sentiment { font-size: 12px; color: var(--fg-3); margin-bottom: 16px; }
.section { margin-bottom: 18px; }
.section h3 { font-size: 13px; font-weight: 700; color: var(--fg-2); margin: 0 0 8px; text-transform: uppercase; letter-spacing: .04em; }
.themeGrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.themeCard { background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--r-md); padding: 12px; }
.themeTitle { font-size: 14px; font-weight: 700; color: var(--fg-1); margin-bottom: 4px; }
.themeDesc { font-size: 12.5px; color: var(--fg-3); line-height: 1.5; }
.list { margin: 0; padding-left: 18px; }
.list li { font-size: 13.5px; color: var(--fg-2); line-height: 1.7; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.tag { font-size: 12px; padding: 3px 9px; border-radius: 99px; background: var(--surface-3); color: var(--fg-3); font-family: var(--font-mono); }
.history { width: 180px; flex-shrink: 0; border-left: 1px solid var(--line); padding-left: 16px; }
.historyTitle { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--fg-4); margin-bottom: 8px; }
.historyItem { display: flex; justify-content: space-between; width: 100%; padding: 7px 9px; border-radius: var(--r-sm); border: none; background: none; color: var(--fg-2); font-size: 13px; cursor: pointer; font-family: var(--font-sans); text-align: left; }
.historyItem:hover { background: var(--surface-2); }
.historyMeta { color: var(--fg-4); font-size: 11px; font-family: var(--font-mono); }
.empty { color: var(--fg-4); font-size: 14px; padding: 40px 0; text-align: center; }
```

- [ ] **Step 4: Wire navigation in `Shell.jsx`** — read `echo-app/src/components/app/Shell.jsx` first to learn how screens/nav items are registered (the existing screens: Feed, Queue, Analytics, Settings, Detail). Add a "Города" / City Explorer nav entry that renders `<CityExplorerScreen />`, following the exact pattern used for the other screens (import, nav-item list, and the screen switch/render). Use an existing icon name (e.g. `search` or `globe` if present in `icons.jsx`; otherwise reuse one already used in the nav). Confirm the chosen icon exists.

- [ ] **Step 5: Build** — `cd echo-app && npm run build` → must succeed.

- [ ] **Step 6: Manual verification** — with backend + `npm run dev` running, log in, open the new "Города" screen, confirm it renders the input + empty state and the nav entry works. (Live report requires SocialCrawl credits; without them the endpoint returns 502 and the UI shows the error banner — that is expected.)

- [ ] **Step 7: Commit** — `git add echo-app/src/components/app/CityExplorer.jsx echo-app/src/components/app/cityexplorer.module.css echo-app/src/services/api.js echo-app/src/components/app/Shell.jsx`; message `feat: City Explorer frontend screen + nav`.

---

## Self-Review Notes

- **Spec coverage:** queries (T1), aggregation/search (T2), LLM summary (T3), cache model (T4), endpoints+caching (T5), UI+nav (T6) — all spec sections covered.
- **Type consistency:** `normalize_city -> (key, hashtag)` used in T1/T5; `run_city_search(provider, city) -> (agg, n, platforms)` used in T2/T5; `summarize_city(city, agg) -> dict` in T3/T5; `CityReport(city, display_city, summary, post_count, platforms, created_at)` consistent across T4/T5. `_city_report_card` parses `summary` JSON back to dict for the API.
- **No credits in tests:** all backend tests monkeypatch the provider and `httpx.post`/`run_city_search`/`summarize_city`. Live calls happen only through the real endpoint at runtime.
- **Open runtime dependency:** live report generation needs a funded SocialCrawl key (currently 0 credits) + the working `LLM_API_KEY`. The feature is fully buildable/testable without either; only the live demo is gated on credits.
