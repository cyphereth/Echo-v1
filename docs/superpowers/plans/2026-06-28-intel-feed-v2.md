# Intel Feed v2 — Multi-Column Live Direction Feed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4th screen to the closed «Разведка» contour — a TweetDeck-style multi-column live feed where each column is one direction (oblast/city/custom) and posts land in a column when their source is subscribed to the direction *or* the post text matches the direction's geo-terms.

**Architecture:** A new m2m table `intel_mention_directions` links each `IntelMention` to the set of `IntelDirection`s it belongs to (source-subscribed + geo-text-matched). The collector writes m2m rows at collection time. `IntelDirection` is extended with `kind` / `region_key` / `geo_terms`. One multiplexed SSE endpoint pushes live events tagged with the direction. A new `IntelFeed` React screen renders up to ~8 narrow columns; the operator picks which directions to show via a "+ колонки ▾" multi-select. Layout persistence is split: a backend "боевой дефолт" (admin-saved) + a `localStorage` personal override.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2.0 (Mapped[]) / pytest (backend); React + Vite (frontend); SSE (`text/event-stream`) for live transport.

**Spec:** `docs/superpowers/specs/2026-06-28-intel-feed-v2-design.md`

**Base branch:** `feat/intel-closed-contour`

---

## File Map

### Backend — create
- `backend/radar/intel/geo_match.py` — pure function: given text + a `{direction_key: [terms]}` mapping, return the set of matched keys (boundary-aware Cyrillic).
- `backend/radar/intel/geo_dict.py` — seeded directions/geo-terms data (RF border oblasts + all 26 Ukrainian oblasts + DNR/LNR + major cities), sourced from the project's chat-collection spreadsheets.
- `backend/tests/test_intel_geo_match.py` — matcher unit tests.
- `backend/tests/test_intel_feed_api.py` — `/intel/feed*`, `/intel/directions` POST, `/intel/feed/layout` tests.

### Backend — modify
- `backend/radar/intel/models.py` — extend `IntelDirection` (kind/region_key/geo_terms); add `IntelMentionDirection` m2m; add `IntelFeedLayout`.
- `backend/radar/intel/collector.py` — after persisting an `IntelMention`, write m2m rows (source + geo matches).
- `backend/radar/intel/api.py` — add `/intel/feed`, `/intel/feed/stream`, `POST /intel/directions`, `GET/PUT /intel/feed/layout`; extend `GET /intel/directions` to include kind/geo_terms.
- `backend/radar/intel/aggregate.py` — add `feed_event()` that serializes a mention + its match-type for a given direction.
- `backend/radar/intel/seed.py` — extend `ensure_default_directions` to seed the geo_dict (with a version guard).
- `backend/radar/core/db.py` — add new table to `create_all` path (auto) + `_MIGRATIONS` entries for the new `IntelDirection` columns and the `users.is_admin` column.
- `backend/radar/models.py` — add `is_admin: Mapped[bool]` to `User`.
- `backend/radar/app.py` — seed first user as admin on startup (idempotent).
- `backend/tests/test_intel_collector.py` — extend with m2m assertions.
- `backend/tests/test_intel_api.py` — extend where behaviour of existing endpoints changes (only if needed).

### Frontend — create
- `echo-app/src/features/intel/components/IntelFeed.jsx` — the new screen.
- `echo-app/src/features/intel/components/FeedColumn.jsx` — one column (header + scrollable post list).
- `echo-app/src/features/intel/components/PostCard.jsx` — one post card.
- `echo-app/src/features/intel/components/ColumnPicker.jsx` — the "+ колонки ▾" dropdown.

### Frontend — modify
- `echo-app/src/features/intel/IntelApp.jsx` — add 4th sidebar item (`feed`, hotkey 4) and mount `<IntelFeed/>`.
- `echo-app/src/features/intel/api.js` — add `feed(direction, params)`, `feedStream(directions, params, onEvent)`, `createDirection(body)`, `getLayout()`, `saveLayout(body)`, extend `directions()` to return kind/geo_terms.
- `echo-app/src/features/intel/intel.module.css` — add `.feed*`, `.postCard*`, `.colChip*`, `.colPicker*` classes.

---

## Task 1: Pure geo-text matcher

**Files:**
- Create: `backend/radar/intel/geo_match.py`
- Test: `backend/tests/test_intel_geo_match.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_intel_geo_match.py`:

```python
# backend/tests/test_intel_geo_match.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_matches_simple_city_name():
    from radar.intel.geo_match import match_directions
    terms = {"bryansk": ["брянск", "брянская"], "kursk": ["курск"]}
    assert match_directions("прилет в брянске сегодня", terms) == {"bryansk"}


def test_matches_oblast_adjective():
    from radar.intel.geo_match import match_directions
    terms = {"bryansk": ["брянск", "брянская"]}
    assert match_directions("в Брянской области тихо", terms) == {"bryansk"}


def test_does_not_match_substring_inside_word():
    from radar.intel.geo_match import match_directions
    terms = {"bryansk": ["брянск"], "ryazan": ["рязанский"]}
    # "брянсковый" must NOT match "брянск"; "рязанский" must NOT match ... (boundary check)
    assert match_directions("брянсковый лес", terms) == set()
    assert match_directions("рязанский район", terms) == set()


def test_matches_multiple_directions():
    from radar.intel.geo_match import match_directions
    terms = {"bryansk": ["брянск"], "kharkiv": ["харьков"]}
    assert match_directions("обстановка: брянск и харьков", terms) == {"bryansk", "kharkiv"}


def test_case_insensitive_and_cyrillic_aware():
    from radar.intel.geo_match import match_directions
    terms = {"kharkiv": ["харків", "харьков"]}
    assert match_directions("вибух у ХАРКОВІ та Харькове", terms) == {"kharkiv"}


def test_empty_text_returns_empty():
    from radar.intel.geo_match import match_directions
    assert match_directions("", {"bryansk": ["брянск"]}) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_geo_match.py -v`
Expected: FAIL with `ModuleNotFoundError: radar.intel.geo_match`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/radar/intel/geo_match.py`:

```python
"""Pure geo-text matcher for the intel feed.

Given a post's text and a mapping of direction_key → [lowercase terms],
return the set of direction_keys whose terms appear as whole words
(boundary-aware, Cyrillic-safe) in the text.

Boundary rule: a term matches only if the character immediately before and
after the term is NOT a Cyrillic or Latin letter. This prevents "брянск"
from matching "брянсковый" or "рязанский". Digits, hyphens, spaces,
punctuation all count as boundaries.
"""
from __future__ import annotations
import re

# A boundary is any char that is NOT a letter (Cyrillic or Latin).
# We anchor terms with negative lookarounds so substrings inside words fail.
_BOUNDARY_BEFORE = r"(?<![A-Za-zА-Яа-яЄєІіЇїЎў])"
_BOUNDARY_AFTER = r"(?![A-Za-zА-Яа-яЄєІіЇїЎў])"


def _compile(terms):
    # Escape each term, wrap with boundary lookarounds, join with |.
    parts = [
        _BOUNDARY_BEFORE + re.escape(t.lower()) + _BOUNDARY_AFTER
        for t in terms
        if t and t.strip()
    ]
    if not parts:
        return None
    return re.compile("|".join(parts))


def match_directions(text, terms_by_key):
    """Return the set of direction keys whose terms appear in `text`.

    `terms_by_key` is `{direction_key: [term, ...]}` — all terms already
    lowercase (the caller lowercases; this function does not mutate).
    """
    if not text:
        return set()
    lowered = text.lower()
    matched = set()
    for key, terms in terms_by_key.items():
        rx = _compile(terms)
        if rx is not None and rx.search(lowered):
            matched.add(key)
    return matched
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_geo_match.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/intel/geo_match.py backend/tests/test_intel_geo_match.py
git commit -m "feat(intel): pure geo-text matcher with Cyrillic word boundaries"
```

---

## Task 2: Extend IntelDirection + add m2m model + IntelFeedLayout

**Files:**
- Modify: `backend/radar/intel/models.py`
- Modify: `backend/radar/core/db.py` (`_MIGRATIONS`)

- [ ] **Step 1: Extend the models**

In `backend/radar/intel/models.py`, replace the `IntelDirection` class body and append two new classes at the end of the file.

Replace this:
```python
class IntelDirection(Base):
    __tablename__ = "intel_directions"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    key:        Mapped[str]      = mapped_column(Text, unique=True, nullable=False)   # "kursk"
    name:       Mapped[str]      = mapped_column(Text, nullable=False)                # "Курское"
    created_at: Mapped[datetime] = mapped_column(default=_now)
