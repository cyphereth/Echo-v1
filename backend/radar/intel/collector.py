"""Intel-domain probe collector.

Lifts the channel-probe branch of radar/news/collector.py and reparameterizes it
against IntelDirection / IntelProbe / IntelMention.  No Scope, no global niche-keyword
gating (intel probes are curated-channel reads — length filter + dedup + watermark only).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import IntelDirection, IntelMention, IntelProbe

log = logging.getLogger(__name__)

# ── Text constants ─────────────────────────────────────────────────────────────

MIN_TEXT_LEN = 20  # posts shorter than this after stripping #-tokens are noise


# ── Utilities ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Core collection ────────────────────────────────────────────────────────────

def collect_probe(session: Session, probe: IntelProbe, provider) -> int:
    """Collect posts for a single IntelProbe and persist them as IntelMention rows.

    - Resolves the probe's IntelDirection; returns 0 if the direction was deleted.
    - Iterates provider.search(query, kind, cursor) pages.
    - Skips posts shorter than MIN_TEXT_LEN after stripping #-tokens.
    - Deduplicates on (platform, post_id) via UNIQUE constraint.
    - Advances the probe watermark to the first post_id seen.
    - Returns the count of newly stored mentions.
    """
    direction = session.get(IntelDirection, probe.direction_id)
    if direction is None:
        return 0

    new_watermark: str | None = None
    count = 0
    cursor = None
    found_watermark = False

    try:
        while not found_watermark:
            page = provider.search(probe.query, probe.kind, cursor)
            if not page.posts:
                break
            for post in page.posts:
                # Record the first post_id seen — this becomes the new watermark.
                if new_watermark is None:
                    new_watermark = post.post_id
                # Stop if we've caught up to the last-seen watermark.
                if probe.watermark and post.post_id == probe.watermark:
                    found_watermark = True
                    break

                # Length gate — drop media-only/very-short posts.
                clean = " ".join(
                    w for w in (post.text or "").split()
                    if not w.startswith("#")
                ).strip()
                if len(clean) < MIN_TEXT_LEN:
                    continue

                # Dedup insert via (platform, post_id) UNIQUE constraint.
                mention = IntelMention(
                    direction_id=probe.direction_id,
                    platform=probe.platform,
                    post_id=post.post_id,
                    author=post.author or "",
                    side=probe.side,
                    text=post.text or "",
                    url=getattr(post, "url", None),
                    views=getattr(post, "likes", 0) or 0,
                    created_at=post.created_at,
                )
                sp = session.begin_nested()
                try:
                    session.add(mention)
                    session.flush()
                    sp.commit()
                    count += 1
                except IntegrityError:
                    sp.rollback()
                    # Post already stored — skip, but keep going.

            next_cursor = getattr(page, "next_cursor", None) or getattr(page, "cursor", None)
            if next_cursor is None:
                break
            cursor = next_cursor

        if new_watermark:
            probe.watermark = new_watermark
        probe.next_run_at = _now()
        session.commit()

    except Exception:
        session.rollback()
        log.exception("IntelProbe %s failed — watermark NOT moved", probe.id)
        raise

    return count
