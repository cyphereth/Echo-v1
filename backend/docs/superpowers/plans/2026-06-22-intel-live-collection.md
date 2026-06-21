# Intel Live Collection (Phase 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect real Telegram channels + chats into `IntelMention` (side from a curated source file, direction auto-tagged per post via geo-keywords + LLM), wired into the scheduler.

**Architecture:** Reuse the existing Telethon provider and the news TG worker pattern. `IntelProbe` becomes a "source" (channel/chat with a side, no fixed direction); the collector tags each post's direction inline by geo-keywords (defaulting to an `unassigned` bucket); a separate LLM pass re-tags ambiguous posts. A military-slang lexicon (operator file) gates chat noise and gives the LLM context. Everything downstream (clustering, stories, board, center) is already built and unchanged.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, pytest, Telethon (existing session/provider).

**Spec:** `backend/docs/superpowers/specs/2026-06-22-intel-live-collection-design.md`.

**Reference template:** the news TG worker `radar/news/passes.py::run_topic_tg_pass` and `radar/news/collector.py`. Mirror their rotation / FloodWait / dedup mechanics; do NOT modify news/brand.

## Global Constraints

- Domain isolation: `radar/intel/*` imports only from `.`, `..core.*`, `..models`. NO `radar.news` / `radar.brand` imports. No `Scope`.
- Side is ALWAYS operator-provided per source (from the file). Never inferred.
- `IntelMention.direction_id` is ALWAYS set (real direction or the `unassigned` bucket) so clustering/board never break.
- Telegram provider interface (existing, in `radar/core/providers/telegram.py`): channels via `provider.search(query, "channel", cursor)` → `SearchPage(posts, cursor)`; chats via `provider.search_chat(handle, term, limit, min_id)` → `list[Post]`. `TelegramFloodWait` is the flood exception.
- `core.spam.looks_like_ad_cheap(text, author, hashtags=None)` for spam detection.
- LLM via `..core.llm` (`complete(...)`, `LLMNotConfigured`); any LLM pass must be SKIPPED (no-op) when the key is absent.
- Full suite stays green at every commit (baseline before this plan: 217 passed). Run all git from repo ROOT `/Users/vovolypsi/Echo-v1/Echo-v1`; never `git init`.

## File Structure

- `radar/intel/models.py` (modify) — `IntelProbe.direction_id` → nullable; add `IntelLexicon` (term, meaning, category).
- `radar/intel/geo.py` (new) — `GEO_KEYWORDS` dict + `detect_direction(text) -> str | None`.
- `radar/intel/tagging.py` (new) — `resolve_direction_id(session, key)` (incl. `unassigned`), inline tag helper, `retag_unassigned(session, limit)` (LLM).
- `radar/intel/collector.py` (modify) — set `direction_id` per post via geo tag; branch `kind="chat"`; chat noise filter.
- `radar/intel/intake.py` (new) — `ingest_sources(session, path)` + `ingest_lexicon(session, path)`; `__main__` CLI.
- `radar/intel/passes.py` (new) — `run_intel_collect(session, tg_provider)`.
- `radar/intel/seed.py` (modify) — seed the `unassigned` direction.
- `radar/core/scheduler.py` (modify) — call the intel collect pass in the tick.
- Tests: `tests/test_intel_geo.py`, `tests/test_intel_intake.py`, `tests/test_intel_lexicon.py`, `tests/test_intel_collect_tagging.py`, `tests/test_intel_passes.py`, `tests/test_intel_retag.py`.

---

### Task 1: Model adjustments — source-centric probe + lexicon + `unassigned` seed

**Files:**
- Modify: `backend/radar/intel/models.py`
- Modify: `backend/radar/intel/seed.py`
- Test: `backend/tests/test_intel_lexicon.py`

