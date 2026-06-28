"""Intel-domain API router.

Exposes the /intel/* endpoints on the closed-contour contract.
All serialisation is delegated to aggregate.py (Task 4).
Credibility/summarise actions delegate to credibility.py (Task 3).

Mount with: app.include_router(router)
Domain isolation: only imports from `.` / `..core.*` / `..models`.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..core.auth import decode_token
from ..models import User
from .models import (IntelDirection, IntelMention, IntelMentionDirection,
                     IntelStory, IntelFeedLayout)
from . import aggregate
from . import credibility

log = logging.getLogger(__name__)

router = APIRouter(tags=["intel"])


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


# ── Window helper ─────────────────────────────────────────────────────────────

def _hours(window: str) -> int:
    """Parse a window string like '1h'|'24h'|'7d' → number of hours (default 24)."""
    w = (window or "24h").strip().lower()
    if w.endswith("d"):
        try:
            return int(w[:-1]) * 24
        except ValueError:
            return 24
    if w.endswith("h"):
        try:
            return int(w[:-1])
        except ValueError:
            return 24
    return 24


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/intel/overview")
def intel_overview(
    window: str = "24h",
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    return aggregate.compute_overview(session, _hours(window))


@router.get("/intel/stream")
def intel_stream(
    window: str = "24h",
    direction: Optional[str] = None,
    limit: int = 50,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    since = datetime.now(timezone.utc) - timedelta(hours=_hours(window))
    q = session.query(IntelMention).filter(IntelMention.created_at >= since)
    if direction:
        d = session.query(IntelDirection).filter_by(key=direction).first()
        if d:
            q = q.filter(IntelMention.direction_id == d.id)
    rows = q.order_by(IntelMention.created_at.desc()).limit(limit).all()
    return [aggregate.event(m) for m in rows]


@router.get("/intel/stories")
def intel_stories(
    direction: Optional[str] = None,
    side: Optional[str] = None,
    verified: Optional[bool] = None,
    sort: str = "recency",
    limit: int = 50,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    q = session.query(IntelStory)
    if direction:
        d = session.query(IntelDirection).filter_by(key=direction).first()
        if d:
            q = q.filter(IntelStory.direction_id == d.id)
    if verified is not None:
        q = q.filter(IntelStory.verified == verified)
    if side:
        from .models import IntelIncident
        subq = (
            session.query(IntelMention.incident_id)
            .join(IntelIncident, IntelMention.incident_id == IntelIncident.id)
            .filter(IntelMention.side == side)
            .subquery()
        )
        from .models import IntelIncident as Inc2
        story_ids_q = (
            session.query(Inc2.story_id)
            .filter(Inc2.id.in_(subq))
            .distinct()
            .subquery()
        )
        q = q.filter(IntelStory.id.in_(story_ids_q))
    if sort == "activity":
        # sort by spike_pct proxy: is_anomaly desc then post_count desc
        q = q.order_by(IntelStory.is_anomaly.desc(), IntelStory.post_count.desc())
    else:
        q = q.order_by(IntelStory.last_seen_at.desc())
    rows = q.limit(limit).all()
    return [aggregate.story_summary(session, st) for st in rows]


@router.get("/intel/stories/{story_id}")
def intel_story_detail(
    story_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    story = session.get(IntelStory, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    return aggregate.story_detail(session, story)


@router.post("/intel/stories/{story_id}/assess")
def intel_assess_story(
    story_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    story = session.get(IntelStory, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    from ..core.llm import LLMNotConfigured
    try:
        credibility.assess_credibility(session, story)
    except LLMNotConfigured:
        raise HTTPException(503, "LLM not configured")
    session.commit()
    return aggregate.story_summary(session, story)


@router.post("/intel/stories/{story_id}/summarize")
def intel_summarize_story(
    story_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    story = session.get(IntelStory, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    from ..core.llm import LLMNotConfigured
    try:
        credibility.summarize_story(session, story)
    except LLMNotConfigured:
        raise HTTPException(503, "LLM not configured")
    session.commit()
    return aggregate.story_summary(session, story)


@router.get("/intel/directions")
def intel_directions(
    window: str = "24h",
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    rows = (session.query(IntelDirection)
            .filter(IntelDirection.kind != "meta")
            .order_by(IntelDirection.kind, IntelDirection.name).all())
    return [_direction_out(session, d, _hours(window)) for d in rows]


def _direction_out(session, d, window_h=24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
    events_count = (session.query(IntelMentionDirection)
                    .join(IntelMention, IntelMentionDirection.mention_id == IntelMention.id)
                    .filter(IntelMentionDirection.direction_id == d.id,
                            IntelMention.created_at >= since).count())
    try:
        terms = json.loads(d.geo_terms or "[]")
    except (ValueError, TypeError):
        terms = []
    return {"id": d.id, "key": d.key, "name": d.name, "kind": d.kind,
            "region_key": d.region_key, "geo_terms": terms,
            "events_count": events_count}


class DirectionCreate(BaseModel):
    key: str
    name: str
    geo_terms: list[str] = []
    region_key: str | None = None


@router.post("/intel/directions")
def intel_create_direction(
    body: DirectionCreate,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    key = body.key.strip().lower()
    if not key:
        raise HTTPException(400, "key required")
    if session.query(IntelDirection).filter_by(key=key).first():
        raise HTTPException(409, "direction already exists")
    d = IntelDirection(
        key=key, name=body.name.strip() or key, kind="custom",
        region_key=body.region_key,
        geo_terms=json.dumps([t.lower() for t in body.geo_terms], ensure_ascii=False),
    )
    session.add(d); session.commit()
    return _direction_out(session, d, 24)


# ── Feed v2 ───────────────────────────────────────────────────────────────────

@router.get("/intel/feed")
def intel_feed(
    direction: str,
    side: Optional[str] = None,
    window: str = "24h",
    limit: int = 50,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """Initial history for one column — mentions linked to `direction` via m2m."""
    d = session.query(IntelDirection).filter_by(key=direction).first()
    if not d:
        raise HTTPException(404, "direction not found")
    since = datetime.now(timezone.utc) - timedelta(hours=_hours(window))
    q = (session.query(IntelMention, IntelMentionDirection.match_type)
         .join(IntelMentionDirection, IntelMentionDirection.mention_id == IntelMention.id)
         .filter(IntelMentionDirection.direction_id == d.id,
                 IntelMention.created_at >= since))
    if side:
        q = q.filter(IntelMention.side == side)
    rows = q.order_by(IntelMention.created_at.desc()).limit(limit).all()
    return [aggregate.feed_event(m, direction, mt) for (m, mt) in rows]


@router.get("/intel/directions/{key}")
def intel_direction_detail(
    key: str,
    window: str = "24h",
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    d = session.query(IntelDirection).filter_by(key=key).first()
    if not d:
        raise HTTPException(404, "Direction not found")
    w = _hours(window)
    since = datetime.now(timezone.utc) - timedelta(hours=w)
    stories = session.query(IntelStory).filter_by(direction_id=d.id).all()
    stream_rows = (
        session.query(IntelMention)
        .filter(IntelMention.direction_id == d.id, IntelMention.created_at >= since)
        .order_by(IntelMention.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "direction": aggregate.direction_card(session, d, w),
        "stories": [aggregate.story_summary(session, st) for st in stories],
        "stream": [aggregate.event(m) for m in stream_rows],
    }


@router.get("/intel/search")
def intel_search(
    q: str = "",
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    if not q:
        return []
    rows = (
        session.query(IntelStory)
        .filter(IntelStory.title.ilike(f"%{q}%"))
        .order_by(IntelStory.last_seen_at.desc())
        .limit(50)
        .all()
    )
    return [aggregate.story_summary(session, st) for st in rows]


# ── Feed v2 — multiplexed live stream ─────────────────────────────────────────

def _feed_stream_gen(direction_keys, side, window_h):
    """Sync generator yielding SSE chunks for the multiplexed feed.

    Polls the DB every 2s for new IntelMention rows linked (via m2m) to any
    of `direction_keys`, since the last-seen mention id. Each event is tagged
    `{"direction": <key>, "event": {…}}`. Heartbeat every 15s.
    """
    from ..core.db import SessionLocal
    last_id = 0
    last_heartbeat = time.monotonic()
    while True:
        try:
            with SessionLocal() as s:
                # Resolve direction ids → keys each pass (cheap; ~8 columns).
                dirs = (s.query(IntelDirection)
                        .filter(IntelDirection.key.in_(direction_keys)).all())
                id_to_key = {d.id: d.key for d in dirs}
                if id_to_key:
                    q = (s.query(IntelMention, IntelMentionDirection.direction_id,
                                 IntelMentionDirection.match_type)
                         .join(IntelMentionDirection,
                               IntelMentionDirection.mention_id == IntelMention.id)
                         .filter(IntelMentionDirection.direction_id.in_(list(id_to_key)),
                                 IntelMention.id > last_id))
                    if side:
                        q = q.filter(IntelMention.side == side)
                    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
                    q = q.filter(IntelMention.created_at >= since)
                    for (m, did, mt) in q.order_by(IntelMention.id).all():
                        last_id = max(last_id, m.id)
                        payload = aggregate.feed_event(m, id_to_key.get(did, "?"), mt)
                        yield f"data: {json.dumps(payload, default=str, ensure_ascii=False)}\n\n"
        except Exception:
            pass  # keep the stream alive on transient errors
        if time.monotonic() - last_heartbeat > 15:
            yield ": ping\n\n"
            last_heartbeat = time.monotonic()
        time.sleep(2)


@router.get("/intel/feed/stream")
def intel_feed_stream(
    directions: str,
    token: Optional[str] = None,
    side: Optional[str] = None,
    window: str = "24h",
    authorization: str = Header(None),
    session: Session = Depends(db),
):
    """SSE stream of new mentions across the requested columns.

    `directions` is a comma-separated list of direction keys. The server
    polls every 2s and emits one event per new mention (tagged with the
    direction it matched).

    Auth: the standard Bearer header OR a `?token=` query param (EventSource
    cannot set Authorization headers, so the frontend passes the token as a
    query string)."""
    raw = authorization or (f"Bearer {token}" if token else None)
    if not raw or not raw.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = decode_token(raw.split(" ", 1)[1])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    user = session.get(User, payload.get("uid"))
    if not user:
        raise HTTPException(401, "User not found")

    keys = [k.strip() for k in directions.split(",") if k.strip()]
    if not keys:
        raise HTTPException(400, "at least one direction required")
    gen = _feed_stream_gen(keys, side, _hours(window))
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


# ── Feed v2 — layout persistence ──────────────────────────────────────────────

class LayoutBody(BaseModel):
    direction_keys: list[str]


@router.get("/intel/feed/layout")
def intel_feed_layout_get(
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    row = session.query(IntelFeedLayout).order_by(IntelFeedLayout.updated_at.desc()).first()
    try:
        keys = json.loads(row.direction_ids) if row else []
    except (ValueError, TypeError):
        keys = []
    return {"direction_keys": keys,
            "updated_at": row.updated_at.isoformat() if row else None}


@router.put("/intel/feed/layout")
def intel_feed_layout_put(
    body: LayoutBody,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "admin only")
    row = session.query(IntelFeedLayout).order_by(IntelFeedLayout.updated_at.desc()).first()
    if row is None:
        row = IntelFeedLayout(direction_ids="[]")
        session.add(row)
    row.direction_ids = json.dumps(body.direction_keys)
    row.updated_by = user.id
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"direction_keys": body.direction_keys,
            "updated_at": row.updated_at.isoformat()}
