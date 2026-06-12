# Telegram Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add Telegram as a parallel monitoring source via Telethon — global keyword search + specific channel/group reads — feeding the existing collector/classify/draft pipeline. TG mentions appear in Feed/Queue like TikTok/Instagram.

**Architecture:** `TelegramProvider` implements the `SearchProvider` interface. It is a *parallel* source: `_get_provider()` stays unchanged; a new `_get_tg_provider()` returns a singleton TG provider when `TELEGRAM_API_ID` is set. In `_run_collect`, probes with `platform="telegram"` route to the TG provider; all others use the main provider. The message→Post parser is a pure module-level function (testable without a live connection).

**Tech Stack:** Python/FastAPI/SQLAlchemy, Telethon 1.43.2 (installed), React. Tests mock Telethon.

**Spec:** `docs/superpowers/specs/2026-06-12-telegram-provider-design.md`
**Test command:** `cd backend && python3 -m pytest tests/ -v`
**Branch:** `feat/telegram-provider`

---

## Task 1: Dependencies, .env, .gitignore

**Files:** Modify `backend/requirements.txt`, `backend/.env`, `.gitignore`

- [ ] **Step 1: Add Telethon to requirements** — append to `backend/requirements.txt`:
```
telethon>=1.43,<2
```

- [ ] **Step 2: Add Telegram credentials to `backend/.env`** (append):
```
TELEGRAM_API_ID=34337081
TELEGRAM_API_HASH=09df1994892ffc472bb2c664682d51c4
TELEGRAM_PHONE=+65859565413597
```

- [ ] **Step 3: Ignore the session file** — append to `.gitignore` (repo root):
```
backend/*.session
backend/*.session-journal
```

- [ ] **Step 4: Verify telethon imports** — Run: `cd backend && python3 -c "import telethon; print(telethon.__version__)"` → expect `1.43.2`.

- [ ] **Step 5: Commit**
```bash
git add backend/requirements.txt .gitignore
git commit -m "chore: add telethon dep + ignore session files

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
(Do NOT commit `.env` — it is gitignored.)

---

## Task 2: TelegramProvider + message parser

**Files:** Create `backend/radar/providers/telegram.py`; Test `backend/tests/test_telegram.py`

- [ ] **Step 1: Write failing tests** — create `backend/tests/test_telegram.py`:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from radar.providers.telegram import _parse_tg_message, _sum_reactions
from radar.providers.base import Post


class _Reaction:
    def __init__(self, count): self.count = count

class _Reactions:
    def __init__(self, counts): self.results = [_Reaction(c) for c in counts]

class _Msg:
    def __init__(self, id=1, message="Заказал суши в Тануки #тануки", views=500,
                 forwards=10, reactions=None, replies_count=3):
        self.id = id
        self.message = message
        self.views = views
        self.forwards = forwards
        self.date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.reactions = _Reactions(reactions) if reactions is not None else None
        class _R: replies = replies_count
        self.replies = _R()


def test_sum_reactions_sums_all_counts():
    assert _sum_reactions(_Msg(reactions=[3, 5, 2])) == 10

def test_sum_reactions_none_is_zero():
    assert _sum_reactions(_Msg(reactions=None)) == 0

def test_parse_tg_message_maps_core_fields():
    p = _parse_tg_message(_Msg(), "@yakitoriya", followers=12000)
    assert isinstance(p, Post)
    assert p.post_id == "1"
    assert p.platform == "telegram"
    assert p.author == "@yakitoriya"
    assert p.followers == 12000
    assert p.text.startswith("Заказал суши")
    assert p.views == 500 and p.shares == 10 and p.comments == 3
    assert p.created_at == datetime(2026, 6, 1, tzinfo=timezone.utc)

def test_parse_tg_message_extracts_hashtags():
    p = _parse_tg_message(_Msg(), "@x", followers=0)
    assert "#тануки" in p.hashtags

def test_parse_tg_message_survives_empty_text():
    m = _Msg(message=None, views=0, forwards=0)
    p = _parse_tg_message(m, "@x", followers=0)
    assert p.text == "" and p.hashtags == [] and p.views == 0
```

- [ ] **Step 2: Run, expect fail** — `cd backend && python3 -m pytest tests/test_telegram.py -v` → `ModuleNotFoundError: radar.providers.telegram`.