**Interfaces:**
- Produces: `IntelProbe.direction_id` nullable; `IntelLexicon(id, term unique, meaning, category, created_at)`; `seed.ensure_unassigned_direction(session) -> IntelDirection` (key `"unassigned"`, name `"Без направления"`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_lexicon.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_intel_probe_direction_nullable():
    from radar.intel.models import IntelProbe
    assert IntelProbe.__table__.c.direction_id.nullable is True

def test_lexicon_model_and_unassigned_seed():
    from radar.intel.models import IntelLexicon, IntelDirection
    from radar.intel import seed
    s = _sess()
    s.add(IntelLexicon(term="300", meaning="раненые", category="casualties")); s.commit()
    assert s.query(IntelLexicon).filter_by(term="300").one().meaning == "раненые"
    d = seed.ensure_unassigned_direction(s)
    assert d.key == "unassigned"
    # idempotent
    d2 = seed.ensure_unassigned_direction(s)
    assert d2.id == d.id and s.query(IntelDirection).filter_by(key="unassigned").count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_lexicon.py -q`
Expected: FAIL (`direction_id.nullable` is False / no `IntelLexicon` / no `ensure_unassigned_direction`).

- [ ] **Step 3: Implement**

In `radar/intel/models.py`: change `IntelProbe.direction_id` to `Mapped[Optional[int]] = mapped_column(ForeignKey("intel_directions.id"))` (nullable). Add at the end:
```python
class IntelLexicon(Base):
    __tablename__ = "intel_lexicon"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    term:       Mapped[str]      = mapped_column(Text, unique=True, nullable=False)
    meaning:    Mapped[str]      = mapped_column(Text, default="")
    category:   Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_now)
```
In `radar/intel/seed.py` add:
```python
def ensure_unassigned_direction(session):
    from .models import IntelDirection
    d = session.query(IntelDirection).filter_by(key="unassigned").first()
    if d is None:
        d = IntelDirection(key="unassigned", name="Без направления")
        session.add(d); session.commit()
    return d
```
Also call `ensure_unassigned_direction(session)` inside the existing `ensure_default_directions(session)` (so app startup seeds it).

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_lexicon.py -q`
Expected: 2 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 219 passed: 217 + 2).
```bash
git add backend/radar/intel/models.py backend/radar/intel/seed.py backend/tests/test_intel_lexicon.py
git commit -m "feat(intel): source-centric probe (nullable direction), lexicon model, unassigned bucket"
```

---

### Task 2: Geo dictionary + per-post direction detection

**Files:**
- Create: `backend/radar/intel/geo.py`
- Create: `backend/radar/intel/tagging.py`
- Test: `backend/tests/test_intel_geo.py`

**Interfaces:**
- Produces: `geo.GEO_KEYWORDS: dict[str, list[str]]`; `geo.detect_direction(text) -> str | None` (direction key or None); `tagging.resolve_direction_id(session, key) -> int` (resolves a direction key to its id, creating via seed for `unassigned`; falls back to `unassigned` for unknown/None).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_geo.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_detect_direction_by_geo_keyword():
    from radar.intel.geo import detect_direction
    assert detect_direction("удар по складу под Суджей") == "kursk"
    assert detect_direction("бои у Работино") == "zaporizhzhia"
    assert detect_direction("просто новость про погоду") is None

def test_resolve_direction_id_defaults_unassigned():
    from radar.intel import seed
    from radar.intel.tagging import resolve_direction_id
    from radar.intel.models import IntelDirection
    s = _sess()
    seed.ensure_default_directions(s)  # seeds real dirs + unassigned
    kid = resolve_direction_id(s, "kursk")
    assert s.get(IntelDirection, kid).key == "kursk"
    uid = resolve_direction_id(s, None)
    assert s.get(IntelDirection, uid).key == "unassigned"
    uid2 = resolve_direction_id(s, "nonsense")
    assert s.get(IntelDirection, uid2).key == "unassigned"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_geo.py -q`
Expected: FAIL (no `radar.intel.geo`).

- [ ] **Step 3: Implement `geo.py`**

```python
from __future__ import annotations
import re

