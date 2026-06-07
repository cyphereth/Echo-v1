# Honest Engagement Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Echo's existing opportunity/draft pipeline into a transparent, auditable human-in-the-loop engagement system — brand replies are clearly from the official brand account, capped to prevent flooding, deduplicated, and every approve/post/skip is logged.

**Architecture:** The review queue, draft generation, and approve/skip endpoints already exist (`Queue.jsx`, `drafts.py`, `/comments/{id}/action`, `/opportunities`). This plan adds four things on top: (1) rewrites the LLM prompts and UI copy so replies disclose they're from the brand instead of "intercepting" audiences covertly; (2) adds anti-spam guardrails (one reply per thread, draft dedup) in a new `engagement.py` module; (3) adds an `EngagementLog` audit table written on every operator action; (4) adds an explicit `posted` state distinct from `approved` so "draft accepted" and "actually published from the brand account" are tracked separately.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / SQLite (backend), React + Vite (frontend), pytest (tests). LLM = Anthropic Claude via `httpx`.

**Test command:** from repo root, `cd backend && python -m pytest tests/ -v`. Tests add `backend/` to `sys.path` themselves (see `tests/test_profile_scan.py`).

**No frontend test harness exists** — frontend tasks include manual verification steps instead of automated tests.

---

## File Structure

- `backend/radar/drafts.py` — **modify**: rewrite `_system_prompt` and `evaluate_opportunity` prompts for transparency (reply is openly from the brand account, helpful-first, no covert "interception").
- `backend/radar/engagement.py` — **create**: pure helpers `normalize_reply`, `is_duplicate_reply`, `thread_already_engaged`, plus `log_engagement`.
- `backend/radar/models.py` — **modify**: add `EngagementLog` model; add `posted` to the `Comment.status` comment.
- `backend/radar/db.py` — **modify**: (new table is auto-created by `create_all`; no migration row needed) — verify only.
- `backend/radar/api.py` — **modify**: guardrail check in `_fetch_and_store_comments`; add `posted` action + audit logging in `comment_action` and `mention_action`; map `posted` in `_STATUS_OUT`; optional `status` filter on `/opportunities`.
- `backend/tests/test_engagement.py` — **create**: tests for guardrails + prompt transparency.
- `echo-app/src/components/app/Queue.jsx` — **modify**: copy changes ("перехватить" → honest wording) + a "Опубликовано" action.
- `echo-app/src/services/api.js` — **modify**: support the `posted` action (verify existing `commentAction` passes action through).

---

## Task 1: Transparency in generated replies (backend prompts)

**Files:**
- Modify: `backend/radar/drafts.py:36-46` (`evaluate_opportunity` system/user strings)
- Modify: `backend/radar/drafts.py:80-102` (`_system_prompt`)
- Test: `backend/tests/test_engagement.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_engagement.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from radar.drafts import _system_prompt, _opportunity_prompts

# Words that signal covert astroturfing — must NOT appear in any prompt.
COVERT = ["перехват", "перехватывать", "выдавать себя", "маскир", "притвор"]


def test_system_prompt_competitor_is_transparent():
    p = _system_prompt("competitor", "Tanuki", [])
    low = p.lower()
    assert "официальн" in low                     # reply is openly from the brand
    assert not any(w in low for w in COVERT)


def test_system_prompt_niche_is_transparent():
    p = _system_prompt("niche", "Tanuki", [])
    low = p.lower()
    assert "официальн" in low
    assert not any(w in low for w in COVERT)


def test_opportunity_prompts_are_transparent():
    system, user = _opportunity_prompts(
        comment_text="где лучше заказать суши?",
        source="competitor", competitor="Якитория", brand_name="Tanuki",
    )
    blob = (system + " " + user).lower()
    assert "официальн" in blob
    assert not any(w in blob for w in COVERT)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_engagement.py -v`
Expected: FAIL — `ImportError: cannot import name '_opportunity_prompts'` (it does not exist yet), and the `_system_prompt` assertions fail because current text uses "перехватывать"/"нативно".

- [ ] **Step 3: Extract opportunity prompt building into a testable function**

In `backend/radar/drafts.py`, replace the inline `system`/`user` construction inside `evaluate_opportunity` (current lines 33-46) with a call to a new pure helper. Add this function just above `evaluate_opportunity`:

```python
def _opportunity_prompts(comment_text: str, source: str,
                         competitor: Optional[str], brand_name: Optional[str]) -> tuple[str, str]:
    """Build (system, user) prompts for judging+drafting a public brand reply.
    The reply is posted openly from the brand's official account — it must read
    as the brand helping, never as an anonymous user pushing the brand."""
    brand = brand_name or "бренд"
    where = (f"под постом о конкуренте {competitor}" if (source == "competitor" and competitor)
             else "под тематическим (нишевым) постом")
    system = (
        f"Ты — SMM-менеджер бренда {brand}. Ты пишешь публичные ответы "
        f"ОТ ОФИЦИАЛЬНОГО аккаунта {brand} в комментариях соцсетей. "
        f"Читатель видит, что отвечает бренд. Твоя цель — реально помочь автору "
        f"(ответить на вопрос, дать пользу), а уже потом — мягко предложить {brand}. "
        f"Никогда не выдавай себя за обычного пользователя и не очерняй конкурентов. "
        f"Отвечай ТОЛЬКО валидным JSON без markdown."
    )
    user = (
        f'Комментарий {where}: "{comment_text}". '
        f'Есть ли здесь уместный повод для официального ответа бренда {brand}, '
        f'который сначала поможет автору? '
        f'Если да — короткий дружелюбный честный ответ от лица {brand} '
        f'(польза + мягкое предложение, без агрессии к конкуренту). '
        f'JSON: {{"is_opportunity": false, "reason": "", "reply": ""}}'
    )
    return system, user
```

- [ ] **Step 4: Use the new helper inside `evaluate_opportunity`**

In `backend/radar/drafts.py`, replace the body of `evaluate_opportunity` that built `brand`/`where`/`system`/`user` (current lines 33-46) with:

```python
    system, user = _opportunity_prompts(comment_text, source, competitor, brand_name)
```

Leave the `if not LLM_API_KEY: return {}`, the `import httpx`, the `_call()` closure, and the retry/except logic unchanged.

- [ ] **Step 5: Rewrite `_system_prompt` for transparency**

In `backend/radar/drafts.py`, replace the `_system_prompt` body (current lines 80-102) with:

```python
def _system_prompt(source: str, brand_name: Optional[str], tone_examples: list[str]) -> str:
    brand = brand_name or "бренд"
    if source == "competitor":
        system = (
            f"Ты пишешь короткие дружелюбные ответы ОТ ОФИЦИАЛЬНОГО аккаунта {brand} "
            f"в соцсетях. Пост касается конкурента. Не очерняя конкурента, по-доброму "
            f"предложи автору попробовать {brand} как альтернативу. По-русски, 1-3 "
            f"предложения, естественно, без спама, с мягким призывом."
        )
    elif source == "niche":
        system = (
            f"Ты пишешь короткие дружелюбные ответы ОТ ОФИЦИАЛЬНОГО аккаунта {brand} "
            f"в соцсетях. Пост по теме ниши, но {brand} не упомянут. Сначала добавь "
            f"пользы в обсуждение, затем уместно упомяни {brand}. По-русски, 1-3 "
            f"предложения, без спама."
        )
    else:
        system = (
            f"Ты — менеджер по репутации бренда {brand}, пишешь черновики ответов "
            f"ОТ ОФИЦИАЛЬНОГО аккаунта по-русски. Всегда давай конкретный следующий "
            f"шаг. Кратко (2-4 предложения)."
        )
    if tone_examples:
        system += "\nMatch this brand voice. Examples:\n" + "\n".join(f"- {e}" for e in tone_examples[:5])
    return system
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_engagement.py -v`
Expected: PASS — all three transparency tests green.

- [ ] **Step 7: Run the full backend suite (no regressions)**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS — existing tests still green.

- [ ] **Step 8: Commit**

```bash
git add backend/radar/drafts.py backend/tests/test_engagement.py
git commit -m "feat: transparent brand-account reply prompts (no covert interception)"
```

---

## Task 2: Anti-spam guardrails module

**Files:**
- Create: `backend/radar/engagement.py`
- Test: `backend/tests/test_engagement.py` (append)

- [ ] **Step 1: Write the failing tests (append to `backend/tests/test_engagement.py`)**

