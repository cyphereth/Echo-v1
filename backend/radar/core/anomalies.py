from __future__ import annotations
import os
from typing import Type

from sqlalchemy.orm import Session

from ..models import Story, StoryPoint

# Tunables (env, calibrate on real brands).
MIN_BUCKETS   = int(os.getenv("ANOMALY_MIN_BUCKETS", "3"))      # baseline buckets required
VOLUME_FACTOR = float(os.getenv("ANOMALY_VOLUME_FACTOR", "3.0"))
MIN_VOLUME    = int(os.getenv("ANOMALY_MIN_VOLUME", "3"))       # absolute floor for a spike
SENT_DROP     = float(os.getenv("ANOMALY_SENT_DROP", "0.4"))    # drop toward negative
SOURCE_FACTOR = float(os.getenv("ANOMALY_SOURCE_FACTOR", "2.0"))


def _mean(xs) -> float:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else 0.0


def detect_anomaly(
    session: Session,
    story_id: int,
    story_model: Type = Story,
    point_model: Type = StoryPoint,
) -> bool:
    """Set story.is_anomaly from its timeline points. Idempotent.

    Trigger = volume spike (required) AND (sentiment drop OR source influx),
    evaluated on the latest bucket vs the mean of all prior buckets. Needs at
    least MIN_BUCKETS prior buckets, else False (no baseline yet).

    ``story_model`` and ``point_model`` default to the legacy Story/StoryPoint so
    the existing ``radar/stories.py`` caller keeps working without modification.
    Pass BrandStory/BrandStoryPoint or NewsStory/NewsStoryPoint to route the same
    logic over domain-specific tables.
    """
    story = session.get(story_model, story_id)
    if story is None:
        return False
    points = (session.query(point_model)
              .filter(point_model.story_id == story_id)
              .order_by(point_model.bucket_start).all())
    result = False
    if len(points) > MIN_BUCKETS:            # need MIN_BUCKETS baseline + 1 current
        last = points[-1]
        base = points[:-1]
        base_vol = _mean([p.mention_count for p in base])
        base_sent = _mean([getattr(p, "avg_sentiment", None) for p in base])
        base_src = _mean([getattr(p, "source_count", None) for p in base])

        spike = (last.mention_count >= MIN_VOLUME and
                 last.mention_count >= base_vol * VOLUME_FACTOR)
        last_sent = getattr(last, "avg_sentiment", None)
        sent_shift = (last_sent is not None and
                      base_sent - last_sent >= SENT_DROP)
        last_src = getattr(last, "source_count", None) or 0
        src_influx = (base_src > 0 and
                      last_src >= base_src * SOURCE_FACTOR)
        result = spike and (sent_shift or src_influx)

    story.is_anomaly = result
    session.flush()
    return result