# direction key -> geo terms (seed; operator-extensible). Keys MUST match seeded IntelDirection keys.
GEO_KEYWORDS: dict[str, list[str]] = {
    "kursk":        ["курск", "суджа", "суджи", "суджей", "глушково", "коренево", "льгов"],
    "zaporizhzhia": ["запорож", "орехов", "работино", "каменское", "пологи", "токмак"],
    "kharkiv":      ["харьков", "купянск", "купянск", "волчанск", "липцы"],
    "donetsk":      ["донецк", "авдеев", "бахмут", "артёмовск", "артемовск", "горловк", "марьинк"],
    "kherson":      ["херсон", "днепр", "каховк", "берислав", "антоновск"],
}

def detect_direction(text: str) -> str | None:
    """Return the direction key whose geo terms appear in `text` (case-insensitive,
    word-boundary), or None. First match wins (dict order)."""
    if not text:
        return None
    low = text.lower()
    for key, terms in GEO_KEYWORDS.items():
        for t in terms:
            if re.search(r"(?<!\w)" + re.escape(t), low):
                return key
    return None
```

- [ ] **Step 4: Implement `resolve_direction_id` in `tagging.py`**

```python
from __future__ import annotations
from .models import IntelDirection
from . import seed

def resolve_direction_id(session, key: str | None) -> int:
    """Resolve a direction key to its id. Unknown/None -> the 'unassigned' bucket
    (seeded on demand). Direction rows are seeded by intel.seed."""
    if key:
        d = session.query(IntelDirection).filter_by(key=key).first()
        if d is not None:
            return d.id
    return seed.ensure_unassigned_direction(session).id
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_geo.py -q`
Expected: 2 passed.

- [ ] **Step 6: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 221 passed).
```bash
git add backend/radar/intel/geo.py backend/radar/intel/tagging.py backend/tests/test_intel_geo.py
git commit -m "feat(intel): geo-keyword direction detection + resolve to unassigned bucket"
```

---

### Task 3: Collector — per-post direction tagging + chat noise filter

**Files:**
- Modify: `backend/radar/intel/collector.py`
- Test: `backend/tests/test_intel_collect_tagging.py`

**Interfaces:**
- Consumes: `geo.detect_direction`, `tagging.resolve_direction_id`, `core.spam.looks_like_ad_cheap`, Task 1 model.
- Produces: `collect_probe(session, probe, provider) -> int` now sets `direction_id` per post via geo detection (default `unassigned`); for `probe.kind == "chat"` applies the hard noise filter and reads via `provider.search_chat`. Exposes `chat_message_relevant(text, author, lexicon_terms) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_collect_tagging.py
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

def test_channel_post_tagged_by_geo():
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelDirection
    s = _sess(); seed.ensure_default_directions(s)
    p = IntelProbe(platform="telegram", kind="channel", query="@rybar", side="ru"); s.add(p); s.commit()
    posts=[SimpleNamespace(post_id="@rybar/1", author="@rybar", text="удар по складу под Суджей",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)]
    prov=SimpleNamespace(search=lambda q,k,c: SimpleNamespace(posts=posts, cursor=None))
    n=collector.collect_probe(s, p, prov)
    assert n==1
    m=s.query(IntelMention).one()
    assert s.get(IntelDirection, m.direction_id).key == "kursk"
    assert m.side == "ru"

def test_channel_post_without_geo_goes_unassigned():
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelDirection
    s = _sess(); seed.ensure_default_directions(s)
    p = IntelProbe(platform="telegram", kind="channel", query="@x", side="ua"); s.add(p); s.commit()
    posts=[SimpleNamespace(post_id="@x/1", author="@x", text="общая сводка дня без географии тут",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)]
    prov=SimpleNamespace(search=lambda q,k,c: SimpleNamespace(posts=posts, cursor=None))
    collector.collect_probe(s, p, prov)
    m=s.query(IntelMention).one()
    assert s.get(IntelDirection, m.direction_id).key == "unassigned"

