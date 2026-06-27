# Intel Thread Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store Telegram reply chains and thread siblings for `IntelMention` rows, and surface them as a collapsible inline thread in the StoryDetail events list.

**Architecture:** New `IntelThreadContext` table holds raw context messages (without passing the relevance filter). A separate `enrich_context` pass fetches parent chains and siblings via Telethon after the main collect cycle. The `IntelMention` table gains `reply_to_tg_id`, `reply_to_id`, `thread_root_id`, and `context_fetched` columns. A new API endpoint `/intel/mention/{id}/context` serves the context payload; the UI renders it inline in the existing «События» collapsible section.

**Tech Stack:** Python 3.14 · SQLAlchemy 2.0 · SQLite · Telethon · FastAPI · React 18

## Global Constraints

- Intel module only — do NOT touch `news/`, `brand/`, or `NewsMention`
- Follow existing `begin_nested()` savepoint pattern for DB writes
- Follow existing `_throttle()` + `TelegramFloodWait` pattern for all Telethon calls
- `post_id` for chat messages has format `"chathandle/msgid"` (e.g. `"mygroup/451"`)
- All new columns on `IntelMention` must have `nullable=True` or `default=` so existing rows are unaffected
- Tests use `sqlite:///:memory:` + `Base.metadata.create_all(eng)` — import `radar.intel.models` before `create_all`
- Run tests with: `cd backend && python -m pytest tests/ -v`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/radar/intel/models.py` | Modify | Add 4 cols to IntelMention; add IntelThreadContext |
| `backend/radar/core/providers/base.py` | Modify | Add `reply_to_tg_id` to Post dataclass |
| `backend/radar/core/providers/telegram.py` | Modify | Extract reply_to_tg_id in parse; add fetch_thread_context |
| `backend/radar/intel/collector.py` | Modify | Pass reply_to_tg_id through to IntelMention in chat branch |
| `backend/radar/intel/context_pass.py` | Create | enrich_context(session, provider, batch_size) |
| `backend/radar/intel/passes.py` | Modify | Call enrich_context after run_intel_collect |
| `backend/radar/intel/aggregate.py` | Modify | Add is_reply + reply_to_tg_id to event() |
| `backend/radar/intel/api.py` | Modify | New GET /intel/mention/{id}/context endpoint |
| `echo-app/src/features/intel/api.js` | Modify | Add mentionContext(id) |
| `echo-app/src/features/intel/components/IntelStories.jsx` | Modify | Inline thread UI in StoryDetail events |
| `backend/tests/test_intel_thread_context.py` | Create | Tests for model, context_pass, API endpoint |
| `backend/tests/test_telegram_thread.py` | Create | Tests for fetch_thread_context |

---

### Task 1: Data Model — IntelMention columns + IntelThreadContext table

**Files:**
- Modify: `backend/radar/intel/models.py`
- Test: `backend/tests/test_intel_thread_context.py`

**Interfaces:**
- Produces: `IntelMention.reply_to_tg_id: Optional[str]`, `IntelMention.reply_to_id: Optional[int]`, `IntelMention.thread_root_id: Optional[int]`, `IntelMention.context_fetched: bool`
- Produces: `IntelThreadContext(mention_id, tg_msg_id, role, depth, author, text, created_at)`

- [ ] **Step 1: Write failing test — IntelThreadContext table exists and is queryable**

Create `backend/tests/test_intel_thread_context.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # registers all tables
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)

def test_intel_mention_has_reply_fields():
    from radar.intel.models import IntelMention
    s = _sess()
    from radar.intel import seed
    seed.ensure_default_directions(s)
    from radar.intel.models import IntelDirection
    d = s.query(IntelDirection).first()
    m = IntelMention(
        direction_id=d.id, platform="telegram", post_id="grp/100",
        author="@x", text="test", created_at=datetime.now(timezone.utc),
        reply_to_tg_id="99",
    )
    s.add(m); s.commit()
    m2 = s.query(IntelMention).one()
    assert m2.reply_to_tg_id == "99"
    assert m2.reply_to_id is None
    assert m2.thread_root_id is None
    assert m2.context_fetched is False

def test_intel_thread_context_stores_parent():
    from radar.intel.models import IntelMention, IntelThreadContext
    s = _sess()
    from radar.intel import seed
    seed.ensure_default_directions(s)
    from radar.intel.models import IntelDirection
    d = s.query(IntelDirection).first()
    m = IntelMention(
        direction_id=d.id, platform="telegram", post_id="grp/100",
        author="@x", text="test", created_at=datetime.now(timezone.utc),
        reply_to_tg_id="99",
    )
    s.add(m); s.commit()
    ctx = IntelThreadContext(
        mention_id=m.id, tg_msg_id="99", role="parent", depth=0,
        author="@root", text="что у вас тут?",
        created_at=datetime.now(timezone.utc),
    )
    s.add(ctx); s.commit()
    row = s.query(IntelThreadContext).one()
    assert row.mention_id == m.id
    assert row.role == "parent"
    assert row.depth == 0
    assert row.tg_msg_id == "99"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_intel_thread_context.py -v
