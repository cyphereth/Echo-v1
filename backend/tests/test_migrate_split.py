import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def _engine_with_old_and_new():
    from sqlalchemy import create_engine
    from radar.models import Base
    import radar.news.models, radar.brand.models  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)  # builds old (mentions/...) AND new (news_*/brand_*) tables
    return eng


def test_migration_routes_rows_by_owner():
    from sqlalchemy.orm import Session
    from radar.models import Brand, Topic, Mention
    from radar.news.models import NewsMention
    from radar.brand.models import BrandMention
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(Brand(id=1, name="B"))
        s.add(Topic(id=1, name="T"))
        s.add(Mention(id=10, brand_id=1, platform="tg", post_id="p1", author="a", text="x", created_at=now))
        s.add(Mention(id=11, topic_id=1, platform="tg", post_id="p2", author="b", text="y", created_at=now))
        s.commit()
    migrate_split(eng)
    with Session(eng) as s:
        assert s.query(BrandMention).count() == 1
        assert s.query(NewsMention).count() == 1
        assert s.get(BrandMention, 10).post_id == "p1"   # PK preserved
        assert s.get(NewsMention, 11).post_id == "p2"


def test_migration_is_idempotent():
    from sqlalchemy.orm import Session
    from radar.models import Topic, Mention
    from radar.news.models import NewsMention
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(Topic(id=1, name="T"))
        s.add(Mention(id=11, topic_id=1, platform="tg", post_id="p2", author="b", text="y", created_at=now))
        s.commit()
    migrate_split(eng)
    migrate_split(eng)  # second run must not duplicate
    with Session(eng) as s:
        assert s.query(NewsMention).count() == 1


def test_brand_child_tables_are_copied():
    """Prove brand child rows route to brand-prefixed tables via migrate_split."""
    from sqlalchemy.orm import Session
    from radar.models import Brand, Mention, Comment
    from radar.brand.models import BrandComment
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(Brand(id=1, name="B"))
        s.add(Mention(id=10, brand_id=1, platform="tg", post_id="p1", author="a", text="x", created_at=now))
        s.add(Comment(mention_id=10, comment_id="c1", author="u", text="t", created_at=now))
        s.commit()
    migrate_split(eng)
    with Session(eng) as s:
        assert s.query(BrandComment).count() == 1


def test_story_points_routing():
    """News-owned story + story_point routes to news_story_points after migrate_split."""
    from sqlalchemy.orm import Session
    from radar.models import Topic, Story, StoryPoint
    from radar.news.models import NewsStoryPoint
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(Topic(id=1, name="T"))
        s.add(Story(id=1, topic_id=1, title="s", first_seen_at=now, last_seen_at=now))
        s.add(StoryPoint(story_id=1, bucket_start=now))
        s.commit()
    migrate_split(eng)
    with Session(eng) as s:
        assert s.query(NewsStoryPoint).count() == 1
