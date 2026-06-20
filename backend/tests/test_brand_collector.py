import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from types import SimpleNamespace


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.brand.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_collect_brand_probe_writes_brand_mention():
    """Happy path: source='brand' post with followers well above the floor (5000 > 100)
    is stored as a non-spam BrandMention and counted in the return value."""
    from radar.brand.models import Brand, BrandProbe, BrandMention
    from radar.brand import collector
    s = _mem()
    b = Brand(name="PapaPizza", keywords='["папа пицца"]')
    s.add(b); s.flush()
    p = BrandProbe(brand_id=b.id, platform="tiktok", kind="keyword", query="папа пицца", source="brand")
    s.add(p); s.commit()
    posts = [SimpleNamespace(post_id="1", author="u", text="заказал папа пицца сегодня",
                             followers=5000, created_at=datetime.now(timezone.utc), hashtags=[],
                             likes=0, views=0, comments=0, shares=0)]
    provider = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, provider)
    assert n == 1
    assert s.query(BrandMention).count() == 1
    mention = s.query(BrandMention).one()
    assert mention.is_spam is False


def test_collect_brand_probe_below_follower_floor_stored_as_spam():
    """Faithful-to-legacy: source='brand' post with followers below the floor (5 < 100)
    is STORED (is_spam=True, hidden) but does NOT count toward n and gets no snapshot.
    Legacy radar/collector.py L291: floor applies to scope.kind=='brand' unconditionally."""
    from radar.brand.models import Brand, BrandProbe, BrandMention, BrandMentionSnapshot
    from radar.brand import collector
    s = _mem()
    b = Brand(name="PapaPizza", keywords='["папа пицца"]')
    s.add(b); s.flush()
    p = BrandProbe(brand_id=b.id, platform="tiktok", kind="keyword", query="папа пицца", source="brand")
    s.add(p); s.commit()
    posts = [SimpleNamespace(post_id="2", author="u2", text="заказал папа пицца вчера",
                             followers=5, created_at=datetime.now(timezone.utc), hashtags=[],
                             likes=0, views=0, comments=0, shares=0)]
    provider = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, provider)
    # Sub-floor post: stored hidden, not counted
    assert n == 0
    assert s.query(BrandMention).count() == 1
    mention = s.query(BrandMention).one()
    assert mention.is_spam is True
    # No snapshot for spam/hidden mentions (matches legacy behavior)
    assert s.query(BrandMentionSnapshot).count() == 0
