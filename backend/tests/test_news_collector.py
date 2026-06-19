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
