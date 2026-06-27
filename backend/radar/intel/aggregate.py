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

def tg_url(m) -> str | None:
    """Best-effort public Telegram deep link to the exact message.

    Two post_id shapes are produced by the collector:
    - channel posts: numeric id (e.g. "103985"); the channel handle is the author
      (e.g. "@warhistory") → https://t.me/warhistory/103985
    - chat messages: "namespace/msgid" (e.g. "Amvrosiivka/130151") → if the namespace
      is a public @username we link https://t.me/Amvrosiivka/130151; a numeric
      namespace (username-less group) has no public link, so we fall back to m.url.

    Returns the stored m.url if a link can't be derived (covers any future shape)."""
    pid = (m.post_id or "").strip()
    if not pid:
        return m.url
    if "/" in pid:
        ns, _, msgid = pid.partition("/")
        ns = ns.lstrip("@")
        if ns and not ns.isdigit() and msgid.isdigit():
            return f"https://t.me/{ns}/{msgid}"
        return m.url
    # channel post — numeric id, handle comes from author
    handle = (m.author or "").strip().lstrip("@")
    if handle and pid.isdigit():
        return f"https://t.me/{handle}/{pid}"
    return m.url

def _sparkline(points) -> list:
    return [int(p.mention_count) for p in sorted(points, key=lambda p: p.bucket_start)][-12:]

def _spike_pct(points) -> float:
    series = [p.mention_count for p in sorted(points, key=lambda p: p.bucket_start)]
    if len(series) < 2:
        return 0.0
    # Skip the current partial hour: bucket N is incomplete until the hour turns.
    # If the last bucket is the current hour (bucket_start == floor(now)), drop it
    # so spike is measured against the last COMPLETE hour.
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    current_hour = now_naive.replace(minute=0, second=0, microsecond=0)
    last_pt = max(points, key=lambda p: p.bucket_start)
    if last_pt.bucket_start >= current_hour and len(series) >= 3:
        series = series[:-1]
    if len(series) < 2:
        return 0.0
    base = sum(series[:-1]) / max(1, len(series) - 1)
    last = series[-1]
    return round((last - base) / base * 100, 1) if base > 0 else (100.0 if last else 0.0)

def _sides(session, story_id) -> list:
    rows = (session.query(IntelMention.side)
            .join(IntelIncident, IntelMention.incident_id == IntelIncident.id)
            .filter(IntelIncident.story_id == story_id,
                    IntelMention.hidden == False).distinct().all())  # noqa: E712
    return sorted({(r[0] or "").strip() for r in rows if (r[0] or "").strip()})

def _points(session, story_id):
    return session.query(IntelStoryPoint).filter_by(story_id=story_id).all()

def _points_since(session, story_id, since_naive):
    return (session.query(IntelStoryPoint)
            .filter(IntelStoryPoint.story_id == story_id,
                    IntelStoryPoint.bucket_start >= since_naive).all())

def story_summary(session, story, since=None) -> dict:
    d = session.get(IntelDirection, story.direction_id)
    pts = _points(session, story.id) if since is None else _points_since(session, story.id, since)
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
            "post_id": m.post_id,
            "text": m.text, "url": tg_url(m), "created_at": _aware(m.created_at).isoformat(),
            "verified": bool(m.verified), "direction": m.direction_id,
            "sig": content_sig(m.text),
            "is_reply": bool(getattr(m, "reply_to_tg_id", None)),
            "reply_to_tg_id": getattr(m, "reply_to_tg_id", None),
            "media": getattr(m, "media", None)}

