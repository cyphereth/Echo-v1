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
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..core.auth import decode_token
from ..models import User
from .models import IntelDirection, IntelMention, IntelStory, IntelProbe, IntelAlert, IntelThreadContext, IntelSpam, IntelIncident, IntelStoryPoint
from ..models import _now
from . import aggregate
from . import credibility
from . import media_cache
from .spam_filter import _norm, is_exact_spam
from .context_pass import _handle_for, _parse_handle_and_msg_id, _parent_post_id
from ..brand.api import _get_tg_provider

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
    from_dt: Optional[str] = None,
    to_dt: Optional[str] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    if from_dt or to_dt:
        try:
            frm = datetime.fromisoformat(from_dt).replace(tzinfo=timezone.utc) if from_dt else None
            tod = datetime.fromisoformat(to_dt).replace(tzinfo=timezone.utc) if to_dt else datetime.now(timezone.utc)
        except ValueError:
            raise HTTPException(400, "Invalid from_dt/to_dt ISO format")
        return aggregate.compute_overview_range(session, frm, tod)
    return aggregate.compute_overview(session, _hours(window))


@router.get("/intel/stream")
def intel_stream(
    window: str = "24h",
    from_dt: Optional[str] = None,
    to_dt: Optional[str] = None,
    direction: Optional[str] = None,
    limit: int = 50,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    if from_dt or to_dt:
        try:
            since = datetime.fromisoformat(from_dt).replace(tzinfo=timezone.utc) if from_dt else None
            until = datetime.fromisoformat(to_dt).replace(tzinfo=timezone.utc) if to_dt else datetime.now(timezone.utc)
        except ValueError:
            raise HTTPException(400, "Invalid from_dt/to_dt ISO format")
        q = session.query(IntelMention)
        if since:
            q = q.filter(IntelMention.created_at >= since.replace(tzinfo=None))
        q = q.filter(IntelMention.created_at <= until.replace(tzinfo=None))
    else:
        since = datetime.now(timezone.utc) - timedelta(hours=_hours(window))
        q = session.query(IntelMention).filter(IntelMention.created_at >= since.replace(tzinfo=None))
    if direction:
        d = session.query(IntelDirection).filter_by(key=direction).first()
        if d:
            q = q.filter(IntelMention.direction_id == d.id)
    q = q.filter(IntelMention.hidden == False)  # noqa: E712  — soft-hidden (спам) не показываем
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
    after_alert_id: int = 0,
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
        last_alert_id = after_alert_id
        if last_alert_id < 0:
            s = get_session()
            try:
                last_alert_id = s.query(func.max(IntelAlert.id)).scalar() or 0
            finally:
                s.close()
        # Open the stream immediately so the client knows it's connected.
        yield ": connected\n\n"
        while True:
            # Wrap each DB poll in its own try/except so a transient SQLite lock or
            # serialisation error doesn't kill the generator — we just skip the tick
            # and send a ping to keep the connection alive.
            payloads: list = []
            apayloads: list = []
            try:
                s = get_session()
                try:
                    q = s.query(IntelMention).filter(IntelMention.id > last_id,
                                                     IntelMention.hidden == False)  # noqa: E712
                    if direction_id is not None:
                        q = q.filter(IntelMention.direction_id == direction_id)
                    rows = q.order_by(IntelMention.id.asc()).limit(100).all()
                    payloads = [(m.id, json.dumps(aggregate.event(m), ensure_ascii=False)) for m in rows]
                finally:
                    s.close()
                s = get_session()
                try:
                    arows = (s.query(IntelAlert).filter(IntelAlert.id > last_alert_id)
                             .order_by(IntelAlert.id.asc()).limit(50).all())
                    apayloads = [(a.id, json.dumps(aggregate.alert_payload(s, a), ensure_ascii=False))
                                 for a in arows]
                finally:
                    s.close()
            except Exception as exc:
                log.warning("SSE tick db error (skipping): %s", exc)
            for mid, payload in payloads:
                last_id = mid
                yield f"data: {payload}\n\n"
            for aid, payload in apayloads:
                last_alert_id = aid
                yield f"event: alert\ndata: {payload}\n\n"
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
    from_dt: Optional[str] = None,
    to_dt: Optional[str] = None,
    window: str = "24h",
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    q = session.query(IntelStory)
    # Time range filter
    if from_dt or to_dt:
        try:
            frm = datetime.fromisoformat(from_dt).replace(tzinfo=None) if from_dt else None
            tod = datetime.fromisoformat(to_dt).replace(tzinfo=None) if to_dt else datetime.now(timezone.utc).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(400, "Invalid from_dt/to_dt")
        if frm:
            q = q.filter(IntelStory.last_seen_at >= frm)
        q = q.filter(IntelStory.last_seen_at <= tod)
    else:
        since = datetime.now(timezone.utc) - timedelta(hours=_hours(window))
        since_naive = since.replace(tzinfo=None)
        q = q.filter(IntelStory.last_seen_at >= since_naive, IntelStory.created_at >= since_naive)
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
        .filter(IntelMention.direction_id == d.id, IntelMention.created_at >= since,
                IntelMention.hidden == False)  # noqa: E712
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

def _probe_dict(p: IntelProbe, dir_key: str | None = None) -> dict:
    nra = p.next_run_at.isoformat() if p.next_run_at else None
    # watermark is the last-seen post_id (a STRING), not a timestamp — do NOT call
    # .isoformat() on it. Surface a simple collected flag + the raw watermark.
    return {
        "id": p.id,
        "handle": p.query,
        "side": p.side,
        "kind": p.kind,
        "subject": getattr(p, "subject", None),
        "direction": dir_key,  # oblast key (None until set); resolved by caller
        "collected": p.watermark is not None,
        "last_collected": p.watermark,  # raw post_id string (None until first collect)
        "next_run_at": nra,
    }


def _resolve_direction(session, key: str | None) -> Optional[int]:
    """Map a direction key to its id for storing on a source. Empty/None clears it;
    an unknown key is a client error."""
    if not key:
        return None
    d = session.query(IntelDirection).filter_by(key=key).first()
    if d is None:
        raise HTTPException(400, f"Unknown direction '{key}'")
    return d.id


def _dir_keys(session, probes: list[IntelProbe]) -> dict:
    """Batch-resolve direction_id -> key for a list of probes (one query)."""
    ids = {p.direction_id for p in probes if p.direction_id}
    if not ids:
        return {}
    rows = session.query(IntelDirection.id, IntelDirection.key).filter(IntelDirection.id.in_(ids)).all()
    return {i: k for (i, k) in rows}


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
    keys = _dir_keys(session, rows)
    return [_probe_dict(p, keys.get(p.direction_id)) for p in rows]


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
    subject = (body.get("subject") or "").strip() or None
    direction_id = _resolve_direction(session, (body.get("direction") or "").strip() or None)
    existing = session.query(IntelProbe).filter_by(query=link).first()
    if existing:
        keys = _dir_keys(session, [existing])
        return {**_probe_dict(existing, keys.get(existing.direction_id)), "created": False}
    # next_run_at in the past → the source jumps to the FRONT of the due queue, so the
    # ticker polls it on its very next pass (within one tick) instead of after the
    # backlog of already-scheduled sources.
    probe = IntelProbe(platform="telegram", kind=kind, query=link, side=side,
                       subject=subject, direction_id=direction_id,
                       next_run_at=datetime(1970, 1, 1, tzinfo=timezone.utc))
    session.add(probe)
    session.commit()
    session.refresh(probe)
    keys = _dir_keys(session, [probe])
    return {**_probe_dict(probe, keys.get(probe.direction_id)), "created": True}


@router.patch("/intel/sources/{source_id}")
def intel_sources_update(
    source_id: int,
    body: dict,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    probe = session.get(IntelProbe, source_id)
    if not probe:
        raise HTTPException(404, "Source not found")
    if "kind" in body:
        kind = (body.get("kind") or "").strip().lower()
        if kind not in _VALID_KINDS:
            raise HTTPException(400, f"Invalid kind '{kind}'. Must be one of: {sorted(_VALID_KINDS)}")
        probe.kind = kind
    if "side" in body:
        side = (body.get("side") or "").strip().lower()
        if side not in _VALID_SIDES:
            raise HTTPException(400, f"Invalid side '{side}'. Must be one of: {sorted(_VALID_SIDES)}")
        probe.side = side
    if "subject" in body:
        probe.subject = (body.get("subject") or "").strip() or None
    if "direction" in body:
        probe.direction_id = _resolve_direction(session, (body.get("direction") or "").strip() or None)
    session.commit()
    session.refresh(probe)
    keys = _dir_keys(session, [probe])
    return _probe_dict(probe, keys.get(probe.direction_id))


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


_VALID_SPAM_KINDS = {"word", "example", "keyword"}


def _spam_dict(s: IntelSpam) -> dict:
    return {
        "id": s.id,
        "kind": s.kind,
        "value": s.value,
        "author": s.author,
        "source_post_id": s.source_post_id,
        "note": s.note or "",
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/intel/spam")
def intel_spam_list(
    kind: Optional[str] = None,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    q = session.query(IntelSpam)
    if kind:
        q = q.filter(IntelSpam.kind == kind)
    rows = q.order_by(IntelSpam.id.desc()).all()
    return [_spam_dict(s) for s in rows]


@router.post("/intel/spam")
def intel_spam_create(
    body: dict,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    kind = (body.get("kind") or "").strip().lower()
    value = (body.get("value") or "").strip()
    if kind not in _VALID_SPAM_KINDS:
        raise HTTPException(400, f"Invalid kind '{kind}'. Must be one of: {sorted(_VALID_SPAM_KINDS)}")
    if not value:
        raise HTTPException(400, "value is required")
    existing = session.query(IntelSpam).filter_by(kind=kind, value=value).first()
    if existing:
        return _spam_dict(existing)
    row = IntelSpam(
        kind=kind,
        value=value,
        author=(body.get("author") or None),
        source_post_id=(body.get("source_post_id") or None),
        note=(body.get("note") or ""),
    )
    session.add(row)
    # Куратор скинул в спам конкретный пост → прячем уже лежащие в БД дословные дубли,
    # чтобы они немедленно пропали из ленты/сюжетов (а не только фильтровались впредь).
    hidden_now = 0
    if kind == "example":
        target = _norm(value)
        candidates = (session.query(IntelMention)
                      .filter(IntelMention.hidden == False)  # noqa: E712
                      .all())
        for m in candidates:
            if _norm(m.text) == target:
                _hide_mention(session, m)
                hidden_now += 1
    session.commit()
    session.refresh(row)
    out = _spam_dict(row)
    out["hidden_now"] = hidden_now
    return out


@router.delete("/intel/spam/{spam_id}")
def intel_spam_delete(
    spam_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    row = session.get(IntelSpam, spam_id)
    if not row:
        raise HTTPException(404, "Spam entry not found")
    session.delete(row)
    session.commit()
    return {"deleted": True}


@router.get("/intel/alerts")
def intel_alerts(
    unread: bool = False,
    limit: int = 50,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    q = session.query(IntelAlert)
    if unread:
        q = q.filter(IntelAlert.acknowledged_at.is_(None))
    rows = q.order_by(IntelAlert.id.desc()).limit(limit).all()
    return [aggregate.alert_payload(session, a) for a in rows]


@router.post("/intel/alerts/ack-all")
def intel_alert_ack_all(
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    rows = session.query(IntelAlert).filter(IntelAlert.acknowledged_at.is_(None)).all()
    for a in rows:
        a.acknowledged_at = _now()
    session.commit()
    return {"ok": True, "count": len(rows)}


@router.post("/intel/alerts/{alert_id}/ack")
def intel_alert_ack(
    alert_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    a = session.get(IntelAlert, alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    if a.acknowledged_at is None:
        a.acknowledged_at = _now()
        session.commit()
    return {"ok": True}


def _hide_mention(session: Session, m: IntelMention) -> None:
    """Soft-hide одного упоминания + best-effort декремент счётчика владеющего сюжета
    (не ниже 0). Не коммитит — это делает вызывающий. Идемпотентность проверяет caller."""
    if m.hidden:
        return
    m.hidden = True
    if m.incident_id is not None:
        inc = session.get(IntelIncident, m.incident_id)
        if inc is not None and inc.story_id is not None:
            story = session.get(IntelStory, inc.story_id)
            if story is not None and (story.post_count or 0) > 0:
                story.post_count -= 1


@router.delete("/intel/stories/{story_id}")
def intel_story_delete(
    story_id: int,
    session: Session = Depends(db),
    user: User = Depends(current_user),
):
    """Удалить сюжет целиком (куратор: «это спам / мусорный кластер»). Прячем все его
    упоминания (hidden=True — они уже привязаны к инцидентам, так что повторно НЕ
    кластеризуются), затем удаляем точки/инциденты/алерты/сам сюжет. Возвращает число
    скрытых упоминаний."""
    story = session.get(IntelStory, story_id)
    if story is None:
        raise HTTPException(404, "Story not found")

    incidents = session.query(IntelIncident).filter_by(story_id=story_id).all()
    inc_ids = [i.id for i in incidents]

    hidden = 0
    if inc_ids:
        mentions = (session.query(IntelMention)
                    .filter(IntelMention.incident_id.in_(inc_ids),
                            IntelMention.hidden == False)  # noqa: E712
                    .all())
        for m in mentions:
            m.hidden = True
            hidden += 1

    # Чистим связанные строки, чтобы сюжет не «всплыл» обратно и не оставил висячих FK.
    session.query(IntelStoryPoint).filter_by(story_id=story_id).delete()
    session.query(IntelAlert).filter_by(story_id=story_id).update({"story_id": None})
    for inc in incidents:
        session.delete(inc)
    session.delete(story)
    session.commit()
    return {"deleted": True, "hidden_mentions": hidden}


@router.post("/intel/mention/{mention_id}/hide")
def intel_mention_hide(
    mention_id: int,
    session: Session = Depends(db),
    user: User = Depends(current_user),
):
    """Soft-hide одного упоминания (куратор скинул его в спам). Пост остаётся в БД,
    но пропадает из ленты/сюжетов/агрегатов. Идемпотентно: повторный вызов на уже
    скрытом ничего не делает (и не двигает post_count повторно)."""
    m = session.get(IntelMention, mention_id)
    if m is None:
        raise HTTPException(404, "Mention not found")

    # Лента схлопывает кросс-канальные репосты по сигнатуре контента и показывает
    # ОДНУ строку на группу. Поэтому прячем не только выбранное упоминание, а ВСЕХ
    # близнецов с той же сигнатурой — иначе после рефреша «всплывёт» дубликат и пост
    # будто вернётся. Окно ±7 дней вокруг поста ограничивает запрос (репосты идут
    # кучно во времени), а пустая сигнатура (пустой текст) дедупу не подлежит.
    sig = aggregate.content_sig(m.text)
    hidden = 0
    if sig:
        win = timedelta(days=7)
        cands = (session.query(IntelMention)
                 .filter(IntelMention.hidden == False,  # noqa: E712
                         IntelMention.created_at >= (m.created_at - win),
                         IntelMention.created_at <= (m.created_at + win))
                 .all())
        for c in cands:
            if aggregate.content_sig(c.text) == sig:
                _hide_mention(session, c)
                hidden += 1
    else:
        if not m.hidden:
            _hide_mention(session, m)
            hidden = 1
    session.commit()
    return {"id": m.id, "hidden": True, "hidden_count": hidden}


def _preview_or_error(provider, post_id: str, handle: str, msg_id: int, kind: str):
    """Общая обвязка кэша+провайдера для media-эндпоинтов. Возвращает FileResponse или
    HTTPException-совместимый ответ через raise."""
    from ..core.providers.telegram import TelegramFloodWait
    if kind not in ("photo", "video"):
        raise HTTPException(404, "no previewable media")
    if provider is None:
        raise HTTPException(503, "provider unavailable")
    try:
        res = media_cache.get_or_fetch(provider, post_id, handle, msg_id, kind)
    except TelegramFloodWait:
        raise HTTPException(503, "rate-limited, try later")
    if res is None:
        raise HTTPException(404, "preview unavailable")
    path, mime = res
    return FileResponse(str(path), media_type=mime,
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/intel/mention/{mention_id}/media")
def intel_mention_media(
    mention_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """Превью фото/постер видео, прикреплённого к самому упоминанию."""
    m = session.get(IntelMention, mention_id)
    if m is None:
        raise HTTPException(404, "mention not found")
    handle = _handle_for(m)
    _, msg_id = _parse_handle_and_msg_id(m.post_id)
    return _preview_or_error(_get_tg_provider(), m.post_id, handle, int(msg_id), m.media or "")


@router.get("/intel/mention/{mention_id}/parent-media/{tg_msg_id}")
def intel_parent_media(
    mention_id: int,
    tg_msg_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """Превью медиа родительского сообщения треда (tg_msg_id) этого упоминания."""
    m = session.get(IntelMention, mention_id)
    if m is None:
        raise HTTPException(404, "mention not found")
    ctx = (session.query(IntelThreadContext)
           .filter(IntelThreadContext.mention_id == mention_id,
                   IntelThreadContext.tg_msg_id == tg_msg_id,
                   IntelThreadContext.role == "parent")
           .first())
    if ctx is None:
        raise HTTPException(404, "parent not in thread")
    handle = _handle_for(m)
    parent_post_id = _parent_post_id(m, tg_msg_id)
    return _preview_or_error(_get_tg_provider(), parent_post_id, handle, int(tg_msg_id), ctx.media or "")


@router.get("/intel/mention/{mention_id}/context")
def intel_mention_context(
    mention_id: int,
    session: Session = Depends(db),
    user: User = Depends(current_user),
):
    mention = session.get(IntelMention, mention_id)
    if mention is None:
        raise HTTPException(404, "Mention not found")

    rows = (session.query(IntelThreadContext)
            .filter(IntelThreadContext.mention_id == mention_id)
            .order_by(IntelThreadContext.role, IntelThreadContext.depth.asc())
            .all())

    reply_chain = sorted(
        [{"tg_msg_id": r.tg_msg_id, "depth": r.depth,
          "author": r.author, "text": r.text,
          "media": r.media,
          "created_at": aggregate._aware(r.created_at).isoformat()}
         for r in rows if r.role == "parent"],
        key=lambda x: x["depth"],
        reverse=True,
    )
    siblings = sorted(
        [{"tg_msg_id": r.tg_msg_id, "author": r.author,
          "text": r.text, "created_at": aggregate._aware(r.created_at).isoformat()}
         for r in rows if r.role == "sibling"],
        key=lambda x: x["created_at"],
    )
    return {"mention_id": mention_id, "reply_chain": reply_chain, "siblings": siblings}
