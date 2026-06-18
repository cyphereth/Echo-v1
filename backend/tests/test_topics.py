import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def _mem_with_vec():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    from radar import vec
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        vec.create_vec_tables(conn)
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


def test_collect_web_by_topic():
    import radar.collector as C
    from radar.scope import scope_for_topic
    from radar.models import Topic, Mention
    s = _mem()
    t = Topic(id=1, name="Военное", keywords='["удар"]', niche_keywords='["удар"]', kind="default")
    s.add(t); s.commit()
    class _W:
        def search(self, q, max_results=None):
            return [{"title":"Удар по складу","url":"https://n.ru/a","content":"удар дрона","published":None}]
    n = C.collect_web(s, scope_for_topic(t), _W())
    assert n == 1
    m = s.query(Mention).filter_by(platform="web").one()
    assert m.topic_id == 1 and m.brand_id is None


def test_stories_and_digest_by_topic(monkeypatch):
    import numpy as np
    import radar.stories as S, radar.digests as D
    from radar.scope import scope_for_topic
    from radar.models import Topic, Mention, Story, Report
    from datetime import datetime, timezone, timedelta
    s = _mem_with_vec()
    t = Topic(id=1, name="Эконом", keywords='["рубль"]', niche_keywords='["рубль"]', kind="default")
    s.add(t); s.flush()
    base = datetime.now(timezone.utc)
    for i in range(2):
        s.add(Mention(topic_id=1, platform="web", post_id=f"p{i}", author="a",
                      text="рубль падает", source="niche", tone="negative",
                      created_at=base - timedelta(minutes=i)))
    s.commit()
    monkeypatch.setattr(S.embeddings, "embed",
        lambda texts: np.tile(np.array([1.0,0,0]+[0]*381, dtype="float32"), (len(texts),1)))
    S.update_stories(s, scope_for_topic(t))
    assert s.query(Story).filter_by(topic_id=1).count() >= 1
    monkeypatch.setattr(D.llm, "complete", lambda *a, **k: "сводка")
    rep = D.build_daily_digest(s, scope_for_topic(t))
    assert rep is not None and rep.topic_id == 1
