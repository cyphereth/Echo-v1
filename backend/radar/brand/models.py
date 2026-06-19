from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..models import Base, _now, Brand, CityReport, User  # reuse shared owner/shared tables

# Re-export for importability as radar.brand.models.*
__all__ = [
    "Brand", "CityReport", "User",
    "BrandProbe", "BrandMention", "BrandMentionSnapshot",
    "BrandComment", "BrandDraftEdit", "BrandEngagementLog",
    "BrandIncident", "BrandStory", "BrandStoryPoint", "BrandReport",
]


class BrandProbe(Base):
    __tablename__ = "brand_probes"
    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:     Mapped[int]           = mapped_column(ForeignKey("brands.id"), nullable=False)
    platform:     Mapped[str]           = mapped_column(Text)
    kind:         Mapped[str]           = mapped_column(Text)
    query:        Mapped[str]           = mapped_column(Text)
    source:       Mapped[str]           = mapped_column(Text, default="brand")  # brand | competitor | niche
    label:        Mapped[Optional[str]] = mapped_column(Text)                    # competitor name / niche term
    watermark:    Mapped[Optional[str]] = mapped_column(Text)
    next_run_at:  Mapped[datetime]      = mapped_column(default=_now)
    interval_sec: Mapped[int]           = mapped_column(Integer, default=3600)


class BrandMention(Base):
    __tablename__ = "brand_mentions"
    __table_args__ = (UniqueConstraint("platform", "post_id"),)
    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:     Mapped[int]           = mapped_column(ForeignKey("brands.id"), nullable=False)
    platform:     Mapped[str]           = mapped_column(Text)
    post_id:      Mapped[str]           = mapped_column(Text)
    author:       Mapped[str]           = mapped_column(Text)
    followers:    Mapped[int]           = mapped_column(Integer, default=0)
    text:         Mapped[str]           = mapped_column(Text, default="")
    hashtags:     Mapped[str]           = mapped_column(Text, default="[]")
    sound_id:     Mapped[Optional[str]] = mapped_column(Text)
    created_at:   Mapped[datetime]      = mapped_column(nullable=False)
    likes:        Mapped[int]           = mapped_column(Integer, default=0)
    views:        Mapped[int]           = mapped_column(Integer, default=0)
    comments:     Mapped[int]           = mapped_column(Integer, default=0)
    shares:       Mapped[int]           = mapped_column(Integer, default=0)
    severity:     Mapped[float]         = mapped_column(Float, default=0.0)
    phase:        Mapped[str]           = mapped_column(Text, default="unknown")
    tone:         Mapped[str]           = mapped_column(Text, default="neutral")
    is_hot:       Mapped[bool]          = mapped_column(Boolean, default=False)
    is_spam:      Mapped[bool]          = mapped_column(Boolean, default=False)
    category:     Mapped[Optional[str]] = mapped_column(Text)
    lane:         Mapped[Optional[str]] = mapped_column(Text)
    incident_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("brand_incidents.id"))
    source:       Mapped[str]           = mapped_column(Text, default="brand")  # brand | competitor | niche
    competitor:   Mapped[Optional[str]] = mapped_column(Text)                    # which competitor (source=competitor)
    opportunity:  Mapped[Optional[str]] = mapped_column(Text)                    # engagement hint for competitor/niche
    confidence:   Mapped[Optional[float]] = mapped_column(Float)
    draft:        Mapped[Optional[str]] = mapped_column(Text)
    draft_flag:   Mapped[Optional[str]] = mapped_column(Text)
    status:       Mapped[str]           = mapped_column(Text, default="new")
    first_seen:   Mapped[datetime]      = mapped_column(default=_now)
    updated_at:   Mapped[datetime]      = mapped_column(default=_now, onupdate=_now)


class BrandMentionSnapshot(Base):
    __tablename__ = "brand_mention_snapshots"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[int]      = mapped_column(ForeignKey("brand_mentions.id"))
    ts:         Mapped[datetime] = mapped_column(default=_now)
    likes:      Mapped[int]      = mapped_column(Integer, default=0)
    views:      Mapped[int]      = mapped_column(Integer, default=0)
    comments:   Mapped[int]      = mapped_column(Integer, default=0)
    shares:     Mapped[int]      = mapped_column(Integer, default=0)


