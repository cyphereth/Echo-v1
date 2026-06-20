"""Brand-domain story clustering.

Wires the generic ``core.clustering.cluster_owner`` engine onto the brand ORM
models (BrandMention / BrandIncident / BrandStory / BrandStoryPoint).

Brand stories are LEAN — BrandStory has NO ``verified`` / ``source_count`` /
``credibility`` / ``credibility_note`` columns (dropped in Task 2.1).  So
unlike news/stories.py we do NOT call _recompute_verification.

What we DO keep from legacy radar/stories.py brand path:
  - anomaly detection: ``anomalies.detect_anomaly(session, sid)`` is called
    for every touched story (BrandStory HAS ``is_anomaly``).
  - ``_recompute_points``: story-point bucket rebuild (BrandStoryPoint exists).

What we DROP vs legacy:
  - ``_recompute_verification``: required Story.source_count / Story.verified,
    which were intentionally removed from BrandStory in Task 2.1.

ADDITIVE: legacy radar/stories.py is untouched.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.clustering import cluster_owner
from ..core.domain import DomainModels
from ..core.embeddings import embed as _batch_embed
from .models import BrandMention, BrandIncident, BrandStory, BrandStoryPoint

# ---------------------------------------------------------------------------
# Domain bundle
# ---------------------------------------------------------------------------

_MODELS = DomainModels(
    owner_field="brand_id",
    Mention=BrandMention,
    Incident=BrandIncident,
    Story=BrandStory,
    StoryPoint=BrandStoryPoint,
)


def _default_embed(text: str):
    """Adapt the batch embedder to the per-text signature cluster_owner expects."""
    return _batch_embed([text])[0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_stories(session: Session, brand_id: int, embed=None) -> None:
    """Cluster pending BrandMentions for *brand_id* into incidents/stories.

    Post-clustering steps (brand-faithful):
      - Anomaly detection via core.anomalies.detect_anomaly (BrandStory has
        is_anomaly; legacy brand path ran this).
      - NO verification recompute (BrandStory has no source_count/verified).
    """
    cluster_owner(
        session,
        owner_id=brand_id,
        models=_MODELS,
        embed=embed if embed is not None else _default_embed,
    )
    # Anomaly detection — mirrors legacy brand path in radar/stories.py.
    # We detect on ALL brand stories (not just touched) to keep it simple and
    # consistent; the anomaly detector is idempotent and cheap.
    try:
        from ..core import anomalies
        stories = session.query(BrandStory).filter_by(brand_id=brand_id).all()
        for st in stories:
            anomalies.detect_anomaly(session, st.id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "anomaly detection failed for brand %s (skipped)", brand_id
        )
    session.flush()