```

Expected: ImportError or AttributeError — `IntelThreadContext` does not exist, `reply_to_tg_id` not on `IntelMention`.

- [ ] **Step 3: Add columns to IntelMention and add IntelThreadContext**

In `backend/radar/intel/models.py`, after the existing `IntelMention` class (after the `first_seen` field), add:

```python
    reply_to_tg_id:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reply_to_id:     Mapped[Optional[int]] = mapped_column(ForeignKey("intel_mentions.id"), nullable=True)
    thread_root_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("intel_mentions.id"), nullable=True)
    context_fetched: Mapped[bool]          = mapped_column(Boolean, default=False, server_default="0")
```

After the `IntelAlert` class at the bottom of the file, add:

```python
class IntelThreadContext(Base):
    __tablename__ = "intel_thread_context"
    __table_args__ = (UniqueConstraint("mention_id", "tg_msg_id"),)
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[int]      = mapped_column(ForeignKey("intel_mentions.id"), nullable=False)
    tg_msg_id:  Mapped[str]      = mapped_column(Text, nullable=False)
    role:       Mapped[str]      = mapped_column(Text, nullable=False)   # "parent" | "sibling"
    depth:      Mapped[int]      = mapped_column(Integer, default=0)
    author:     Mapped[str]      = mapped_column(Text, default="")
    text:       Mapped[str]      = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(nullable=False)
```

Make sure `UniqueConstraint` is imported — add it to the existing SQLAlchemy imports line if not present.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_intel_thread_context.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Apply migration to the live database**

```bash
cd backend && python - <<'EOF'
import sqlite3
conn = sqlite3.connect("echo_radar.db")
c = conn.cursor()
c.execute("ALTER TABLE intel_mentions ADD COLUMN reply_to_tg_id TEXT")
c.execute("ALTER TABLE intel_mentions ADD COLUMN reply_to_id INTEGER REFERENCES intel_mentions(id)")
c.execute("ALTER TABLE intel_mentions ADD COLUMN thread_root_id INTEGER REFERENCES intel_mentions(id)")
c.execute("ALTER TABLE intel_mentions ADD COLUMN context_fetched INTEGER NOT NULL DEFAULT 0")
c.execute("""
CREATE TABLE IF NOT EXISTS intel_thread_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mention_id INTEGER NOT NULL REFERENCES intel_mentions(id),
    tg_msg_id TEXT NOT NULL,
    role TEXT NOT NULL,
    depth INTEGER DEFAULT 0,
    author TEXT DEFAULT '',
    text TEXT DEFAULT '',
    created_at DATETIME NOT NULL,
    UNIQUE(mention_id, tg_msg_id)
)
""")
conn.commit(); conn.close()
print("Migration complete")
EOF
```

Expected output: `Migration complete`

- [ ] **Step 6: Commit**

```bash
cd backend && git add radar/intel/models.py tests/test_intel_thread_context.py
git commit -m "feat(intel): add IntelThreadContext table and reply fields on IntelMention"
```

---

### Task 2: Post dataclass + `_parse_tg_chat_message` reply extraction

**Files:**
- Modify: `backend/radar/core/providers/base.py`
- Modify: `backend/radar/core/providers/telegram.py`
- Test: `backend/tests/test_telegram_thread.py`

**Interfaces:**
- Consumes: `IntelMention.reply_to_tg_id` (Task 1)
- Produces: `Post.reply_to_tg_id: Optional[str] = None`
- Produces: `_parse_tg_chat_message(msg, namespace, fallback_author) -> Post` — now sets `.reply_to_tg_id`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_telegram_thread.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from radar.core.providers.base import Post
from radar.core.providers.telegram import _parse_tg_chat_message


class _Sender:
    username = "alice"

class _ChatMsg:
    def __init__(self, id=200, message="БПЛА сбили над районом", reply_to_msg_id=None):
        self.id = id
        self.message = message
        self.reply_to_msg_id = reply_to_msg_id
        self.date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.sender = _Sender()
        self.views = 0
        self.forwards = 0
        self.reactions = None


def test_parse_chat_msg_no_reply():
    p = _parse_tg_chat_message(_ChatMsg(), "mygroup", "@mygroup")
    assert p.reply_to_tg_id is None

def test_parse_chat_msg_with_reply():
    p = _parse_tg_chat_message(_ChatMsg(reply_to_msg_id=199), "mygroup", "@mygroup")
    assert p.reply_to_tg_id == "199"

def test_parse_chat_msg_post_id_format():
    p = _parse_tg_chat_message(_ChatMsg(id=200), "mygroup", "@mygroup")
    assert p.post_id == "mygroup/200"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_telegram_thread.py -v
```

Expected: `AttributeError: Post has no field 'reply_to_tg_id'` or similar.

- [ ] **Step 3: Add reply_to_tg_id to Post dataclass**

In `backend/radar/core/providers/base.py`, add the field at the end of the `Post` dataclass (after `sound_id`):