def test_chat_noise_filter_drops_irrelevant_keeps_relevant():
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention
    s = _sess(); seed.ensure_default_directions(s)
    p = IntelProbe(platform="telegram", kind="chat", query="@chat", side="ru"); s.add(p); s.commit()
    msgs=[
        SimpleNamespace(post_id="@chat/1", author="u1", text="привет всем как дела", followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0),  # noise
        SimpleNamespace(post_id="@chat/2", author="u2", text="прилёт под Суджей, вторичная детонация", followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0),  # relevant (geo)
    ]
    prov=SimpleNamespace(search_chat=lambda handle,term,limit=20,min_id=0: msgs)
    n=collector.collect_probe(s, p, prov)
    assert n==1
    assert s.query(IntelMention).one().post_id == "@chat/2"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_collect_tagging.py -q`
Expected: FAIL (collector still uses `probe.direction_id`, no chat branch).

- [ ] **Step 3: Implement**

In `radar/intel/collector.py`: read the current file and adapt `collect_probe`:
- Import `from .geo import detect_direction`, `from .tagging import resolve_direction_id`, `from ..core.spam import looks_like_ad_cheap`.
- For each post, compute `dir_id = resolve_direction_id(session, detect_direction(post.text))` and write `IntelMention(direction_id=dir_id, side=probe.side, ...)` (replace the old `direction_id=probe.direction_id`).
- Branch on `probe.kind`: `"channel"` → keep `provider.search(probe.query, probe.kind, cursor).posts`; `"chat"` → `provider.search_chat(probe.query, term="", limit=50, min_id=int(probe.watermark or 0) if (probe.watermark or "").isdigit() else 0)` and iterate that list.
- Add `chat_message_relevant(text, author, lexicon_terms=()) -> bool`: returns False if `looks_like_ad_cheap(text, author)` or `len(text.strip()) < MIN_TEXT_LEN` or no alpha word; returns True only if `detect_direction(text)` is not None OR any lexicon term appears in `text.lower()` (word-boundary). (Phase 1: `lexicon_terms` defaults empty; Task 5 wires real lexicon.)
- For `kind == "chat"`, skip a message unless `chat_message_relevant(...)`. For `kind == "channel"`, keep the existing light filter (length + dedup).
- Keep the per-row `begin_nested()` savepoint dedup and watermark advance.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_collect_tagging.py -q`
Expected: 3 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 224 passed). Ensure the prior `tests/test_intel_collector.py` still passes (adapt it if it asserted `direction_id` from probe — update those asserts to expect geo/unassigned).
```bash
git add backend/radar/intel/collector.py backend/tests/test_intel_collect_tagging.py backend/tests/test_intel_collector.py
git commit -m "feat(intel): per-post geo direction tagging + chat noise filter in collector"
```

---

### Task 4: Source-file intake

**Files:**
- Create: `backend/radar/intel/intake.py`
- Test: `backend/tests/test_intel_intake.py`

**Interfaces:**
- Produces: `ingest_sources(session, path) -> dict` (counts `{added, updated}`); upserts `IntelProbe` keyed by normalized `query` (the link/`@handle`). File line format: `link | side | kind` (`side` in {ru, ua}, `kind` in {channel, chat}); blank lines and `#` comments skipped.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_intake.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_ingest_sources_upserts(tmp_path):
    from radar.intel.intake import ingest_sources
    from radar.intel.models import IntelProbe
    s = _sess()
    f = tmp_path / "src.txt"
    f.write_text("# my sources\n@rybar | ru | channel\nhttps://t.me/foo | ua | chat\n\n", encoding="utf-8")
    out = ingest_sources(s, str(f))
    assert out == {"added": 2, "updated": 0}
    p = s.query(IntelProbe).filter_by(query="@rybar").one()
    assert p.side == "ru" and p.kind == "channel"
    # re-ingest with changed side -> update, not duplicate
    f.write_text("@rybar | ua | channel\n", encoding="utf-8")
    out2 = ingest_sources(s, str(f))
    assert out2 == {"added": 0, "updated": 1}
    assert s.query(IntelProbe).filter_by(query="@rybar").one().side == "ua"
    assert s.query(IntelProbe).count() == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_intake.py -q`
Expected: FAIL (no `radar.intel.intake`).

- [ ] **Step 3: Implement**

```python
# backend/radar/intel/intake.py
from __future__ import annotations
from .models import IntelProbe, IntelLexicon