- [ ] **Step 3: Create `backend/radar/providers/telegram.py`**:
```python
"""Telegram provider via Telethon. Parallel source to TikHub/SocialCrawl.

Requires a session file created once via `python -m radar.tg_auth`. The parser
(`_parse_tg_message`) is a pure function so it can be tested without a live client.
"""
import logging, os, re
from typing import Optional

from .base import SearchProvider, SearchPage, Post

log = logging.getLogger(__name__)

SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "tg_session")
API_ID   = os.getenv("TELEGRAM_API_ID", "")
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

_HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)


def _sum_reactions(msg) -> int:
    """Sum all reaction counts on a Telethon message; 0 if none."""
    reactions = getattr(msg, "reactions", None)
    if not reactions:
        return 0
    results = getattr(reactions, "results", None) or []
    return sum(int(getattr(r, "count", 0) or 0) for r in results)


def _parse_tg_message(msg, author_handle: str, followers: int) -> Post:
    """Map a Telethon Message to a Post. `author_handle` is the channel @username,
    `followers` the channel participant count (both resolved by the caller)."""
    text = getattr(msg, "message", None) or ""
    replies = getattr(msg, "replies", None)
    return Post(
        post_id    = str(msg.id),
        platform   = "telegram",
        author     = author_handle,
        followers  = int(followers or 0),
        text       = text,
        hashtags   = _HASHTAG_RE.findall(text),
        created_at = msg.date,
        likes      = _sum_reactions(msg),
        views      = int(getattr(msg, "views", 0) or 0),
        comments   = int(getattr(replies, "replies", 0) or 0) if replies else 0,
        shares     = int(getattr(msg, "forwards", 0) or 0),
        sound_id   = None,
    )


class TelegramProvider(SearchProvider):
    """Telethon-backed. Pass `client` for tests; otherwise a real client is built
    and connected against the session file."""

    def __init__(self, client=None):
        if client is not None:
            self._client = client
        else:
            from telethon.sync import TelegramClient
            self._client = TelegramClient(SESSION_FILE, int(API_ID), API_HASH)
            self._client.connect()

    def search(self, query: str, kind: str, cursor: Optional[str], platform: str = "telegram") -> SearchPage:
        if kind == "channel":
            return self._read_channel(query, cursor)
        return self._global_search(query, cursor)

    def _global_search(self, query: str, cursor: Optional[str]) -> SearchPage:
        from telethon.errors import FloodWaitError
        offset_id = int(cursor) if cursor else 0
        try:
            msgs = self._client.get_messages(None, search=query, limit=20, offset_id=offset_id)
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise RuntimeError(f"Telegram flood wait {e.seconds}s")
        posts = []
        for m in msgs:
            chat = getattr(m, "chat", None)
            uname = getattr(chat, "username", None)
            handle = f"@{uname}" if uname else str(getattr(getattr(m, "peer_id", None), "channel_id", "tg"))
            followers = getattr(chat, "participants_count", 0) or 0
            try:
                posts.append(_parse_tg_message(m, handle, followers))
            except Exception:
                continue
        next_cursor = str(min(m.id for m in msgs)) if len(msgs) >= 20 else None
        return SearchPage(posts=posts, next_cursor=next_cursor)

    def _read_channel(self, username: str, cursor: Optional[str]) -> SearchPage:
        from telethon.errors import FloodWaitError, ChannelPrivateError
        offset_id = int(cursor) if cursor else 0
        handle = username if username.startswith("@") else f"@{username}"
        try:
            entity = self._client.get_entity(handle)
            msgs = self._client.get_messages(entity, limit=20, offset_id=offset_id)
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise RuntimeError(f"Telegram flood wait {e.seconds}s")
        except ChannelPrivateError:
            log.warning("Telegram channel private/unavailable: %s", handle)
            return SearchPage(posts=[], next_cursor=None)
        followers = getattr(entity, "participants_count", 0) or 0
        posts = [_parse_tg_message(m, handle, followers) for m in msgs if getattr(m, "id", None)]
        next_cursor = str(min(m.id for m in msgs)) if len(msgs) >= 20 else None
        return SearchPage(posts=posts, next_cursor=next_cursor)
```

- [ ] **Step 4: Run, expect pass** — `cd backend && python3 -m pytest tests/test_telegram.py -v` → 5 pass.

