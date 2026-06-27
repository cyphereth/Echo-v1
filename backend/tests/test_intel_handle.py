"""Tests for Telegram handle normalisation in the intel collector."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from types import SimpleNamespace


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


# ── Unit tests for _clean_handle / _is_invite_link ────────────────────────────

def test_clean_handle():
    from radar.intel.collector import _clean_handle, _is_invite_link

    assert _clean_handle("https://t.me/pravdanews") == "@pravdanews"
    assert _clean_handle("t.me/x") == "@x"
    assert _clean_handle("@y") == "@y"
    assert _clean_handle("z") == "@z"
    # Invite links must be returned unchanged
    assert _clean_handle("https://t.me/+ABC") == "https://t.me/+ABC"

    assert _is_invite_link("https://t.me/+ABC") is True
    assert _is_invite_link("https://t.me/x") is False


# ── _ensure_joined dedups when an invite resolves to an already-tracked source ─

def test_ensure_joined_drops_duplicate_on_resolve():
    """Two different invite links resolving to the same #id must not create a dup:
    the second probe is deleted and _ensure_joined returns False (skip collect)."""
    from radar.intel import passes
    from radar.intel.models import IntelProbe

    s = _sess()
    # Probe A already tracks the resolved chat id.
    a = IntelProbe(platform="telegram", kind="chat", query="#123", side="ru")
    # Probe B is a fresh invite link that will resolve to the same #123.
    b = IntelProbe(platform="telegram", kind="chat", query="https://t.me/+DUP", side="ru")
    s.add_all([a, b]); s.commit()
    bid = b.id

    prov = SimpleNamespace(join_invite=lambda link: "#123")
    kept = passes._ensure_joined(b, prov, s)

    assert kept is False, "duplicate probe must signal skip"
    assert s.get(IntelProbe, bid) is None, "duplicate probe must be deleted"
    assert s.query(IntelProbe).filter_by(query="#123").count() == 1


def test_ensure_joined_rewrites_query_when_unique():
    """A fresh invite link resolving to a NOT-yet-tracked handle just rewrites query."""
    from radar.intel import passes
    from radar.intel.models import IntelProbe

    s = _sess()
    b = IntelProbe(platform="telegram", kind="channel", query="https://t.me/+NEW", side="ua")
    s.add(b); s.commit()

    prov = SimpleNamespace(join_invite=lambda link: "@resolved_handle")
    kept = passes._ensure_joined(b, prov, s)

    assert kept is True
    assert s.get(IntelProbe, b.id).query == "@resolved_handle"


# ── collect_probe passes clean handle to provider.search ─────────────────────

def test_collect_uses_clean_handle():
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention, IntelDirection, IntelLexicon

    s = _sess()
    seed.ensure_default_directions(s)
    s.add(IntelLexicon(term="удар", meaning="strike", category="military"))

    p = IntelProbe(platform="telegram", kind="channel", query="https://t.me/rbc", side="ru")
    s.add(p)
    s.commit()

    called_with: list[str] = []
    post = SimpleNamespace(
        post_id="@rbc/1",
        author="@rbc",
        text="удар по складу под Суджей, новые данные",
        followers=0,
        created_at=datetime.now(timezone.utc),
        hashtags=[],
        likes=0,
    )

    def mock_search(q, kind, cursor):
        called_with.append(q)
        return SimpleNamespace(posts=[post], cursor=None)

    prov = SimpleNamespace(search=mock_search)
    n = collector.collect_probe(s, p, prov)

    assert called_with == ["@rbc"], f"provider.search was called with {called_with!r}, expected ['@rbc']"
    assert n == 1
    assert s.query(IntelMention).count() == 1


# ── invite-link chat probe is skipped cleanly ─────────────────────────────────

def test_invite_chat_collected_via_link():
    from radar.intel import seed, collector
    from radar.intel.models import IntelProbe, IntelMention

    s = _sess()
    seed.ensure_default_directions(s)

    p = IntelProbe(platform="telegram", kind="chat", query="https://t.me/+ABC", side="ru")
    s.add(p)
    s.commit()

    search_chat_called = []

    def mock_search_chat(handle, term="", limit=50, min_id=0):
        search_chat_called.append(handle)
        return []

    prov = SimpleNamespace(search_chat=mock_search_chat)
    n = collector.collect_probe(s, p, prov)

    # После авто-join (passes._ensure_joined) invite-чат собирается как обычный:
    # ссылка передаётся в search_chat как handle — провайдер её резолвит.
    assert n == 0, f"expected 0 but got {n}"
    assert search_chat_called == ["https://t.me/+ABC"], \
        "invite-link chat is now collected: search_chat called with the invite link"
    assert s.query(IntelMention).count() == 0
