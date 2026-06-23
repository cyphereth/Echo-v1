"""Intel-domain API router.

Exposes the /intel/* endpoints on the closed-contour contract.
All serialisation is delegated to aggregate.py (Task 4).
Credibility/summarise actions delegate to credibility.py (Task 3).

Mount with: app.include_router(router)
Domain isolation: only imports from `.` / `..core.*` / `..models`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..core.auth import decode_token
from ..models import User
from .models import IntelDirection, IntelMention, IntelStory, IntelProbe
from . import aggregate
from . import credibility

_VALID_SIDES = {"ru", "ua", "by", "mx", "ge", "md", "pmr"}
_VALID_KINDS = {"channel", "chat"}

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


def _auth_user_from_header(authorization: str) -> User:
    """Authenticate from a raw Authorization header using a short-lived session.

    Used by the SSE stream, which must NOT hold a request-scoped session open for the
    whole (possibly hours-long) connection."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = decode_token(authorization.split(" ", 1)[1])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    s = get_session()
    try:
        user = s.get(User, payload.get("uid"))
    finally:
        s.close()
    if not user:
        raise HTTPException(401, "User not found")
    return user


# Server-side tail interval. The realtime listener writes new mentions the instant a
# source publishes; this loop forwards them to the browser within one cycle → ~1-2s
# end-to-end latency without a per-event client round-trip.
INTEL_SSE_INTERVAL = 1.0


@router.get("/intel/stream/live")
async def intel_stream_live(
    after_id: int = 0,
    direction: Optional[str] = None,
    authorization: str = Header(None),
):
    """Server-Sent Events: pushes each new IntelMention (id > after_id) as it lands.

    The browser opens this once and receives `data: {event}` frames live. On reconnect
    it passes the last id it saw via after_id, so no event is missed or duplicated.
    """
    _auth_user_from_header(authorization)

    direction_id: Optional[int] = None
    if direction:
        s = get_session()
        try:
            d = s.query(IntelDirection).filter_by(key=direction).first()
            direction_id = d.id if d else None
        finally:
            s.close()

    async def event_gen():
        last_id = after_id
        if last_id <= 0:
            s = get_session()
            try:
                last_id = s.query(func.max(IntelMention.id)).scalar() or 0
            finally:
                s.close()
        # Open the stream immediately so the client knows it's connected.
        yield ": connected\n\n"
        while True:
            s = get_session()
            try:
                q = s.query(IntelMention).filter(IntelMention.id > last_id)
                if direction_id is not None:
                    q = q.filter(IntelMention.direction_id == direction_id)
                rows = q.order_by(IntelMention.id.asc()).limit(100).all()
                payloads = [(m.id, json.dumps(aggregate.event(m), ensure_ascii=False)) for m in rows]
            finally:
                s.close()
            for mid, payload in payloads:
                last_id = mid
                yield f"data: {payload}\n\n"
            # Heartbeat keeps the connection alive through proxies between bursts.
            yield ": ping\n\n"
            await asyncio.sleep(INTEL_SSE_INTERVAL)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering so frames flush at once
        },
    )


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
    dirs = session.query(IntelDirection).all()
    return [aggregate.direction_card(session, d, _hours(window)) for d in dirs]


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


# ── Sources management ────────────────────────────────────────────────────────

def _probe_dict(p: IntelProbe) -> dict:
    nra = p.next_run_at.isoformat() if p.next_run_at else None
    # watermark is the last-seen post_id (a STRING), not a timestamp — do NOT call
    # .isoformat() on it. Surface a simple collected flag + the raw watermark.
    return {
        "id": p.id,
        "handle": p.query,
        "side": p.side,
        "kind": p.kind,
        "collected": p.watermark is not None,
        "last_collected": p.watermark,  # raw post_id string (None until first collect)
        "next_run_at": nra,
    }


@router.get("/intel/sources")
def intel_sources_list(
    side: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 500,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    q = session.query(IntelProbe)
    if side:
        q = q.filter(IntelProbe.side == side)
    if kind:
        q = q.filter(IntelProbe.kind == kind)
    rows = q.order_by(IntelProbe.id).limit(limit).all()
    return [_probe_dict(p) for p in rows]


@router.post("/intel/sources")
def intel_sources_create(
    body: dict,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    link = (body.get("link") or "").strip()
    side = (body.get("side") or "").strip().lower()
    kind = (body.get("kind") or "").strip().lower()
    if side not in _VALID_SIDES:
        raise HTTPException(400, f"Invalid side '{side}'. Must be one of: {sorted(_VALID_SIDES)}")
    if kind not in _VALID_KINDS:
        raise HTTPException(400, f"Invalid kind '{kind}'. Must be one of: {sorted(_VALID_KINDS)}")
    if not link:
        raise HTTPException(400, "link is required")
    existing = session.query(IntelProbe).filter_by(query=link).first()
    if existing:
        return {**_probe_dict(existing), "created": False}
    # next_run_at in the past → the source jumps to the FRONT of the due queue, so the
    # ticker polls it on its very next pass (within one tick) instead of after the
    # backlog of already-scheduled sources.
    probe = IntelProbe(platform="telegram", kind=kind, query=link, side=side,
                       next_run_at=datetime(1970, 1, 1, tzinfo=timezone.utc))
    session.add(probe)
    session.commit()
    session.refresh(probe)
    return {**_probe_dict(probe), "created": True}


@router.delete("/intel/sources/{source_id}")
def intel_sources_delete(
    source_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    probe = session.get(IntelProbe, source_id)
    if not probe:
        raise HTTPException(404, "Source not found")
    session.delete(probe)
    session.commit()
    return {"deleted": True}
