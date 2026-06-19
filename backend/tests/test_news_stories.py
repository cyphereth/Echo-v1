import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.news.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_news_update_stories_clusters_and_verifies():
    from radar.news.models import NewsTopic, NewsMention, NewsStory
    from radar.news import stories
    s = _mem()
    t = NewsTopic(name="Военное"); s.add(t); s.flush()
    now = datetime.now(timezone.utc)
    for i, author in enumerate(["@a", "@b", "@c"]):
        s.add(NewsMention(topic_id=t.id, platform="tg", post_id=f"p{i}", author=author,
                          text="взрыв на нефтебазе под Брянском", created_at=now))
    s.commit()
    stories.update_stories(s, t.id, embed=lambda txt: [float(len(txt))])
    st = s.query(NewsStory).first()
    assert st is not None
    assert st.source_count == 3   # 3 distinct authors
    assert st.verified is True    # >= STORY_VERIFY_MIN_SOURCES (3)
