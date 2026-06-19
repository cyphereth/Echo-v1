from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..models import Base, _now
import json


class NewsTopic(Base):
    __tablename__ = "news_topics"
    id:             Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:        Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    name:           Mapped[str]           = mapped_column(Text, nullable=False)
    keywords:       Mapped[str]           = mapped_column(Text, default="[]")
    niche_keywords: Mapped[str]           = mapped_column(Text, default="[]")
    kind:           Mapped[str]           = mapped_column(Text, default="search")
    market:         Mapped[str]           = mapped_column(Text, default="ru")
    auto_collect:   Mapped[bool]          = mapped_column(Boolean, default=True)
    created_at:     Mapped[datetime]      = mapped_column(default=_now)

    def keywords_list(self):       return json.loads(self.keywords or "[]")
    def niche_keywords_list(self): return json.loads(self.niche_keywords or "[]")


class NewsProbe(Base):
    __tablename__ = "news_probes"
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:     Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    platform:     Mapped[str]      = mapped_column(Text)
    kind:         Mapped[str]      = mapped_column(Text)              # channel | global
    query:        Mapped[str]      = mapped_column(Text)
    label:        Mapped[Optional[str]] = mapped_column(Text)
    watermark:    Mapped[Optional[str]] = mapped_column(Text)
    next_run_at:  Mapped[datetime] = mapped_column(default=_now)
    interval_sec: Mapped[int]      = mapped_column(Integer, default=3600)


class NewsMention(Base):
    __tablename__ = "news_mentions"
    __table_args__ = (UniqueConstraint("platform", "post_id"),)
    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:    Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    platform:    Mapped[str]      = mapped_column(Text)
    post_id:     Mapped[str]      = mapped_column(Text)
    author:      Mapped[str]      = mapped_column(Text)
    followers:   Mapped[int]      = mapped_column(Integer, default=0)
    text:        Mapped[str]      = mapped_column(Text, default="")
    hashtags:    Mapped[str]      = mapped_column(Text, default="[]")
    created_at:  Mapped[datetime] = mapped_column(nullable=False)
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("news_incidents.id"))
    source:      Mapped[str]      = mapped_column(Text, default="channel")  # channel | global
    first_seen:  Mapped[datetime] = mapped_column(default=_now)


class NewsIncident(Base):
    __tablename__ = "news_incidents"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:      Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    story_id:      Mapped[Optional[int]] = mapped_column(ForeignKey("news_stories.id"))
    title:         Mapped[str]      = mapped_column(Text, default="")
    summary:       Mapped[Optional[str]] = mapped_column(Text)
    post_count:    Mapped[int]      = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at:  Mapped[datetime] = mapped_column(nullable=False)
    created_at:    Mapped[datetime] = mapped_column(default=_now)


class NewsStory(Base):
    __tablename__ = "news_stories"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:      Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    title:         Mapped[str]      = mapped_column(Text, default="")
    status:        Mapped[str]      = mapped_column(Text, default="active")
    is_anomaly:    Mapped[bool]     = mapped_column(Boolean, default=False)
    post_count:    Mapped[int]      = mapped_column(Integer, default=0)
    source_count:  Mapped[int]      = mapped_column(Integer, default=0)
    verified:      Mapped[bool]     = mapped_column(Boolean, default=False)
    credibility:   Mapped[str]      = mapped_column(Text, default="unrated")
    credibility_note: Mapped[str]   = mapped_column(Text, default="")
    summary:       Mapped[str]      = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at:  Mapped[datetime] = mapped_column(nullable=False)
    created_at:    Mapped[datetime] = mapped_column(default=_now)


class NewsStoryPoint(Base):
    __tablename__ = "news_story_points"
    __table_args__ = (UniqueConstraint("story_id", "bucket_start"),)
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id:      Mapped[int]      = mapped_column(ForeignKey("news_stories.id"))
    bucket_start:  Mapped[datetime] = mapped_column(nullable=False)
    mention_count: Mapped[int]      = mapped_column(Integer, default=0)
    source_count:  Mapped[int]      = mapped_column(Integer, default=0)


class NewsReport(Base):
    __tablename__ = "news_reports"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id:   Mapped[int]      = mapped_column(ForeignKey("news_topics.id"), nullable=False)
    story_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("news_stories.id"))
    kind:       Mapped[str]      = mapped_column(Text, default="digest")
    body:       Mapped[str]      = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
