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
    created_at: Mapped[datetime] = mapped_column(default=_now)


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
    reply_to_tg_id:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reply_to_id:     Mapped[Optional[int]] = mapped_column(ForeignKey("intel_mentions.id"), nullable=True)
    thread_root_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("intel_mentions.id"), nullable=True)
    context_fetched: Mapped[bool]          = mapped_column(Boolean, default=False, server_default="0")


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


class IntelAlert(Base):
    __tablename__ = "intel_alerts"
    id:              Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope:           Mapped[str]      = mapped_column(Text, nullable=False)   # "story" | "direction"
    direction_id:    Mapped[Optional[int]] = mapped_column(ForeignKey("intel_directions.id"))
    story_id:        Mapped[Optional[int]] = mapped_column(ForeignKey("intel_stories.id"))
    kind:            Mapped[str]      = mapped_column(Text, nullable=False)   # spike|sentiment|source_influx|direction_burst
    magnitude:       Mapped[float]    = mapped_column(default=0.0)            # SQLAlchemy infers Float from Mapped[float]
    title:           Mapped[str]      = mapped_column(Text, default="")
    message:         Mapped[str]      = mapped_column(Text, default="")
    fired_at:        Mapped[datetime] = mapped_column(default=_now)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class IntelSpam(Base):
    """Curator-managed spam filter. Two kinds of rows:
    - kind="word":    a stop-word/phrase; posts containing it are dropped (fast layer).
    - kind="example": a junk post the curator threw in; used as a reference for the
                      LLM example-comparison layer (classify_spam_batch).
    """
    __tablename__ = "intel_spam"
    __table_args__ = (UniqueConstraint("kind", "value"),)
    id:             Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind:           Mapped[str]      = mapped_column(Text, nullable=False)   # "word" | "example"
    value:          Mapped[str]      = mapped_column(Text, nullable=False)   # stop-word or example text
    author:         Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_post_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note:           Mapped[str]      = mapped_column(Text, default="")
    created_at:     Mapped[datetime] = mapped_column(default=_now)


class IntelThreadContext(Base):
    __tablename__ = "intel_thread_context"
    __table_args__ = (UniqueConstraint("mention_id", "tg_msg_id"),)
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[int]      = mapped_column(ForeignKey("intel_mentions.id"), nullable=False)
    tg_msg_id:  Mapped[str]      = mapped_column(Text, nullable=False)
    role:       Mapped[str]      = mapped_column(Text, nullable=False)   # "parent" | "sibling"
    depth:      Mapped[int]      = mapped_column(Integer, default=0)
    author:     Mapped[str]      = mapped_column(Text, default="")
    text:       Mapped[str]      = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(nullable=False)
