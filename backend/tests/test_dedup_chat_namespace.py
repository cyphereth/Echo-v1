"""Скрипт схлопывания marked/unmarked дублей чат-сообщений и бэкфилла оборванных веток."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from datetime import datetime, timezone


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    from radar.intel.models import IntelDirection
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = Session(eng)
    d = IntelDirection(key="test", name="Test")
    s.add(d); s.flush()
    s._test_direction_id = d.id
    return s


def _m(s, post_id, **kw):
    from radar.intel.models import IntelMention
    kw.setdefault("direction_id", s._test_direction_id)
    m = IntelMention(platform="telegram", post_id=post_id, author="@u", side="ru",
                     text="t", created_at=datetime.now(timezone.utc), **kw)
    s.add(m); s.flush()
    return m


def test_find_pairs_marked_and_unmarked():
    from dedup_chat_namespace import find_namespace_dupes
    s = _sess()
    marked = _m(s, "-1001234567890/567")
    unmarked = _m(s, "1234567890/567")
    _m(s, "1234567890/999")  # одиночка — не пара
    s.commit()

    pairs = find_namespace_dupes(s)
    assert len(pairs) == 1
    keep, drop = pairs[0]
    ids = {keep.post_id, drop.post_id}
    assert ids == {"-1001234567890/567", "1234567890/567"}
    # keep — unmarked (канонический), drop — marked
    assert keep.post_id == "1234567890/567"


def test_collapse_repoints_context_and_refs():
    from dedup_chat_namespace import collapse_dupe
    from radar.intel.models import IntelThreadContext, IntelMention
    s = _sess()
    keep = _m(s, "1234567890/567")
    drop = _m(s, "-1001234567890/567")
    # чужое упоминание ссылается на drop
    child = _m(s, "1234567890/600", reply_to_id=drop.id, thread_root_id=drop.id)
    ctx = IntelThreadContext(mention_id=drop.id, tg_msg_id="500", role="parent",
                             depth=1, author="@a", text="x",
                             created_at=datetime.now(timezone.utc))
    s.add(ctx); s.commit()

    collapse_dupe(s, keep, drop)
    s.commit()

    assert s.get(IntelMention, drop.id) is None
    assert s.query(IntelThreadContext).filter_by(mention_id=keep.id).count() == 1
    refreshed = s.get(IntelMention, child.id)
    assert refreshed.reply_to_id == keep.id
    assert refreshed.thread_root_id == keep.id


def test_reset_broken_chains():
    from dedup_chat_namespace import reset_broken_chains
    s = _sess()
    broken = _m(s, "ns/1", reply_to_tg_id="9", reply_to_id=None, context_fetched=True)
    ok = _m(s, "ns/2", reply_to_tg_id="9", reply_to_id=broken.id, context_fetched=True)
    s.commit()

    n = reset_broken_chains(s, limit=200)
    s.commit()
    assert n == 1
    assert s.get(type(broken), broken.id).context_fetched is False
    assert s.get(type(ok), ok.id).context_fetched is True