```python
    reply_to_tg_id: Optional[str] = None
```

The full `Post` dataclass should now end with:
```python
    sound_id:       Optional[str] = None
    reply_to_tg_id: Optional[str] = None
```

- [ ] **Step 4: Update `_parse_tg_chat_message` in telegram.py**

In `backend/radar/core/providers/telegram.py`, find `_parse_tg_chat_message` and update the `return Post(...)` call to include `reply_to_tg_id`:

Replace the entire function body's return statement:

```python
def _parse_tg_chat_message(msg, namespace: str, fallback_author: str) -> Post:
    text   = getattr(msg, "message", None) or ""
    sender = getattr(msg, "sender", None)
    uname  = getattr(sender, "username", None) if sender else None
    author = f"@{uname}" if uname else fallback_author
    ns     = str(namespace).lstrip("@")
    raw_reply = getattr(msg, "reply_to_msg_id", None)
    return Post(
        post_id        = f"{ns}/{msg.id}",
        platform       = "telegram",
        author         = author,
        followers      = 0,
        text           = text,
        hashtags       = _HASHTAG_RE.findall(text),
        created_at     = msg.date,
        likes          = _sum_reactions(msg),
        views          = int(getattr(msg, "views", 0) or 0),
        comments       = 0,
        shares         = int(getattr(msg, "forwards", 0) or 0),
        sound_id       = None,
        reply_to_tg_id = str(raw_reply) if raw_reply is not None else None,
    )
```

- [ ] **Step 5: Run tests**

```bash
cd backend && python -m pytest tests/test_telegram_thread.py tests/test_telegram.py -v
```

Expected: all PASS (existing tests unaffected because `reply_to_tg_id` has a default of `None`).

- [ ] **Step 6: Commit**

```bash
cd backend && git add radar/core/providers/base.py radar/core/providers/telegram.py tests/test_telegram_thread.py
git commit -m "feat(intel): extract reply_to_tg_id from Telegram chat messages"
```

---

### Task 3: `TelegramProvider.fetch_thread_context`

**Files:**
- Modify: `backend/radar/core/providers/telegram.py`
- Test: `backend/tests/test_telegram_thread.py` (extend existing file)

**Interfaces:**
- Produces: `TelegramProvider.fetch_thread_context(handle, reply_to_tg_id: str, current_tg_id: str, depth_limit: int = 5, sibling_limit: int = 10) -> dict`
- Return shape: `{"parents": [{"tg_msg_id": str, "depth": int, "author": str, "text": str, "created_at": datetime}], "siblings": [{"tg_msg_id": str, "author": str, "text": str, "created_at": datetime}]}`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_telegram_thread.py`:

```python
from radar.core.providers.telegram import TelegramProvider


class _FakeMsg:
    def __init__(self, id, text, reply_to_msg_id=None, sender_username="bot"):
        self.id = id
        self.message = text
        self.reply_to_msg_id = reply_to_msg_id
        self.date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.sender = type("S", (), {"username": sender_username})()
        self.reactions = None
        self.views = 0
        self.forwards = 0


class _FakeClient:
    """Simulates: msg 300 replies to 299, which replies to 298 (root). Siblings of 298: [301]."""
    def get_entity(self, h): return h
    def is_connected(self): return True
    def get_messages(self, entity, ids=None, reply_to=None, limit=None, **kw):
        db = {
            298: _FakeMsg(298, "корень треда"),
            299: _FakeMsg(299, "первый ответ", reply_to_msg_id=298),
            300: _FakeMsg(300, "БПЛА сбили", reply_to_msg_id=299),
            301: _FakeMsg(301, "подтверждаем", reply_to_msg_id=298),
        }
        if ids is not None:
            single = ids if isinstance(ids, int) else ids[0]
            return [db[single]] if single in db else []
        if reply_to is not None:
            return [m for m in db.values()
                    if m.reply_to_msg_id == reply_to and m.id != 300][:limit]
        return []


def test_fetch_thread_context_parent_chain():
    provider = TelegramProvider(client=_FakeClient())
    result = provider.fetch_thread_context("@grp", reply_to_tg_id="299", current_tg_id="300")
    parents = result["parents"]
    # depth 0 = direct parent (299), depth 1 = grandparent (298)
    assert len(parents) == 2
    depths = {p["depth"] for p in parents}
    assert depths == {0, 1}
    tg_ids = {p["tg_msg_id"] for p in parents}
    assert tg_ids == {"299", "298"}

def test_fetch_thread_context_siblings():
    provider = TelegramProvider(client=_FakeClient())
    result = provider.fetch_thread_context("@grp", reply_to_tg_id="299", current_tg_id="300")
    siblings = result["siblings"]
    # 301 replies to 298 (same root), excluding current msg 300
    assert any(s["tg_msg_id"] == "301" for s in siblings)

def test_fetch_thread_context_no_reply():
    provider = TelegramProvider(client=_FakeClient())
    result = provider.fetch_thread_context("@grp", reply_to_tg_id=None, current_tg_id="300")
    assert result == {"parents": [], "siblings": []}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_telegram_thread.py::test_fetch_thread_context_parent_chain -v