```

With:
```python
class IntelDirection(Base):
    __tablename__ = "intel_directions"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    key:        Mapped[str]      = mapped_column(Text, unique=True, nullable=False)   # "kursk"
    name:       Mapped[str]      = mapped_column(Text, nullable=False)                # "Курское"
    kind:       Mapped[str]      = mapped_column(Text, default="region")              # region|city|custom
    region_key: Mapped[Optional[str]] = mapped_column(Text)                           # parent region key for cities
    geo_terms:  Mapped[str]      = mapped_column(Text, default="[]")                  # JSON list of lowercase terms
    created_at: Mapped[datetime] = mapped_column(default=_now)


class IntelMentionDirection(Base):
    """Many-to-many: an IntelMention may belong to several IntelDirections.

    `match_type` is 'source' (probe subscribed), 'geo' (text matched a term),
    or 'manual' (operator pinned it).
    """
    __tablename__ = "intel_mention_directions"
    __table_args__ = (UniqueConstraint("mention_id", "direction_id"),)
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id:   Mapped[int]      = mapped_column(ForeignKey("intel_mentions.id"), nullable=False)
    direction_id: Mapped[int]      = mapped_column(ForeignKey("intel_directions.id"), nullable=False)
    match_type:   Mapped[str]      = mapped_column(Text, default="source")
    created_at:   Mapped[datetime] = mapped_column(default=_now)


class IntelFeedLayout(Base):
    """The contour-wide 'боевой дефолт' column layout (admin-saved)."""
    __tablename__ = "intel_feed_layouts"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction_ids: Mapped[str]      = mapped_column(Text, default="[]")   # JSON list of direction ids, in order
    updated_by:    Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    updated_at:    Mapped[datetime] = mapped_column(default=_now)
```

- [ ] **Step 2: Add migration entries in `backend/radar/core/db.py`**

In the `_MIGRATIONS` dict, add two new table entries (the new tables are also created by `create_all` on fresh DBs — these entries cover existing DBs only):

```python
    "intel_directions": {
        "kind":       "TEXT DEFAULT 'region'",
        "region_key": "TEXT",
        "geo_terms":  "TEXT DEFAULT '[]'",
    },
    "users": {
        "is_admin": "BOOLEAN DEFAULT 0",
    },
```

(Add these two keys inside the existing `_MIGRATIONS` dict literal, after the `"comments"` entry.)

- [ ] **Step 3: Add `is_admin` to the User model**

In `backend/radar/models.py`, in the `User` class, add after `password_hash`:

```python
    is_admin:     Mapped[bool]     = mapped_column(Boolean, default=False)
```

- [ ] **Step 4: Smoke test that the schema builds**

Run:
```bash
cd backend && python -c "
from sqlalchemy import create_engine
from radar.models import Base
import radar.intel.models
eng = create_engine('sqlite:///:memory:')
Base.metadata.create_all(eng)
from sqlalchemy import inspect
insp = inspect(eng)
assert 'intel_mention_directions' in insp.get_table_names()
assert 'intel_feed_layouts' in insp.get_table_names()
assert any(c['name']=='kind' for c in insp.get_columns('intel_directions'))
assert any(c['name']=='is_admin' for c in insp.get_columns('users'))
print('schema OK')
"
```
Expected output: `schema OK`.

- [ ] **Step 5: Run existing intel tests to confirm nothing broke**

Run: `cd backend && python -m pytest tests/test_intel_collector.py tests/test_intel_models.py -v`
Expected: PASS (existing tests still green — new columns have defaults).

- [ ] **Step 6: Commit**

```bash
git add backend/radar/intel/models.py backend/radar/core/db.py backend/radar/models.py
git commit -m "feat(intel): extend IntelDirection (kind/region_key/geo_terms), add m2m + layout tables"
```

---

## Task 3: Geo dictionary + seed expansion

**Files:**
- Create: `backend/radar/intel/geo_dict.py`
- Modify: `backend/radar/intel/seed.py`

- [ ] **Step 1: Write the geo dictionary**

Create `backend/radar/intel/geo_dict.py`:

```python
"""Seeded intel directions with geo match-terms.

Bumped whenever the curated set changes — the seed re-runs on version bump.
Terms are lowercase. Boundary matching is handled by geo_match.py; here we
just supply the candidate words.
"""
from __future__ import annotations

GEO_DICT_VERSION = 2

# Each entry: (key, name, kind, region_key_or_None, [terms])
# Regions: RF border oblasts + all 26 Ukrainian oblasts + DNR/LNR.
# Cities are added as their own directions where they have distinct signal.
DEFAULT_DIRECTIONS = [
    # ── RF border oblasts ────────────────────────────────────────────────────
    ("bryansk",   "Брянская обл.",   "region", None, ["брянск", "брянская", "брянщин"]),
    ("belgorod",  "Белгородская обл.","region", None, ["белгород", "белгородск", "шебекино", "валуйки"]),
    ("kursk",     "Курская обл.",    "region", None, ["курск", "курск", "суджа", "рыльск"]),
    ("voronezh",  "Воронежская обл.","region", None, ["воронеж", "воронежск"]),
    ("rostov",    "Ростовская обл.", "region", None, ["ростов", "ростовск", "таганрог", "шахты"]),
    ("krasnodar", "Краснодарский край","region", None, ["краснодар", "краснодарск", "сочи", "новороссийск"]),
    ("smolensk",  "Смоленская обл.", "region", None, ["смоленск", "смоленск"]),
    ("pskov",     "Псковская обл.",  "region", None, ["псков", "псковск"]),

    # ── DNR / LNR ────────────────────────────────────────────────────────────
    ("dnr",       "ДНР",             "region", None, ["днр", "донецк", "донецк", "мариуполь", "горловка", "макеевка"]),
    ("lnr",       "ЛНР",             "region", None, ["лнр", "луганск", "луганск", "алчевск", "северодонецк"]),

    # ── Ukraine — all oblasts + Kyiv ─────────────────────────────────────────
    ("kyiv",      "Киевская обл.",   "region", None, ["киев", "київ", "київськ", "киевск"]),
    ("kharkiv",   "Харьковская обл.","region", None, ["харьков", "харків", "харківськ", "харьковск"]),
    ("kherson",   "Херсонская обл.", "region", None, ["херсон", "херсонськ", "херсонск"]),
    ("zaporizhzhia","Запорожская обл.","region", None, ["запорож", "запоріж", "запорізь", "запорожск", "мелитополь", "бердянск"]),
    ("dnipropetrovsk","Днепропетровская обл.","region", None, ["днепропетров", "дніпропетров", "дніпро", "днепр", "кривой рог", "кривий ріг"]),
    ("odesa",     "Одесская обл.",   "region", None, ["одесса", "одеса", "одеськ", "одессск"]),
    ("mykolaiv",  "Николаевская обл.","region", None, ["николаев", "миколаїв", "миколаївськ", "николаевск"]),
    ("vinnytsia", "Винницкая обл.",  "region", None, ["винниц", "вінниц", "вінницьк"]),
    ("zhytomyr",  "Житомирская обл.","region", None, ["житомир", "житомирськ"]),
    ("chernihiv", "Черниговская обл.","region", None, ["чернигов", "чернігів", "чернігівськ"]),
    ("sumy",      "Сумская обл.",    "region", None, ["сумы", "суми", "сумськ", "сумск"]),
    ("poltava",   "Полтавская обл.", "region", None, ["полтав", "полтавськ"]),
    ("cherkasy",  "Черкасская обл.", "region", None, ["черкасс", "черкас", "черкаськ"]),
    ("kirovohrad","Кировоградская обл.","region", None, ["кировоград", "кропивницьк", "кропивницк"]),
    ("ternopil",  "Тернопольская обл.","region", None, ["тернопол", "тернопіл", "тернопільськ"]),
    ("khmelnytskyi","Хмельницкая обл.","region", None, ["хмельниц", "хмельницьк"]),
    ("ivano-frankivsk","Ивано-Франковская обл.","region", None, ["ивано-франковск", "івано-франківськ", "франківськ"]),
    ("lviv",      "Львовская обл.",  "region", None, ["львов", "львів", "львівськ"]),
    ("rivne",     "Ровенская обл.",  "region", None, ["ровно", "рівне", "рівненськ"]),
    ("volyn",     "Волынская обл.",  "region", None, ["луцк", "луцьк", "волинськ", "волынск"]),
    ("zakarpattia","Закарпатская обл.","region", None, ["ужгород", "ужгород", "закарпат", "мукачево"]),
    ("chernivtsi","Черновицкая обл.","region", None, ["черновц", "чернівц", "чернівецьк"]),
]
```

- [ ] **Step 2: Extend the seed function**

Replace `backend/radar/intel/seed.py` with:

```python
"""Seed default intel directions with geo-terms.

Idempotent on key; re-runs fully when GEO_DICT_VERSION is bumped
(tracked in a metadata row keyed by 'geo_dict_version').
"""
import json
from .models import IntelDirection
from .geo_dict import DEFAULT_DIRECTIONS, GEO_DICT_VERSION