_SIDES = {"ru", "ua"}
_KINDS = {"channel", "chat"}

def ingest_sources(session, path: str) -> dict:
    added = updated = 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            query, side, kind = parts[0], parts[1].lower(), parts[2].lower()
            if side not in _SIDES or kind not in _KINDS or not query:
                continue
            p = session.query(IntelProbe).filter_by(query=query).first()
            if p is None:
                session.add(IntelProbe(platform="telegram", kind=kind, query=query, side=side))
                added += 1
            else:
                p.side, p.kind = side, kind
                updated += 1
    session.commit()
    return {"added": added, "updated": updated}

def ingest_lexicon(session, path: str) -> dict:
    added = updated = 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            term = parts[0].lower()
            meaning = parts[1] if len(parts) > 1 else ""
            category = parts[2] if len(parts) > 2 else None
            if not term:
                continue
            row = session.query(IntelLexicon).filter_by(term=term).first()
            if row is None:
                session.add(IntelLexicon(term=term, meaning=meaning, category=category))
                added += 1
            else:
                row.meaning, row.category = meaning, category
                updated += 1
    session.commit()
    return {"added": added, "updated": updated}

if __name__ == "__main__":
    import sys
    from .seed import ensure_default_directions  # noqa
    from ..core.db import get_session
    cmd, path = sys.argv[1], sys.argv[2]
    with get_session() as s:
        out = ingest_sources(s, path) if cmd == "sources" else ingest_lexicon(s, path)
        print(out)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_intake.py -q`
Expected: 1 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 225 passed).
```bash
git add backend/radar/intel/intake.py backend/tests/test_intel_intake.py
git commit -m "feat(intel): idempotent file intake for sources + lexicon (CLI: python -m radar.intel.intake)"
```

---

### Task 5: Lexicon-aware chat noise gate

**Files:**
- Modify: `backend/radar/intel/collector.py`
- Test: extend `backend/tests/test_intel_collect_tagging.py`

**Interfaces:**
- Consumes: `IntelLexicon` (Task 1), `ingest_lexicon` (Task 4).
- Produces: `collect_probe` loads active lexicon terms once per call and passes them to `chat_message_relevant`, so a chat message with a slang term (e.g. "300") but no geo-key still passes the gate.

- [ ] **Step 1: Write the failing test (append)**

```python
def test_chat_lexicon_term_passes_gate(tmp_path):
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelLexicon
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:"); Base.metadata.create_all(eng); s = Session(eng)
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="300", meaning="раненые", category="casualties")); s.commit()
    p = IntelProbe(platform="telegram", kind="chat", query="@c", side="ru"); s.add(p); s.commit()
    msgs=[SimpleNamespace(post_id="@c/1", author="u", text="у них трое 300 после обстрела",
                          followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)]  # no geo, but lexicon "300"
    prov=SimpleNamespace(search_chat=lambda handle,term,limit=20,min_id=0: msgs)
    n=collector.collect_probe(s, p, prov)
    assert n==1 and s.query(IntelMention).count()==1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_collect_tagging.py::test_chat_lexicon_term_passes_gate -q`
Expected: FAIL (lexicon not consulted; message dropped).

- [ ] **Step 3: Implement**

In `collect_probe`, before the message loop, load `lexicon_terms = [t for (t,) in session.query(IntelLexicon.term).all()]`. Pass `lexicon_terms` into `chat_message_relevant(text, author, lexicon_terms)`. In `chat_message_relevant`, the relevance condition becomes: `detect_direction(text) is not None OR any(re.search(r"(?<!\w)"+re.escape(term), text.lower()) for term in lexicon_terms)` (plus the existing spam/length drops). Import `IntelLexicon` from `.models` and `re`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_collect_tagging.py -q`
Expected: 4 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 226 passed).
```bash
git add backend/radar/intel/collector.py backend/tests/test_intel_collect_tagging.py
git commit -m "feat(intel): military-lexicon terms admit slang chat messages through the noise gate"
```

---

