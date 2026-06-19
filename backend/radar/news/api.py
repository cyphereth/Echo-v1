"""News-domain API router.

Ports the news/topics/stories/inbox/digests/sources endpoints from radar/api.py
into an APIRouter, rebound to NewsTopic / NewsStory / NewsMention / NewsReport
models from radar.news.*.

Mount with: app.include_router(news_router)
All legacy /news/topics, /stories?topic_id=, /topics/{id}/... endpoints
in radar/api.py are removed once this router is mounted there.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..core.auth import decode_token
from ..models import User, Probe, Mention  # legacy Probe / Mention still used for source panel
from .models import NewsTopic, NewsMention, NewsStory, NewsStoryPoint, NewsIncident, NewsReport  # noqa: F401 — NewsStory etc. kept for potential future use
from . import credibility as news_credibility
from . import digests as news_digests

log = logging.getLogger(__name__)

router = APIRouter(tags=["news"])


# ── Dependency ────────────────────────────────────────────────────────────────

def db() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def current_user(authorization: str = Header(None), session: Session = Depends(db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = decode_token(authorization.split(" ", 1)[1])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    user = session.get(User, payload.get("uid"))
    if not user:
        raise HTTPException(401, "User not found")
    return user


# ── Ownership helpers ─────────────────────────────────────────────────────────

def _owned_news_topic(session: Session, topic_id: int, user: User) -> NewsTopic:
    """Load a NewsTopic and verify ownership (user_id None = global/public)."""
    t = session.get(NewsTopic, topic_id)
    if not t:
        raise HTTPException(404, "Topic not found")
    if t.user_id is not None and t.user_id != user.id:
        raise HTTPException(403, "Forbidden")
    return t


def _owned_news_story(session: Session, story_id: int, user: User) -> NewsStory:
    st = session.get(NewsStory, story_id)
    if st is None:
        raise HTTPException(404, "Story not found")
    _owned_news_topic(session, st.topic_id, user)
    return st


# ── Schemas ───────────────────────────────────────────────────────────────────

class TopicOut(BaseModel):
    id:           int
    name:         str
    kind:         str
    keywords:     list[str]
    auto_collect: bool


class TopicCreate(BaseModel):
    name:     str
    keywords: list[str] = []


class StoryOut(BaseModel):
    id:               int
    title:            str
    status:           str
    is_anomaly:       bool
    post_count:       int
    last_seen_at:     datetime
    avg_sentiment:    float | None = None
    source_count:     int = 0
    verified:         bool = False
    credibility:      str = "unrated"
    credibility_note: str = ""
    summary:          str = ""


class StoryPointOut(BaseModel):
    bucket_start:  datetime
    mention_count: int
    source_count:  int


class IncidentOut(BaseModel):
    id:           int
    title:        str
    post_count:   int
    last_seen_at: datetime


class SourceRefOut(BaseModel):
    author:     str
    first_seen: datetime
    count:      int


class StoryDetailOut(StoryOut):
    points:    list[StoryPointOut]
    incidents: list[IncidentOut]
    sources:   list[SourceRefOut] = []


class ReportOut(BaseModel):
    id:         int
    kind:       str
    body:       str
    created_at: datetime
    story_id:   int | None = None


class SourceOut(BaseModel):
    id:            int | None = None   # probe id (None for read-only web domains)
    kind:          str                  # channel | global | web
    handle:        str
    title:         str = ""
    mention_count: int = 0


class SourceAdd(BaseModel):
    handle: str


# ── Serialization helpers ─────────────────────────────────────────────────────

def _story_fields(session: Session, st: NewsStory) -> dict:
    return dict(
        id=st.id, title=st.title, status=st.status, is_anomaly=st.is_anomaly,
        post_count=st.post_count, last_seen_at=st.last_seen_at, avg_sentiment=None,
        source_count=st.source_count, verified=st.verified,
        credibility=st.credibility, credibility_note=st.credibility_note,
        summary=st.summary,
    )


def _story_sources(session: Session, story_id: int) -> list[SourceRefOut]:
    """Distinct sources behind a news story: earliest-first, with count."""
    rows = (
        session.query(NewsMention.author,
                      func.min(NewsMention.created_at),
                      func.count(NewsMention.id))
        .join(NewsIncident, NewsMention.incident_id == NewsIncident.id)
        .filter(NewsIncident.story_id == story_id, NewsMention.author.isnot(None))
        .group_by(NewsMention.author).all()
    )
    refs = [SourceRefOut(author=a, first_seen=fs, count=c) for (a, fs, c) in rows if (a or "").strip()]
    refs.sort(key=lambda r: r.first_seen)
    return refs


def _mention_card(m: NewsMention) -> dict:
    return {
        "id":         m.id,
        "platform":   m.platform,
        "author":     m.author,
        "text":       m.text,
        "source":     m.source or "channel",
        "created_at": (m.created_at.isoformat() + "Z"
                       if m.created_at.tzinfo is None
                       else m.created_at.isoformat()),
    }


# ── News / Topics ─────────────────────────────────────────────────────────────

@router.get("/news/topics", response_model=list[TopicOut])
def news_topics(user: User = Depends(current_user), session: Session = Depends(db)):
    from sqlalchemy import or_
    rows = (session.query(NewsTopic)
            .filter(or_(NewsTopic.user_id.is_(None), NewsTopic.user_id == user.id))
            .order_by(NewsTopic.kind.desc(), NewsTopic.created_at.desc()).all())
    return [TopicOut(id=t.id, name=t.name, kind=t.kind,
                     keywords=t.keywords_list(), auto_collect=t.auto_collect) for t in rows]


@router.post("/news/topics", response_model=TopicOut)
def create_news_topic(body: TopicCreate, user: User = Depends(current_user), session: Session = Depends(db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name required")
    kws = body.keywords or [name]
    t = NewsTopic(
        user_id=user.id, kind="search", name=name,
        keywords=json.dumps(kws, ensure_ascii=False),
        niche_keywords=json.dumps(kws, ensure_ascii=False),
        auto_collect=True,
    )
    session.add(t); session.commit()
    return TopicOut(id=t.id, name=t.name, kind=t.kind,
                    keywords=t.keywords_list(), auto_collect=t.auto_collect)


# ── Topic digests ─────────────────────────────────────────────────────────────

@router.post("/topics/{topic_id}/digest", response_model=ReportOut)
def create_topic_digest(topic_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_news_topic(session, topic_id, user)
    from ..core.llm import LLMNotConfigured
    try:
        report = news_digests.build_topic_digest(session, topic_id)
    except LLMNotConfigured:
        raise HTTPException(503, "Digest generation unavailable — set LLM_API_KEY in backend/.env")
    if report is None:
        raise HTTPException(404, "No active stories to summarize")
    session.commit()
    return ReportOut(id=report.id, kind=report.kind, body=report.body,
                     created_at=report.created_at, story_id=report.story_id)


@router.get("/topics/{topic_id}/digests", response_model=list[ReportOut])
def list_topic_digests(topic_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_news_topic(session, topic_id, user)
    rows = (session.query(NewsReport)
            .filter(NewsReport.topic_id == topic_id, NewsReport.kind == "digest")
            .order_by(NewsReport.created_at.desc()).limit(50).all())
    return [ReportOut(id=r.id, kind=r.kind, body=r.body,
                      created_at=r.created_at, story_id=r.story_id) for r in rows]


# ── Topic sources panel ───────────────────────────────────────────────────────

@router.get("/topics/{topic_id}/sources", response_model=list[SourceOut])
def list_topic_sources(topic_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_news_topic(session, topic_id, user)
    out: list[SourceOut] = []
    # Telegram channel + global probes (still tracked via legacy Probe on news topics)
    probes = (session.query(Probe)
              .filter(Probe.topic_id == topic_id, Probe.platform == "telegram",
                      Probe.kind.in_(("channel", "global"))).all())
    for p in probes:
        cnt = (session.query(func.count(Mention.id))
               .filter(Mention.topic_id == topic_id, Mention.author == p.query).scalar() or 0)
        out.append(SourceOut(id=p.id, kind=p.kind, handle=p.query,
                             title=p.label or "", mention_count=cnt))
    # Web domains collected as NewsMentions
    web = (session.query(NewsMention.author, func.count(NewsMention.id))
           .filter(NewsMention.topic_id == topic_id, NewsMention.platform == "web")
           .group_by(NewsMention.author).all())
    for author, cnt in web:
        out.append(SourceOut(id=None, kind="web", handle=author or "?", mention_count=cnt))
    out.sort(key=lambda x: x.mention_count, reverse=True)
    return out


@router.post("/topics/{topic_id}/sources", response_model=SourceOut)
def add_topic_source(topic_id: int, body: SourceAdd, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_news_topic(session, topic_id, user)
    handle = body.handle.strip()
    if not handle:
        raise HTTPException(400, "handle required")
    if not handle.startswith("@"):
        handle = "@" + handle
    exists = (session.query(Probe)
              .filter(Probe.topic_id == topic_id, Probe.platform == "telegram",
                      Probe.query == handle).first())
    if exists:
        raise HTTPException(409, "source already exists")
    p = Probe(topic_id=topic_id, platform="telegram", kind="channel", query=handle,
              source="niche", label="manual",
              next_run_at=datetime.now(timezone.utc), interval_sec=3600)
    session.add(p); session.commit()
    return SourceOut(id=p.id, kind="channel", handle=handle, title="manual", mention_count=0)


@router.delete("/topics/{topic_id}/sources/{probe_id}")
def delete_topic_source(topic_id: int, probe_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_news_topic(session, topic_id, user)
    p = session.get(Probe, probe_id)
    if p is None or p.topic_id != topic_id:
        raise HTTPException(404, "source not found")
    (session.query(Mention)
     .filter(Mention.topic_id == topic_id, Mention.author == p.query)
     .delete(synchronize_session=False))
    session.delete(p); session.commit()
    return {"ok": True}
