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


def _attach_to_incident(session, conn, brand_id, m, v) -> Incident:
    created = _aware(m.created_at)
    for inc_id, dist in vec.knn(conn, "incident_vec", v, k=5):
        if (1.0 - dist) < INCIDENT_SIM:
            break  # sorted by distance; nothing closer qualifies
        inc = session.get(Incident, inc_id)
        if inc is None or inc.brand_id != brand_id:
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
    inc = Incident(brand_id=brand_id, title=_title(m.text),
                   sentiment=_tone_score(m.tone), post_count=1,
                   first_seen_at=created, last_seen_at=created)
    session.add(inc); session.flush()
    vec.store(conn, "incident_vec", inc.id, v)
    return inc


def update_stories(session: Session, brand_id: int) -> dict:
    conn = _raw(session)
    new = (session.query(Mention)
           .filter(Mention.brand_id == brand_id,
                   Mention.incident_id.is_(None),
                   Mention.is_spam.is_(False))
           .order_by(Mention.created_at).all())
    if not new:
        return {"mentions": 0, "incidents": 0}
    vecs = embeddings.embed([m.text or "" for m in new])
    incidents_touched = set()
    for m, v in zip(new, vecs):
        v = _normalize(v)
        vec.store(conn, "mention_vec", m.id, v)
        inc = _attach_to_incident(session, conn, brand_id, m, v)
        m.incident_id = inc.id
        incidents_touched.add(inc.id)
    session.commit()
    return {"mentions": len(new), "incidents": len(incidents_touched)}