### Task 6: Collection pass (rotation + flood breaker)

**Files:**
- Create: `backend/radar/intel/passes.py`
- Test: `backend/tests/test_intel_passes.py`

**Interfaces:**
- Consumes: `collector.collect_probe`, `IntelProbe`, `TelegramFloodWait`.
- Produces: `run_intel_collect(session, tg_provider) -> None` — rotate due `IntelProbe` by `next_run_at`, cap per run (`MAX_INTEL_SOURCES_PER_RUN`, env default 12), call `collect_probe`, advance `next_run_at` by `interval_sec`, abort the batch on `TelegramFloodWait` (mirror `news/passes.run_topic_tg_pass`). No-op when `tg_provider is None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_passes.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_run_intel_collect_noop_without_provider():
    from radar.intel.passes import run_intel_collect
    run_intel_collect(_sess(), None)  # must not raise

def test_run_intel_collect_collects_due_channel():
    from radar.intel import seed, passes
    from radar.intel.models import IntelProbe, IntelMention
    s = _sess(); seed.ensure_default_directions(s)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    s.add(IntelProbe(platform="telegram", kind="channel", query="@rybar", side="ru", next_run_at=past)); s.commit()
    posts=[SimpleNamespace(post_id="@rybar/1", author="@rybar", text="бои под Авдеевкой",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)]
    prov=SimpleNamespace(search=lambda q,k,c: SimpleNamespace(posts=posts, cursor=None))
    passes.run_intel_collect(s, prov)
    assert s.query(IntelMention).count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_passes.py -q`
Expected: FAIL (no `radar.intel.passes`).

- [ ] **Step 3: Implement**

Read `radar/news/passes.py::run_topic_tg_pass` and mirror its rotation/flood structure for intel:
```python
from __future__ import annotations
import os, logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from .models import IntelProbe
from . import collector

log = logging.getLogger("radar.intel.passes")
MAX_INTEL_SOURCES_PER_RUN = int(os.getenv("MAX_INTEL_SOURCES_PER_RUN", "12"))

def run_intel_collect(session: Session, tg_provider) -> None:
    if tg_provider is None:
        return
    from ..core.providers.telegram import TelegramFloodWait
    now = datetime.now(timezone.utc)
    due = (session.query(IntelProbe)
           .filter(IntelProbe.next_run_at <= now)
           .order_by(IntelProbe.next_run_at.asc())
           .limit(MAX_INTEL_SOURCES_PER_RUN).all())
    for probe in due:
        try:
            collector.collect_probe(session, probe, tg_provider)
            probe.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=probe.interval_sec or 3600)
            session.commit()
        except TelegramFloodWait as e:
            log.warning("intel collect flood-wait, aborting batch: %s", e)
            return
        except Exception:
            log.exception("intel source %s failed", probe.id)
            session.rollback()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_passes.py -q`
Expected: 2 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 228 passed).
```bash
git add backend/radar/intel/passes.py backend/tests/test_intel_passes.py
git commit -m "feat(intel): scheduler collect pass (rotation, cap, flood breaker)"
```

---

### Task 7: LLM direction re-tagging pass

**Files:**
- Modify: `backend/radar/intel/tagging.py`
- Test: `backend/tests/test_intel_retag.py`

**Interfaces:**
- Consumes: `..core.llm` (`complete`, `LLMNotConfigured`), `IntelMention`, `IntelLexicon`, `geo.GEO_KEYWORDS` (valid keys), `resolve_direction_id`.
- Produces: `retag_unassigned(session, limit=50) -> int` — re-tag mentions currently in the `unassigned` bucket using the LLM (with lexicon glossary context); returns the count re-tagged. No-op returning 0 when the LLM key is absent.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intel_retag.py
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