```python
from radar.engagement import normalize_reply, is_duplicate_reply


def test_normalize_reply_strips_case_punct_space():
    assert normalize_reply("  Привет!!  Заходи  ") == normalize_reply("привет заходи")


def test_is_duplicate_reply_detects_near_identical():
    recent = ["Заходите к нам в Tanuki, у нас акция!"]
    assert is_duplicate_reply("заходите к нам в tanuki у нас акция", recent) is True


def test_is_duplicate_reply_allows_distinct():
    recent = ["Заходите к нам в Tanuki, у нас акция!"]
    assert is_duplicate_reply("Спасибо за отзыв! Чем можем помочь?", recent) is False


def test_is_duplicate_reply_empty_history():
    assert is_duplicate_reply("любой текст", []) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_engagement.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.engagement'`.

- [ ] **Step 3: Create `backend/radar/engagement.py`**

```python
"""Engagement guardrails + audit logging.

These keep the human-in-the-loop reply flow honest: cap one brand reply per
thread, drop near-duplicate drafts so the brand never carpet-bombs the same line,
and record every operator decision for accountability.
"""
from __future__ import annotations
import re
from typing import Optional
from sqlalchemy.orm import Session


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_reply(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for dedup comparison."""
    t = (text or "").lower()
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


def is_duplicate_reply(candidate: str, recent: list[str], threshold: float = 0.85) -> bool:
    """True if `candidate` is at/above `threshold` word-overlap (Jaccard) with any
    recent reply. Prevents the brand from posting the same canned line repeatedly."""
    cand = set(normalize_reply(candidate).split())
    if not cand:
        return False
    for r in recent:
        prev = set(normalize_reply(r).split())
        if not prev:
            continue
        overlap = len(cand & prev) / len(cand | prev)
        if overlap >= threshold:
            return True
    return False


def thread_already_engaged(session: Session, mention_id: int) -> bool:
    """True if the brand has already approved/posted a reply under this mention —
    one brand reply per thread keeps engagement from looking like flooding."""
    from .models import Comment
    return (
        session.query(Comment)
        .filter(Comment.mention_id == mention_id,
                Comment.status.in_(("sent", "posted")))
        .first()
        is not None
    )


def log_engagement(session: Session, *, brand_id: Optional[int], mention_id: int,
                   comment_id: Optional[int], action: str, actor: str,
                   text: Optional[str]) -> None:
    """Append an audit row. Caller commits."""
    from .models import EngagementLog
    session.add(EngagementLog(
        brand_id=brand_id, mention_id=mention_id, comment_id=comment_id,
        action=action, actor=actor, text=text or "",
    ))
```

- [ ] **Step 4: Run the new pure-helper tests**

Run: `cd backend && python -m pytest tests/test_engagement.py -k "normalize or duplicate" -v`
Expected: PASS — `thread_already_engaged`/`log_engagement` need the model (Task 3); they're not exercised by these tests yet.

- [ ] **Step 5: Commit**

```bash
git add backend/radar/engagement.py backend/tests/test_engagement.py
git commit -m "feat: engagement guardrails — reply dedup + one-reply-per-thread helpers"
```

---

## Task 3: EngagementLog audit model + thread-guard test

**Files:**
- Modify: `backend/radar/models.py` (add `EngagementLog`; update `Comment.status` comment)
- Test: `backend/tests/test_engagement.py` (append)

- [ ] **Step 1: Write the failing test (append to `backend/tests/test_engagement.py`)**

```python
def _mem_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_thread_already_engaged_true_after_sent():
    from datetime import datetime, timezone
    from radar.models import Mention, Comment
    from radar.engagement import thread_already_engaged
    s = _mem_session()
    m = Mention(brand_id=1, platform="tiktok", post_id="p1", author="a",
                text="t", created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    s.add(Comment(mention_id=m.id, comment_id="c1", text="x",
                  status="sent", created_at=datetime.now(timezone.utc)))
    s.commit()
    assert thread_already_engaged(s, m.id) is True


def test_thread_already_engaged_false_when_only_pending():
    from datetime import datetime, timezone
    from radar.models import Mention, Comment
    from radar.engagement import thread_already_engaged
    s = _mem_session()
    m = Mention(brand_id=1, platform="tiktok", post_id="p2", author="a",
                text="t", created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    s.add(Comment(mention_id=m.id, comment_id="c1", text="x",
                  status="pending", created_at=datetime.now(timezone.utc)))
    s.commit()
    assert thread_already_engaged(s, m.id) is False


def test_log_engagement_writes_row():
    from radar.models import EngagementLog
    from radar.engagement import log_engagement
    s = _mem_session()
    log_engagement(s, brand_id=1, mention_id=5, comment_id=9,
                   action="posted", actor="ops@x.com", text="hi")
    s.commit()
    row = s.query(EngagementLog).one()
    assert row.action == "posted" and row.actor == "ops@x.com"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_engagement.py -k "thread_already or log_engagement" -v`
