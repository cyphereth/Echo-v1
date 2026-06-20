"""Brand-domain scheduler passes.

Extracts the brand-specific pass functions from ``radar/core/scheduler.py`` into
named, testable functions bound to brand models and ``radar.brand.*`` modules.

Functions:
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

ADDITIVE: legacy radar/core/scheduler.py is untouched until Phase 5.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence, Callable

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


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
    Uses radar.collector.collect_web (the legacy shared web collector) since
    test_web.py patches it at that path.
    """
    from ..collector import collect_web  # legacy shared; test patches here
    from .pipeline import classify_and_draft
    from .models import Brand
    from . import stories as _stories
    from ..scope import scope_for_brand

    for b in session.query(Brand).filter(Brand.auto_collect.is_(True)).all():
        try:
            scope = scope_for_brand(b)
            n = collect_web(session, scope, web_provider)
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