```

Expected: `AttributeError: 'TelegramProvider' object has no attribute 'fetch_thread_context'`

- [ ] **Step 3: Implement `fetch_thread_context`**

Add this method to `TelegramProvider` in `backend/radar/core/providers/telegram.py`, after `fetch_comments`:

```python
def fetch_thread_context(self, handle: str, reply_to_tg_id: Optional[str],
                         current_tg_id: str, depth_limit: int = 5,
                         sibling_limit: int = 10) -> dict:
    """Fetch parent chain and siblings for a reply message.

    Returns:
      {"parents": [{tg_msg_id, depth, author, text, created_at}],
       "siblings": [{tg_msg_id, author, text, created_at}]}

    Raises TelegramFloodWait so callers can back off.
    Parents are ordered depth=0 (direct parent) → depth=N (root).
    Siblings are messages that share the same root parent (excl. current_tg_id).
    """
    from telethon.errors import FloodWaitError
    if reply_to_tg_id is None:
        return {"parents": [], "siblings": []}

    h = handle if (not handle or handle.startswith("@") or handle.startswith("#")) else f"@{handle}"

    def _author(msg) -> str:
        sender = getattr(msg, "sender", None)
        uname = getattr(sender, "username", None) if sender else None
        return f"@{uname}" if uname else str(getattr(msg, "sender_id", "") or "")

    def _get_one(entity, msg_id: int):
        try:
            msgs = self._await(self._client.get_messages(entity, ids=msg_id))
            return msgs[0] if msgs else None
        except FloodWaitError:
            raise
        except Exception:
            return None

    try:
        entity = self._await(self._client.get_entity(h))
    except FloodWaitError:
        raise
    except Exception:
        return {"parents": [], "siblings": []}

    # Walk up the parent chain
    parents = []
    depth = 0
    next_id = int(reply_to_tg_id)
    root_tg_id: Optional[int] = None

    while next_id and depth < depth_limit:
        try:
            msg = _get_one(entity, next_id)
        except FloodWaitError:
            raise
        if msg is None:
            break
        parents.append({
            "tg_msg_id": str(msg.id),
            "depth": depth,
            "author": _author(msg),
            "text": getattr(msg, "message", "") or "",
            "created_at": msg.date,
        })
        parent_of_parent = getattr(msg, "reply_to_msg_id", None)
        if parent_of_parent:
            next_id = int(parent_of_parent)
            depth += 1
        else:
            root_tg_id = msg.id
            break

    if root_tg_id is None and parents:
        root_tg_id = int(parents[-1]["tg_msg_id"])

    # Fetch siblings (other replies to root, excluding current message)
    siblings = []
    if root_tg_id:
        try:
            sibling_msgs = self._await(self._client.get_messages(
                entity, reply_to=root_tg_id, limit=sibling_limit))
            for m in (sibling_msgs or []):
                if str(m.id) == current_tg_id:
                    continue
                siblings.append({
                    "tg_msg_id": str(m.id),
                    "author": _author(m),
                    "text": getattr(m, "message", "") or "",
                    "created_at": m.date,
                })
        except FloodWaitError:
            raise
        except Exception:
            pass  # siblings are best-effort

    return {"parents": parents, "siblings": siblings}
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_telegram_thread.py -v
```

Expected: all PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
cd backend && git add radar/core/providers/telegram.py tests/test_telegram_thread.py
git commit -m "feat(intel): add TelegramProvider.fetch_thread_context"
```

---

### Task 4: `intel/collector.py` — persist `reply_to_tg_id`

**Files:**
- Modify: `backend/radar/intel/collector.py`
- Test: `backend/tests/test_intel_thread_context.py` (extend)

**Interfaces:**
- Consumes: `Post.reply_to_tg_id` (Task 2)
- Consumes: `IntelMention.reply_to_tg_id` (Task 1)
- Produces: chat-branch `IntelMention` rows now carry `reply_to_tg_id` when the source message is a reply

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_intel_thread_context.py`:

```python
def test_collector_stores_reply_to_tg_id():
    from types import SimpleNamespace
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelLexicon
    s = _sess()
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="БПЛА", meaning="drone", category="military"))
    s.commit()
    probe = IntelProbe(platform="telegram", kind="chat", query="@grp", side="ru")
    s.add(probe); s.commit()

    posts = [SimpleNamespace(
        post_id="grp/200", author="@alice", text="БПЛА сбили над Херсоном",
        followers=0, created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        hashtags=[], likes=0, reply_to_tg_id="199",
    )]
    prov = SimpleNamespace(search_chat=lambda h, term, limit, min_id: posts)
    n = collector.collect_probe(s, probe, prov)
    assert n == 1
    m = s.query(IntelMention).one()
    assert m.reply_to_tg_id == "199"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_intel_thread_context.py::test_collector_stores_reply_to_tg_id -v
