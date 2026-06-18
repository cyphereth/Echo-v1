"""One-off maintenance helpers for news-mode data hygiene."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Topic, Probe, Mention
from .seed import TOPIC_SEED_CHANNELS


def purge_topic_sources(session: Session, topic_id: int | None = None) -> int:
    """Delete non-seed channel probes (the junk discovered by the old keyword
    search) and their mentions, so the source set can be re-seeded cleanly.
    Keeps seed channels, global probes, and web mentions. Returns the number of
    channel probes removed. Idempotent."""
    q = session.query(Topic)
    if topic_id is not None:
        q = q.filter(Topic.id == topic_id)
    removed = 0
    for topic in q.all():
        keep = set(TOPIC_SEED_CHANNELS.get(topic.name, []))
        probes = (session.query(Probe)
                  .filter(Probe.topic_id == topic.id, Probe.platform == "telegram",
                          Probe.kind == "channel").all())
        for p in probes:
            if p.query in keep:
                continue
            # drop this channel's mentions for the topic, then the probe itself
            (session.query(Mention)
             .filter(Mention.topic_id == topic.id, Mention.author == p.query)
             .delete(synchronize_session=False))
            session.delete(p)
            removed += 1
    session.commit()
    return removed
