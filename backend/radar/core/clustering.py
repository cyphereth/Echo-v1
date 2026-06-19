"""Generic story/incident clustering engine, parameterised by a DomainModels bundle.

No provider imports, no Scope references, no news-specific logic (credibility,
source-count). All table access goes through the ``models`` bundle.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

import numpy as np

from . import vec

# ---------------------------------------------------------------------------
# Tunables (same env-vars as stories.py so existing deployments are unaffected)
# ---------------------------------------------------------------------------
INCIDENT_SIM    = float(os.getenv("STORY_INCIDENT_SIM", "0.90"))
STORY_SIM       = float(os.getenv("STORY_STORY_SIM", "0.78"))
INCIDENT_WINDOW = timedelta(hours=int(os.getenv("STORY_INCIDENT_WINDOW_H", "48")))
STORY_WINDOW    = timedelta(days=int(os.getenv("STORY_STORY_WINDOW_D", "14")))


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _tone_score(tone: str) -> float:
    return {"positive": 1.0, "negative": -1.0}.get(tone or "", 0.0)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _raw(session):
    return session.connection().connection  # DBAPI conn for vec ops


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v if n == 0 else (v / n).astype(np.float32)


def _centroid(conn, table: str, row_id: int) -> np.ndarray:
    row = conn.execute(
        f"SELECT embedding FROM {table} WHERE id = ?", (row_id,)
    ).fetchone()
    return np.frombuffer(row[0], dtype=np.float32).copy()


def _title(text: str) -> str:
    t = (text or "").strip().replace("\n", " ")
    return (t[:80] + "…") if len(t) > 80 else (t or "(без текста)")


def _attach_to_incident(session, conn, models, owner_id: int, m, v: np.ndarray):
    """Attach mention *m* (with embedding *v*) to the best matching incident,
    or create a new one. Returns the incident ORM object."""
    created = _aware(m.created_at)
    tone = getattr(m, "tone", None)
    for inc_id, dist in vec.knn(conn, "incident_vec", v, k=5):
        if (1.0 - dist) < INCIDENT_SIM:
            break  # sorted by distance; nothing closer qualifies
        inc = session.get(models.Incident, inc_id)
        if inc is None or getattr(inc, models.owner_field) != owner_id:
            continue
        if abs(_aware(inc.last_seen_at) - created) > INCIDENT_WINDOW:
            continue
        old = _centroid(conn, "incident_vec", inc_id)
        n = inc.post_count
        merged = _normalize((old * n + v) / (n + 1))
        vec.store(conn, "incident_vec", inc_id, merged)
        inc.post_count = n + 1
        if hasattr(inc, "sentiment"):
            inc.sentiment = (inc.sentiment * n + _tone_score(tone)) / (n + 1)
        inc.first_seen_at = min(_aware(inc.first_seen_at), created)
        inc.last_seen_at = max(_aware(inc.last_seen_at), created)
        session.flush()
        return inc
    inc = models.Incident(**models.owner_kwargs(owner_id), title=_title(m.text),
                          post_count=1,
                          first_seen_at=created, last_seen_at=created)
    if hasattr(inc, "sentiment"):
        inc.sentiment = _tone_score(tone)
    session.add(inc)
    session.flush()
    vec.store(conn, "incident_vec", inc.id, v)
    return inc


def _bump_story(conn, st, inc, centroid: np.ndarray) -> None:
    """Update story centroid (running mean) and time bounds."""
    old = _centroid(conn, "story_vec", st.id)
    w = max(st.post_count, 1)
    merged = _normalize((old * w + centroid) / (w + 1))
    vec.store(conn, "story_vec", st.id, merged)
    st.first_seen_at = min(_aware(st.first_seen_at), _aware(inc.first_seen_at))
    st.last_seen_at = max(_aware(st.last_seen_at), _aware(inc.last_seen_at))
    st.post_count = (st.post_count or 0) + 1


def _attach_to_story(session, conn, models, owner_id: int, inc, centroid: np.ndarray):
    """Attach incident *inc* to the best matching story, or create a new one.
    Returns the story ORM object."""
    if inc.story_id is not None:
        st = session.get(models.Story, inc.story_id)
        _bump_story(conn, st, inc, centroid)
        return st
    for st_id, dist in vec.knn(conn, "story_vec", centroid, k=5):
        if (1.0 - dist) < STORY_SIM:
            break
        st = session.get(models.Story, st_id)
        if st is None or getattr(st, models.owner_field) != owner_id:
            continue
        if abs(_aware(st.last_seen_at) - _aware(inc.last_seen_at)) > STORY_WINDOW:
            continue
        _bump_story(conn, st, inc, centroid)
        return st
    st = models.Story(**models.owner_kwargs(owner_id), title=inc.title,
                      first_seen_at=inc.first_seen_at, last_seen_at=inc.last_seen_at,
                      post_count=0)
    session.add(st)
    session.flush()
    vec.store(conn, "story_vec", st.id, centroid)
    _bump_story(conn, st, inc, centroid)
    return st


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def cluster_owner(session, owner_id: int, models, embed: Callable,
                  *, sim_threshold: float = 0.78, now=None) -> None:
    """Generic story/incident clustering for one owner (brand or topic).

    Reads models.Mention rows for owner_id with incident_id IS NULL, embeds via
    ``embed(text) -> vector``, attaches to the nearest incident/story above
    sim_threshold or creates new ones, and refreshes story_points + counts.
    All table access goes through the ``models`` bundle — no Scope, no globals.
    """
    conn = _raw(session)
    # Ensure vec tables exist (idempotent; real DBs already have them via init_db)
    vec.create_vec_tables(conn)
    owner_col = getattr(models.Mention, models.owner_field)

    q = (session.query(models.Mention)
         .filter(owner_col == owner_id,
                 models.Mention.incident_id.is_(None))
         .order_by(models.Mention.created_at))

    # Conditionally filter spam if the model has that column
    is_spam_attr = getattr(models.Mention, "is_spam", None)
    if is_spam_attr is not None:
        q = q.filter(is_spam_attr.is_(False))

    new = q.all()
    if not new:
        return

    for m in new:
        text = m.text or ""
        raw_v = embed(text)
        v = _normalize(np.asarray(raw_v, dtype=np.float32))
        vec.store(conn, "mention_vec", m.id, v)
        inc = _attach_to_incident(session, conn, models, owner_id, m, v)
        m.incident_id = inc.id
        cen = _centroid(conn, "incident_vec", inc.id)
        st = _attach_to_story(session, conn, models, owner_id, inc, cen)
        inc.story_id = st.id

    session.flush()