- [ ] **Step 5: Add provider routing tests (append to `test_telegram.py`)**:
```python
def test_search_keyword_calls_global(monkeypatch):
    from radar.providers.telegram import TelegramProvider
    calls = {}
    class FakeClient:
        def get_messages(self, entity, **kw):
            calls["entity"] = entity; calls["kw"] = kw
            return []
    p = TelegramProvider(client=FakeClient())
    page = p.search("тануки", "keyword", None, "telegram")
    assert calls["entity"] is None             # global search uses None
    assert calls["kw"].get("search") == "тануки"
    assert page.posts == [] and page.next_cursor is None


def test_search_channel_resolves_entity(monkeypatch):
    from radar.providers.telegram import TelegramProvider
    class FakeEntity: participants_count = 100
    seen = {}
    class FakeClient:
        def get_entity(self, h): seen["handle"] = h; return FakeEntity()
        def get_messages(self, entity, **kw): seen["entity"] = entity; return []
    p = TelegramProvider(client=FakeClient())
    p.search("@yakitoriya", "channel", None, "telegram")
    assert seen["handle"] == "@yakitoriya"
    assert isinstance(seen["entity"], FakeEntity)
```

- [ ] **Step 6: Run, expect pass** — `cd backend && python3 -m pytest tests/test_telegram.py -v` → 7 pass.

- [ ] **Step 7: Commit**
```bash
git add backend/radar/providers/telegram.py backend/tests/test_telegram.py
git commit -m "feat: TelegramProvider — global search + channel read via Telethon

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: One-shot session creator (`tg_auth.py`)

**Files:** Create `backend/radar/tg_auth.py`

> Interactive script — not unit-tested. Verified by the user running it once.

- [ ] **Step 1: Create `backend/radar/tg_auth.py`**:
```python
"""One-time Telegram session creator.

Run interactively: `cd backend && python -m radar.tg_auth`
Enter the login code Telegram sends to TELEGRAM_PHONE (and 2FA password if set).
Saves the session next to the provider so TelegramProvider works autonomously.
"""
import os
from dotenv import load_dotenv

load_dotenv()

from telethon.sync import TelegramClient

SESSION_FILE = os.path.join(os.path.dirname(__file__), "tg_session")


