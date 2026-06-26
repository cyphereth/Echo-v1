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

def test_enrich_context_resolves_locally_without_network():
    """Parent already in DB → chain built from DB, provider.fetch_thread_context NOT called."""
    from types import SimpleNamespace
    from datetime import datetime, timedelta, timezone
    from radar.intel import seed
    from radar.intel.models import IntelMention, IntelThreadContext, IntelDirection
    from radar.intel.context_pass import enrich_context

    s = _sess()
    seed.ensure_default_directions(s)
    d = s.query(IntelDirection).first()
    now = datetime.now(timezone.utc)

    # Root post and its direct parent already collected from the same channel.
    root = IntelMention(
        direction_id=d.id, platform="telegram", post_id="grp/700",
        author="@root", text="корневой пост", created_at=now - timedelta(minutes=10),
        context_fetched=True,
    )
    parent = IntelMention(
        direction_id=d.id, platform="telegram", post_id="grp/701",
        author="@mid", text="промежуточный", created_at=now - timedelta(minutes=5),
        reply_to_tg_id="700", context_fetched=True,
    )
    s.add_all([root, parent]); s.commit()

    # The new reply whose parent (701) is already local.
    reply = IntelMention(
        direction_id=d.id, platform="telegram", post_id="grp/702",
        author="@x", text="ответ", created_at=now, reply_to_tg_id="701",
    )
    s.add(reply); s.commit()

    calls = []
    fake_provider = SimpleNamespace(
        fetch_thread_context=lambda *a, **kw: calls.append(1) or {"parents": [], "siblings": []}
    )

    n = enrich_context(s, fake_provider, batch_size=10)
    assert n == 1
    assert calls == [], "local resolution must not hit Telegram"

    m2 = s.get(IntelMention, reply.id)
    assert m2.context_fetched is True
    assert m2.reply_to_id == parent.id
    assert m2.thread_root_id == root.id

    chain = (s.query(IntelThreadContext)
             .filter_by(mention_id=reply.id, role="parent")
             .order_by(IntelThreadContext.depth).all())
    assert [c.tg_msg_id for c in chain] == ["701", "700"]


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


def test_context_api_endpoint_returns_reply_chain():
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa

    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
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
    fake_user = User(email="t@t.com", password_hash="x")
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

def test_context_api_endpoint_reply_chain_depth_order_and_siblings_by_created_at():
    """Test that reply_chain is sorted root-first (descending depth) and siblings by created_at asc."""
    from datetime import datetime, timedelta, timezone
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa

    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = Session(eng)

    from radar.intel import seed
    seed.ensure_default_directions(s)
    from radar.intel.models import IntelDirection, IntelMention, IntelThreadContext

    d = s.query(IntelDirection).first()
    m = IntelMention(
        direction_id=d.id, platform="telegram", post_id="grp/600",
        author="@x", text="test", created_at=datetime.now(timezone.utc),
        reply_to_tg_id="598", context_fetched=True,
    )
    s.add(m); s.commit()

    # Create 3 parents with increasing depth: depth=0 (direct parent), depth=1 (root)
    now = datetime.now(timezone.utc)
    ctx_parent_direct = IntelThreadContext(
        mention_id=m.id, tg_msg_id="598", role="parent", depth=0,
        author="@parent", text="direct parent", created_at=now,
    )
    ctx_parent_root = IntelThreadContext(
        mention_id=m.id, tg_msg_id="597", role="parent", depth=1,
        author="@root", text="root ancestor", created_at=now - timedelta(hours=1),
    )
    s.add(ctx_parent_direct); s.add(ctx_parent_root); s.commit()

    # Create 1 sibling
    ctx_sibling = IntelThreadContext(
        mention_id=m.id, tg_msg_id="599", role="sibling", depth=None,
        author="@sibling", text="sibling message", created_at=now + timedelta(minutes=5),
    )
    s.add(ctx_sibling); s.commit()

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
    fake_user = User(email="t@t.com", password_hash="x")
    app.dependency_overrides[current_user] = lambda: fake_user

    client = TestClient(app)
    resp = client.get(f"/intel/mention/{m.id}/context")
    assert resp.status_code == 200
    data = resp.json()

    # Check mention_id
    assert data["mention_id"] == m.id

    # Check reply_chain: should be sorted root-first (depth descending)
    # reply_chain[0] should have depth=1 (root)
    # reply_chain[1] should have depth=0 (direct parent)
    assert len(data["reply_chain"]) == 2
    assert data["reply_chain"][0]["depth"] == 1, f"Expected root (depth=1) first, got {data['reply_chain'][0]}"
    assert data["reply_chain"][0]["tg_msg_id"] == "597"
    assert data["reply_chain"][1]["depth"] == 0, f"Expected direct parent (depth=0) second, got {data['reply_chain'][1]}"
    assert data["reply_chain"][1]["tg_msg_id"] == "598"

    # Check siblings: should have 1 sibling
    assert len(data["siblings"]) == 1
    assert data["siblings"][0]["tg_msg_id"] == "599"
