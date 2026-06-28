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

from .models import IntelDirection, IntelMention, IntelMentionDirection, IntelProbe
from .geo_match import match_directions

log = logging.getLogger(__name__)

# ── Text constants ─────────────────────────────────────────────────────────────

MIN_TEXT_LEN = 20  # posts shorter than this after stripping #-tokens are noise


# ── Utilities ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _geo_index(session):
    """Build {key: [lowercase terms]} + {key: direction_id} for all non-meta
    directions. Called once per collect_probe pass (~32 directions, cheap)."""
    terms_by_key = {}
    id_by_key = {}
    for d in session.query(IntelDirection).filter(IntelDirection.kind != "meta").all():
        id_by_key[d.key] = d.id
        try:
            terms = json.loads(d.geo_terms or "[]")
        except (ValueError, TypeError):
            terms = []
        if terms:
            terms_by_key[d.key] = [t.lower() for t in terms]
    return terms_by_key, id_by_key


def _write_m2m(session, mention, primary_direction_id, terms_by_key, id_by_key) -> None:
    """Persist IntelMentionDirection rows for a freshly-inserted mention.

    The primary direction is always written with match_type='source' even if it
    also has no geo_terms. Geo-matched directions get match_type='geo'. Dedup
    on (mention_id, direction_id) is enforced by a UNIQUE constraint.
    """
    matched_keys = match_directions(mention.text or "", terms_by_key)
    rows = {primary_direction_id: "source"}
    for key in matched_keys:
        did = id_by_key.get(key)
        if did is not None:
            rows.setdefault(did, "geo")
    for did, mtype in rows.items():
        session.add(IntelMentionDirection(
            mention_id=mention.id, direction_id=did, match_type=mtype))


# ── Core collection ────────────────────────────────────────────────────────────

def collect_probe(session: Session, probe: IntelProbe, provider) -> int:
    """Collect posts for a single IntelProbe and persist them as IntelMention rows.

    - Resolves the probe's IntelDirection; returns 0 if the direction was deleted.
    - Iterates provider.search(query, kind, cursor) pages.
    - Skips posts shorter than MIN_TEXT_LEN after stripping #-tokens.
    - Deduplicates on (platform, post_id) via UNIQUE constraint.
    - Writes m2m rows linking the mention to its source + geo-matched directions.
    - Advances the probe watermark to the first post_id seen.
    - Returns the count of newly stored mentions.
    """
    direction = session.get(IntelDirection, probe.direction_id)
    if direction is None:
        return 0

    # Build geo-term index once per collect pass (cheap; ~32 directions).
    terms_by_key, id_by_key = _geo_index(session)

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
                    _write_m2m(session, mention, probe.direction_id,
                               terms_by_key, id_by_key)
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