def test_retag_unassigned_uses_llm(monkeypatch):
    from radar.intel import seed, tagging
    from radar.intel.models import IntelMention, IntelDirection
    s = _sess(); seed.ensure_default_directions(s)
    uid = tagging.resolve_direction_id(s, None)  # unassigned
    s.add(IntelMention(direction_id=uid, platform="telegram", post_id="p1", author="a",
                       side="ru", text="ночью прилёт по логистике, детонация", created_at=datetime.now(timezone.utc)))
    s.commit()
    # stub the LLM to return a direction key
    monkeypatch.setattr(tagging, "_llm_classify", lambda text, keys, glossary: "kursk")
    n = tagging.retag_unassigned(s, limit=10)
    assert n == 1
    m = s.query(IntelMention).one()
    assert s.get(IntelDirection, m.direction_id).key == "kursk"

def test_retag_noop_without_llm(monkeypatch):
    from radar.intel import seed, tagging
    from radar.intel.models import IntelMention
    s = _sess(); seed.ensure_default_directions(s)
    uid = tagging.resolve_direction_id(s, None)
    s.add(IntelMention(direction_id=uid, platform="telegram", post_id="p2", author="a",
                       side="ru", text="нечто без географии", created_at=datetime.now(timezone.utc)))
    s.commit()
    from ..core import llm  # type: ignore
    def _raise(*a, **k):
        from radar.core.llm import LLMNotConfigured
        raise LLMNotConfigured()
    monkeypatch.setattr("radar.core.llm.complete", _raise)
    assert tagging.retag_unassigned(s, limit=10) == 0
```

> Note: in `test_retag_noop_without_llm` the `from ..core import llm` line is illustrative — use `monkeypatch.setattr("radar.core.llm.complete", _raise)` as shown; `_llm_classify` must call `core.llm.complete` and let `LLMNotConfigured` propagate so `retag_unassigned` catches it and returns 0.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_retag.py -q`
Expected: FAIL (no `retag_unassigned` / `_llm_classify`).

- [ ] **Step 3: Implement (append to `tagging.py`)**

```python
def _llm_classify(text: str, keys: list[str], glossary: str) -> str | None:
    """Ask the LLM which direction key the text belongs to, or None. Raises
    LLMNotConfigured if no key — caller treats that as 'skip'."""
    from ..core.llm import complete
    system = ("Ты классифицируешь сообщение по направлению фронта. "
              "Верни РОВНО один ключ из списка или 'none'. Глоссарий сленга:\n" + glossary)
    user = f"Ключи: {', '.join(keys)}\nСообщение: {text}\nКлюч:"
    out = (complete(system, user, max_tokens=8) or "").strip().lower()
    return out if out in keys else None

def retag_unassigned(session, limit: int = 50) -> int:
    from .models import IntelMention, IntelLexicon, IntelDirection
    from .geo import GEO_KEYWORDS
    from ..core.llm import LLMNotConfigured
    uid = seed.ensure_unassigned_direction(session).id
    rows = (session.query(IntelMention).filter(IntelMention.direction_id == uid)
            .order_by(IntelMention.id.desc()).limit(limit).all())
    if not rows:
        return 0
    glossary = "\n".join(f"{t} = {m}" for (t, m) in session.query(IntelLexicon.term, IntelLexicon.meaning).all())
    keys = list(GEO_KEYWORDS.keys())
    changed = 0
    try:
        for m in rows:
            key = _llm_classify(m.text, keys, glossary)
            if key:
                m.direction_id = resolve_direction_id(session, key)
                changed += 1
    except LLMNotConfigured:
        session.rollback()
        return 0
    session.commit()
    return changed
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_retag.py -q`
Expected: 2 passed.

- [ ] **Step 5: Full suite + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 230 passed).
```bash
git add backend/radar/intel/tagging.py backend/tests/test_intel_retag.py
git commit -m "feat(intel): LLM re-tagging of unassigned mentions with lexicon glossary (skips without key)"
```

---

### Task 8: Scheduler wiring + tick order

**Files:**
- Modify: `backend/radar/core/scheduler.py`
- Test: `backend/tests/test_intel_passes.py` (extend)

