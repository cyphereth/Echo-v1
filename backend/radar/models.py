from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def _now(): return datetime.now(timezone.utc)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    email:         Mapped[str]      = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str]      = mapped_column(Text, nullable=False)
    is_admin:      Mapped[bool]     = mapped_column(Boolean, default=False)
    created_at:    Mapped[datetime] = mapped_column(default=_now)


class Brand(Base):
    """Shared owner model — re-imported by radar.brand.models."""
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
    sphere:                Mapped[str]      = mapped_column(Text, default="")
    geo:                   Mapped[str]      = mapped_column(Text, default="")
    category_terms:        Mapped[str]      = mapped_column(Text, default="[]")
    audience_terms:        Mapped[str]      = mapped_column(Text, default="[]")
    tg_channels:           Mapped[str]      = mapped_column(Text, default="[]")
    followers:             Mapped[int]      = mapped_column(Integer, default=0)
    local_mode:            Mapped[bool]     = mapped_column(Boolean, default=False)
    market:                Mapped[str]      = mapped_column(Text, default="global")
    auto_collect:          Mapped[bool]     = mapped_column(Boolean, default=False)
    mention_limit_monthly: Mapped[int]      = mapped_column(Integer, default=10000)
    created_at:            Mapped[datetime] = mapped_column(default=_now)

    def keywords_list(self):       return json.loads(self.keywords)
    def hashtags_list(self):       return json.loads(self.hashtags)
    def exclusions_list(self):     return json.loads(self.exclusions)
    def competitors_list(self):    return json.loads(self.competitors)
    def niche_keywords_list(self): return json.loads(self.niche_keywords or "[]")
    def category_terms_list(self): return json.loads(self.category_terms or "[]")
    def audience_terms_list(self): return json.loads(self.audience_terms or "[]")
    def tg_channels_list(self):    return json.loads(self.tg_channels or "[]")
    def tone_examples_list(self):  return json.loads(self.tone_examples or "[]")


class CityReport(Base):
    """Cached City Explorer summary — shared, re-imported by radar.brand.models."""
    __tablename__ = "city_reports"
    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    city:         Mapped[str]      = mapped_column(Text)
    display_city: Mapped[str]      = mapped_column(Text, default="")
    summary:      Mapped[str]      = mapped_column(Text, default="{}")
    post_count:   Mapped[int]      = mapped_column(Integer, default=0)
    platforms:    Mapped[str]      = mapped_column(Text, default="")
    created_at:   Mapped[datetime] = mapped_column(default=_now)