def story_detail(session, story) -> dict:
    base = story_summary(session, story)
    pts = _points(session, story.id)
    src = {}
    rows = (session.query(IntelMention)
            .join(IntelIncident, IntelMention.incident_id == IntelIncident.id)
            .filter(IntelIncident.story_id == story.id,
                    IntelMention.hidden == False).all())  # noqa: E712
    for m in rows:
        key = m.author or "—"
        e = src.setdefault(key, {"name": key, "side": m.side, "count": 0, "last_at": None, "url": tg_url(m)})
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
         .filter(IntelMention.direction_id == direction.id, IntelMention.created_at >= since,
                 IntelMention.hidden == False))  # noqa: E712
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
    # IntelStoryPoint.bucket_start is stored as naive UTC — strip tz for SQL comparison.
    since_naive = since.replace(tzinfo=None)
    events = session.query(func.count(IntelMention.id)).filter(
        IntelMention.created_at >= since_naive, IntelMention.hidden == False).scalar() or 0  # noqa: E712
    # Only stories that had activity within the window.
    stories = (session.query(IntelStory)
               .filter(IntelStory.status == "active", IntelStory.last_seen_at >= since_naive).all())
    # Mention count per story WITHIN the window (from timeline buckets — fast indexed query).
    window_counts: dict[int, int] = {}
    if stories:
        rows = (session.query(IntelStoryPoint.story_id,
                              func.sum(IntelStoryPoint.mention_count))
                .filter(IntelStoryPoint.story_id.in_([st.id for st in stories]),
                        IntelStoryPoint.bucket_start >= since_naive)
                .group_by(IntelStoryPoint.story_id).all())
        window_counts = {sid: int(cnt or 0) for sid, cnt in rows}
    summaries = [story_summary(session, st, since=since_naive) for st in stories]
    summary_map = {s["id"]: s for s in summaries}

    # "Горит сейчас" — только сюжеты созданные в пределах окна (24ч), сортировка по spike_pct.
    # Нет fallback на старые истории — аналитик выбирает другой период через пикер сам.
    hot_ids = {st.id for st in stories
               if st.created_at and st.created_at >= since_naive and (st.post_count or 0) >= 2}
    hot_candidates = [summary_map[sid] for sid in hot_ids if sid in summary_map]
    if not hot_candidates:
        # Абсолютный минимум: созданы в окне (24ч) со spike — без старых мегасюжетов
        fresh_ids = {st.id for st in stories if st.created_at and st.created_at >= since_naive}
        hot_candidates = [s for s in summaries if s["id"] in fresh_ids and s.get("spike_pct", 0) > 0]
    if not hot_candidates:
        # Если совсем пусто — любые свежие (24ч), хотя бы что-то
        hot_candidates = [s for s in summaries if s["id"] in fresh_ids]
    hot = sorted(hot_candidates, key=lambda x: x["spike_pct"], reverse=True)[:8]

    # "Крупнейшие" — созданы в окне (24ч) И активны в последние 2ч.
    two_h_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None)
    top_ids = {st.id for st in stories
               if st.created_at and st.created_at >= since_naive
               and st.last_seen_at and st.last_seen_at >= two_h_ago
               and (st.post_count or 0) >= 2}
    top_candidates = [summary_map[sid] for sid in top_ids if sid in summary_map]
    if not top_candidates:
        # Абсолютный минимум: созданы в окне (24ч) И активны в последние 2ч — без старых мегасюжетов
        top_candidates = [summary_map[st.id] for st in stories
                          if st.created_at and st.created_at >= since_naive
                          and st.last_seen_at and st.last_seen_at >= two_h_ago
                          and st.id in summary_map]
    if not top_candidates:
        # Если совсем ничего свежего — берём хоть что-то созданное в окне по упоминаниям
        top_candidates = [summary_map[st.id] for st in stories
                          if st.created_at and st.created_at >= since_naive
                          and st.id in summary_map]
    top = sorted(top_candidates, key=lambda x: window_counts.get(x["id"], 0), reverse=True)[:8]
    # Only recent unacknowledged alerts: the "Сигналы" panel mirrors the bell, which
    # shows a rolling 2h window. Without a time filter day-old alerts pile up forever.
    alert_since = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None)
    alert_rows = (session.query(IntelAlert)
                  .filter(IntelAlert.acknowledged_at.is_(None),
                          IntelAlert.fired_at >= alert_since)
                  .order_by(IntelAlert.id.desc()).limit(20).all())
    alerts = [alert_payload(session, a) for a in alert_rows]
    spiking_dirs = len({s["direction"] for s in summaries if s["spike_pct"] >= 50})
    return {"kpis": {"events": events, "active_stories": len(stories), "spiking_dirs": spiking_dirs},
            "hot": hot, "alerts": alerts, "top_stories": top}


def compute_overview_range(session, from_dt, to_dt) -> dict:
    """Like compute_overview but for an arbitrary [from_dt, to_dt] range."""
    frm_naive = from_dt.replace(tzinfo=None) if from_dt else None
    to_naive = to_dt.replace(tzinfo=None) if to_dt else datetime.now(timezone.utc).replace(tzinfo=None)
    q = session.query(func.count(IntelMention.id)).filter(IntelMention.hidden == False)  # noqa: E712
    if frm_naive:
        q = q.filter(IntelMention.created_at >= frm_naive)
    q = q.filter(IntelMention.created_at <= to_naive)
    events = q.scalar() or 0
    story_q = session.query(IntelStory).filter(IntelStory.status == "active")
    if frm_naive:
        story_q = story_q.filter(IntelStory.last_seen_at >= frm_naive)
    story_q = story_q.filter(IntelStory.last_seen_at <= to_naive)
    stories = story_q.all()
    window_counts: dict[int, int] = {}
    if stories:
        pt_q = (session.query(IntelStoryPoint.story_id,
                              func.sum(IntelStoryPoint.mention_count))
                .filter(IntelStoryPoint.story_id.in_([st.id for st in stories]),
                        IntelStoryPoint.bucket_start <= to_naive))
        if frm_naive:
            pt_q = pt_q.filter(IntelStoryPoint.bucket_start >= frm_naive)
        rows = pt_q.group_by(IntelStoryPoint.story_id).all()
        window_counts = {sid: int(cnt or 0) for sid, cnt in rows}
    summaries = [story_summary(session, st, since=frm_naive) for st in stories]
    summary_map_r = {s["id"]: s for s in summaries}
    hot_ids_r = {st.id for st in stories if frm_naive and st.created_at and st.created_at >= frm_naive}
    hot_candidates_r = [summary_map_r[sid] for sid in hot_ids_r if sid in summary_map_r] or summaries
    hot = sorted(hot_candidates_r, key=lambda x: x["spike_pct"], reverse=True)[:8]
    top = sorted(summaries, key=lambda x: window_counts.get(x["id"], 0), reverse=True)[:8]
    spiking_dirs = len({s["direction"] for s in summaries if s["spike_pct"] >= 50})
    return {"kpis": {"events": events, "active_stories": len(stories), "spiking_dirs": spiking_dirs},
            "hot": hot, "alerts": [], "top_stories": top}


def alert_payload(session, a) -> dict:
    d = session.get(IntelDirection, a.direction_id) if a.direction_id else None
    return {"id": a.id, "scope": a.scope, "story_id": a.story_id,
            "direction": d.key if d else None, "kind": a.kind,
            "magnitude": a.magnitude, "title": a.title, "message": a.message,
            "at": _aware(a.fired_at).isoformat() if a.fired_at else None,
            "acknowledged": a.acknowledged_at is not None}
