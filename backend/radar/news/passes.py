"""News-domain scheduler passes.

Ports _run_topic_tg_pass and _run_topic_web_pass from radar/core/scheduler.py
into functions that operate exclusively on news-domain models (NewsTopic /
NewsProbe) via radar.news.collector / sources / stories.

ADDITIVE: the legacy scheduler.py functions are NOT removed here; core/scheduler.py
is updated separately to call these functions instead of the inline bodies.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import NewsTopic, NewsProbe
from .collector import collect_probe, collect_web
from .sources import ensure_topic_channels_discovered, ensure_topic_global_probe
from .stories import update_stories  # update_stories(session, topic_id)

log = logging.getLogger(__name__)

# Per-pass cap on channel reads per topic — least-recently-run first, rest rotate
# in on later passes. Keeps a topic with dozens of channels from bursting into a
# flood-wait every cycle (mirrors MAX_CHATS_PER_RUN for brand chats).
MAX_TOPIC_CHANNELS_PER_RUN = int(os.getenv("MAX_TOPIC_CHANNELS_PER_RUN", "8"))


def run_topic_tg_pass(session: Session, tg_provider) -> None:
    """Discover + collect Telegram for each auto-collect NewsTopic, then cluster into
    NewsStories. Global search + public-channel reads only (no joining). Best-effort.

    Flood control: no discovery fan-out, channel reads capped + rotated per pass,
    and a flood-wait aborts the whole cycle (don't keep hammering a limited account).
    """
    if tg_provider is None:
        return
    from ..core.providers.telegram import TelegramFloodWait
    for t in session.query(NewsTopic).filter(NewsTopic.auto_collect.is_(True)).all():
        try:
            ensure_topic_channels_discovered(session, t, tg_provider)
            ensure_topic_global_probe(session, t)
        except TelegramFloodWait as e:
            log.warning("topic TG pass: flood wait %ss during discovery — aborting cycle", e.seconds)
            return
        except Exception:
            log.exception("topic TG discovery failed for topic %s", t.id)
        # One global probe (cheap) + the least-recently-run channel probes, capped.
        gprobes = (session.query(NewsProbe)
                   .filter(NewsProbe.topic_id == t.id, NewsProbe.platform == "telegram",
                           NewsProbe.kind == "global").all())
        cprobes = (session.query(NewsProbe)
                   .filter(NewsProbe.topic_id == t.id, NewsProbe.platform == "telegram",
                           NewsProbe.kind == "channel")
                   .order_by(NewsProbe.next_run_at.asc())
                   .limit(MAX_TOPIC_CHANNELS_PER_RUN).all())
        for probe in gprobes + cprobes:
            try:
                collect_probe(session, probe, tg_provider)
            except TelegramFloodWait as e:
                log.warning("topic TG pass: flood wait %ss — aborting cycle", e.seconds)
                return
            except Exception:
                log.exception("collect_probe failed for news probe %s", probe.id)
            # Push to the back of the rotation regardless of outcome.
            probe.next_run_at = datetime.now(timezone.utc) + timedelta(
                seconds=probe.interval_sec or 3600
            )
        session.commit()
        # update_stories returns early when there are no new mentions, so calling
        # it unconditionally is cheap and keeps the pass simple.
        try:
            update_stories(session, t.id)
        except Exception:
            log.exception("topic TG clustering failed for topic %s", t.id)


def run_topic_web_pass(session: Session, web_provider) -> None:
    """Search the web per auto-collect NewsTopic and cluster results into NewsStories.

    News-mode counterpart of the brand web pass: topics have no brand and no
    reply-drafting pipeline, so we only collect + cluster (no classify_and_draft).
    """
    for t in session.query(NewsTopic).filter(NewsTopic.auto_collect.is_(True)).all():
        try:
            n = collect_web(session, t.id, web_provider)
        except Exception:
            log.exception("collect_web failed for news topic %s", t.id)
            continue
        if n:
            try:
                update_stories(session, t.id)
            except Exception:
                log.exception("topic web clustering failed for topic %s", t.id)
