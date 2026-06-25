from __future__ import annotations
import hashlib
import re
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from .models import IntelDirection, IntelMention, IntelIncident, IntelStory, IntelStoryPoint, IntelAlert

def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)

_URL_RE = re.compile(r"https?://\S+")
_NONWORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")

def content_sig(text: str) -> str:
    """Stable signature of a post's CONTENT for cross-channel dedup.

    Normalises (lowercase, drop URLs + punctuation/emoji, collapse whitespace) and
    hashes the first 120 chars — so verbatim reposts collapse even when each channel
    appends its own footer/links. Empty text → '' (never deduped)."""
    t = (text or "").lower()
    t = _URL_RE.sub(" ", t)
    t = _NONWORD_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()[:120]
    return hashlib.md5(t.encode("utf-8")).hexdigest()[:16] if t else ""

def _sparkline(points) -> list:
    return [int(p.mention_count) for p in sorted(points, key=lambda p: p.bucket_start)][-12:]

def _spike_pct(points) -> float:
    series = [p.mention_count for p in sorted(points, key=lambda p: p.bucket_start)]
    if len(series) < 2:
        return 0.0
    base = sum(series[:-1]) / max(1, len(series) - 1)
    last = series[-1]
    return round((last - base) / base * 100, 1) if base > 0 else (100.0 if last else 0.0)

def _sides(session, story_id) -> list:
    rows = (session.query(IntelMention.side)
            .join(IntelIncident, IntelMention.incident_id == IntelIncident.id)
            .filter(IntelIncident.story_id == story_id).distinct().all())
    return sorted({(r[0] or "").strip() for r in rows if (r[0] or "").strip()})

def _points(session, story_id):
    return session.query(IntelStoryPoint).filter_by(story_id=story_id).all()

def story_summary(session, story) -> dict:
    d = session.get(IntelDirection, story.direction_id)
    pts = _points(session, story.id)
    return {
        "id": story.id, "title": story.title, "direction": d.key if d else None,
        "sides": _sides(session, story.id),
        "source_count": story.source_count, "post_count": story.post_count,
        "verified": bool(story.verified), "credibility": story.credibility,
        "credibility_note": story.credibility_note or "",
        "spike_pct": _spike_pct(pts), "sparkline": _sparkline(pts),
        "last_seen_at": _aware(story.last_seen_at).isoformat() if story.last_seen_at else None,
    }

def event(m) -> dict:
    return {"id": m.id, "platform": m.platform, "author": m.author, "side": m.side,
            "text": m.text, "url": m.url, "created_at": _aware(m.created_at).isoformat(),
            "verified": bool(m.verified), "direction": m.direction_id,
            "sig": content_sig(m.text)}

def story_detail(session, story) -> dict:
    base = story_summary(session, story)
    pts = _points(session, story.id)
    src = {}
    rows = (session.query(IntelMention)
            .join(IntelIncident, IntelMention.incident_id == IntelIncident.id)
            .filter(IntelIncident.story_id == story.id).all())
    for m in rows:
        key = m.author or "—"
        e = src.setdefault(key, {"name": key, "side": m.side, "count": 0, "last_at": None, "url": m.url})
        e["count"] += 1
        at = _aware(m.created_at)
        if e["last_at"] is None or at.isoformat() > e["last_at"]:
            e["last_at"] = at.isoformat()
    base.update({
        "summary_text": story.summary or "",
        "points": [{"bucket_start": _aware(p.bucket_start).isoformat(),
                    "mention_count": p.mention_count, "source_count": p.source_count} for p in pts],
        "sources": list(src.values()),
        "events": [event(m) for m in sorted(rows, key=lambda m: m.created_at, reverse=True)[:50]],
    })
    return base

def direction_card(session, direction, window_h=24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
    q = (session.query(IntelMention)
         .filter(IntelMention.direction_id == direction.id, IntelMention.created_at >= since))
    events_count = q.count()
    stories = session.query(IntelStory).filter_by(direction_id=direction.id).all()
    spike = max([_spike_pct(_points(session, st.id)) for st in stories], default=0.0)
    last = q.order_by(IntelMention.created_at.desc()).first()
    creds = [st.credibility for st in stories if st.credibility and st.credibility != "unrated"]
    dominant = max(set(creds), key=creds.count) if creds else "unrated"
    activity = min(100, events_count * 5)
    return {"key": direction.key, "name": direction.name, "activity_level": activity,
            "spike_pct": spike, "events_count": events_count, "dominant_credibility": dominant,
            "last_event": ({"text": last.text, "at": _aware(last.created_at).isoformat(),
                            "source": last.author} if last else None)}

def compute_overview(session, window_h=24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
    events = session.query(func.count(IntelMention.id)).filter(IntelMention.created_at >= since).scalar() or 0
    stories = session.query(IntelStory).filter_by(status="active").all()
    summaries = [story_summary(session, st) for st in stories]
    summary_by_id = {st.id: s for st, s in zip(stories, summaries)}
    hot = sorted(summaries, key=lambda x: x["spike_pct"], reverse=True)[:8]
    top = sorted(summaries, key=lambda x: x["post_count"], reverse=True)[:8]
    alerts = [{"id": st.id, "story_id": st.id, "direction": summary_by_id[st.id]["direction"],
               "kind": "spike", "magnitude": summary_by_id[st.id]["spike_pct"],
               "message": st.title, "at": _aware(st.last_seen_at).isoformat() if st.last_seen_at else None}
              for st in stories if st.is_anomaly][:20]
    spiking_dirs = len({s["direction"] for s in summaries if s["spike_pct"] >= 50})
    return {"kpis": {"events": events, "active_stories": len(stories), "spiking_dirs": spiking_dirs},
            "hot": hot, "alerts": alerts, "top_stories": top}


def alert_payload(session, a) -> dict:
    d = session.get(IntelDirection, a.direction_id) if a.direction_id else None
    return {"id": a.id, "scope": a.scope, "story_id": a.story_id,
            "direction": d.key if d else None, "kind": a.kind,
            "magnitude": a.magnitude, "title": a.title, "message": a.message,
            "at": _aware(a.fired_at).isoformat() if a.fired_at else None,
            "acknowledged": a.acknowledged_at is not None}
