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
        followers=0, created_at=datetime.now(timezone.utc),
        hashtags=[], likes=0, reply_to_tg_id="199",
    )]
    prov = SimpleNamespace(search_chat=lambda h, term, limit, min_id: posts)
    n = collector.collect_probe(s, probe, prov)
    assert n == 1
    m = s.query(IntelMention).one()
    assert m.reply_to_tg_id == "199"