```

Expected: FAIL — `reply_to_tg_id` is `None` because collector doesn't set it yet.

- [ ] **Step 3: Update chat branch in `collect_probe`**

In `backend/radar/intel/collector.py`, find the `IntelMention(...)` constructor inside the `if probe.kind == "chat":` branch and add `reply_to_tg_id`:

```python
                mention = IntelMention(
                    direction_id=dir_id,
                    platform=probe.platform,
                    post_id=post.post_id,
                    author=author,
                    side=probe.side,
                    text=text,
                    url=getattr(post, "url", None),
                    views=getattr(post, "likes", 0) or 0,
                    created_at=post.created_at,
                    reply_to_tg_id=getattr(post, "reply_to_tg_id", None),
                )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_intel_thread_context.py tests/test_intel_collect_tagging.py -v
```

Expected: all PASS (existing tests unaffected).

- [ ] **Step 5: Commit**

```bash
cd backend && git add radar/intel/collector.py tests/test_intel_thread_context.py
git commit -m "feat(intel): persist reply_to_tg_id on IntelMention in chat collect"
```

---

### Task 5: `intel/context_pass.py` + hook in `passes.py`

**Files:**
- Create: `backend/radar/intel/context_pass.py`
- Modify: `backend/radar/intel/passes.py`
- Test: `backend/tests/test_intel_thread_context.py` (extend)

**Interfaces:**
- Consumes: `IntelMention.reply_to_tg_id`, `IntelMention.context_fetched`, `IntelMention.post_id` format `"chathandle/msgid"` (Task 1, Task 4)
- Consumes: `TelegramProvider.fetch_thread_context(handle, reply_to_tg_id, current_tg_id)` (Task 3)
- Consumes: `IntelThreadContext(mention_id, tg_msg_id, role, depth, author, text, created_at)` (Task 1)
- Produces: `enrich_context(session, provider, batch_size=50) -> int` (count of enriched mentions)

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_intel_thread_context.py`:

```python
def test_enrich_context_stores_parent_and_sibling():
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from radar.intel import seed
    from radar.intel.models import IntelMention, IntelThreadContext, IntelLexicon
    from radar.intel.context_pass import enrich_context

    s = _sess()
    seed.ensure_default_directions(s)
    from radar.intel.models import IntelDirection
    d = s.query(IntelDirection).first()

    m = IntelMention(
        direction_id=d.id, platform="telegram", post_id="grp/300",
        author="@x", text="БПЛА сбили", created_at=datetime.now(timezone.utc),
        reply_to_tg_id="299",
    )
    s.add(m); s.commit()

    fake_parent = {"tg_msg_id": "299", "depth": 0, "author": "@root",
                   "text": "что тут?", "created_at": datetime.now(timezone.utc)}
    fake_sibling = {"tg_msg_id": "301", "author": "@sis",
                    "text": "подтверждаем", "created_at": datetime.now(timezone.utc)}

    fake_provider = SimpleNamespace(
        fetch_thread_context=lambda handle, reply_to_tg_id, current_tg_id, **kw: {
            "parents": [fake_parent],
            "siblings": [fake_sibling],
        }
    )

    n = enrich_context(s, fake_provider, batch_size=10)
    assert n == 1

    ctx_rows = s.query(IntelThreadContext).all()
    roles = {r.role for r in ctx_rows}
    assert "parent" in roles
    assert "sibling" in roles

    m2 = s.get(IntelMention, m.id)
    assert m2.context_fetched is True

def test_enrich_context_skips_already_fetched():
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from radar.intel import seed
    from radar.intel.models import IntelMention
    from radar.intel.context_pass import enrich_context

    s = _sess()
    seed.ensure_default_directions(s)
    from radar.intel.models import IntelDirection
    d = s.query(IntelDirection).first()

    m = IntelMention(
        direction_id=d.id, platform="telegram", post_id="grp/400",
        author="@x", text="test", created_at=datetime.now(timezone.utc),
        reply_to_tg_id="399", context_fetched=True,
    )
    s.add(m); s.commit()

    calls = []
    fake_provider = SimpleNamespace(
        fetch_thread_context=lambda *a, **kw: calls.append(1) or {"parents": [], "siblings": []}
    )
    n = enrich_context(s, fake_provider, batch_size=10)
    assert n == 0
    assert len(calls) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_intel_thread_context.py::test_enrich_context_stores_parent_and_sibling -v
```

Expected: `ModuleNotFoundError: No module named 'radar.intel.context_pass'`

- [ ] **Step 3: Create `backend/radar/intel/context_pass.py`**

