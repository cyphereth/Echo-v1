from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .core import embeddings, vec
from .core.clustering import cluster_owner
from .core.domain import DomainModels
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
    owner_col = getattr(Mention, scope.kind + "_id")

    # Snapshot the unprocessed mention IDs BEFORE clustering so post-clustering
    # steps and returned counts are scoped to THIS batch only — not all-time history.
    pending_ids = [
        mid for (mid,) in
        session.query(Mention.id)
               .filter(owner_col == scope.id,
                       Mention.incident_id.is_(None),
                       Mention.is_spam.is_(False))
               .all()
    ]
    if not pending_ids:
        return {"mentions": 0, "incidents": 0, "stories": 0}

    # Build DomainModels bundle for the news/brand domain (global ORM classes).
    domain = DomainModels(
        owner_field=f"{scope.kind}_id",
        Mention=Mention,
        Incident=Incident,
        Story=Story,
        StoryPoint=StoryPoint,
    )
    # Delegate clustering to the engine; embed is adapted from batch to per-text.
    cluster_owner(
        session,
        owner_id=scope.id,
        models=domain,
        embed=lambda t: embeddings.embed([t])[0],
    )

    # Derive touched sets from the mentions processed in THIS batch only.
    rows = (session.query(Mention.incident_id)
                   .filter(Mention.id.in_(pending_ids),
                           Mention.incident_id.isnot(None))
                   .all())
    incidents_touched = {iid for (iid,) in rows}
    inc_owner_col = getattr(Incident, scope.kind + "_id")
    stories_touched = set(
        sid for (sid,) in
        session.query(Incident.story_id)
               .filter(Incident.id.in_(incidents_touched),
                       Incident.story_id.isnot(None))
               .distinct()
    ) if incidents_touched else set()

    from .core import anomalies
    for sid in stories_touched:
        _recompute_points(session, sid)
        _recompute_verification(session, sid)
        anomalies.detect_anomaly(session, sid)
    session.commit()
    return {"mentions": len(pending_ids), "incidents": len(incidents_touched),
            "stories": len(stories_touched)}