Expected: FAIL — `ImportError: cannot import name 'EngagementLog' from 'radar.models'`.

- [ ] **Step 3: Add the `EngagementLog` model**

In `backend/radar/models.py`, append after the `DraftEdit` class (after current line 146):

```python
class EngagementLog(Base):
    """Audit trail: every operator decision on a brand reply (approve/post/skip)."""
    __tablename__ = "engagement_log"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("brands.id"))
    mention_id: Mapped[int]           = mapped_column(ForeignKey("mentions.id"))
    comment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("comments.id"))
    action:     Mapped[str]           = mapped_column(Text)   # approved | posted | skipped | rejected
    actor:      Mapped[str]           = mapped_column(Text, default="")  # user email
    text:       Mapped[str]           = mapped_column(Text, default="")  # final reply text at decision time
    created_at: Mapped[datetime]      = mapped_column(default=_now)
```

- [ ] **Step 4: Update the `Comment.status` comment to document the new state**

In `backend/radar/models.py`, change the `Comment.status` line (current line 131) from:

```python
    status:     Mapped[str]             = mapped_column(Text, default="pending")  # pending | sent | skipped
```

to:

```python
    status:     Mapped[str]             = mapped_column(Text, default="pending")  # pending | sent (approved) | posted | skipped
```

- [ ] **Step 5: Run the model-backed tests**

Run: `cd backend && python -m pytest tests/test_engagement.py -v`
Expected: PASS — all engagement tests green (`EngagementLog` is auto-created by `Base.metadata.create_all`).

- [ ] **Step 6: Commit**

```bash
git add backend/radar/models.py backend/tests/test_engagement.py
git commit -m "feat: EngagementLog audit model + posted comment state"
```

---

## Task 4: Apply guardrails in comment fetch pipeline

**Files:**
- Modify: `backend/radar/api.py:908-922` (opportunity branch in `_fetch_and_store_comments`)

- [ ] **Step 1: Write the failing test (append to `backend/tests/test_engagement.py`)**

```python
def test_fetch_skips_when_thread_already_engaged(monkeypatch):
    """If a brand reply already went out under a mention, no new opportunity
    draft is generated for further comments in that same thread."""
    from datetime import datetime, timezone
    from radar import api
    from radar.models import Brand, Mention, Comment
    s = _mem_session()
    b = Brand(id=1, name="Tanuki", sphere="суши"); s.add(b)
    m = Mention(brand_id=1, platform="tiktok", post_id="p9", author="a",
                text="t", source="competitor", competitor="Якитория",
                created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    # An already-sent reply in this thread:
    s.add(Comment(mention_id=m.id, comment_id="old", text="x",
                  status="sent", created_at=datetime.now(timezone.utc)))
    s.commit()

    # Provider returns a fresh comment that WOULD be an opportunity.
    from radar.providers.base import FetchedComment
    fc = FetchedComment(comment_id="new1", author="u", followers=0,
                        text="где лучше заказать суши?", likes=5,
                        created_at=datetime.now(timezone.utc))
    monkeypatch.setattr(api, "_get_provider",
                        lambda: type("P", (), {"fetch_comments": lambda self, *a, **k: [fc]})())
    # If evaluate_opportunity is called, fail loudly — it must be skipped.
    import radar.drafts as d
    monkeypatch.setattr(d, "evaluate_opportunity",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should skip")))
    monkeypatch.setattr("radar.spam.classify_ads_batch", lambda texts, sphere="": [False] * len(texts))
    monkeypatch.setattr("radar.spam.looks_like_ad_cheap", lambda *a, **k: False)

    api._fetch_and_store_comments(s, m)
    stored = s.query(Comment).filter_by(comment_id="new1").one()
    assert stored.is_opportunity is False and stored.draft is None
```