```python
"""Enrich IntelMention rows that are replies with their parent chain and siblings.

Called after collect_probe (in passes.py). Fetches context lazily — only for mentions
not yet enriched (context_fetched=False). On TelegramFloodWait the mention is skipped
and retried next run. On any other error context_fetched is set True to avoid retry loops.
"""
from __future__ import annotations
import logging
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .models import IntelMention, IntelThreadContext

log = logging.getLogger(__name__)


def _parse_handle_and_msg_id(post_id: str) -> tuple[str, str]:
    """Split 'chathandle/123' → ('@chathandle', '123').

    For numeric handles like '#-1001234567/123' (private group via id) the '#' prefix
    is preserved so TelegramProvider.get_entity can resolve it.
    """
    if "/" not in post_id:
        return post_id, post_id
    handle, msg_id = post_id.rsplit("/", 1)
    if not handle.startswith("@") and not handle.startswith("#"):
        handle = f"@{handle}"
    return handle, msg_id


def enrich_context(session: Session, provider, batch_size: int = 50) -> int:
    """Fetch and store thread context for unprocessed reply mentions.

    Returns the count of mentions that were successfully enriched.
    """
    from ..core.providers.telegram import TelegramFloodWait

    pending = (
        session.query(IntelMention)
        .filter(
            IntelMention.reply_to_tg_id.isnot(None),
            IntelMention.context_fetched.is_(False),
        )
        .limit(batch_size)
        .all()
    )

    enriched = 0
    for mention in pending:
        handle, current_tg_id = _parse_handle_and_msg_id(mention.post_id)
        try:
            result = provider.fetch_thread_context(
                handle,
                reply_to_tg_id=mention.reply_to_tg_id,
                current_tg_id=current_tg_id,
            )
        except TelegramFloodWait as e:
            log.warning("context_pass flood-wait %ds — aborting batch", e.seconds)
            session.commit()
            return enriched
        except Exception:
            log.exception("context_pass: fetch failed for mention %s — marking done", mention.id)
            mention.context_fetched = True
            session.commit()
            continue

        for p in result.get("parents", []):
            ctx = IntelThreadContext(
                mention_id=mention.id,
                tg_msg_id=p["tg_msg_id"],
                role="parent",
                depth=p["depth"],
                author=p.get("author", ""),
                text=p.get("text", ""),
                created_at=p["created_at"],
            )
            sp = session.begin_nested()
            try:
                session.add(ctx); session.flush(); sp.commit()
            except IntegrityError:
                sp.rollback()

        for s in result.get("siblings", []):
            ctx = IntelThreadContext(
                mention_id=mention.id,
                tg_msg_id=s["tg_msg_id"],
                role="sibling",
                depth=0,
                author=s.get("author", ""),
                text=s.get("text", ""),
                created_at=s["created_at"],
            )
            sp = session.begin_nested()
            try:
                session.add(ctx); session.flush(); sp.commit()
            except IntegrityError:
                sp.rollback()

        # Resolve reply_to_id and thread_root_id from index
        if mention.reply_to_tg_id:
            parent_post_id_suffix = f"/{mention.reply_to_tg_id}"
            parent_in_index = (
                session.query(IntelMention)
                .filter(IntelMention.post_id.endswith(parent_post_id_suffix))
                .first()
            )
            if parent_in_index:
                mention.reply_to_id = parent_in_index.id

        parents = result.get("parents", [])
        if parents:
            root_tg_id = parents[-1]["tg_msg_id"]
            root_suffix = f"/{root_tg_id}"
            root_in_index = (
                session.query(IntelMention)
                .filter(IntelMention.post_id.endswith(root_suffix))
                .first()
            )
            if root_in_index:
                mention.thread_root_id = root_in_index.id

        mention.context_fetched = True
        session.commit()
        enriched += 1

    return enriched
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_intel_thread_context.py -v
```

Expected: all PASS.

- [ ] **Step 5: Hook into `passes.py`**

In `backend/radar/intel/passes.py`, after `run_intel_collect(session, tg_provider)` inside `run_intel_tick`, add:

```python
    # Enrich reply mentions with parent chain + siblings (separate pass, non-blocking).
    try:
        from .context_pass import enrich_context
        enrich_context(session, tg_provider, batch_size=50)
    except Exception:
        log.exception("intel context enrichment failed (skipped)")
        session.rollback()
```

- [ ] **Step 6: Run full intel test suite**

```bash
cd backend && python -m pytest tests/ -v -k "intel"
```

Expected: all existing intel tests PASS.

- [ ] **Step 7: Commit**

```bash
cd backend && git add radar/intel/context_pass.py radar/intel/passes.py tests/test_intel_thread_context.py
git commit -m "feat(intel): context_pass enrich_context + hook in run_intel_tick"
```

---

### Task 6: API — `aggregate.event()` + `/intel/mention/{id}/context` endpoint

**Files:**
- Modify: `backend/radar/intel/aggregate.py`
- Modify: `backend/radar/intel/api.py`
- Test: `backend/tests/test_intel_thread_context.py` (extend)

**Interfaces:**
- Consumes: `IntelMention.reply_to_tg_id`, `IntelMention.context_fetched` (Task 1)
- Consumes: `IntelThreadContext` rows (Task 5)
- Produces: `aggregate.event(m)` returns `{"is_reply": bool, "reply_to_tg_id": str|null, ...}`
- Produces: `GET /intel/mention/{mention_id}/context` → `{"mention_id": int, "reply_chain": [...], "siblings": [...]}`

