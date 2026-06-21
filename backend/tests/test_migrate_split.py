"""test_migrate_split.py — tests for core.migrate_split one-shot data migration.

Legacy tables (mentions, comments, stories, story_points, topics) no longer have
ORM classes in radar.models (they were removed in Phase 5). This file defines minimal
"legacy stub" mapped classes just for test fixture creation; they produce the same
table DDL that migrate_split expects as input.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone

from sqlalchemy import Integer, Text, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from typing import Optional


# ── Minimal legacy stubs (produce the same tables migrate_split reads from) ─────

class _LegacyBase(DeclarativeBase):
    pass


class _Topic(_LegacyBase):
    __tablename__ = "topics"
    id:   Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)


class _Mention(_LegacyBase):
    __tablename__ = "mentions"
    __table_args__ = {"extend_existing": True}
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:   Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    topic_id:   Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    platform:   Mapped[str]           = mapped_column(Text)
    post_id:    Mapped[str]           = mapped_column(Text)
    author:     Mapped[str]           = mapped_column(Text)
    text:       Mapped[str]           = mapped_column(Text)
    created_at: Mapped[datetime]      = mapped_column(DateTime)


class _Comment(_LegacyBase):
    __tablename__ = "comments"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[int]           = mapped_column(Integer)
    comment_id: Mapped[str]           = mapped_column(Text)
    author:     Mapped[Optional[str]] = mapped_column(Text)
    text:       Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime]      = mapped_column(DateTime)


class _Story(_LegacyBase):
    __tablename__ = "stories"
    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:      Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    topic_id:      Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title:         Mapped[str]           = mapped_column(Text, default="")
    status:        Mapped[str]           = mapped_column(Text, default="active")
    first_seen_at: Mapped[datetime]      = mapped_column(DateTime)
    last_seen_at:  Mapped[datetime]      = mapped_column(DateTime)


class _StoryPoint(_LegacyBase):
    __tablename__ = "story_points"
    id:           Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id:     Mapped[int]  = mapped_column(Integer)
    bucket_start: Mapped[datetime] = mapped_column(DateTime)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)


def _engine_with_old_and_new():
    from sqlalchemy import create_engine
    from radar.models import Base
    import radar.news.models, radar.brand.models  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)          # new domain tables
    _LegacyBase.metadata.create_all(eng)   # legacy source tables
    return eng


def test_migration_routes_rows_by_owner():
    from sqlalchemy.orm import Session
    from radar.models import Brand
    from radar.news.models import NewsMention
    from radar.brand.models import BrandMention
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(Brand(id=1, name="B"))
        s.add(_Topic(id=1, name="T"))
        s.add(_Mention(id=10, brand_id=1, platform="tg", post_id="p1", author="a", text="x", created_at=now))
        s.add(_Mention(id=11, topic_id=1, platform="tg", post_id="p2", author="b", text="y", created_at=now))
        s.commit()
    migrate_split(eng)
    with Session(eng) as s:
        assert s.query(BrandMention).count() == 1
        assert s.query(NewsMention).count() == 1
        assert s.get(BrandMention, 10).post_id == "p1"   # PK preserved
        assert s.get(NewsMention, 11).post_id == "p2"


def test_migration_is_idempotent():
    from sqlalchemy.orm import Session
    from radar.news.models import NewsMention
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(_Topic(id=1, name="T"))
        s.add(_Mention(id=11, topic_id=1, platform="tg", post_id="p2", author="b", text="y", created_at=now))
        s.commit()
    migrate_split(eng)
    migrate_split(eng)  # second run must not duplicate
    with Session(eng) as s:
        assert s.query(NewsMention).count() == 1


def test_brand_child_tables_are_copied():
    """Prove brand child rows route to brand-prefixed tables via migrate_split."""
    from sqlalchemy.orm import Session
    from radar.models import Brand
    from radar.brand.models import BrandComment
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(Brand(id=1, name="B"))
        s.add(_Mention(id=10, brand_id=1, platform="tg", post_id="p1", author="a", text="x", created_at=now))
        s.add(_Comment(mention_id=10, comment_id="c1", author="u", text="t", created_at=now))
        s.commit()
    migrate_split(eng)
    with Session(eng) as s:
        assert s.query(BrandComment).count() == 1


def test_story_points_routing():
    """News-owned story + story_point routes to news_story_points after migrate_split."""
    from sqlalchemy.orm import Session
    from radar.news.models import NewsStoryPoint
    from radar.core.migrate_split import migrate_split
    eng = _engine_with_old_and_new()
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(_Topic(id=1, name="T"))
        s.add(_Story(id=1, topic_id=1, title="s", first_seen_at=now, last_seen_at=now))
        s.add(_StoryPoint(story_id=1, bucket_start=now))
        s.commit()
    migrate_split(eng)
    with Session(eng) as s:
        assert s.query(NewsStoryPoint).count() == 1