class BrandComment(Base):
    __tablename__ = "brand_comments"
    __table_args__ = (UniqueConstraint("mention_id", "comment_id"),)
    id:             Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id:     Mapped[int]             = mapped_column(ForeignKey("brand_mentions.id"))
    comment_id:     Mapped[str]             = mapped_column(Text)
    author:         Mapped[str]             = mapped_column(Text, default="")
    followers:      Mapped[int]             = mapped_column(Integer, default=0)
    text:           Mapped[str]             = mapped_column(Text, default="")
    likes:          Mapped[int]             = mapped_column(Integer, default=0)
    sentiment:      Mapped[str]             = mapped_column(Text, default="neutral")
    draft:          Mapped[Optional[str]]   = mapped_column(Text)
    draft_flag:     Mapped[Optional[str]]   = mapped_column(Text)
    is_opportunity: Mapped[bool]            = mapped_column(Boolean, default=False)
    opportunity:    Mapped[Optional[str]]   = mapped_column(Text)   # short reason
    is_spam:        Mapped[bool]            = mapped_column(Boolean, default=False)
    status:         Mapped[str]             = mapped_column(Text, default="pending")  # pending | sent | posted | skipped
    created_at:     Mapped[datetime]        = mapped_column(nullable=False)
    fetched_at:     Mapped[datetime]        = mapped_column(default=_now)


class BrandDraftEdit(Base):
    __tablename__ = "brand_draft_edits"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[int]           = mapped_column(ForeignKey("brand_mentions.id"))
    brand_id:   Mapped[int]           = mapped_column(ForeignKey("brands.id"))
    category:   Mapped[Optional[str]] = mapped_column(Text)
    original:   Mapped[str]           = mapped_column(Text)
    edited:     Mapped[str]           = mapped_column(Text)
    created_at: Mapped[datetime]      = mapped_column(default=_now)


class BrandEngagementLog(Base):
    """Audit trail: every operator decision on a brand reply (approve/post/skip)."""
    __tablename__ = "brand_engagement_log"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:   Mapped[int]           = mapped_column(ForeignKey("brands.id"), nullable=False)
    mention_id: Mapped[int]           = mapped_column(ForeignKey("brand_mentions.id"))
    comment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("brand_comments.id"))
    action:     Mapped[str]           = mapped_column(Text)   # approved | posted | skipped | rejected
    actor:      Mapped[str]           = mapped_column(Text, default="")  # user email
    text:       Mapped[str]           = mapped_column(Text, default="")  # final reply text at decision time
    created_at: Mapped[datetime]      = mapped_column(default=_now)


class BrandIncident(Base):
    __tablename__ = "brand_incidents"
    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:      Mapped[int]           = mapped_column(ForeignKey("brands.id"), nullable=False)
    story_id:      Mapped[Optional[int]] = mapped_column(ForeignKey("brand_stories.id"))
    title:         Mapped[str]           = mapped_column(Text, default="")
    summary:       Mapped[Optional[str]] = mapped_column(Text)
    sentiment:     Mapped[float]         = mapped_column(Float, default=0.0)  # -1..1
    post_count:    Mapped[int]           = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime]      = mapped_column(nullable=False)
    last_seen_at:  Mapped[datetime]      = mapped_column(nullable=False)
    created_at:    Mapped[datetime]      = mapped_column(default=_now)


class BrandStory(Base):
    __tablename__ = "brand_stories"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:      Mapped[int]      = mapped_column(ForeignKey("brands.id"), nullable=False)
    title:         Mapped[str]      = mapped_column(Text, default="")
    status:        Mapped[str]      = mapped_column(Text, default="active")   # active | dormant
    is_anomaly:    Mapped[bool]     = mapped_column(Boolean, default=False)
    post_count:    Mapped[int]      = mapped_column(Integer, default=0)
    summary:       Mapped[str]      = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_at:  Mapped[datetime] = mapped_column(nullable=False)
    created_at:    Mapped[datetime] = mapped_column(default=_now)


class BrandStoryPoint(Base):
    __tablename__ = "brand_story_points"
    __table_args__ = (UniqueConstraint("story_id", "bucket_start"),)
    id:            Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id:      Mapped[int]             = mapped_column(ForeignKey("brand_stories.id"))
    bucket_start:  Mapped[datetime]        = mapped_column(nullable=False)
    mention_count: Mapped[int]             = mapped_column(Integer, default=0)
    avg_sentiment: Mapped[Optional[float]] = mapped_column(Float)
    source_count:  Mapped[int]             = mapped_column(Integer, default=0)


class BrandReport(Base):
    __tablename__ = "brand_reports"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:   Mapped[int]           = mapped_column(ForeignKey("brands.id"), nullable=False)
    story_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("brand_stories.id"))
    kind:       Mapped[str]           = mapped_column(Text, default="digest")  # digest | story | alert
    body:       Mapped[str]           = mapped_column(Text, default="")
    created_at: Mapped[datetime]      = mapped_column(default=_now)
