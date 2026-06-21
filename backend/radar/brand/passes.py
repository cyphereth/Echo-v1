"""Brand-domain scheduler passes.

Extracts the brand-specific pass functions from ``radar/core/scheduler.py`` into
named, testable functions bound to brand models and ``radar.brand.*`` modules.

Functions:
  run_brand_collect(session, tg_provider, provider, bucket_acquire)
      per-probe collection loop (BrandProbe → brand.collector.collect_probe).
  run_brand_pipeline(session, brand_id, provider, tg_provider)
      classify + draft + comment-fetch + story clustering for one brand.
  run_web_pass(session, web_provider)
      web search per auto-collect brand → pipeline → story clustering.
  run_chat_monitor(session, tg_provider, provider)
      Telegram group-chat monitoring per auto-collect brand (worker body).
  run_hotwatch(session, provider, brand_ids, acquire)
      hot-mention re-poll for auto-collect brands.

Semantics (rotation/flood/cap/scheduling) are preserved byte-for-byte from
the legacy implementations in scheduler.py; only the imports are redirected to
brand-domain modules.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence, Callable

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

INTERVAL_HOT    = 300
INTERVAL_NORMAL = 3600
INTERVAL_QUIET  = 7200


def _adaptive_interval(probe, new_mentions: int) -> int:
    """Mirrors adaptive_interval() in scheduler.py: hot/normal/quiet + night multiplier."""
    import random
    from datetime import datetime, timezone
    import os

    NIGHT_START_UTC  = 21
    NIGHT_END_UTC    = 6
    NIGHT_MULTIPLIER = 2.0

    if new_mentions > 5:    interval = INTERVAL_HOT
    elif new_mentions > 0:  interval = INTERVAL_NORMAL
    else:                   interval = INTERVAL_QUIET
    hour = datetime.now(timezone.utc).hour
    if hour >= NIGHT_START_UTC or hour < NIGHT_END_UTC:
        interval = int(interval * NIGHT_MULTIPLIER)
    jitter = random.randint(-int(interval * 0.1), int(interval * 0.1))
    return interval + jitter


def run_brand_collect(
    session,
    tg_provider,
    provider,
    bucket_acquire=None,
) -> set:
    """Per-probe brand collection loop using BrandProbe + brand.collector.collect_probe.

    Migrated from ``Scheduler._run_once`` (the Probe/Brand/legacy-collector block).
    Queries BrandProbe joined to Brand, filters auto_collect + due + not chat kinds,
    calls brand.collector.collect_probe, updates next_run_at via adaptive interval.

    Returns the set of brand_ids that received new mentions this tick so the
    caller can run the pipeline for each.
    """
    from datetime import datetime, timezone, timedelta
    from .models import Brand, BrandProbe
    from .collector import collect_probe

    due = (
        session.query(BrandProbe).join(Brand)
        .filter(
            BrandProbe.next_run_at <= datetime.now(timezone.utc),
            Brand.auto_collect.is_(True),
            BrandProbe.kind.notin_(("chat", "chat_linked")),
        )
        .all()
    )
    touched: set = set()
    for probe in due:
        prov = tg_provider if probe.platform == "telegram" else provider
        if prov is None:
            continue  # telegram probe but TG provider unavailable — skip
        if bucket_acquire is not None:
            bucket_acquire()
        try:
            count = collect_probe(session, probe, prov)
            interval = _adaptive_interval(probe, count)
            probe.next_run_at  = datetime.now(timezone.utc) + timedelta(seconds=interval)
            probe.interval_sec = interval
            session.commit()
            if count:
                touched.add(probe.brand_id)
        except Exception:
            log.exception("BrandProbe %s failed", probe.id)
    return touched


def run_brand_pipeline(
    session: Session,
    brand_id: int,
    provider,
    tg_provider,
) -> None:
    """Classify + draft + comment-fetch + story clustering for one brand.

    Mirrors ``_run_brand_pipeline`` in scheduler.py but uses brand-domain
    modules (radar.brand.pipeline, radar.brand.stories).

    Story clustering is best-effort: failure is logged but does NOT poison
    the classify/draft pipeline (matches legacy behaviour).
    """
    from .pipeline import classify_and_draft, fetch_new_comments
    from .models import Brand
    from . import stories as _stories

    classify_and_draft(session, brand_id)
    fetch_new_comments(session, brand_id, provider, tg_provider)

    try:
        _stories.update_stories(session, brand_id)
    except Exception:
        log.exception(
            "update_stories failed for brand %s (story layer skipped)", brand_id
        )


def run_web_pass(session: Session, web_provider) -> None:
    """Search the web per auto-collect brand and feed results into the pipeline.

    Mirrors ``_run_web_pass`` in scheduler.py but uses brand-domain modules.
    Uses radar.brand.collector.collect_web (brand-native) so results are written
    as BrandMention rows visible to the brand domain (NOT the legacy Mention table).
    """
    from .collector import collect_web  # brand-native; writes BrandMention
    from .pipeline import classify_and_draft
    from .models import Brand
    from . import stories as _stories

    for b in session.query(Brand).filter(Brand.auto_collect.is_(True)).all():
        try:
            n = collect_web(session, b, web_provider)
        except Exception:
            log.exception("collect_web failed for brand %s", b.id)
            continue
        if n:
            try:
                classify_and_draft(session, b.id)
                _stories.update_stories(session, b.id)
            except Exception:
                log.exception("web pipeline failed for brand %s", b.id)


def run_chat_monitor(session: Session, tg_provider, provider) -> None:
    """Telegram group-chat monitoring pass (worker body) for auto-collect brands.

    Mirrors the body of ``_collect_chats_worker`` in scheduler.py:
      - ensure_chats_discovered per brand
      - collect_chats per brand
      - if new messages: run_brand_pipeline

    MAX_CHATS_PER_RUN and flood-control semantics are delegated to the
    brand-domain collector (collect_chats uses its own cap internally).
    """
    from .collector import ensure_chats_discovered, collect_chats
    from .models import Brand

    brands = session.query(Brand).filter(Brand.auto_collect.is_(True)).all()
    for b in brands:
        try:
            ensure_chats_discovered(session, b, tg_provider)
            n = collect_chats(session, b, tg_provider)
            if n:
                run_brand_pipeline(session, b.id, provider, tg_provider)
                log.info(
                    "Chat monitor: %d new niche message(s) for brand %s", n, b.id
                )
        except Exception:
            log.exception("chat monitor failed for brand %s", b.id)


def run_hotwatch(
    session: Session,
    provider,
    brand_ids: Optional[Sequence[int]] = None,
    acquire: Optional[Callable[[], None]] = None,
) -> None:
    """Re-poll hot BrandMentions and rescore them.

    Mirrors ``_maybe_hotwatch`` in scheduler.py:
      - scoped to auto-collect brands (brand_ids list from caller)
      - acquire token-bucket slot before each API call

    Returns nothing; logs count internally.
    """
    from .hotwatch import hotwatch_tick

    try:
        n = hotwatch_tick(session, provider, brand_ids=brand_ids, acquire=acquire)
        if n:
            log.info("Hot-watch re-polled %d brand mention(s)", n)
    except Exception:
        log.exception("Hot-watch tick failed")
