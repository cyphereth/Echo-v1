import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from types import SimpleNamespace


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.news.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_collect_channel_probe_writes_news_mention():
    from radar.news.models import NewsTopic, NewsProbe
    from radar.news import collector
    s = _mem()
    t = NewsTopic(name="Экономика", keywords='["инфляция"]', niche_keywords='["инфляция","рубль"]')
    s.add(t); s.flush()
    p = NewsProbe(topic_id=t.id, platform="telegram", kind="channel", query="@rbc_news")
    s.add(p); s.commit()
    posts = [SimpleNamespace(post_id="@rbc_news/1", author="@rbc_news",
                             text="инфляция в РФ ускорилась", followers=1000,
                             created_at=datetime.now(timezone.utc), hashtags=[])]
    provider = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, provider)
    from radar.news.models import NewsMention
    assert n == 1
    assert s.query(NewsMention).count() == 1


def test_collect_global_probe_niche_keyword_gating():
    """Global probes: posts without niche keywords are dropped."""
    from radar.news.models import NewsTopic, NewsProbe, NewsMention
    from radar.news import collector
    s = _mem()
    t = NewsTopic(name="Экономика", keywords='["инфляция"]', niche_keywords='["инфляция","рубль"]')
    s.add(t); s.flush()
    p = NewsProbe(topic_id=t.id, platform="telegram", kind="global", query="инфляция")
    s.add(p); s.commit()
    posts = [
        SimpleNamespace(post_id="g/1", author="@ch1",
                        text="инфляция в России выросла до 8%", followers=0,
                        created_at=datetime.now(timezone.utc), hashtags=[]),
        SimpleNamespace(post_id="g/2", author="@ch2",
                        text="кот сидел на подоконнике и смотрел в окно вдаль",
                        followers=0, created_at=datetime.now(timezone.utc), hashtags=[]),
    ]
    provider = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, provider)
    assert n == 1
    assert s.query(NewsMention).count() == 1


def test_dedup_on_platform_post_id():
    """Calling collect_probe twice must not double-insert the same post."""
    from radar.news.models import NewsTopic, NewsProbe, NewsMention
    from radar.news import collector
    s = _mem()
    t = NewsTopic(name="Экономика", keywords='["инфляция"]', niche_keywords='["инфляция"]')
    s.add(t); s.flush()
    p = NewsProbe(topic_id=t.id, platform="telegram", kind="channel", query="@rbc_news")
    s.add(p); s.commit()
    posts = [SimpleNamespace(post_id="@rbc_news/1", author="@rbc_news",
                             text="инфляция снова растёт по всей стране", followers=500,
                             created_at=datetime.now(timezone.utc), hashtags=[])]
    provider = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    collector.collect_probe(s, p, provider)
    # Reset watermark so it runs again on the same post
    p.watermark = None
    s.commit()
    n2 = collector.collect_probe(s, p, provider)
    assert n2 == 0  # already stored, not counted again
    assert s.query(NewsMention).count() == 1


def test_mixed_page_new_post_survives_duplicate():
    """A page with a new post followed by a duplicate must persist the new post.

    Before the savepoint fix, session.rollback() on the duplicate discarded
    the new post added earlier in the same transaction — data loss.
    """
    from radar.news.models import NewsTopic, NewsProbe, NewsMention
    from radar.news import collector
    s = _mem()
    t = NewsTopic(name="Экономика", keywords='["инфляция"]', niche_keywords='["инфляция"]')
    s.add(t); s.flush()
    p = NewsProbe(topic_id=t.id, platform="telegram", kind="channel", query="@rbc_news")
    s.add(p); s.commit()

    # Pre-insert the duplicate post so its (platform, post_id) already exists.
    existing = NewsMention(
        topic_id=t.id,
        platform="telegram",
        post_id="p_dup",
        author="@ch",
        followers=0,
        text="инфляция уже существует в базе данных",
        hashtags="[]",
        created_at=datetime.now(timezone.utc),
        source="channel",
    )
    s.add(existing)
    s.commit()

    # Provider returns one NEW post followed by the pre-existing DUPLICATE on the same page.
    posts = [
        SimpleNamespace(post_id="p_new", author="@ch",
                        text="инфляция продолжает расти в стране", followers=0,
                        created_at=datetime.now(timezone.utc), hashtags=[]),
        SimpleNamespace(post_id="p_dup", author="@ch",
                        text="инфляция уже существует в базе данных", followers=0,
                        created_at=datetime.now(timezone.utc), hashtags=[]),
    ]
    provider = SimpleNamespace(search=lambda q, kind, cursor: SimpleNamespace(posts=posts, cursor=None))
    n = collector.collect_probe(s, p, provider)

    # Only p_new should have been inserted (p_dup was already present).
    assert n == 1, f"expected 1 new insert, got {n}"
    # p_new must exist in the DB — it must not have been lost by the duplicate's rollback.
    assert s.query(NewsMention).filter_by(post_id="p_new").count() == 1, "p_new was not persisted"
    # p_dup must still be exactly 1 row (no second insert).
    assert s.query(NewsMention).filter_by(post_id="p_dup").count() == 1, "p_dup was duplicated"
    # Total: the pre-existing row + the new row.
    assert s.query(NewsMention).count() == 2
