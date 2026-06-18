from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy.orm import Session

from . import embeddings, vec
from .models import Mention, Incident, Story, StoryPoint

# Tunables (cosine SIMILARITY thresholds; distance = 1 - sim). Calibrate on real brands.
INCIDENT_SIM    = float(os.getenv("STORY_INCIDENT_SIM", "0.90"))
STORY_SIM       = float(os.getenv("STORY_STORY_SIM", "0.78"))
INCIDENT_WINDOW = timedelta(hours=int(os.getenv("STORY_INCIDENT_WINDOW_H", "48")))
STORY_WINDOW    = timedelta(days=int(os.getenv("STORY_STORY_WINDOW_D", "14")))
BUCKET          = timedelta(hours=1)
VERIFY_MIN_SOURCES = int(os.getenv("STORY_VERIFY_MIN_SOURCES", "3"))  # ≥N independent sources → verified


def _tone_score(tone: str) -> float:
    return {"positive": 1.0, "negative": -1.0}.get(tone or "", 0.0)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _raw(session: Session):
    return session.connection().connection  # DBAPI conn for vec ops


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v if n == 0 else (v / n).astype(np.float32)


def _centroid(conn, table, row_id) -> np.ndarray:
    row = conn.execute(
        f"SELECT embedding FROM {table} WHERE id = ?", (row_id,)
    ).fetchone()
    return np.frombuffer(row[0], dtype=np.float32).copy()


def _title(text: str) -> str:
    t = (text or "").strip().replace("\n", " ")
    return (t[:80] + "…") if len(t) > 80 else (t or "(без текста)")


def _attach_to_incident(session, conn, scope, m, v) -> Incident:
    created = _aware(m.created_at)
    owner_id = getattr(m, scope.kind + "_id")
    for inc_id, dist in vec.knn(conn, "incident_vec", v, k=5):
        if (1.0 - dist) < INCIDENT_SIM:
            break  # sorted by distance; nothing closer qualifies
        inc = session.get(Incident, inc_id)
        if inc is None or getattr(inc, scope.kind + "_id") != owner_id:
            continue
        if abs(_aware(inc.last_seen_at) - created) > INCIDENT_WINDOW:
            continue
        old = _centroid(conn, "incident_vec", inc_id)
        n = inc.post_count
        merged = _normalize((old * n + v) / (n + 1))
        vec.store(conn, "incident_vec", inc_id, merged)
        inc.post_count = n + 1
        inc.sentiment = (inc.sentiment * n + _tone_score(m.tone)) / (n + 1)
        inc.first_seen_at = min(_aware(inc.first_seen_at), created)
        inc.last_seen_at = max(_aware(inc.last_seen_at), created)
        session.flush()
        return inc
    inc = Incident(**scope.owner_kwargs(), title=_title(m.text),
                   sentiment=_tone_score(m.tone), post_count=1,
                   first_seen_at=created, last_seen_at=created)
    session.add(inc); session.flush()
    vec.store(conn, "incident_vec", inc.id, v)
    return inc


def _attach_to_story(session, conn, scope, inc, centroid) -> Story:
    if inc.story_id is not None:
        st = session.get(Story, inc.story_id)
        _bump_story(conn, st, inc, centroid)
        return st
    owner_id = getattr(inc, scope.kind + "_id")
    for st_id, dist in vec.knn(conn, "story_vec", centroid, k=5):
        if (1.0 - dist) < STORY_SIM:
            break
        st = session.get(Story, st_id)
        if st is None or getattr(st, scope.kind + "_id") != owner_id:
            continue
        if abs(_aware(st.last_seen_at) - _aware(inc.last_seen_at)) > STORY_WINDOW:
            continue
        _bump_story(conn, st, inc, centroid)
        return st
    st = Story(**scope.owner_kwargs(), title=inc.title,
               first_seen_at=inc.first_seen_at, last_seen_at=inc.last_seen_at,
               post_count=0)
    session.add(st); session.flush()
    vec.store(conn, "story_vec", st.id, centroid)
    _bump_story(conn, st, inc, centroid)
    return st