- [ ] **Step 1: Write failing test for API endpoint**

Append to `backend/tests/test_intel_thread_context.py`:

```python
def test_context_api_endpoint_returns_reply_chain():
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = Session(eng)

    from radar.intel import seed
    seed.ensure_default_directions(s)
    from radar.intel.models import IntelDirection, IntelMention, IntelThreadContext

    d = s.query(IntelDirection).first()
    m = IntelMention(
        direction_id=d.id, platform="telegram", post_id="grp/500",
        author="@x", text="test", created_at=datetime.now(timezone.utc),
        reply_to_tg_id="499", context_fetched=True,
    )
    s.add(m); s.commit()
    ctx = IntelThreadContext(
        mention_id=m.id, tg_msg_id="499", role="parent", depth=0,
        author="@root", text="корень", created_at=datetime.now(timezone.utc),
    )
    s.add(ctx); s.commit()

    app = FastAPI()
    from radar.intel.api import router
    app.include_router(router)

    def override_db():
        yield s

    from radar.intel.api import db
    app.dependency_overrides[db] = override_db

    # Bypass auth
    from radar.intel.api import current_user
    from radar.models import User
    fake_user = User(email="t@t.com", hashed_password="x")
    app.dependency_overrides[current_user] = lambda: fake_user

    client = TestClient(app)
    resp = client.get(f"/intel/mention/{m.id}/context")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mention_id"] == m.id
    assert len(data["reply_chain"]) == 1
    assert data["reply_chain"][0]["tg_msg_id"] == "499"
    assert data["reply_chain"][0]["depth"] == 0
    assert data["siblings"] == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_intel_thread_context.py::test_context_api_endpoint_returns_reply_chain -v
```

Expected: FAIL — endpoint does not exist yet.

- [ ] **Step 3: Update `aggregate.event()` to expose `is_reply`**

In `backend/radar/intel/aggregate.py`, find the `event(m)` function and update it:

```python
def event(m) -> dict:
    return {"id": m.id, "platform": m.platform, "author": m.author, "side": m.side,
            "text": m.text, "url": m.url, "created_at": _aware(m.created_at).isoformat(),
            "verified": bool(m.verified), "direction": m.direction_id,
            "sig": content_sig(m.text),
            "is_reply": bool(getattr(m, "reply_to_tg_id", None)),
            "reply_to_tg_id": getattr(m, "reply_to_tg_id", None)}
```

- [ ] **Step 4: Add endpoint to `intel/api.py`**

In `backend/radar/intel/api.py`, add this import at the top (with the existing model imports):

```python
from .models import IntelDirection, IntelMention, IntelStory, IntelProbe, IntelAlert, IntelThreadContext
```

Then add the endpoint (place it after the existing `/intel/stream` or `/intel/search` block):

```python
@router.get("/intel/mention/{mention_id}/context")
def intel_mention_context(
    mention_id: int,
    session: Session = Depends(db),
    user: User = Depends(current_user),
):
    mention = session.get(IntelMention, mention_id)
    if mention is None:
        raise HTTPException(404, "Mention not found")

    rows = (session.query(IntelThreadContext)
            .filter(IntelThreadContext.mention_id == mention_id)
            .order_by(IntelThreadContext.role, IntelThreadContext.depth.asc())
            .all())

    from . import aggregate
    reply_chain = sorted(
        [{"tg_msg_id": r.tg_msg_id, "depth": r.depth,
          "author": r.author, "text": r.text,
          "created_at": aggregate._aware(r.created_at).isoformat()}
         for r in rows if r.role == "parent"],
        key=lambda x: x["depth"],
    )
    siblings = [
        {"tg_msg_id": r.tg_msg_id, "author": r.author,
         "text": r.text, "created_at": aggregate._aware(r.created_at).isoformat()}
        for r in rows if r.role == "sibling"
    ]
    return {"mention_id": mention_id, "reply_chain": reply_chain, "siblings": siblings}
```

- [ ] **Step 5: Run tests**

```bash
cd backend && python -m pytest tests/test_intel_thread_context.py -v
```

Expected: all PASS.

- [ ] **Step 6: Verify existing intel API tests still pass**

```bash
cd backend && python -m pytest tests/test_intel_api.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
cd backend && git add radar/intel/aggregate.py radar/intel/api.py tests/test_intel_thread_context.py
git commit -m "feat(intel): add is_reply to event() and GET /intel/mention/{id}/context endpoint"
```

---

### Task 7: Frontend — `api.js` + inline thread UI in `IntelStories.jsx`

**Files:**
- Modify: `echo-app/src/features/intel/api.js`
- Modify: `echo-app/src/features/intel/components/IntelStories.jsx`

**Interfaces:**
- Consumes: `GET /intel/mention/{id}/context` → `{mention_id, reply_chain, siblings}` (Task 6)
- Consumes: `event.is_reply: bool`, `event.id: int` from existing event payload (Task 6)

- [ ] **Step 1: Add `mentionContext` to `api.js`**