> **Note:** confirm the provider comment dataclass name/shape in `backend/radar/providers/base.py` (it may be `Comment`/`FetchedComment` with different fields). Adjust the `fc` construction to match the real class before running.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_engagement.py -k "thread_already_engaged or already_engaged" -v`
Expected: FAIL — `AssertionError: should skip` (guardrail not wired yet, so `evaluate_opportunity` is called).

- [ ] **Step 3: Wire the guardrail into the opportunity branch**

In `backend/radar/api.py`, find the opportunity branch in `_fetch_and_store_comments` (current lines 910-922). Add an import at the top of the function body (near the other local imports, after current line 881) :

```python
    from .engagement import thread_already_engaged, is_duplicate_reply
    engaged = thread_already_engaged(session, mention.id)
    sent_replies = [c.draft for c in mention.comment_rows
                    if c.draft and c.status in ("sent", "posted")]
```

Then change the opportunity branch (current lines 910-922) from:

```python
        elif is_comp_niche:
            # Opportunity interception: prefilter cheaply, then let Claude decide
            # and write the intercept reply in one call.
            if _is_opportunity_candidate(fc.text, sentiment) and drafted < MAX_COMMENT_DRAFTS:
                ev = evaluate_opportunity(
                    fc.text, mention.source, mention.competitor,
                    brand.name if brand else None,
                )
                if ev.get("is_opportunity") and ev.get("reply"):
                    draft      = ev["reply"]
                    opp_reason = ev.get("reason") or None
                    is_opp     = True
                    drafted   += 1
```

to:

```python
        elif is_comp_niche and not engaged:
            # Honest engagement: one brand reply per thread, prefilter cheaply,
            # then let Claude decide and write an openly-branded reply. Skip
            # near-duplicate drafts so the brand never repeats a canned line.
            if _is_opportunity_candidate(fc.text, sentiment) and drafted < MAX_COMMENT_DRAFTS:
                ev = evaluate_opportunity(
                    fc.text, mention.source, mention.competitor,
                    brand.name if brand else None,
                )
                reply = ev.get("reply")
                if ev.get("is_opportunity") and reply and not is_duplicate_reply(reply, sent_replies):
                    draft      = reply
                    opp_reason = ev.get("reason") or None
                    is_opp     = True
                    drafted   += 1
                    engaged    = True  # cap to one fresh draft per thread per fetch