**Interfaces:**
- Consumes: `intel.passes.run_intel_collect`, `intel.stories.update_stories`, `intel.tagging.retag_unassigned`.
- Produces: a scheduler step that, per tick, runs intel collect → LLM retag → cluster per direction. Mirrors how `_run_topic_tg_pass` is wired.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_intel_passes.py
def test_intel_tick_collects_and_clusters(monkeypatch):
    from radar.intel import seed, passes, stories
    from radar.intel.models import IntelProbe, IntelMention, IntelStory, IntelDirection
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    s = _sess(); seed.ensure_default_directions(s)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    s.add(IntelProbe(platform="telegram", kind="channel", query="@rybar", side="ru", next_run_at=past)); s.commit()
    posts=[SimpleNamespace(post_id=f"@rybar/{i}", author=f"@a{i}", text="удар по Работино, активизация",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0) for i in range(3)]
    prov=SimpleNamespace(search=lambda q,k,c: SimpleNamespace(posts=posts, cursor=None))
    # the tick: collect, then cluster each direction that got mentions
    passes.run_intel_tick(s, tg_provider=prov, embed=lambda t:[float(len(t))])
    assert s.query(IntelMention).count() == 3
    assert s.query(IntelStory).filter(IntelStory.direction_id.isnot(None)).count() >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_intel_passes.py::test_intel_tick_collects_and_clusters -q`
Expected: FAIL (no `run_intel_tick`).

- [ ] **Step 3: Implement**

Add to `radar/intel/passes.py`:
```python
def run_intel_tick(session, tg_provider, web_provider=None, embed=None) -> None:
    """One intel cycle: collect -> LLM retag -> cluster each touched direction."""
    from . import tagging, stories
    from .models import IntelMention
    run_intel_collect(session, tg_provider)
    try:
        tagging.retag_unassigned(session)
    except Exception:
        log.exception("intel retag failed (skipped)")
    dir_ids = [d for (d,) in session.query(IntelMention.direction_id)
               .filter(IntelMention.incident_id.is_(None)).distinct().all() if d]
    for did in dir_ids:
        try:
            stories.update_stories(session, did, embed=embed)
        except Exception:
            log.exception("intel clustering failed for direction %s", did)
```
In `radar/core/scheduler.py`: add a thin delegate `_run_intel_pass(session, tg_provider)` that calls `radar.intel.passes.run_intel_tick(session, tg_provider)`, and invoke it in the tick alongside the existing topic/brand passes (mirror how `_run_topic_tg_pass` is called in `_run_once`). Leave news/brand wiring unchanged.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_intel_passes.py -q`
Expected: 3 passed.

- [ ] **Step 5: Full suite + boot smoke + commit**

Run: `cd backend && python3 -m pytest -q 2>&1 | tail -2` (expect 231 passed).
Run: `cd backend && python3 -c "import radar.app; print('app ok')"` → `app ok`.
```bash
git add backend/radar/intel/passes.py backend/radar/core/scheduler.py backend/tests/test_intel_passes.py
git commit -m "feat(intel): wire collect->retag->cluster tick into the scheduler"
```

---

## Notes / Deferred (per spec §2)
- **Existing-DB migration:** making `IntelProbe.direction_id` nullable only affects freshly-created tables; an existing SQLite DB (e.g. `echo_radar.db`) keeps the old NOT NULL column, and Task 4 intake inserts probes WITHOUT a direction_id → it would fail there. Since `intel_*` data is pre-production/test-only, Task 1 should include a one-time guard in `init_db` (or a tiny helper) that, if `intel_probes.direction_id` is NOT NULL on an existing DB, rebuilds the `intel_probes` table to the new schema (SQLite cannot `ALTER` a NOT NULL away). Simplest acceptable alternative for dev: drop the `intel_*` tables once and let `create_all` rebuild them. Confirm fresh `init_db` + intake works end-to-end during Task 8.
- Phase 2 (auto-suggestion of channels + approval queue) is a separate spec/plan.
- In-UI editing of geo dictionary and lexicon, and in-UI slang decode/tooltips, are deferred (file ingest + table now).
- Geo dictionary lives in code (`geo.py`) for Phase 1; promoting it to a DB table the operator edits is a later enhancement.
- Tune LLM retag cadence/batch and chat back-read depth against real flood limits during rollout.