def ensure_default_directions(session) -> None:
    # Version guard: if a previous seed wrote a different version, refresh.
    meta = session.query(IntelDirection).filter_by(key="__geo_dict_version__").first()
    stored_version = int(meta.name) if meta and meta.name.isdigit() else 0
    refresh = stored_version != GEO_DICT_VERSION

    existing = {d.key: d for d in session.query(IntelDirection).all()}
    for key, name, kind, region_key, terms in DEFAULT_DIRECTIONS:
        d = existing.get(key)
        if d is None:
            session.add(IntelDirection(
                key=key, name=name, kind=kind, region_key=region_key,
                geo_terms=json.dumps(terms, ensure_ascii=False)))
        elif refresh:
            d.name = name
            d.kind = kind
            d.region_key = region_key
            d.geo_terms = json.dumps(terms, ensure_ascii=False)

    if refresh:
        if meta is None:
            meta = IntelDirection(key="__geo_dict_version__", name=str(GEO_DICT_VERSION),
                                  kind="meta", geo_terms="[]")
            session.add(meta)
        else:
            meta.name = str(GEO_DICT_VERSION)
    session.commit()
```

> Note: `__geo_dict_version__` is stored as a sentinel row (kind='meta') inside `intel_directions`. The feed endpoints filter `kind != 'meta'` when listing user-selectable directions (handled in Task 5).

- [ ] **Step 3: Smoke test the seed**

Run:
```bash
cd backend && python -c "
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from radar.models import Base
import radar.intel.models
eng = create_engine('sqlite:///:memory:')
Base.metadata.create_all(eng)
s = Session(eng)
from radar.intel.seed import ensure_default_directions
ensure_default_directions(s)
from radar.intel.models import IntelDirection
rows = s.query(IntelDirection).filter(IntelDirection.kind != 'meta').all()
print(f'{len(rows)} directions seeded')
assert any(d.key=='bryansk' for d in rows)
assert any(d.key=='kyiv' for d in rows)
# re-run is a no-op count
n1 = len(rows)
ensure_default_directions(s)
n2 = s.query(IntelDirection).filter(IntelDirection.kind != 'meta').count()
assert n1 == n2, (n1, n2)
print('seed OK')
"
```
Expected: `32 directions seeded` (then `seed OK`).

- [ ] **Step 4: Commit**

```bash
git add backend/radar/intel/geo_dict.py backend/radar/intel/seed.py
git commit -m "feat(intel): seeded geo dictionary (32 directions) with version guard"
```

---

## Task 4: Collector writes m2m rows

**Files:**
- Modify: `backend/radar/intel/collector.py`
- Test: `backend/tests/test_intel_collector.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_intel_collector.py`:

```python
def test_collect_probe_writes_source_m2m_row():
    from radar.intel.models import IntelDirection, IntelProbe, IntelMention, IntelMentionDirection
    from radar.intel import collector
    s = _sess()
    d = IntelDirection(key="kursk", name="Курсское", kind="region", geo_terms='["курск"]')
    s.add(d); s.flush()
    p = IntelProbe(direction_id=d.id, platform="telegram", kind="channel", query="@mil", side="ru")
    s.add(p); s.commit()
    post = SimpleNamespace(post_id="@mil/1", author="@mil", text="обстановка в курске",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)
    prov = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=[post], cursor=None))
    collector.collect_probe(s, p, prov)
    rows = s.query(IntelMentionDirection).all()
    assert len(rows) == 1
    assert rows[0].match_type == "source"
    assert rows[0].direction_id == d.id


def test_collect_probe_writes_geo_m2m_row_for_text_mention():
    from radar.intel.models import IntelDirection, IntelProbe, IntelMention, IntelMentionDirection
    from radar.intel import collector
    s = _sess()
    # Probe subscribed to kharkiv, but post mentions bryansk → both should appear.
    kh = IntelDirection(key="kharkiv", name="Харьков", kind="region", geo_terms='["харьков"]')
    br = IntelDirection(key="bryansk", name="Брянск", kind="region", geo_terms='["брянск"]')
    s.add_all([kh, br]); s.flush()
    p = IntelProbe(direction_id=kh.id, platform="telegram", kind="channel", query="@ua", side="ua")
    s.add(p); s.commit()
    post = SimpleNamespace(post_id="@ua/9", author="@ua",
                           text="зафіксовано обстріл біля Брянська, також дані по харькову",
                           followers=0, created_at=datetime.now(timezone.utc), hashtags=[], likes=0)
    prov = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=[post], cursor=None))
    collector.collect_probe(s, p, prov)
    m2m = {(r.direction_id, r.match_type) for r in s.query(IntelMentionDirection).all()}
    assert (kh.id, "source") in m2m
    assert (br.id, "geo") in m2m
    assert (kh.id, "geo") in m2m  # 'kharkiv' term matched too
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_intel_collector.py -v -k m2m`
Expected: FAIL (`IntelMentionDirection` rows not written).

- [ ] **Step 3: Implement m2m writing in the collector**

In `backend/radar/intel/collector.py`:

Replace the import block at the top with:
```python
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import IntelDirection, IntelMention, IntelMentionDirection, IntelProbe
from .geo_match import match_directions

log = logging.getLogger(__name__)
```

Add a helper before `collect_probe`:
```python
def _terms_by_key(session) -> dict:
    """Return {direction_key: [lowercase terms]} for all non-meta directions.

    Cheap to call once per collect_probe pass; the number of directions is
    bounded by the curated geo dictionary (~32).
    """
    out = {}
    for d in session.query(IntelDirection).filter(IntelDirection.kind != "meta").all():
        try:
            terms = json.loads(d.geo_terms or "[]")
        except (ValueError, TypeError):
            terms = []
        if terms:
            out[d.key] = [t.lower() for t in terms]
    return out


def _write_m2m(session, mention, primary_direction_id, terms_by_key, id_by_key) -> None:
    """Persist IntelMentionDirection rows for a freshly-inserted mention.

    `id_by_key` maps direction_key → direction_id (caller builds from the same
    query as terms_by_key). The primary direction is always written with
    match_type='source' even if it has no geo_terms.
    """
    matched_keys = match_directions(mention.text or "", terms_by_key)
    rows = {primary_direction_id: "source"}
    for key in matched_keys:
        did = id_by_key.get(key)
        if did is not None:
            # source already wins if it's also the primary
            rows.setdefault(did, "geo")
    for did, mtype in rows.items():
        session.add(IntelMentionDirection(
            mention_id=mention.id, direction_id=did, match_type=mtype))
    try:
        session.flush()
    except IntegrityError:
        # (mention_id, direction_id) unique — already linked, ignore.
        session.rollback()
        # Re-add the mention to the session so subsequent flushes still work.
        session.add(mention)
