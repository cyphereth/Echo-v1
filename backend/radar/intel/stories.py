"""Intel-domain story clustering + verification + anomaly detection.

Wires the generic ``core.clustering.cluster_owner`` engine onto the intel
ORM models (IntelMention / IntelIncident / IntelStory / IntelStoryPoint) and
re-implements the per-story source-count / verified recomputation faithful
to the legacy ``radar/stories.py::_recompute_verification`` logic
(author normalisation + VERIFY_MIN_SOURCES threshold).

ADDITIVE: legacy radar/stories.py, radar/news/stories.py, radar/brand/stories.py
are untouched. Domain isolation: only imports from `.` / `..core.*`.
"""
from __future__ import annotations
import logging
import os

from sqlalchemy.orm import Session

from ..core.clustering import cluster_owner
from ..core.domain import DomainModels
from ..core.embeddings import embed as _batch_embed
from .models import IntelMention, IntelIncident, IntelStory, IntelStoryPoint

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables — mirror the legacy env-var name/default so behaviour is identical.
# Legacy in radar/stories.py: VERIFY_MIN_SOURCES = int(os.getenv("STORY_VERIFY_MIN_SOURCES", "3"))
# ---------------------------------------------------------------------------
STORY_VERIFY_MIN_SOURCES = int(os.getenv("STORY_VERIFY_MIN_SOURCES", "3"))

# ---------------------------------------------------------------------------
# Domain bundle for the intel models
# ---------------------------------------------------------------------------
_MODELS = DomainModels(
    owner_field="direction_id",
    Mention=IntelMention,
    Incident=IntelIncident,
    Story=IntelStory,
    StoryPoint=IntelStoryPoint,
)


def _default_embed(text: str):
    """Adapt the batch embedder to the per-text signature cluster_owner expects."""
    return _batch_embed([text])[0]


def update_stories(session: Session, direction_id: int, embed=None) -> None:
    """Cluster pending IntelMentions for *direction_id* into incidents/stories, then
    recompute source_count + verified for every story under that direction, and
    run anomaly detection."""
    cluster_owner(
        session,
        owner_id=direction_id,
        models=_MODELS,
        embed=embed if embed is not None else _default_embed,
    )
    _recompute_verification(session, direction_id)
    _detect_anomalies(session, direction_id)


def _detect_anomalies(session: Session, direction_id: int) -> None:
    """Run anomaly detection on every IntelStory under direction_id.

    Mirrors how news/stories.py iterated touched stories and called detect_anomaly,
    wrapped in per-story try/except so one failure does not abort the rest.
    """
    from ..core import anomalies
    stories = session.query(IntelStory).filter_by(direction_id=direction_id).all()
    for st in stories:
        try:
            anomalies.detect_anomaly(session, st.id, IntelStory, IntelStoryPoint)
        except Exception:
            log.exception("anomaly detection failed for intel story %s (skipped)", st.id)


def _recompute_verification(session: Session, direction_id: int) -> None:
    """Recompute source_count and verified for every IntelStory under direction_id.

    Faithful port of legacy radar/stories.py::_recompute_verification:
      - author normalisation: (a or "").strip(), drop blanks
      - threshold: STORY_VERIFY_MIN_SOURCES (same env-var, same default=3)
    The legacy function operates per story_id; we iterate all stories for
    the direction and call the same logic for each.
    """
    stories = session.query(IntelStory).filter_by(direction_id=direction_id).all()
    for st in stories:
        rows = (
            session.query(IntelMention.author)
            .join(IntelIncident, IntelMention.incident_id == IntelIncident.id)
            .filter(IntelIncident.story_id == st.id)
            .all()
        )
        # Identical normalisation to legacy: (a or "").strip(), skip blanks
        sources = {(a or "").strip() for (a,) in rows if (a or "").strip()}
        st.source_count = len(sources)
        st.verified = len(sources) >= STORY_VERIFY_MIN_SOURCES
    session.flush()
