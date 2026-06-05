from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

def _now(): return datetime.now(timezone.utc)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    email:         Mapped[str]      = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str]      = mapped_column(Text, nullable=False)
    created_at:    Mapped[datetime] = mapped_column(default=_now)

class Brand(Base):
    __tablename__ = "brands"
    id:                    Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:               Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    name:                  Mapped[str]           = mapped_column(Text, nullable=False)
    keywords:              Mapped[str]      = mapped_column(Text, default="[]")
    hashtags:              Mapped[str]      = mapped_column(Text, default="[]")
    exclusions:            Mapped[str]      = mapped_column(Text, default="[]")
    tone_examples:         Mapped[str]      = mapped_column(Text, default="[]")
    competitors:           Mapped[str]      = mapped_column(Text, default="[]")
    niche_keywords:        Mapped[str]      = mapped_column(Text, default="[]")
    sphere:                Mapped[str]      = mapped_column(Text, default="")  # brand DNA / industry
    geo:                   Mapped[str]      = mapped_column(Text, default="")  # city/region, "" = national
    category_terms:        Mapped[str]      = mapped_column(Text, default="[]")  # service-category competitors
    audience_terms:        Mapped[str]      = mapped_column(Text, default="[]")  # broad audience themes (local mode)
    followers:             Mapped[int]      = mapped_column(Integer, default=0)
    local_mode:            Mapped[bool]     = mapped_column(Boolean, default=False)
    market:                Mapped[str]      = mapped_column(Text, default="global")  # ru | global
    auto_collect:          Mapped[bool]     = mapped_column(Boolean, default=False)
    mention_limit_monthly: Mapped[int]      = mapped_column(Integer, default=10000)
    created_at:            Mapped[datetime] = mapped_column(default=_now)
    probes:                Mapped[list[Probe]]   = relationship(back_populates="brand")
    mentions:              Mapped[list[Mention]] = relationship(back_populates="brand")

    def keywords_list(self):       return json.loads(self.keywords)
    def hashtags_list(self):       return json.loads(self.hashtags)
    def exclusions_list(self):     return json.loads(self.exclusions)
    def competitors_list(self):    return json.loads(self.competitors)
    def niche_keywords_list(self): return json.loads(self.niche_keywords or "[]")
    def category_terms_list(self): return json.loads(self.category_terms or "[]")
    def audience_terms_list(self): return json.loads(self.audience_terms or "[]")
    def tone_examples_list(self):  return json.loads(self.tone_examples or "[]")

class Probe(Base):
    __tablename__ = "probes"
    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:     Mapped[int]           = mapped_column(ForeignKey("brands.id"))
    platform:     Mapped[str]           = mapped_column(Text)
    kind:         Mapped[str]           = mapped_column(Text)
    query:        Mapped[str]           = mapped_column(Text)
    source:       Mapped[str]           = mapped_column(Text, default="brand")  # brand | competitor | niche
    label:        Mapped[Optional[str]] = mapped_column(Text)                    # competitor name / niche term
    watermark:    Mapped[Optional[str]] = mapped_column(Text)
    next_run_at:  Mapped[datetime]      = mapped_column(default=_now)
    interval_sec: Mapped[int]           = mapped_column(Integer, default=3600)
    brand:        Mapped[Brand]         = relationship(back_populates="probes")

class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (UniqueConstraint("platform", "post_id"),)
    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id:     Mapped[int]           = mapped_column(ForeignKey("brands.id"))
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
    source:       Mapped[str]           = mapped_column(Text, default="brand")  # brand | competitor | niche
    competitor:   Mapped[Optional[str]] = mapped_column(Text)                    # which competitor (source=competitor)
    opportunity:  Mapped[Optional[str]] = mapped_column(Text)                    # engagement hint for competitor/niche
    confidence:   Mapped[Optional[float]] = mapped_column(Float)
    draft:        Mapped[Optional[str]] = mapped_column(Text)
    draft_flag:   Mapped[Optional[str]] = mapped_column(Text)
    status:       Mapped[str]           = mapped_column(Text, default="new")
    first_seen:   Mapped[datetime]      = mapped_column(default=_now)
    updated_at:   Mapped[datetime]      = mapped_column(default=_now, onupdate=_now)
    brand:        Mapped[Brand]         = relationship(back_populates="mentions")
    snapshots:    Mapped[list[MentionSnapshot]] = relationship(back_populates="mention", order_by="MentionSnapshot.ts")
    draft_edits:  Mapped[list[DraftEdit]]       = relationship(back_populates="mention")
    comment_rows: Mapped[list["Comment"]]       = relationship(back_populates="mention", order_by="Comment.likes.desc()")

class MentionSnapshot(Base):
    __tablename__ = "mention_snapshots"
    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[int]      = mapped_column(ForeignKey("mentions.id"))
    ts:         Mapped[datetime] = mapped_column(default=_now)
    likes:      Mapped[int]      = mapped_column(Integer, default=0)
    views:      Mapped[int]      = mapped_column(Integer, default=0)
    comments:   Mapped[int]      = mapped_column(Integer, default=0)
    shares:     Mapped[int]      = mapped_column(Integer, default=0)
    mention:    Mapped[Mention]  = relationship(back_populates="snapshots")

class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (UniqueConstraint("mention_id", "comment_id"),)
    id:         Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[int]             = mapped_column(ForeignKey("mentions.id"))
    comment_id: Mapped[str]             = mapped_column(Text)
    author:     Mapped[str]             = mapped_column(Text, default="")
    followers:  Mapped[int]             = mapped_column(Integer, default=0)
    text:       Mapped[str]             = mapped_column(Text, default="")
    likes:      Mapped[int]             = mapped_column(Integer, default=0)
    sentiment:  Mapped[str]             = mapped_column(Text, default="neutral")
    draft:      Mapped[Optional[str]]   = mapped_column(Text)
    draft_flag: Mapped[Optional[str]]   = mapped_column(Text)
    is_opportunity: Mapped[bool]        = mapped_column(Boolean, default=False)
    opportunity:    Mapped[Optional[str]] = mapped_column(Text)   # short reason
    is_spam:    Mapped[bool]            = mapped_column(Boolean, default=False)
    status:     Mapped[str]             = mapped_column(Text, default="pending")  # pending | sent | skipped
    created_at: Mapped[datetime]        = mapped_column(nullable=False)
    fetched_at: Mapped[datetime]        = mapped_column(default=_now)
    mention:    Mapped[Mention]         = relationship(back_populates="comment_rows")


class DraftEdit(Base):
    __tablename__ = "draft_edits"
    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id: Mapped[int]           = mapped_column(ForeignKey("mentions.id"))
    brand_id:   Mapped[int]           = mapped_column(ForeignKey("brands.id"))
    category:   Mapped[Optional[str]] = mapped_column(Text)
    original:   Mapped[str]           = mapped_column(Text)
    edited:     Mapped[str]           = mapped_column(Text)
    created_at: Mapped[datetime]      = mapped_column(default=_now)
    mention:    Mapped[Mention]       = relationship(back_populates="draft_edits")
