"""News-domain source discovery and maintenance.

Lifts ensure_topic_channels_discovered, ensure_topic_global_probe, classify_source
from radar/collector.py, and purge_topic_sources from radar/maintenance.py.
Reparameterized against NewsTopic / NewsProbe / NewsMention.
No Scope, no brand-only concepts.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from ..news.collector import _term_hit  # shared helper — already in this package
from .models import NewsMention, NewsProbe, NewsTopic
from ..seed import TOPIC_SEED_CHANNELS

log = logging.getLogger(__name__)

TOPIC_RECS_PER_SEED = int(os.getenv("TOPIC_RECS_PER_SEED", "5"))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _topic_terms(topic: NewsTopic) -> list[str]:
    terms = topic.keywords_list() + topic.niche_keywords_list() + [topic.name]
    return [t.lower() for t in terms if t]


def _seed_handles_for(topic: NewsTopic) -> list[str]:
    return TOPIC_SEED_CHANNELS.get(topic.name, [])


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


# ── Public API ────────────────────────────────────────────────────────────────

def classify_source(title: str, topic: NewsTopic) -> bool:
    """LLM yes/no gate: is this a NEWS channel about the topic?
    Degrades to the title term-hit filter when no LLM key is configured."""
    try:
        from radar import llm  # type: ignore[import]
        ans = llm.complete(
            "Ты — фильтр новостных источников. Ответь РОВНО одним словом: YES или NO.",
            f"Тема: {topic.name} (ключевые слова: {', '.join(topic.keywords_list()[:6])}).\n"
            f"Название Telegram-канала: «{title}».\n"
            f"Это новостной канал по этой теме? NO, если это реклама, психология, "
            f"мотивация, боты курсов валют, личный блог, торговые сигналы или не по теме.",
            max_tokens=5,
        )
        return ans.strip().upper().startswith("Y")
    except Exception:
        # LLMNotConfigured or any import error → degrade to term-hit
        return _term_hit(title, _topic_terms(topic))


def ensure_topic_global_probe(session: Session, topic: NewsTopic) -> None:
    """Idempotently ensure one global-search Telegram probe exists for the topic."""
    exists = (session.query(NewsProbe)
              .filter(NewsProbe.topic_id == topic.id,
                      NewsProbe.platform == "telegram",
                      NewsProbe.kind == "global").first())
    if exists is not None:
        return
    session.add(NewsProbe(
        topic_id=topic.id, platform="telegram", kind="global",
        query=(topic.keywords_list() or [topic.name])[0],
        label="global", next_run_at=_now(), interval_sec=3600,
    ))
    session.commit()


def ensure_topic_channels_discovered(
    session: Session,
    topic: NewsTopic,
    provider,
    min_chan: int = 6,
    max_add: int = 30,
) -> int:
    """Hybrid source discovery for a topic:
      1. Add vetted seed channels (no gate).
      2. If still below min_chan, grow via 'similar channels' off the seeds.
      3. For seed-less topics, fall back to keyword discovery, LLM-gated by title.
    Idempotent; fail-open per provider call.
    """
    existing = (session.query(NewsProbe)
                .filter(NewsProbe.topic_id == topic.id,
                        NewsProbe.platform == "telegram",
                        NewsProbe.kind == "channel").all())
    seen = {p.query for p in existing}
    added = 0

    def _add(handle: str, label: str) -> None:
        nonlocal added
        if handle and handle not in seen and added < max_add:
            seen.add(handle)
            session.add(NewsProbe(
                topic_id=topic.id, platform="telegram", kind="channel",
                query=handle, label=(label or "")[:120],
                next_run_at=_now(), interval_sec=3600,
            ))
            added += 1

    # 1. Vetted seeds — always ensure present, no gate.
    seeds = _seed_handles_for(topic)
    for h in seeds:
        _add(h, "seed")

    # 2/3. Grow only if still thin.
    if len(existing) + added < min_chan:
        if seeds and hasattr(provider, "channel_recommendations"):
            # Similar-to-vetted: news-adjacent, bounded, no title to gate on → trust.
            for h in seeds:
                try:
                    for rec in provider.channel_recommendations(h, limit=TOPIC_RECS_PER_SEED):
                        _add(rec, "similar")
                except Exception:
                    log.warning("channel_recommendations failed for %s", h)
        elif not seeds and hasattr(provider, "discover_channels"):
            # Seed-less (user) topic: keyword discovery, LLM-gated by title.
            for kw in topic.keywords_list()[:4]:
                try:
                    for c in provider.discover_channels(kw, limit=20):
                        if classify_source(c.get("title", ""), topic):
                            _add(c.get("handle"), c.get("title", ""))
                except Exception:
                    log.warning("discover_channels failed for topic %s kw %r", topic.id, kw)

    session.commit()
    return added


def purge_topic_sources(session: Session, topic_id: int | None = None) -> int:
    """Delete non-seed channel NewsProbes and their NewsMentions, so the source set
    can be re-seeded cleanly.  Keeps seed channels, global probes, and any web
    mentions.  Returns the number of channel probes removed.  Idempotent."""
    q = session.query(NewsTopic)
    if topic_id is not None:
        q = q.filter(NewsTopic.id == topic_id)
    removed = 0
    for topic in q.all():
        keep = set(TOPIC_SEED_CHANNELS.get(topic.name, []))
        probes = (session.query(NewsProbe)
                  .filter(NewsProbe.topic_id == topic.id,
                          NewsProbe.platform == "telegram",
                          NewsProbe.kind == "channel").all())
        for p in probes:
            if p.query in keep:
                continue
            # Drop this channel's mentions for the topic, then the probe itself.
            (session.query(NewsMention)
             .filter(NewsMention.topic_id == topic.id,
                     NewsMention.author == p.query)
             .delete(synchronize_session=False))
            session.delete(p)
            removed += 1
    session.commit()
    return removed