def _bump_story(conn, st, inc, centroid) -> None:
    # story centroid = running mean of member-incident centroids (approx by post_count)
    old = _centroid(conn, "story_vec", st.id)
    w = max(st.post_count, 1)
    merged = _normalize((old * w + centroid) / (w + 1))
    vec.store(conn, "story_vec", st.id, merged)
    st.first_seen_at = min(_aware(st.first_seen_at), _aware(inc.first_seen_at))
    st.last_seen_at = max(_aware(st.last_seen_at), _aware(inc.last_seen_at))
    st.post_count = (st.post_count or 0) + 1


def _bucket(dt: datetime) -> datetime:
    dt = _aware(dt)
    return dt.replace(minute=0, second=0, microsecond=0)


def _recompute_points(session: Session, story_id: int) -> None:
    # All mentions whose incident belongs to this story.
    rows = (session.query(Mention)
            .join(Incident, Mention.incident_id == Incident.id)
            .filter(Incident.story_id == story_id).all())
    buckets: dict[datetime, dict] = {}
    for m in rows:
        b = _bucket(m.created_at)
        agg = buckets.setdefault(b, {"n": 0, "sent": 0.0, "src": set()})
        agg["n"] += 1
        agg["sent"] += _tone_score(m.tone)
        agg["src"].add(m.author or "")
    # Wipe + rewrite this story's points (idempotent on every recompute).
    session.query(StoryPoint).filter(StoryPoint.story_id == story_id).delete()
    for b, agg in buckets.items():
        session.add(StoryPoint(
            story_id=story_id, bucket_start=b,
            mention_count=agg["n"],
            avg_sentiment=(agg["sent"] / agg["n"]) if agg["n"] else None,
            source_count=len(agg["src"]),
        ))
    session.flush()


def _recompute_verification(session: Session, story_id: int) -> None:
    """Set story.source_count = distinct non-blank authors of its mentions, and
    story.verified = that count >= VERIFY_MIN_SOURCES. Independent corroboration
    is the core trust signal: a story carried by many distinct channels/domains
    is far likelier to be real than a single-source claim."""
    story = session.get(Story, story_id)
    if story is None:
        return
    rows = (session.query(Mention.author)
            .join(Incident, Mention.incident_id == Incident.id)
            .filter(Incident.story_id == story_id).all())
    sources = {(a or "").strip() for (a,) in rows if (a or "").strip()}
    story.source_count = len(sources)
    story.verified = len(sources) >= VERIFY_MIN_SOURCES
    session.flush()


def update_stories(session: Session, scope) -> dict:
    """Cluster unprocessed Mentions for the given Scope into Incidents and Stories.

    ``scope`` is a :class:`radar.scope.Scope` (brand or topic).
    """
    conn = _raw(session)
    owner_col = getattr(Mention, scope.kind + "_id")
    new = (session.query(Mention)
           .filter(owner_col == scope.id,
                   Mention.incident_id.is_(None),
                   Mention.is_spam.is_(False))
           .order_by(Mention.created_at).all())
    if not new:
        return {"mentions": 0, "incidents": 0, "stories": 0}
    vecs = embeddings.embed([m.text or "" for m in new])
    incidents_touched = set()
    stories_touched = set()
    for m, v in zip(new, vecs):
        v = _normalize(v)
        vec.store(conn, "mention_vec", m.id, v)
        inc = _attach_to_incident(session, conn, scope, m, v)
        m.incident_id = inc.id
        cen = _centroid(conn, "incident_vec", inc.id)
        st = _attach_to_story(session, conn, scope, inc, cen)
        inc.story_id = st.id
        incidents_touched.add(inc.id)
        stories_touched.add(st.id)
    session.flush()
    from . import anomalies
    for sid in stories_touched:
        _recompute_points(session, sid)
        _recompute_verification(session, sid)
        anomalies.detect_anomaly(session, sid)
    session.commit()
    return {"mentions": len(new), "incidents": len(incidents_touched),
            "stories": len(stories_touched)}
