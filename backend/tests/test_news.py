import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_news_default_topics_created():
    from radar import news
    from radar.models import NewsTopic
    s = _mem()
    news.ensure_default_topics(s)
    names = {r.name for r in s.query(NewsTopic).all()}
    assert "Военные действия" in names
    assert "Экономика" in names


def test_news_store_web_result_classifies_event():
    from radar import news
    from radar.models import NewsTopic, NewsEvent
    s = _mem()
    topic = NewsTopic(name="Военные действия", query="бпла пво")
    s.add(topic); s.commit()
    added = news._store_web_result(s, topic, {
        "title": "Несколько каналов сообщили про БПЛА",
        "url": "https://example.com/a",
        "content": "ПВО работает, источники подтверждают сигнал",
        "published": "2026-06-16",
    })
    s.commit()
    row = s.query(NewsEvent).one()
    assert added is True
    assert row.event_type == "БПЛА"
    assert row.source == "example.com"
    assert row.confidence > 0.5


def test_news_summary_counts_events():
    from radar import news
    from radar.models import NewsTopic, NewsEvent
    s = _mem()
    topic = NewsTopic(name="Экономика", query="рынки")
    s.add(topic); s.flush()
    s.add(NewsEvent(topic_id=topic.id, event_type="Сигнал", zone="Центр",
                    title="рынки", text="рынки растут", source="a.ru",
                    source_url="https://a.ru/1", confidence=0.8, severity=0.4,
                    occurred_at=datetime.now(timezone.utc)))
    s.commit()
    # Exercise the same aggregation shape used by the API without TestClient wiring.
    events = [news.event_card(e) for e in s.query(NewsEvent).all()]
    assert events[0]["confidence"] == 80
    assert events[0]["zone"] == "Центр"


def test_news_store_tg_post():
    from types import SimpleNamespace
    from radar import news
    from radar.models import NewsTopic, NewsEvent
    s = _mem()
    topic = NewsTopic(name="Военные действия", query="бпла")
    s.add(topic); s.commit()
    post = SimpleNamespace(
        post_id="channel/42", author="@channel",
        text="Сообщают о БПЛА, несколько источников подтверждают",
        created_at=datetime.now(timezone.utc),
    )
    assert news._store_tg_post(s, topic, post) is True
    s.commit()
    row = s.query(NewsEvent).one()
    assert row.event_type == "БПЛА"
    assert row.source == "@channel"
    assert row.source_url == "https://t.me/channel/42"