def main():
    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    phone = os.getenv("TELEGRAM_PHONE", "")
    if not (api_id and api_hash and phone):
        print("Set TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE in backend/.env first.")
        return
    with TelegramClient(SESSION_FILE, int(api_id), api_hash) as client:
        client.start(phone=phone)
        me = client.get_me()
        print(f"✅ Session saved. Logged in as: {me.username or me.first_name} (id={me.id})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax check** — Run: `cd backend && python3 -c "import ast; ast.parse(open('radar/tg_auth.py').read()); print('ok')"` → `ok`.

- [ ] **Step 3: Commit**
```bash
git add backend/radar/tg_auth.py
git commit -m "feat: tg_auth.py — one-shot Telegram session creator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Brand.tg_channels model + migration

**Files:** Modify `backend/radar/models.py`, `backend/radar/db.py`; Test append `backend/tests/test_telegram.py`

- [ ] **Step 1: Append test to `backend/tests/test_telegram.py`**:
```python
def test_brand_tg_channels_list():
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base, Brand
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = _S(eng)
    b = Brand(name="Tanuki", tg_channels=json.dumps(["@yakitoriya", "@sushiwok"]))
    s.add(b); s.commit()
    assert b.tg_channels_list() == ["@yakitoriya", "@sushiwok"]

def test_brand_tg_channels_default_empty():
    from radar.models import Brand
    b = Brand(name="x")
    # default column value applies on flush; the helper must handle "[]"/None
    assert b.tg_channels_list() == []
```

- [ ] **Step 2: Run, expect fail** — `cd backend && python3 -m pytest tests/test_telegram.py -k tg_channels -v` → `AttributeError: tg_channels` / `tg_channels_list`.

- [ ] **Step 3: Add the column + helper to `Brand` in `backend/radar/models.py`** — add the column near the other `Text` list columns (e.g. after `audience_terms`):
```python
    tg_channels:           Mapped[str]      = mapped_column(Text, default="[]")  # ["@channel", ...]
```
And add the helper next to the other `*_list()` methods:
```python
    def tg_channels_list(self):    return json.loads(self.tg_channels or "[]")
```

- [ ] **Step 4: Add migration row in `backend/radar/db.py`** — in the `_MIGRATIONS["brands"]` dict, add:
```python
        "tg_channels": "TEXT DEFAULT '[]'",
```

- [ ] **Step 5: Run, expect pass** — `cd backend && python3 -m pytest tests/test_telegram.py -v` → all pass.
- [ ] **Step 6: Full suite** — `cd backend && python3 -m pytest tests/ -v` → PASS.
- [ ] **Step 7: Commit**
```bash
git add backend/radar/models.py backend/radar/db.py backend/tests/test_telegram.py
git commit -m "feat: Brand.tg_channels field + migration

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Wire Telegram into the pipeline (`api.py`)

**Files:** Modify `backend/radar/api.py`

- [ ] **Step 1: Append integration tests to `backend/tests/test_telegram.py`**:
```python
def test_get_tg_provider_none_without_credentials(monkeypatch):
    from radar import api
    monkeypatch.setattr(api, "TELEGRAM_API_ID", "")
    api._tg_provider_singleton = None
    assert api._get_tg_provider() is None

def test_post_url_telegram():
    from radar import api
    from radar.models import Mention
    m = Mention(platform="telegram", author="@yakitoriya", post_id="123",
                brand_id=1, created_at=None)
    assert api._post_url(m) == "https://t.me/yakitoriya/123"

def test_rebuild_probes_adds_tg_channel_probes(monkeypatch):
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar import api
    from radar.models import Base, Brand, Probe
    monkeypatch.setattr(api, "TELEGRAM_API_ID", "123")  # enable TG probes
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = _S(eng)
    b = Brand(name="Tanuki", keywords=json.dumps(["Тануки"]),
              competitors="[]", niche_keywords="[]", category_terms="[]",
              audience_terms="[]", tg_channels=json.dumps(["@yakitoriya"]))
    s.add(b); s.flush()
    api._rebuild_probes(s, b)
    tg = [p for p in s.query(Probe).filter_by(brand_id=b.id, platform="telegram").all()]
    assert any(p.kind == "channel" and p.query == "@yakitoriya" for p in tg)
    assert any(p.kind == "keyword" and p.query == "Тануки" for p in tg)
```

- [ ] **Step 2: Run, expect fail** — `cd backend && python3 -m pytest tests/test_telegram.py -k "tg_provider or post_url_telegram or rebuild_probes_adds_tg" -v` → fails (`_get_tg_provider`/`TELEGRAM_API_ID` missing, `_post_url` returns None for telegram, no TG probes).

- [ ] **Step 3: Add TG provider singleton + accessor** — in `backend/radar/api.py`, near `TIKHUB_TOKEN`/`SOCIALCRAWL_TOKEN` (around line 25-26), add:
```python
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
_tg_provider_singleton = None


def _get_tg_provider():
    """Singleton TelegramProvider, or None if not configured / session missing."""
    global _tg_provider_singleton
    if not TELEGRAM_API_ID:
        return None
    if _tg_provider_singleton is None:
        try:
            from .providers.telegram import TelegramProvider
            _tg_provider_singleton = TelegramProvider()
        except Exception:
            log.exception("Telegram provider init failed (run `python -m radar.tg_auth`?)")
            return None
    return _tg_provider_singleton
```

- [ ] **Step 4: Add the telegram branch to `_post_url`** — in `_post_url` (around line 158), before `return None`:
```python
    if m.platform == "telegram":
        return f"https://t.me/{(m.author or '').lstrip('@')}/{m.post_id}"
```

- [ ] **Step 5: Make `MONITORED_PLATFORMS` conditional + add TG channel probes in `_rebuild_probes`** — change (around line 335):
```python
MONITORED_PLATFORMS = ("tiktok", "instagram")
```
to:
```python
def _monitored_platforms() -> tuple:
    return ("tiktok", "instagram", "telegram") if TELEGRAM_API_ID else ("tiktok", "instagram")
```
In `_rebuild_probes`, change the loop header `for pf in MONITORED_PLATFORMS:` to `for pf in _monitored_platforms():`. Then, at the END of `_rebuild_probes` (after the keyword-probe loop), add channel probes:
```python
    if TELEGRAM_API_ID:
        for handle in brand.tg_channels_list():
            session.add(Probe(brand_id=brand.id, platform="telegram", kind="channel",
                              source="competitor", label=handle, query=handle))
```

- [ ] **Step 6: Route TG probes to the TG provider in `_run_collect`** — in `_run_collect` (around line 715), replace the probe loop body. Change:
```python
        total = 0
        for probe in probes:
            try:
                log.info("Collecting probe '%s' via %s", probe.query, provider.__class__.__name__)
                count = collect_probe(session, probe, provider)
                log.info("Probe '%s' → %d new mentions", probe.query, count)
                total += count
            except Exception as e:
                log.warning("Probe '%s' failed: %s", probe.query, e)
```
to:
```python
        tg_provider = _get_tg_provider()
        total = 0
        for probe in probes:
            prov = tg_provider if probe.platform == "telegram" else provider
            if prov is None:
                continue  # telegram probe but provider unavailable — skip
            try:
                log.info("Collecting probe '%s' via %s", probe.query, prov.__class__.__name__)
                count = collect_probe(session, probe, prov)
                log.info("Probe '%s' → %d new mentions", probe.query, count)
                total += count
            except Exception as e:
                log.warning("Probe '%s' failed: %s", probe.query, e)
```

- [ ] **Step 7: Run, expect pass** — `cd backend && python3 -m pytest tests/test_telegram.py -v` → all pass.
- [ ] **Step 8: Full suite** — `cd backend && python3 -m pytest tests/ -v` → PASS, no regressions.
- [ ] **Step 9: Commit**
```bash
git add backend/radar/api.py backend/tests/test_telegram.py
git commit -m "feat: wire Telegram provider into probes, collect, and post URLs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Frontend — Telegram channels field + icon

**Files:** Modify `echo-app/src/components/app/Settings.jsx`, `echo-app/src/services/api.js` (if config helper needed), `echo-app/src/components/shared/icons.jsx`

> No frontend test harness — verify with `npm run build` + manual.

- [ ] **Step 1: Add a Telegram icon** — read `echo-app/src/components/shared/icons.jsx` first to learn the `PATHS` map shape, then add a `telegram` entry using the standard Telegram paper-plane SVG path:
```
telegram: "M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z",
```
(If that key/format differs from the file's convention, adapt to match exactly — confirm the icon renders.)

- [ ] **Step 2: Add the "Telegram-каналы" field to Settings** — read `echo-app/src/components/app/Settings.jsx` first to find how an existing list field (e.g. `competitors` or `niche_keywords`) is rendered and saved via `saveBrandConfig`/`POST /brands/{id}/config`. Add a matching field bound to `tg_channels` (comma- or newline-separated `@handles`), following that exact pattern. Placeholder: `@yakitoriya, @sushiwok_official`. It must serialize to a JSON list and be included in the config-save payload as `tg_channels`.

- [ ] **Step 3: Verify the backend accepts `tg_channels`** — confirm `BrandConfigBody` in `backend/radar/api.py` includes `tg_channels: Optional[list[str]] = None` and that the config endpoint persists it. If absent, add the field to `BrandConfigBody` and the assignment in the config handler (mirror how `competitors` is handled), then re-run `cd backend && python3 -m pytest tests/ -v`.

- [ ] **Step 4: Build** — `cd echo-app && npm run build` → must succeed.

- [ ] **Step 5: Manual verification** — with backend + `npm run dev`, open Settings for a brand, confirm the "Telegram-каналы" field renders, accepts `@handles`, and saves (network tab: `tg_channels` in the POST body). The Telegram icon appears on TG mentions once collection runs.

- [ ] **Step 6: Commit**
```bash
git add echo-app/src/components/app/Settings.jsx echo-app/src/components/shared/icons.jsx echo-app/src/services/api.js backend/radar/api.py
git commit -m "feat: Telegram channels field in Settings + telegram icon

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Post-Implementation: Session Creation (manual, by user)

After all tasks merge:
```bash
cd backend && python3 -m radar.tg_auth
# Enter the code Telegram sends to +65859565413597 (+ 2FA password if set)
# → tg_session.session created
```
Restart `uvicorn`. Telegram probes now collect on the next `/brands/{id}/collect` or scheduler tick. Add `@channels` in Settings for channel-monitoring; keyword probes work automatically.

---

## Self-Review Notes

- **Spec coverage:** provider + parser (T2), session creator (T3), Brand.tg_channels (T4), pipeline wiring incl. `_get_tg_provider` / `_post_url` / probe routing / channel probes (T5), frontend field + icon (T6), deps/env/gitignore (T1). All spec sections covered.
- **Type consistency:** `_parse_tg_message(msg, author_handle, followers) -> Post` used in T2; `TelegramProvider(client=None)` injectable for tests; `_get_tg_provider() -> TelegramProvider | None` used in T5; `brand.tg_channels_list() -> list[str]` defined T4, used T5.
- **No live connection in tests:** every test injects a fake client or builds Post from a fake message object. `tg_auth.py` is the only live path and is run manually by the user.
- **Parallel-source invariant:** `_get_provider()` is untouched; TG routing happens only in `_run_collect` by `probe.platform`. Non-TG behavior is unchanged.
- **Open runtime dependency:** live collection needs the session file (`python -m radar.tg_auth`) and valid credentials. Fully buildable/testable without it; collection silently skips TG probes when `_get_tg_provider()` returns None.
