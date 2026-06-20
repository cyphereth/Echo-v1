import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def _post(post_id, created_at, text="нишевый пост"):
    from radar.core.providers.base import Post
    return Post(post_id=post_id, platform="telegram", author="@ch", followers=0,
                text=text, hashtags=[], created_at=created_at,
                likes=0, views=0, comments=0, shares=0)


def test_store_niche_post_skips_stale():
    """Niche posts older than the freshness window must not be stored."""
    import radar.collector as C
    from radar.models import Brand, Mention
    from radar.scope import scope_for_brand
    s = _mem()
    b = Brand(id=1, name="b"); s.add(b); s.commit()
    scope = scope_for_brand(b)
    now = datetime.now(timezone.utc)
    assert C._store_niche_post(s, scope, _post("fresh", now), spam=False) is True
    assert C._store_niche_post(s, scope, _post("stale", now - timedelta(hours=48)), spam=False) is False
    s.commit()
    assert s.query(Mention).filter_by(post_id="fresh").count() == 1
    assert s.query(Mention).filter_by(post_id="stale").count() == 0


def test_inbox_hides_stale_niche_but_keeps_brand(monkeypatch, tmp_path):
    """The feed must drop stale niche posts but keep brand mentions regardless of age."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'n.db'}")
    import importlib
    import radar.core.db as db; importlib.reload(db); db.init_db()
    # Reload brand_api FIRST so the app.include_router picks up the reloaded current_user
    import radar.brand.api as brand_api; importlib.reload(brand_api)
    import radar.api as api; importlib.reload(api)
    from fastapi.testclient import TestClient
    from radar.models import Brand, User

    s = db.get_session()
    u = User(email="n@n.n", password_hash="x"); s.add(u); s.flush()
    s.add(Brand(id=1, user_id=u.id, name="b")); s.flush()
    now = datetime.now(timezone.utc)

    from radar.brand.models import BrandMention
    def mk(pid, source, age_h, text):
        s.add(BrandMention(brand_id=1, platform="telegram", post_id=pid, author="@a",
                           text=text, source=source, lane="none", is_spam=False,
                           created_at=now - timedelta(hours=age_h),
                           first_seen=now - timedelta(hours=age_h)))
    mk("nf", "niche", 2,  "свежая ниша")
    mk("ns", "niche", 48, "старая ниша")     # stale niche → must be hidden
    mk("bo", "brand", 240, "старый бренд")    # old brand mention → must stay
    s.commit()

    # /inbox?brand_id= is served by brand router — override brand_api.current_user
    api.app.dependency_overrides[brand_api.current_user] = lambda: u
    client = TestClient(api.app)
    body = client.get("/inbox?brand_id=1").json()
    texts = {c["text"] for c in body["pr"] + body["smm"]}
    api.app.dependency_overrides.clear()

    assert "свежая ниша" in texts
    assert "старый бренд" in texts        # brand kept regardless of age
    assert "старая ниша" not in texts     # stale niche hidden
