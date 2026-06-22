"""Intel-domain API router.

Exposes the /intel/* endpoints on the closed-contour contract.
All serialisation is delegated to aggregate.py (Task 4).
Credibility/summarise actions delegate to credibility.py (Task 3).

Mount with: app.include_router(router)
Domain isolation: only imports from `.` / `..core.*` / `..models`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
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
    wm = p.watermark.isoformat() if p.watermark else None
    return {
        "id": p.id,
        "handle": p.query,
        "side": p.side,
        "kind": p.kind,
        "last_collected": wm,
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
    probe = IntelProbe(platform="telegram", kind=kind, query=link, side=side)
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