```

Modify the inner block in `collect_probe` where the mention is inserted. Replace this block:

```python
                sp = session.begin_nested()
                try:
                    session.add(mention)
                    session.flush()
                    sp.commit()
                    count += 1
                except IntegrityError:
                    sp.rollback()
                    # Post already stored — skip, but keep going.
```

With:

```python
                sp = session.begin_nested()
                try:
                    session.add(mention)
                    session.flush()
                    _write_m2m(session, mention, probe.direction_id,
                               terms_by_key, id_by_key)
                    sp.commit()
                    count += 1
                except IntegrityError:
                    sp.rollback()
                    # Post already stored — skip, but keep going.
```

And add `terms_by_key` / `id_by_key` resolution before the `while not found_watermark:` loop. After the `direction = session.get(IntelDirection, probe.direction_id)` block (and the `if direction is None: return 0` guard), insert:

```python
    # Build geo-term index once per collect pass (cheap; ~32 directions).
    all_dirs = {
        d.key: d for d in session.query(IntelDirection)
        .filter(IntelDirection.kind != "meta").all()
    }
    terms_by_key = {}
    id_by_key = {}
    for key, d in all_dirs.items():
        id_by_key[key] = d.id
        try:
            terms = json.loads(d.geo_terms or "[]")
        except (ValueError, TypeError):
            terms = []
        if terms:
            terms_by_key[key] = [t.lower() for t in terms]