```

- [ ] **Step 4: Run the guardrail test**

Run: `cd backend && python -m pytest tests/test_engagement.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/radar/api.py backend/tests/test_engagement.py
git commit -m "feat: cap one brand reply per thread + drop duplicate drafts"
```

---

## Task 5: Audit logging + `posted` action in operator endpoints

**Files:**
- Modify: `backend/radar/api.py:840` (`_STATUS_OUT`)
- Modify: `backend/radar/api.py:987-1011` (`CommentActionBody`, `comment_action`)
- Modify: `backend/radar/api.py:790-816` (`mention_action`)

- [ ] **Step 1: Write the failing test (append to `backend/tests/test_engagement.py`)**

```python
def test_comment_action_posted_logs_and_sets_status(monkeypatch):
    from datetime import datetime, timezone
    from radar import api
    from radar.models import Brand, Mention, Comment, EngagementLog
    s = _mem_session()
    s.add(Brand(id=1, name="Tanuki")); 
    m = Mention(brand_id=1, platform="tiktok", post_id="p", author="a",
                text="t", created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    c = Comment(mention_id=m.id, comment_id="c", text="q", draft="ответ",
                status="pending", created_at=datetime.now(timezone.utc))
    s.add(c); s.commit()

    monkeypatch.setattr(api, "_owned_mention", lambda session, mid, user: m)
    body = api.CommentActionBody(action="posted")

    class U: id = 1; email = "ops@x.com"
    api.comment_action(c.id, body, user=U(), session=s)

    assert s.get(Comment, c.id).status == "posted"
    log = s.query(EngagementLog).filter_by(action="posted").one()
    assert log.actor == "ops@x.com" and log.comment_id == c.id
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_engagement.py -k "posted_logs" -v`
Expected: FAIL — `comment_action` rejects `action="posted"` with `HTTPException(400, "Unknown action: posted")`.

- [ ] **Step 3: Map `posted` in the status-out table**

In `backend/radar/api.py`, change `_STATUS_OUT` (current line 840) from:

```python
_STATUS_OUT = {"sent": "approved", "skipped": "skipped", "pending": "pending"}
```

to:

```python
_STATUS_OUT = {"sent": "approved", "posted": "posted", "skipped": "skipped", "pending": "pending"}
```

- [ ] **Step 4: Add `posted` handling + audit logging to `comment_action`**

In `backend/radar/api.py`, replace the body of `comment_action` (current lines 992-1011) from the `if body.action == "approve":` block through `session.commit(); return {"ok": True}` with:

```python
    c = session.get(Comment, comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    mention = _owned_mention(session, c.mention_id, user)
    actor = getattr(user, "email", "") or ""
    from .engagement import log_engagement
    if body.action == "approve":
        if body.draft and body.draft != c.draft:
            session.add(DraftEdit(
                mention_id=c.mention_id, brand_id=mention.brand_id if mention else None,
                category="comment", original=c.draft or "", edited=body.draft,
            ))
        c.draft  = body.draft or c.draft
        c.status = "sent"
        log_engagement(session, brand_id=mention.brand_id if mention else None,
                       mention_id=c.mention_id, comment_id=c.id,
                       action="approved", actor=actor, text=c.draft)
    elif body.action == "posted":
        c.draft  = body.draft or c.draft
        c.status = "posted"
        log_engagement(session, brand_id=mention.brand_id if mention else None,
                       mention_id=c.mention_id, comment_id=c.id,
                       action="posted", actor=actor, text=c.draft)
    elif body.action == "skip":
        c.status = "skipped"
        log_engagement(session, brand_id=mention.brand_id if mention else None,
                       mention_id=c.mention_id, comment_id=c.id,
                       action="skipped", actor=actor, text=c.draft)
    else:
        raise HTTPException(400, f"Unknown action: {body.action}")
    session.commit()
    return {"ok": True}
```

> The `_owned_mention` call now both authorizes and gives us `mention.brand_id`; this replaces the old separate `_owned_mention(...)` + inline `session.get(Mention, ...)`.

- [ ] **Step 5: Add audit logging to `mention_action`**

In `backend/radar/api.py`, inside `mention_action` (current lines 790-816), after the `approve`/`reject`/`pr` branches and before `session.commit()` (current line 815), insert:

```python
    from .engagement import log_engagement
    _action_map = {"approve": "approved", "reject": "rejected", "pr": "pr"}
    log_engagement(session, brand_id=m.brand_id, mention_id=m.id, comment_id=None,
                   action=_action_map.get(body.action, body.action),
                   actor=getattr(user, "email", "") or "", text=m.draft)
```

- [ ] **Step 6: Run the new test**

Run: `cd backend && python -m pytest tests/test_engagement.py -k "posted_logs" -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/radar/api.py backend/tests/test_engagement.py
git commit -m "feat: posted action + engagement audit log on operator decisions"
```

---

## Task 6: Frontend honesty copy + "Опубликовано" action

**Files:**
- Modify: `echo-app/src/components/app/Queue.jsx:67-73` (badge tooltip), `:252-256` (filter chip), `:117-129` (actions)
- Verify: `echo-app/src/services/api.js` (`commentAction` passes `action` through)

- [ ] **Step 1: Verify the api service passes the action through**

Run: `grep -n "commentAction\|getOpportunities" echo-app/src/services/api.js`
Expected: `commentAction(id, action, draft)` posts `{ action, draft }` to `/comments/{id}/action`. If it hard-codes `approve`/`skip`, widen it to forward any `action` string. No change needed if it already forwards `action`.

- [ ] **Step 2: Replace covert "перехват" copy in the opportunity badge tooltip**

In `echo-app/src/components/app/Queue.jsx`, change line 69 from:

```jsx
              title={c.opportunity || 'Возможность перехватить аудиторию'}
```

to:

```jsx
              title={c.opportunity || 'Уместный повод ответить от бренда'}
```

- [ ] **Step 3: Replace covert copy in the filter chip tooltip**

In `echo-app/src/components/app/Queue.jsx`, change line 254 from:

```jsx
              title="Только перехват аудитории конкурентов">
```

to:

```jsx
              title="Только поводы ответить от бренда">
```

- [ ] **Step 4: Add a "Опубликовано" action to `ReplyCard`**

In `echo-app/src/components/app/Queue.jsx`, the `ReplyCard` actions row (current lines 117-129) has Пропустить / Изменить / Отправить. Update the props and buttons so an operator can mark a reply as actually published from the brand account.

Change the `ReplyCard` signature (line 46) from:

```jsx
function ReplyCard({ c, postUrl, onApprove, onSkip }) {
```

to:

```jsx
function ReplyCard({ c, postUrl, onApprove, onSkip, onPosted }) {
```

Then in the actions row, change the primary "Отправить" button (current lines 126-128) from:

```jsx
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => { onApprove(c.id, draft); setDone(true); setDoneType('sent'); }}>
              <Icon name="send" size={13} />Отправить
            </button>
```

to:

```jsx
            <button className={`${styles.btn} ${styles.btnGhost}`} onClick={() => { onApprove(c.id, draft); setDone(true); setDoneType('sent'); }}>
              <Icon name="check" size={13} />Одобрить
            </button>
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => { onPosted(c.id, draft); setDone(true); setDoneType('sent'); }}>
              <Icon name="send" size={13} />Опубликовано
            </button>
```

- [ ] **Step 5: Wire `onPosted` in `QueueScreen`**

In `echo-app/src/components/app/Queue.jsx`, after the `onSkip` handler (current lines 173-176), add:

```jsx
  const onPosted = (id, draft) => {
    setStates(s => ({ ...s, [id]: 'approved' }));
    if (oppIds.has(id)) api.commentAction(id, 'posted', draft).catch(() => {});
  };
```

Then pass it to the card (current line 335) — change:

```jsx
                      <ReplyCard key={c.id} c={c} postUrl={video.url} onApprove={onApprove} onSkip={onSkip} />
```

to:

```jsx
                      <ReplyCard key={c.id} c={c} postUrl={video.url} onApprove={onApprove} onSkip={onSkip} onPosted={onPosted} />
```

- [ ] **Step 6: Manual verification**

Run the app (`cd echo-app && npm run dev`, backend running separately), open the Queue / Возможности view for a brand that has opportunity comments. Confirm:
- The "🎯 Возможность" badge tooltip reads "Уместный повод ответить от бренда".
- Each reply card shows Пропустить / Изменить / **Одобрить** / **Опубликовано**.
- Clicking "Опубликовано" marks the card done and (network tab) POSTs `{action:"posted"}` to `/comments/{id}/action`.
- Backend: the comment row status becomes `posted` and a row appears in `engagement_log` (`sqlite3 backend/echo_radar.db "select action,actor from engagement_log order by id desc limit 3;"`).

- [ ] **Step 7: Commit**

```bash
git add echo-app/src/components/app/Queue.jsx echo-app/src/services/api.js
git commit -m "feat: honest engagement copy + Опубликовано action in queue"
```

---

## Self-Review Notes

- **Spec coverage:** (1) transparency → Task 1 + Task 6; (2) operator queue/workflow → existing queue + `posted` state in Tasks 3/5/6; (3) anti-spam guardrails → Tasks 2/4; (4) audit → Tasks 3/5. All four parts covered.
- **Type consistency:** `EngagementLog(brand_id, mention_id, comment_id, action, actor, text, created_at)` is defined in Task 3 and used identically in Tasks 5; `log_engagement(session, *, brand_id, mention_id, comment_id, action, actor, text)` signature matches all call sites; `is_duplicate_reply(candidate, recent, threshold=0.85)` and `thread_already_engaged(session, mention_id)` used consistently in Task 4.
- **Open verification point (flagged in Task 4 Step 1):** confirm the provider fetched-comment dataclass name/fields in `backend/radar/providers/base.py` before writing that test's `fc` object.
- **Status vocabulary:** `Comment.status` ∈ {pending, sent, posted, skipped}; `_STATUS_OUT` maps sent→approved, posted→posted. Frontend keeps `doneType='sent'` cosmetics for both Одобрить and Опубликовано (visual only); the persisted action differs (`approve` vs `posted`).
- **YAGNI:** no new tables beyond `engagement_log`; relevance gating reuses the LLM's existing `is_opportunity` decision rather than adding a separate scorer.
```