In `echo-app/src/features/intel/api.js`, add to the `intelApi` object (after `ackAllAlerts`):

```js
  mentionContext: (id) => request(`/intel/mention/${id}/context`),
```

- [ ] **Step 2: Add `ThreadContext` component to `IntelStories.jsx`**

In `echo-app/src/features/intel/components/IntelStories.jsx`, add this import at the top (after the existing imports):

```jsx
import { intelApi, CREDIBILITY, DIRECTION_NAMES, SIDE, spikeLevel, agoStrShort } from '../api';
```

(already present — no change needed)

Add the `ThreadContext` component **before** `StoryDetail` (around line 146):

```jsx
function ThreadContext({ mentionId }) {
  const [open, setOpen] = useState(false);
  const [ctx, setCtx] = useState(null);
  const [loading, setLoading] = useState(false);

  function toggle() {
    if (open) { setOpen(false); return; }
    if (ctx) { setOpen(true); return; }
    setLoading(true);
    intelApi.mentionContext(mentionId)
      .then(data => { setCtx(data); setOpen(true); })
      .catch(() => setCtx({ reply_chain: [], siblings: [] }))
      .finally(() => setLoading(false));
  }

  const borderStyle = { borderLeft: '2px solid #2BB3C7', paddingLeft: 8, margin: '4px 0' };

  return (
    <div style={{ marginBottom: 4 }}>
      <button
        onClick={toggle}
        style={{ background: 'none', border: 'none', color: '#4A6378', fontSize: 10,
                 fontFamily: 'var(--font-mono)', cursor: 'pointer', padding: '0 0 2px' }}>
        {loading ? '…' : open ? '↓ свернуть тред' : '↑ контекст'}
      </button>
      {open && ctx && (
        <div style={borderStyle}>
          {[...ctx.reply_chain].reverse().map((p, i) => (
            <div key={p.tg_msg_id} style={{ color: '#4A6378', fontSize: 11, marginBottom: 2,
                                            paddingLeft: i * 8 }}>
              <span style={{ color: '#3A5368', marginRight: 4 }}>{p.author}</span>
              {p.text}
            </div>
          ))}
          {ctx.siblings.map(s => (
            <div key={s.tg_msg_id} style={{ color: '#4A6378', fontSize: 11, marginBottom: 2,
                                            paddingLeft: (ctx.reply_chain.length) * 8 }}>
              <span style={{ color: '#3A5368', marginRight: 4 }}>{s.author}</span>
              {s.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Use `ThreadContext` in `StoryDetail` events list**

In `IntelStories.jsx`, find the `CollapsibleSection` for events (around the block with `detail.events.map(e => ...)`). Inside the event row, **before** the `<span className={styles.eventTime}>` add:

```jsx
{e.is_reply && <ThreadContext mentionId={e.id} />}
```

The full event row block should look like:

```jsx
{detail.events.map(e => {
  const sd = SIDE[e.side] || SIDE.ru;
  return (
    <div key={e.id} className={styles.eventRow}>
      <span className={styles.eventSide} style={{ color: sd.color, background: sd.color + '1A' }}>{sd.label}</span>
      <div className={styles.eventBody}>
        <div className={styles.eventText}>{e.text}</div>
        <div className={styles.eventMeta}>{e.author}{e.verified ? ' · ✓' : ''}</div>
        {e.is_reply && <ThreadContext mentionId={e.id} />}
      </div>
      <span className={styles.eventTime}>{agoStrShort(e.created_at)}</span>
    </div>
  );
})}
```

- [ ] **Step 4: Start the dev server and verify visually**

```bash
cd echo-app && npm run dev
```

Open the browser at the URL shown. Navigate to **Разведка → Сюжеты**, pick any story with events. Check:
- Events without `is_reply` show no «↑ контекст» button
- An event with `is_reply: true` shows the button
- Clicking it fires a request to `/intel/mention/{id}/context` and renders the chain above the event text
- Clicking again collapses
- Other story navigation still works (no regressions)

- [ ] **Step 5: Commit**

```bash
cd echo-app && git add src/features/intel/api.js src/features/intel/components/IntelStories.jsx
git commit -m "feat(intel): inline thread context UI in StoryDetail events"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 3 levels covered — parent chain (Tasks 2,3,5), siblings (Tasks 3,5), collapsible UI (Task 7). `context_fetched` column prevents retry loops (Task 1,5). `is_reply` field in event payload (Task 6). `reply_to_id` / `thread_root_id` FK resolution in `enrich_context` (Task 5).
- [x] **Placeholder scan:** No TBD or TODO. Every step has full code.
- [x] **Type consistency:** `fetch_thread_context` returns `{"parents": [...], "siblings": [...]}` in Task 3, consumed with `.get("parents", [])` / `.get("siblings", [])` in Task 5. `IntelThreadContext` fields defined in Task 1 match construction in Task 5.
- [x] **Intel-only:** No news/brand files touched.
- [x] **Migration:** ALTER TABLE commands in Task 1 Step 5 cover all 4 new columns + new table.