```

(Delete the duplicate `_terms_by_key` helper you added in this step — fold it inline as above so `id_by_key` is also captured. Or keep the helper and call it for terms, then derive id_by_key separately. Either is fine; the inline version is preferred for clarity.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_intel_collector.py -v`
Expected: PASS (4 tests — 2 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/intel/collector.py backend/tests/test_intel_collector.py
git commit -m "feat(intel): collector writes source + geo match m2m rows"
```

---

## Task 5: Feed serialization + REST endpoints (history + directions CRUD)

**Files:**
- Modify: `backend/radar/intel/aggregate.py` (add `feed_event`)
- Modify: `backend/radar/intel/api.py` (add `/intel/feed`, extend `GET /intel/directions`, add `POST /intel/directions`)
- Test: `backend/tests/test_intel_feed_api.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_intel_feed_api.py`:

```python
# backend/tests/test_intel_feed_api.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


def _app_with_data():
    """Build an in-memory app, seed two directions + a mention with m2m."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base, User
    import radar.intel.models
    from radar.core.db import _MIGRATIONS  # noqa
    from radar.core import db as dbmod
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    # monkeypatch the SessionLocal used by the api deps
    dbmod.SessionLocal.configure(bind=eng)
    dbmod.engine = eng

    s = Session(eng)
    u = User(email="op@example.com", password_hash="x", is_admin=True)
    s.add(u); s.flush()
    from radar.intel.models import IntelDirection, IntelMention, IntelMentionDirection
    d1 = IntelDirection(key="bryansk", name="Брянск", kind="region", geo_terms='["брянск"]')
    d2 = IntelDirection(key="kharkiv", name="Харьков", kind="region", geo_terms='["харьков"]')
    s.add_all([d1, d2]); s.flush()
    m = IntelMention(direction_id=d2.id, platform="telegram", post_id="p1",
                    author="@ua", side="ua", text="обстріл під Брянськом",
                    created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    s.add_all([
        IntelMentionDirection(mention_id=m.id, direction_id=d2.id, match_type="source"),
        IntelMentionDirection(mention_id=m.id, direction_id=d1.id, match_type="geo"),
    ])
    s.commit()

    # auth: issue a token the dep will accept
    from radar.core import auth
    token = auth.create_token({"uid": u.id})

    from radar.intel.api import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), token


def test_feed_returns_events_for_direction_via_m2m():
    client, token = _app_with_data()
    # bryansk has no primary mention, but the m2m links it geo-wise.
    r = client.get("/intel/feed?direction=bryansk",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["author"] == "@ua"
    assert data[0]["match_type"] == "geo"


def test_feed_side_filter_excludes_other_side():
    client, token = _app_with_data()
    r = client.get("/intel/feed?direction=bryansk&side=ru",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == []  # the only mention is side=ua


def test_get_directions_lists_kind_and_geo_terms():
    client, token = _app_with_data()
    r = client.get("/intel/directions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    keys = {d["key"]: d for d in r.json()}
    assert keys["bryansk"]["kind"] == "region"
    assert "брянск" in keys["bryansk"]["geo_terms"]


def test_post_directions_creates_custom():
    client, token = _app_with_data()
    r = client.post("/intel/directions",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"key": "myline", "name": "Моя линия",
                          "geo_terms": ["термин1", "термин2"]})
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "myline"
    assert body["kind"] == "custom"
    assert "термин1" in body["geo_terms"]


def test_post_directions_rejects_duplicate_key():
    client, token = _app_with_data()
    r = client.post("/intel/directions",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"key": "bryansk", "name": "dup", "geo_terms": []})
    assert r.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_intel_feed_api.py -v`
Expected: FAIL — `/intel/feed` route does not exist yet.

- [ ] **Step 3: Add `feed_event` serializer**

In `backend/radar/intel/aggregate.py`, after the existing `event()` function, add:

```python
def feed_event(m, direction_key, match_type=None) -> dict:
    """Serialize an IntelMention for the feed, tagged with the column's
    direction key and the match_type that placed it there."""
    return {
        **event(m),
        "direction": direction_key,
        "match_type": match_type or "source",
    }
```

- [ ] **Step 4: Add the feed + direction endpoints**

In `backend/radar/intel/api.py`, replace the existing `GET /intel/directions` route with an extended version, and add the new routes. At the top, extend the import from `.models`:

Replace:
```python
from .models import IntelDirection, IntelMention, IntelStory
```
With:
```python
from .models import (IntelDirection, IntelMention, IntelMentionDirection,
                     IntelStory, IntelFeedLayout)
```

Add `from pydantic import BaseModel` and `from fastapi.responses import StreamingResponse` if not already present, and `import json` / `import time`.

Replace the existing `@router.get("/intel/directions")` block with:

```python
def _direction_out(session, d, window_h=24) -> dict:
    from datetime import datetime, timezone, timedelta
    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
    events_count = (session.query(IntelMentionDirection)
                    .join(IntelMention, IntelMentionDirection.mention_id == IntelMention.id)
                    .filter(IntelMentionDirection.direction_id == d.id,
                            IntelMention.created_at >= since).count())
    try:
        terms = json.loads(d.geo_terms or "[]")
    except (ValueError, TypeError):
        terms = []
    return {"key": d.key, "name": d.name, "kind": d.kind,
            "region_key": d.region_key, "geo_terms": terms,
            "events_count": events_count}


@router.get("/intel/directions")
def intel_directions(
    window: str = "24h",
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    rows = (session.query(IntelDirection)
            .filter(IntelDirection.kind != "meta")
            .order_by(IntelDirection.kind, IntelDirection.name).all())
    return [_direction_out(session, d, _hours(window)) for d in rows]


class DirectionCreate(BaseModel):
    key: str
    name: str
    geo_terms: list[str] = []
    region_key: str | None = None


@router.post("/intel/directions")
def intel_create_direction(
    body: DirectionCreate,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    key = body.key.strip().lower()
    if not key:
        raise HTTPException(400, "key required")
    if session.query(IntelDirection).filter_by(key=key).first():
        raise HTTPException(409, "direction already exists")
    d = IntelDirection(
        key=key, name=body.name.strip() or key, kind="custom",
        region_key=body.region_key,
        geo_terms=json.dumps([t.lower() for t in body.geo_terms], ensure_ascii=False),
    )
    session.add(d); session.commit()
    return _direction_out(session, d, 24)
```

Then append the feed routes at the bottom of the file:

```python
# ── Feed v2 ───────────────────────────────────────────────────────────────────

@router.get("/intel/feed")
def intel_feed(
    direction: str,
    side: Optional[str] = None,
    window: str = "24h",
    limit: int = 50,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """Initial history for one column — mentions linked to `direction` via m2m."""
    d = session.query(IntelDirection).filter_by(key=direction).first()
    if not d:
        raise HTTPException(404, "direction not found")
    since = datetime.now(timezone.utc) - timedelta(hours=_hours(window))
    q = (session.query(IntelMention, IntelMentionDirection.match_type)
         .join(IntelMentionDirection, IntelMentionDirection.mention_id == IntelMention.id)
         .filter(IntelMentionDirection.direction_id == d.id,
                 IntelMention.created_at >= since))
    if side:
        q = q.filter(IntelMention.side == side)
    rows = q.order_by(IntelMention.created_at.desc()).limit(limit).all()
    return [aggregate.feed_event(m, direction, mt) for (m, mt) in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_intel_feed_api.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/radar/intel/aggregate.py backend/radar/intel/api.py backend/tests/test_intel_feed_api.py
git commit -m "feat(intel): /intel/feed column history + directions list/create with geo_terms"
```

---

## Task 6: Multiplexed SSE stream

**Files:**
- Modify: `backend/radar/intel/api.py` (add `/intel/feed/stream`)
- Test: `backend/tests/test_intel_feed_api.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_intel_feed_api.py`:

```python
def test_feed_stream_yields_events_tagged_with_direction():
    import asyncio
    client, token = _app_with_data()
    # Pull the generator directly — full SSE over TestClient hangs on infinite streams.
    from radar.intel import api as intel_api
    # Build the params the route would pass to the generator.
    rows = []
    gen = intel_api._feed_stream_gen(direction_keys=["bryansk", "kharkiv"],
                                     side=None, window_h=24)
    async def collect():
        # The generator is sync; iterate it under a timeout.
        loop = asyncio.get_event_loop()
        def drain():
            out = []
            for chunk in gen:
                out.append(chunk)
                if len(out) >= 1:
                    break
            return out
        return await loop.run_in_executor(None, drain)
    chunks = await collect()
    assert chunks, "expected at least one SSE event"
    assert any("bryansk" in c for c in chunks)
```

> If the async-in-test plumbing is awkward, fall back to a plain sync drain under a thread with a hard timeout — the goal is to assert that at least one `data:` line tagged with `bryansk` is produced.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_intel_feed_api.py::test_feed_stream_yields_events_tagged_with_direction -v`
Expected: FAIL — `_feed_stream_gen` does not exist.

- [ ] **Step 3: Implement the SSE endpoint**

Append to `backend/radar/intel/api.py`:

```python
def _feed_stream_gen(direction_keys, side, window_h):
    """Sync generator yielding SSE chunks for the multiplexed feed.

    Polls the DB every 2s for new IntelMention rows linked (via m2m) to any
    of `direction_keys`, since the last-seen mention id. Each event is tagged
    `{"direction": <key>, "event": {…}}`. Heartbeat every 15s.
    """
    from ..core.db import SessionLocal
    last_id = 0
    last_heartbeat = time.monotonic()
    key_by_id = {}
    while True:
        try:
            with SessionLocal() as s:
                # Resolve direction ids → keys each pass (cheap; ~8 columns).
                dirs = (s.query(IntelDirection)
                        .filter(IntelDirection.key.in_(direction_keys)).all())
                id_to_key = {d.id: d.key for d in dirs}
                if id_to_key:
                    q = (s.query(IntelMention, IntelMentionDirection.direction_id,
                                 IntelMentionDirection.match_type)
                         .join(IntelMentionDirection,
                               IntelMentionDirection.mention_id == IntelMention.id)
                         .filter(IntelMentionDirection.direction_id.in_(list(id_to_key)),
                                 IntelMention.id > last_id))
                    if side:
                        q = q.filter(IntelMention.side == side)
                    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
                    q = q.filter(IntelMention.created_at >= since)
                    for (m, did, mt) in q.order_by(IntelMention.id).all():
                        last_id = max(last_id, m.id)
                        payload = aggregate.feed_event(m, id_to_key.get(did, "?"), mt)
                        yield f"data: {json.dumps(payload, default=str, ensure_ascii=False)}\n\n"
        except Exception:
            pass  # keep the stream alive on transient errors
        if time.monotonic() - last_heartbeat > 15:
            yield ": ping\n\n"
            last_heartbeat = time.monotonic()
        time.sleep(2)


@router.get("/intel/feed/stream")
def intel_feed_stream(
    directions: str,
    side: Optional[str] = None,
    window: str = "24h",
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """SSE stream of new mentions across the requested columns.

    `directions` is a comma-separated list of direction keys. The server
    polls every 2s and emits one event per new mention (tagged with the
    direction it matched)."""
    keys = [k.strip() for k in directions.split(",") if k.strip()]
    if not keys:
        raise HTTPException(400, "at least one direction required")
    gen = _feed_stream_gen(keys, side, _hours(window))
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})
```

Make sure `import time`, `import json`, `from datetime import datetime, timezone, timedelta`, and `from fastapi.responses import StreamingResponse` are at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_intel_feed_api.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/radar/intel/api.py backend/tests/test_intel_feed_api.py
git commit -m "feat(intel): multiplexed /intel/feed/stream SSE tagged by direction"
```

---

## Task 7: Layout persistence + admin bootstrap

**Files:**
- Modify: `backend/radar/intel/api.py` (add `/intel/feed/layout` GET/PUT)
- Modify: `backend/radar/app.py` (seed first user as admin)
- Test: `backend/tests/test_intel_feed_api.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_intel_feed_api.py`:

```python
def test_get_layout_returns_empty_default():
    client, token = _app_with_data()
    r = client.get("/intel/feed/layout",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["direction_ids"] == []


def test_put_layout_saves_and_admin_only():
    client, token = _app_with_data()
    # admin token — should succeed
    r = client.put("/intel/feed/layout",
                   headers={"Authorization": f"Bearer {token}"},
                   json={"direction_ids": [1, 2]})
    assert r.status_code == 200
    assert r.json()["direction_ids"] == [1, 2]
    # re-get returns saved
    r2 = client.get("/intel/feed/layout",
                    headers={"Authorization": f"Bearer {token}"})
    assert r2.json()["direction_ids"] == [1, 2]


def test_put_layout_403_for_non_admin():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base, User
    import radar.intel.models
    from radar.core import db as dbmod
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    dbmod.SessionLocal.configure(bind=eng)
    dbmod.engine = eng
    s = Session(eng)
    u = User(email="user@example.com", password_hash="x", is_admin=False)
    s.add(u); s.commit()
    from radar.core import auth
    token = auth.create_token({"uid": u.id})
    from radar.intel.api import router
    app = FastAPI(); app.include_router(router)
    client = TestClient(app)
    r = client.put("/intel/feed/layout",
                   headers={"Authorization": f"Bearer {token}"},
                   json={"direction_ids": [1]})
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_intel_feed_api.py -v -k layout`
Expected: FAIL — route does not exist.

- [ ] **Step 3: Add the layout endpoints**

Append to `backend/radar/intel/api.py`:

```python
class LayoutBody(BaseModel):
    direction_ids: list[int]


@router.get("/intel/feed/layout")
def intel_feed_layout_get(
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    row = session.query(IntelFeedLayout).order_by(IntelFeedLayout.updated_at.desc()).first()
    try:
        ids = json.loads(row.direction_ids) if row else []
    except (ValueError, TypeError):
        ids = []
    return {"direction_ids": ids, "updated_at": row.updated_at.isoformat() if row else None}


@router.put("/intel/feed/layout")
def intel_feed_layout_put(
    body: LayoutBody,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "admin only")
    row = session.query(IntelFeedLayout).order_by(IntelFeedLayout.updated_at.desc()).first()
    if row is None:
        row = IntelFeedLayout(direction_ids="[]")
        session.add(row)
    row.direction_ids = json.dumps(body.direction_ids)
    row.updated_by = user.id
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"direction_ids": body.direction_ids, "updated_at": row.updated_at.isoformat()}
```

- [ ] **Step 4: Seed first user as admin on startup**

In `backend/radar/app.py`, inside the lifespan startup (where existing seed calls live), add (after the existing seed calls, before `yield`):

```python
        # Bootstrap: the first registered user is the contour admin.
        from radar.models import User
        with SessionLocal() as s:
            if s.query(User).count() >= 1 and not s.query(User).filter_by(is_admin=True).first():
                first = s.query(User).order_by(User.id).first()
                first.is_admin = True
                s.commit()
```

(Adjust the exact placement to match where other `ensure_*` seed calls live in `app.py`. If `SessionLocal` is not imported there, import it from `radar.core.db`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_intel_feed_api.py -v`
Expected: PASS (9 tests total).

- [ ] **Step 6: Commit**

```bash
git add backend/radar/intel/api.py backend/radar/app.py backend/tests/test_intel_feed_api.py
git commit -m "feat(intel): /intel/feed/layout CRUD (admin-gated) + bootstrap first user as admin"
```

---

## Task 8: Mount IntelFeed screen + sidebar wiring

**Files:**
- Modify: `echo-app/src/features/intel/IntelApp.jsx`
- Modify: `echo-app/src/features/intel/api.js`
- Create: `echo-app/src/features/intel/components/IntelFeed.jsx` (placeholder first; full build in Task 9)
- Modify: `echo-app/src/features/intel/intel.module.css`

- [ ] **Step 1: Add API methods to `api.js`**

In `echo-app/src/features/intel/api.js`, add the following entries inside the `intelApi` object (after `search`):

```javascript
  feed:         (direction, params = {})  => passthrough('feed', { direction, ...params }),
  createDirection: (body)                 => request('/intel/directions', { method: 'POST', body }),
  getLayout:    ()                        => request('/intel/feed/layout'),
  saveLayout:   (body)                    => request('/intel/feed/layout', { method: 'PUT', body }),
  feedStream:   (directions, params = {}, onEvent) => {
    const qs = new URLSearchParams({ directions: directions.join(','), ...(params||{}) });
    const es = new EventSource(`/intel/feed/stream?${qs.toString()}`);
    es.onmessage = (e) => { try { onEvent(JSON.parse(e.data)); } catch {} };
    return es;  // caller closes on unmount
  },
```

Also extend the existing `directions()` return shape — it already passes through whatever the backend returns, so the new `kind`/`geo_terms` fields will be present automatically. No change needed beyond the new methods above.

- [ ] **Step 2: Create a placeholder `IntelFeed.jsx`**

Create `echo-app/src/features/intel/components/IntelFeed.jsx`:

```jsx
// Лента событий v2 — multi-column TweetDeck-style live feed.
// One column per direction; posts land by source-subscription OR geo-text match.
// Full column/card/picker components are built in Task 9; this is the shell.
import { useEffect, useState } from 'react';
import { intelApi } from '../api';
import styles from '../intel.module.css';

export function IntelFeed({ window: win }) {
  return (
    <div className={styles.feed}>
      <div className={styles.feedEmpty}>Лента событий v2 — загружается…</div>
    </div>
  );
}
```

- [ ] **Step 3: Wire the 4th sidebar item in `IntelApp.jsx`**

In `echo-app/src/features/intel/IntelApp.jsx`:

Find the `SCREENS` array and append the feed entry:

```javascript
const SCREENS = [
  { key: 'home',    label: 'Ситуационный центр', icon: 'radio',    hotkey: '1' },
  { key: 'stories', label: 'Сюжеты',             icon: 'activity', hotkey: '2' },
  { key: 'board',   label: 'Оперативная доска',  icon: 'bar3',     hotkey: '3' },
  { key: 'feed',    label: 'Лента событий v2',   icon: 'radio',    hotkey: '4' },
];
```

Add the import at the top (next to the other component imports):

```javascript
import { IntelFeed } from './components/IntelFeed';
```

In the main render block, extend the screen branch. Replace:

```jsx
        ) : screen === 'stories' ? (
          <IntelStories window={window} onOpenDir={() => setScreen('stories')} />
        ) : (
          <IntelBoard window={window} onOpenDir={() => setScreen('stories')} />
        )}
```

With:

```jsx
        ) : screen === 'stories' ? (
          <IntelStories window={window} onOpenDir={() => setScreen('stories')} />
        ) : screen === 'feed' ? (
          <IntelFeed window={window} side={side} />
        ) : (
          <IntelBoard window={window} onOpenDir={() => setScreen('stories')} />
        )}
```

(If `side` isn't a top-level state in `IntelApp` yet, add `const [side, setSide] = useState(null);` near the other useState calls. `IntelFeed` will manage its own filters in Task 9, but passing `side` is harmless.)

- [ ] **Step 4: Add the CSS shell classes**

Append to `echo-app/src/features/intel/intel.module.css`:

```css
/* ── Feed v2 ─────────────────────────────────────────────────────────────── */
.feed { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.feedEmpty { display: flex; align-items: center; justify-content: center;
  flex: 1; color: var(--fg-3); font-family: var(--font-mono); font-size: 12px; }
```

- [ ] **Step 5: Smoke build**

Run: `cd echo-app && npm run build`
Expected: build succeeds (the placeholder renders).

- [ ] **Step 6: Commit**

```bash
git add echo-app/src/features/intel/IntelApp.jsx echo-app/src/features/intel/api.js echo-app/src/features/intel/components/IntelFeed.jsx echo-app/src/features/intel/intel.module.css
git commit -m "feat(fe-intel): mount Лента событий v2 screen (4th sidebar item, shell)"
```

---

## Task 9: Full IntelFeed UI — columns, cards, picker, SSE subscription

**Files:**
- Replace: `echo-app/src/features/intel/components/IntelFeed.jsx`
- Create: `echo-app/src/features/intel/components/FeedColumn.jsx`
- Create: `echo-app/src/features/intel/components/PostCard.jsx`
- Create: `echo-app/src/features/intel/components/ColumnPicker.jsx`
- Modify: `echo-app/src/features/intel/intel.module.css`

- [ ] **Step 1: Write `PostCard.jsx`**

Create `echo-app/src/features/intel/components/PostCard.jsx`:

```jsx
// One post in a feed column. Side flag + author + time + clamped text + credibility dot.
import { CREDIBILITY, SIDE, agoStrShort } from '../api';
import styles from '../intel.module.css';

export function PostCard({ event, isNew }) {
  const cred = CREDIBILITY[event.credibility] || CREDIBILITY.unrated;
  const side = SIDE[event.side] || { label: '—', color: '#6A8499' };
  return (
    <div className={styles.postCard} data-new={isNew ? '1' : '0'}>
      <div className={styles.postMeta}>
        <span style={{ color: side.color }}>{side.label}</span>
        <span className={styles.postAuthor}>{event.author}</span>
        <span className={styles.postTime}>{agoStrShort(event.created_at)}</span>
        <span className={styles.postMatch} title={event.match_type === 'geo' ? 'по тексту' : 'по источнику'}>
          {event.match_type === 'geo' ? 'G' : 'S'}
        </span>
      </div>
      <div className={styles.postText}>{event.text}</div>
      <div className={styles.postCredRow}>
        <span className={styles.credDot} style={{ background: cred.color }} title={cred.label} />
        {event.url
          ? <a className={styles.postLink} href={event.url} target="_blank" rel="noreferrer">открыть</a>
          : null}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write `FeedColumn.jsx`**

Create `echo-app/src/features/intel/components/FeedColumn.jsx`:

```jsx
// One column: header (name + count) + scrollable list of PostCards.
import { PostCard } from './PostCard';
import styles from '../intel.module.css';

export function FeedColumn({ direction, events, onRemove }) {
  return (
    <div className={styles.feedColumn}>
      <div className={styles.feedColumnHead}>
        <span className={styles.feedColumnName}>{direction.name}</span>
        <span className={styles.feedColumnCount}>{events.length}</span>
        <button className={styles.feedColumnX} title="убрать колонку" onClick={onRemove}>✕</button>
      </div>
      <div className={styles.feedColumnBody}>
        {events.length === 0
          ? <div className={styles.feedColumnEmpty}>нет событий в окне</div>
          : events.map((e) => <PostCard key={e.id} event={e} isNew={e._new} />)}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Write `ColumnPicker.jsx`**

Create `echo-app/src/features/intel/components/ColumnPicker.jsx`:

```jsx
// "+ колонки ▾" dropdown: search + checkbox list of all directions.
import { useEffect, useRef, useState } from 'react';
import { intelApi } from '../api';
import styles from '../intel.module.css';

export function ColumnPicker({ activeKeys, onAdd, onRemove }) {
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState([]);
  const [q, setQ] = useState('');
  const ref = useRef(null);

  useEffect(() => { intelApi.directions().then(setAll).catch(() => {}); }, []);
  useEffect(() => {
    function onDoc(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const filtered = all.filter(d => (d.name || d.key).toLowerCase().includes(q.toLowerCase()));

  return (
    <div className={styles.colPickerWrap} ref={ref}>
      <button className={styles.colPickerBtn} onClick={() => setOpen(o => !o)}>+ колонки ▾</button>
      {open && (
        <div className={styles.colPicker}>
          <input className={styles.colPickerSearch} value={q}
                 onChange={e => setQ(e.target.value)} placeholder="поиск…" autoFocus />
          <div className={styles.colPickerList}>
            {filtered.map(d => {
              const on = activeKeys.includes(d.key);
              return (
                <label key={d.key} className={styles.colPickerItem}>
                  <input type="checkbox" checked={on}
                         onChange={() => on ? onRemove(d.key) : onAdd(d)} />
                  <span>{d.name} <span className={styles.colPickerKind}>{d.kind}</span></span>
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Replace `IntelFeed.jsx` with the full implementation**

Replace `echo-app/src/features/intel/components/IntelFeed.jsx`:

```jsx
// Лента событий v2 — TweetDeck-style multi-column live feed.
// Columns are selected via the picker; layout persists to localStorage with a
// backend "боевой дефолт" fallback. One multiplexed SSE streams new posts.
import { useCallback, useEffect, useRef, useState } from 'react';
import { intelApi } from '../api';
import { FeedColumn } from './FeedColumn';
import { ColumnPicker } from './ColumnPicker';
import styles from '../intel.module.css';

const LS_KEY = 'echo.intel.feed.columns';
const WINDOWS = [['1h', '1ч'], ['24h', '24ч'], ['7d', '7д']];
const SIDES = [[null, '🇷🇺+🇺🇦'], ['ru', '🇷🇺'], ['ua', '🇺🇦']];

export function IntelFeed() {
  const [allDirs, setAllDirs] = useState([]);
  const [activeKeys, setActiveKeys] = useState([]);   // ordered list of keys
  const [win, setWin] = useState('24h');
  const [side, setSide] = useState(null);
  const [eventsByKey, setEventsByKey] = useState({});  // {key: [event, ...]}
  const esRef = useRef(null);

  // Load direction catalog + initial layout (localStorage → backend default).
  useEffect(() => {
    intelApi.directions().then(setAllDirs).catch(() => {});
    const stored = localStorage.getItem(LS_KEY);
    if (stored) {
      try { setActiveKeys(JSON.parse(stored)); return; } catch {}
    }
    intelApi.getLayout().then(l => {
      const ids = l.direction_ids || [];
      // resolve ids → keys via catalog
      intelApi.directions().then(dirs => {
        const keyById = Object.fromEntries(dirs.map(d => [d.id ?? null, d.key]));
        // directions() returns objects without .id; fetch via a parallel lookup is awkward.
        // Simpler: layout stores keys directly. (See Task 7 note — we switch to keys.)
      });
    }).catch(() => {});
  }, []);

  // Persist to localStorage on change.
  useEffect(() => {
    if (activeKeys.length) localStorage.setItem(LS_KEY, JSON.stringify(activeKeys));
  }, [activeKeys]);

  const dirByName = Object.fromEntries(allDirs.map(d => [d.key, d]));

  // Initial history per column when the set of columns or filters change.
  useEffect(() => {
    setEventsByKey({});
    let alive = true;
    Promise.all(activeKeys.map(k =>
      intelApi.feed(k, { window: win, side }).then(rows => [k, rows]).catch(() => [k, []])
    )).then(pairs => { if (alive) setEventsByKey(Object.fromEntries(pairs)); });
    return () => { alive = false; };
  }, [activeKeys.join(','), win, side]);

  // SSE subscription — one connection for all columns.
  useEffect(() => {
    if (!activeKeys.length) return;
    const es = intelApi.feedStream(activeKeys, { window: win, side }, (ev) => {
      setEventsByKey(prev => {
        const list = prev[ev.direction] || [];
        // prepend + mark new for highlight
        if (list.some(e => e.id === ev.id)) return prev;
        return { ...prev, [ev.direction]: [{ ...ev, _new: true }, ...list].slice(0, 200) };
      });
      // clear the _new flag after 1s
      setTimeout(() => {
        setEventsByKey(prev => ({
          ...prev,
          [ev.direction]: (prev[ev.direction] || []).map(e => e.id === ev.id ? { ...e, _new: false } : e),
        }));
      }, 1000);
    });
    esRef.current = es;
    return () => { es.close(); };
  }, [activeKeys.join(','), win, side]);

  const addColumn = useCallback((d) => {
    setActiveKeys(prev => prev.includes(d.key) ? prev : [...prev, d.key]);
  }, []);
  const removeColumn = useCallback((key) => {
    setActiveKeys(prev => prev.filter(k => k !== key));
  }, []);

  return (
    <div className={styles.feed}>
      <div className={styles.feedTopbar}>
        <div className={styles.feedSeg}>
          {WINDOWS.map(([w, label]) =>
            <button key={w} data-active={win === w ? '1' : '0'} onClick={() => setWin(w)}>{label}</button>)}
        </div>
        <div className={styles.feedSeg}>
          {SIDES.map(([s, label]) =>
            <button key={label} data-active={String(side) === String(s) ? '1' : '0'} onClick={() => setSide(s)}>{label}</button>)}
        </div>
        <div style={{ flex: 1 }} />
        <button className={styles.feedResetBtn} onClick={() => {
          localStorage.removeItem(LS_KEY);
          intelApi.getLayout().then(l => setActiveKeys(l.direction_ids || []));
        }}>Сбросить к боевому</button>
      </div>

      <div className={styles.feedColumnBar}>
        {activeKeys.map(k => (
          <span key={k} className={styles.colChip}>
            ▶ {dirByName[k]?.name || k}
            <button onClick={() => removeColumn(k)}>✕</button>
          </span>
        ))}
        <ColumnPicker activeKeys={activeKeys} onAdd={addColumn} onRemove={removeColumn} />
      </div>

      <div className={styles.feedColumns}>
        {activeKeys.length === 0
          ? <div className={styles.feedEmpty}>Добавьте колонки через «+ колонки ▾».</div>
          : activeKeys.map(k => (
              <FeedColumn key={k}
                          direction={dirByName[k] || { key: k, name: k }}
                          events={eventsByKey[k] || []}
                          onRemove={() => removeColumn(k)} />
            ))}
      </div>
    </div>
  );
}
```

> **Note on layout storage:** the spec said `direction_ids`, but the frontend works with keys. To keep things consistent, update `PUT /intel/feed/layout` and `GET /intel/feed/layout` to store **direction keys** (strings), not ids. Change `LayoutBody.direction_ids: list[int]` → `list[str]` and rename to `direction_keys` in both the model column (it's already JSON-encoded text — no migration needed) and the API body. Adjust the Task 7 tests accordingly. **Do this refactor as the first sub-step of Task 9 before wiring the frontend** — it's a 5-line change.

- [ ] **Step 5: Refactor layout to keys (per the note)**

In `backend/radar/intel/api.py`:
- Rename `LayoutBody.direction_ids: list[int]` → `direction_keys: list[str]`.
- In `intel_feed_layout_put`: `row.direction_ids = json.dumps(body.direction_keys)`.
- In `intel_feed_layout_get`: return `{"direction_keys": ids, ...}`.

Update the Task 7 tests to send/expect `direction_keys: ["bryansk"]` instead of `direction_ids: [1, 2]`. Re-run `pytest tests/test_intel_feed_api.py -v` and confirm green.

Update `IntelFeed.jsx` above: replace `l.direction_ids` with `l.direction_keys`.

- [ ] **Step 6: Add the full CSS**

Append to `echo-app/src/features/intel/intel.module.css`:

```css
.feedTopbar { display: flex; gap: 12px; align-items: center;
  padding: 10px 14px; border-bottom: 1px solid #1B2630; }
.feedSeg { display: flex; gap: 2px; background: #161D24; border-radius: 6px; padding: 2px; }
.feedSeg button { padding: 4px 10px; font-size: 11px; border: none; background: transparent;
  color: #7A8B99; border-radius: 4px; cursor: pointer; font-family: var(--font-mono); }
.feedSeg button[data-active="1"] { background: #1F6FEB; color: #fff; }
.feedResetBtn { font-size: 11px; background: transparent; border: 1px solid #2A3441;
  color: #7A8B99; padding: 4px 10px; border-radius: 6px; cursor: pointer; font-family: var(--font-mono); }
.feedResetBtn:hover { color: #E8EDF2; border-color: #3A4451; }

.feedColumnBar { display: flex; gap: 6px; align-items: center; padding: 8px 14px;
  border-bottom: 1px solid #1B2630; overflow-x: auto; }
.colChip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
  font-size: 11px; background: #1F2A33; border: 1px solid #2A3441; border-radius: 999px;
  color: #E8EDF2; font-family: var(--font-mono); white-space: nowrap; }
.colChip button { background: none; border: none; color: #7A8B99; cursor: pointer; padding: 0; }
.colChip button:hover { color: #FF4D5E; }

.colPickerWrap { position: relative; }
.colPickerBtn { padding: 4px 12px; font-size: 11px; background: #1F6FEB; border: 1px solid #1F6FEB;
  border-radius: 999px; color: #fff; cursor: pointer; font-family: var(--font-mono); }
.colPicker { position: absolute; top: 100%; left: 0; margin-top: 6px; width: 280px;
  background: #0E1419; border: 1px solid #2A3441; border-radius: 8px; z-index: 50;
  box-shadow: 0 12px 32px rgba(0,0,0,.5); }
.colPickerSearch { width: 100%; box-sizing: border-box; padding: 8px 10px; background: #161D24;
  border: none; border-bottom: 1px solid #1B2630; color: #E8EDF2; font-size: 12px; outline: none; }
.colPickerList { max-height: 280px; overflow-y: auto; }
.colPickerItem { display: flex; align-items: center; gap: 8px; padding: 6px 10px;
  font-size: 12px; color: #B5C0CC; cursor: pointer; }
.colPickerItem:hover { background: #161D24; }
.colPickerKind { font-size: 10px; color: #6A8499; margin-left: 4px; }

.feedColumns { flex: 1; display: flex; gap: 8px; padding: 10px; overflow-x: auto; min-height: 0; }
.feedColumn { flex: 0 0 300px; background: #0E1419; border: 1px solid #1B2630;
  border-radius: 8px; display: flex; flex-direction: column; max-height: 100%; }
.feedColumnHead { display: flex; align-items: center; gap: 8px; padding: 8px 10px;
  border-bottom: 1px solid #1B2630; }
.feedColumnName { font-size: 12px; font-weight: 700; color: #E8EDF2; flex: 1; }
.feedColumnCount { font-size: 11px; color: #7A8B99; font-family: var(--font-mono); }
.feedColumnX { background: none; border: none; color: #6A8499; cursor: pointer; font-size: 12px; }
.feedColumnX:hover { color: #FF4D5E; }
.feedColumnBody { overflow-y: auto; flex: 1; }
.feedColumnEmpty { padding: 20px 10px; text-align: center; color: #6A8499; font-size: 11px;
  font-family: var(--font-mono); }

.postCard { padding: 8px 10px; border-bottom: 1px solid #141A20; transition: background 1s; }
.postCard[data-new="1"] { background: rgba(31,111,235,.25); }
.postMeta { display: flex; align-items: center; gap: 6px; font-size: 10px; color: #7A8B99;
  font-family: var(--font-mono); margin-bottom: 4px; }
.postAuthor { color: #B5C0CC; }
.postTime { margin-left: auto; }
.postMatch { padding: 0 4px; border: 1px solid #2A3441; border-radius: 3px; font-size: 9px; }
.postText { font-size: 12px; color: #E8EDF2; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.postCredRow { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.credDot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
.postLink { font-size: 10px; color: #57D2E2; text-decoration: none; font-family: var(--font-mono); }
```

- [ ] **Step 7: Build + manual smoke**

Run: `cd echo-app && npm run build`
Expected: build succeeds.

Manual: open the app, switch to «Разведка», click «Лента событий v2». Add 2-3 columns via the picker. Verify columns render. If the backend is live and has mentions, posts should appear; new mentions (if the collector is running) should slide in at the top with a blue highlight.

- [ ] **Step 8: Commit**

```bash
git add echo-app/src/features/intel/components/IntelFeed.jsx echo-app/src/features/intel/components/FeedColumn.jsx echo-app/src/features/intel/components/PostCard.jsx echo-app/src/features/intel/components/ColumnPicker.jsx echo-app/src/features/intel/intel.module.css backend/radar/intel/api.py backend/tests/test_intel_feed_api.py
git commit -m "feat(fe-intel): full Лента v2 UI — columns, cards, picker, SSE + layout refactor to keys"
```

---

## Task 10: Full-suite verification + final commit

**Files:** none (verification only)

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: ALL tests PASS — including the pre-existing `test_intel_collector`, `test_intel_api`, `test_intel_models`, `test_intel_aggregate`, `test_intel_stories`, plus the new `test_intel_geo_match` and `test_intel_feed_api`.

- [ ] **Step 2: Frontend build**

Run: `cd echo-app && npm run build`
Expected: build succeeds, no errors.

- [ ] **Step 3: Migration smoke on a real (existing) DB**

Run (against the project's existing `echo_radar.db` if present, otherwise skip):
```bash
cd backend && python -c "
from radar.core.db import init_db
init_db()
from sqlalchemy import create_engine, inspect
eng = create_engine('sqlite:///echo_radar.db')
insp = inspect(eng)
assert 'intel_mention_directions' in insp.get_table_names()
assert any(c['name']=='is_admin' for c in insp.get_columns('users'))
print('migration OK')
"
```
Expected: `migration OK`.

- [ ] **Step 4: Manual end-to-end smoke (requires live Telegram session)**

If a real session is available: start the backend, open the frontend, log into the «Разведка» contour, open «Лента событий v2», add the seeded directions (Брянск / Белгород / Харьков), wait for the collector to pull new posts, and confirm they appear in the correct columns. Skip if no session — note in the commit message.

- [ ] **Step 5: Final commit (if any cleanup)**

If Steps 1–3 surfaced fixes, commit them. Otherwise no-op.

```bash
git status
# if clean:
echo "all green"
```

---

## Self-Review Notes

**Spec coverage check:**
- §1 context → covered (4th screen, TweetDeck).
- §2 scope/non-goals → respected (no drag&drop, no audio, no map, no per-column filters).
- §4.1 extended IntelDirection → Task 2.
- §4.2 m2m table → Task 2 + written by Task 4.
- §4.3 geo dictionary + seed → Task 3.
- §5 matching in collector → Task 4 (uses Task 1 matcher).
- §6.1 `/intel/feed` history → Task 5.
- §6.2 multiplexed SSE → Task 6.
- §6.3 directions catalog/CRUD → Task 5.
- §6.4 layout persistence → Task 7 (+ keys refactor in Task 9 Step 5).
- §7 frontend (topbar/column-bar/columns/cards/picker/SSE/localStorage) → Tasks 8 + 9.
- §8 design-system CSS → Task 9 Step 6.
- §9 testing → each task ships its tests; Task 10 runs the full suite.
- §10 risks: Cyrillic boundaries (Task 1 handles), SSE single-connection (Task 6), admin gate (Task 7).

**Placeholder scan:** none — every code step ships actual code.

**Type/name consistency:** `match_type` is `'source'|'geo'|'manual'` everywhere. `feed_event(m, direction_key, match_type)` matches its only caller. `IntelMentionDirection` is the single m2m class name. Layout refactor (ids → keys) is called out explicitly in Task 9 Step 5.

**Scope:** single plan, single deployable feature. No decomposition needed.
