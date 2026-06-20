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
    from radar.brand.models import Brand, BrandProbe, BrandMention
    from radar.brand import collector
    s = _mem()
    b = Brand(name="PapaPizza", keywords='["папа пицца"]')
    s.add(b); s.flush()
    p = BrandProbe(brand_id=b.id, platform="tiktok", kind="keyword", query="папа пицца", source="brand")
    s.add(p); s.commit()
    posts = [SimpleNamespace(post_id="1", author="u", text="заказал папа пицца сегодня",
                             followers=10, created_at=datetime.now(timezone.utc), hashtags=[],
                             likes=0, views=0, comments=0, shares=0)]
    provider = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, provider)
    assert n == 1
    assert s.query(BrandMention).count() == 1
