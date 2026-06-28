from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..models import Base, _now


class IntelDirection(Base):
    __tablename__ = "intel_directions"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    key:        Mapped[str]      = mapped_column(Text, unique=True, nullable=False)   # "kursk"
    name:       Mapped[str]      = mapped_column(Text, nullable=False)                # "Курское"
    kind:       Mapped[str]      = mapped_column(Text, default="region")              # region|city|custom|meta
    region_key: Mapped[Optional[str]] = mapped_column(Text)                           # parent region key for cities
    geo_terms:  Mapped[str]      = mapped_column(Text, default="[]")                  # JSON list of lowercase terms
    created_at: Mapped[datetime] = mapped_column(default=_now)


class IntelMentionDirection(Base):
    """Many-to-many: an IntelMention may belong to several IntelDirections.

    `match_type` is 'source' (probe subscribed), 'geo' (text matched a term),
    or 'manual' (operator pinned it).
    """
    __tablename__ = "intel_mention_directions"
    __table_args__ = (UniqueConstraint("mention_id", "direction_id"),)
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id:   Mapped[int]      = mapped_column(ForeignKey("intel_mentions.id"), nullable=False)
    direction_id: Mapped[int]      = mapped_column(ForeignKey("intel_directions.id"), nullable=False)
    match_type:   Mapped[str]      = mapped_column(Text, default="source")
    created_at:   Mapped[datetime] = mapped_column(default=_now)


class IntelFeedLayout(Base):
    """The contour-wide 'боевой дефолт' column layout (admin-saved)."""
    __tablename__ = "intel_feed_layouts"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction_ids: Mapped[str]      = mapped_column(Text, default="[]")   # JSON list of direction keys, in order
    updated_by:    Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    updated_at:    Mapped[datetime] = mapped_column(default=_now)


class IntelProbe(Base):
    __tablename__ = "intel_probes"
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("intel_directions.id"))
    platform:     Mapped[str]      = mapped_column(Text)
    kind:         Mapped[str]      = mapped_column(Text)              # channel | global
    query:        Mapped[str]      = mapped_column(Text)
    side:         Mapped[Optional[str]] = mapped_column(Text)         # "ru" | "ua" | None
    watermark:    Mapped[Optional[str]] = mapped_column(Text)
    next_run_at:  Mapped[datetime] = mapped_column(default=_now)
    interval_sec: Mapped[int]      = mapped_column(Integer, default=3600)


class IntelMention(Base):
    __tablename__ = "intel_mentions"
    __table_args__ = (UniqueConstraint("platform", "post_id"),)
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction_id: Mapped[int]      = mapped_column(ForeignKey("intel_directions.id"), nullable=False)
    platform:     Mapped[str]      = mapped_column(Text)
    post_id:      Mapped[str]      = mapped_column(Text)
    author:       Mapped[str]      = mapped_column(Text)
    side:         Mapped[Optional[str]] = mapped_column(Text)          # "ru" | "ua" | None
    text:         Mapped[str]      = mapped_column(Text, default="")
    url:          Mapped[Optional[str]] = mapped_column(Text)
    views:        Mapped[int]      = mapped_column(Integer, default=0)
    created_at:   Mapped[datetime] = mapped_column(nullable=False)
    incident_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("intel_incidents.id"))
    verified:     Mapped[bool]     = mapped_column(Boolean, default=False)
    first_seen:   Mapped[datetime] = mapped_column(default=_now)


class IntelIncident(Base):
    __tablename__ = "intel_incidents"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction_id:  Mapped[int]      = mapped_column(ForeignKey("intel_directions.id"), nullable=False)
    story_id:      Mapped[Optional[int]] = mapped_column(ForeignKey("intel_stories.id"))
    title:         Mapped[str]      = mapped_column(Text, default="")
    post_count:    Mapped[int]      = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at:  Mapped[datetime] = mapped_column(nullable=False)
    created_at:    Mapped[datetime] = mapped_column(default=_now)


class IntelStory(Base):
    __tablename__ = "intel_stories"
    id:               Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction_id:     Mapped[int]      = mapped_column(ForeignKey("intel_directions.id"), nullable=False)
    title:            Mapped[str]      = mapped_column(Text, default="")
    status:           Mapped[str]      = mapped_column(Text, default="active")
    is_anomaly:       Mapped[bool]     = mapped_column(Boolean, default=False, server_default="0")
    post_count:       Mapped[int]      = mapped_column(Integer, default=0)
    source_count:     Mapped[int]      = mapped_column(Integer, default=0)
    verified:         Mapped[bool]     = mapped_column(Boolean, default=False)
    credibility:      Mapped[str]      = mapped_column(Text, default="unrated")
    credibility_note: Mapped[str]      = mapped_column(Text, default="")
    summary:          Mapped[str]      = mapped_column(Text, default="")
    first_seen_at:    Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at:     Mapped[datetime] = mapped_column(nullable=False)
    created_at:       Mapped[datetime] = mapped_column(default=_now)


class IntelStoryPoint(Base):
    __tablename__ = "intel_story_points"
    __table_args__ = (UniqueConstraint("story_id", "bucket_start"),)
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id:      Mapped[int]      = mapped_column(ForeignKey("intel_stories.id"))
    bucket_start:  Mapped[datetime] = mapped_column(nullable=False)
    mention_count: Mapped[int]      = mapped_column(Integer, default=0)
    source_count:  Mapped[int]      = mapped_column(Integer, default=0)


class IntelLexicon(Base):
    __tablename__ = "intel_lexicon"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    term:       Mapped[str]      = mapped_column(Text, unique=True, nullable=False)
    meaning:    Mapped[str]      = mapped_column(Text, default="")
    category:   Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_now)
