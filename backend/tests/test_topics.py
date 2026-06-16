import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_topic_and_topic_id_columns():
    from radar.models import Topic, Mention, Story
    from datetime import datetime, timezone
    s = _mem()
    t = Topic(name="Экономика", keywords='["инфляция","рубль"]', kind="default", user_id=None)
    s.add(t); s.flush()
    s.add(Mention(topic_id=t.id, platform="web", post_id="p", author="a", text="x",
                  source="niche", created_at=datetime.now(timezone.utc)))
    s.add(Story(topic_id=t.id, title="s",
                first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc)))
    s.commit()
    assert t.id and t.kind == "default" and t.user_id is None
    assert s.query(Mention).filter_by(topic_id=t.id).count() == 1
    assert s.query(Story).filter_by(topic_id=t.id).count() == 1
    assert t.keywords_list() == ["инфляция", "рубль"]


def test_scope_owner_kwargs_and_keywords():
    from radar.models import Brand, Topic
    from radar.scope import scope_for_brand, scope_for_topic
    s = _mem()
    b = Brand(id=1, name="B", keywords='["k1"]', niche_keywords='["n1"]'); s.add(b)
    t = Topic(id=1, name="T", keywords='["k2"]', niche_keywords='["n2"]', kind="default"); s.add(t)
    s.flush()
    sb = scope_for_brand(b); st = scope_for_topic(t)
    assert sb.kind == "brand" and sb.owner_kwargs() == {"brand_id": 1} and "k1" in sb.keywords
    assert st.kind == "topic" and st.owner_kwargs() == {"topic_id": 1} and "n2" in st.niche_keywords
