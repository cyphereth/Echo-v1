"""News-domain story clustering + verification.

Wires the generic ``core.clustering.cluster_owner`` engine onto the news
ORM models (NewsMention / NewsIncident / NewsStory / NewsStoryPoint) and
re-implements the per-story source-count / verified recomputation faithful
to the legacy ``radar/stories.py::_recompute_verification`` logic
(author normalisation + VERIFY_MIN_SOURCES threshold).

ADDITIVE: legacy radar/stories.py, radar/credibility.py, radar/digests.py
are untouched.
"""
from __future__ import annotations
import os

from sqlalchemy.orm import Session

from ..core.clustering import cluster_owner
from ..core.domain import DomainModels
from ..core.embeddings import embed as _batch_embed
from .models import NewsMention, NewsIncident, NewsStory, NewsStoryPoint

# ---------------------------------------------------------------------------
# Tunables — mirror the legacy env-var name/default so behaviour is identical.
# Legacy in radar/stories.py: VERIFY_MIN_SOURCES = int(os.getenv("STORY_VERIFY_MIN_SOURCES", "3"))
# ---------------------------------------------------------------------------
STORY_VERIFY_MIN_SOURCES = int(os.getenv("STORY_VERIFY_MIN_SOURCES", "3"))

# ---------------------------------------------------------------------------
# Domain bundle for the news models
# ---------------------------------------------------------------------------
_MODELS = DomainModels(
    owner_field="topic_id",
    Mention=NewsMention,
    Incident=NewsIncident,
    Story=NewsStory,
    StoryPoint=NewsStoryPoint,
)


def _default_embed(text: str):
    """Adapt the batch embedder to the per-text signature cluster_owner expects."""
    return _batch_embed([text])[0]


def update_stories(session: Session, topic_id: int, embed=None) -> None:
    """Cluster pending NewsMentions for *topic_id* into incidents/stories, then
    recompute source_count + verified for every story under that topic."""
    cluster_owner(
        session,
        owner_id=topic_id,
        models=_MODELS,
        embed=embed if embed is not None else _default_embed,
    )
    _recompute_verification(session, topic_id)


def _recompute_verification(session: Session, topic_id: int) -> None:
    """Recompute source_count and verified for every NewsStory under topic_id.

    Faithful port of legacy radar/stories.py::_recompute_verification:
      - author normalisation: (a or "").strip(), drop blanks
      - threshold: STORY_VERIFY_MIN_SOURCES (same env-var, same default=3)
    The legacy function operates per story_id; we iterate all stories for
    the topic and call the same logic for each.
    """
    stories = session.query(NewsStory).filter_by(topic_id=topic_id).all()
    for st in stories:
        rows = (
            session.query(NewsMention.author)
            .join(NewsIncident, NewsMention.incident_id == NewsIncident.id)
            .filter(NewsIncident.story_id == st.id)
            .all()
        )
        # Identical normalisation to legacy: (a or "").strip(), skip blanks
        sources = {(a or "").strip() for (a,) in rows if (a or "").strip()}
        st.source_count = len(sources)
        st.verified = len(sources) >= STORY_VERIFY_MIN_SOURCES
    session.flush()
