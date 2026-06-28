"""Intel alerts: detect story/direction bursts and persist deduplicated IntelAlert rows.

Runs inside the ticker (passes.run_intel_tick) after clustering + anomaly detection.
A per-(scope, ref, kind) cooldown collapses one sustained burst into a single alert.
"""
from __future__ import annotations
import os
import logging
from datetime import datetime, timezone, timedelta

from ..models import _now
from ..core.anomalies import VOLUME_FACTOR, SOURCE_FACTOR, MIN_VOLUME, MIN_BUCKETS
from . import aggregate
from .models import IntelAlert, IntelDirection, IntelStory, IntelStoryPoint, IntelMention

log = logging.getLogger("radar.intel.alerts")

ALERT_COOLDOWN_H = int(os.getenv("ALERT_COOLDOWN_H", "6"))


def _recent_exists(session, scope, kind, *, direction_id=None, story_id=None) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_H)
    q = (session.query(IntelAlert)
         .filter(IntelAlert.scope == scope, IntelAlert.kind == kind,
                 IntelAlert.fired_at >= cutoff))
    if scope == "story":
        q = q.filter(IntelAlert.story_id == story_id)
    else:
        q = q.filter(IntelAlert.direction_id == direction_id)
    return session.query(q.exists()).scalar()


def _emit(session, scope, kind, *, title, message, magnitude,
          direction_id=None, story_id=None):
    """Insert an alert unless one of the same (scope, ref, kind) fired within the
    cooldown. Returns the new IntelAlert or None when suppressed."""
    if _recent_exists(session, scope, kind, direction_id=direction_id, story_id=story_id):
        return None
    alert = IntelAlert(scope=scope, kind=kind, title=title or "", message=message or "",
                       magnitude=float(magnitude or 0.0),
                       direction_id=direction_id, story_id=story_id, fired_at=_now())
    session.add(alert)
    session.flush()
    return alert


def _classify_story(points) -> tuple:
    """Return (kind, magnitude) for an anomalous story from its timeline points."""
    pts = sorted(points, key=lambda p: p.bucket_start)
    magnitude = aggregate._spike_pct(pts)
    kind = "spike"
    if len(pts) > MIN_BUCKETS:
        base = pts[:-1]
        last = pts[-1]
        base_src = sum((getattr(p, "source_count", 0) or 0) for p in base) / max(1, len(base))
        last_src = getattr(last, "source_count", 0) or 0
        if base_src > 0 and last_src >= base_src * SOURCE_FACTOR:
            kind = "source_influx"
    return kind, magnitude


def _story_message(kind: str, magnitude: float, title: str) -> str:
    head = "Приток источников" if kind == "source_influx" else f"Всплеск +{int(magnitude)}%"
    return f"{head}: {title}" if title else head


def scan_story_alerts(session) -> list:
    """Emit an alert for every currently-anomalous active story (cooldown-deduped).
    Заглушённые сюжеты и сюжеты заглушённых направлений пропускаются."""
    out = []
    muted_dir_ids = {row[0] for row in
                     session.query(IntelDirection.id)
                     .filter(IntelDirection.muted.is_(True)).all()}
    stories = (session.query(IntelStory)
               .filter(IntelStory.is_anomaly.is_(True), IntelStory.status == "active",
                       IntelStory.muted.is_(False)).all())
    for st in stories:
        if st.direction_id in muted_dir_ids:
            continue
        pts = aggregate._points(session, st.id)
        kind, magnitude = _classify_story(pts)
        alert = _emit(session, "story", kind,
                      title=st.title or "",
                      message=_story_message(kind, magnitude, st.title or ""),
                      magnitude=magnitude, direction_id=st.direction_id, story_id=st.id)
        if alert is not None:
            out.append(alert)
    return out


def _direction_hourly_counts(session, direction_id) -> list:
    rows = (session.query(IntelMention.created_at)
            .filter(IntelMention.direction_id == direction_id).all())
    buckets: dict = {}
    for (created_at,) in rows:
        if created_at is None:
            continue
        ts = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        key = ts.replace(minute=0, second=0, microsecond=0)
        buckets[key] = buckets.get(key, 0) + 1
    return [buckets[k] for k in sorted(buckets)]


def detect_direction_burst(session, direction_id):
    """Spike pct if the latest hour bursts vs the mean of prior hours, else None."""
    series = _direction_hourly_counts(session, direction_id)
    if len(series) <= MIN_BUCKETS:
        return None
    base = series[:-1]
    last = series[-1]
    base_mean = sum(base) / max(1, len(base))
    spike = last >= MIN_VOLUME and (last >= base_mean * VOLUME_FACTOR if base_mean > 0 else True)
    if not spike:
        return None
    return round((last - base_mean) / base_mean * 100, 1) if base_mean > 0 else 100.0


def scan_direction_alerts(session) -> list:
    out = []
    for d in session.query(IntelDirection).all():
        if d.key == "unassigned" or d.muted:
            continue
        magnitude = detect_direction_burst(session, d.id)
        if magnitude is None:
            continue
        alert = _emit(session, "direction", "direction_burst",
                      title=d.name or d.key,
                      message=f"Всплеск активности +{int(magnitude)}% по направлению {d.name or d.key}",
                      magnitude=magnitude, direction_id=d.id)
        if alert is not None:
            out.append(alert)
    return out


def scan(session) -> list:
    """Tick entrypoint: emit story + direction alerts. Never raises."""
    out = []
    try:
        out += scan_story_alerts(session)
    except Exception:
        log.exception("intel story alert scan failed")
    try:
        out += scan_direction_alerts(session)
    except Exception:
        log.exception("intel direction alert scan failed")
    return out
