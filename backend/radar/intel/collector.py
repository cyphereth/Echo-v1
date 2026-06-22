"""Intel-domain probe collector.

Lifts the channel-probe branch of radar/news/collector.py and reparameterizes it
against IntelDirection / IntelProbe / IntelMention.  No Scope, no global niche-keyword
gating (intel probes are curated-channel reads — length filter + dedup + watermark only).

Chat probes additionally apply a hard noise filter (chat_message_relevant) before storing.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import IntelLexicon, IntelMention, IntelProbe
from .geo import detect_direction
from .tagging import resolve_direction_id
from ..core.spam import looks_like_ad_cheap

log = logging.getLogger(__name__)

# ── Text constants ─────────────────────────────────────────────────────────────

MIN_TEXT_LEN = 20  # posts shorter than this after stripping #-tokens are noise


# ── Utilities ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_handle(raw: str) -> str:
    """Normalize a stored source link to a Telegram handle the provider can resolve.

    https://t.me/NAME, t.me/NAME, @NAME, NAME -> '@NAME'. Invite links
    (t.me/+HASH or t.me/joinchat/HASH) are returned UNCHANGED (need a join, handled
    separately) — caller detects them via _is_invite_link()."""
    s = (raw or "").strip()
    low = s.lower()
    if "/+" in s or "joinchat" in low:
        return s  # private invite link — leave as-is
    for pre in ("https://", "http://"):
        if low.startswith(pre):
            s = s[len(pre):]
            low = s.lower()
    for pre in ("t.me/", "telegram.me/"):
        if low.startswith(pre):
            s = s[len(pre):]
    s = s.strip("/").lstrip("@").strip()
    return ("@" + s) if s else s


def _is_invite_link(raw: str) -> bool:
    s = (raw or "").lower()
    return "/+" in (raw or "") or "joinchat" in s


def chat_message_relevant(text: str, author: str, lexicon_terms: tuple = ()) -> bool:
    """Return True if a chat message is worth storing as an IntelMention.

    Hard drop conditions (any → False):
    - looks_like_ad_cheap(text, author) — universal spam/seller signal
    - text shorter than MIN_TEXT_LEN after stripping
    - no alphabetic word in the text

    Admit conditions (any → True):
    - detect_direction(text) is not None (geo hit)
    - any lexicon term appears in text (word-boundary, case-insensitive)

    Phase 1: lexicon_terms defaults to empty; Task 5 wires real lexicon.
    """
    stripped = (text or "").strip()

    # Hard drops
    if looks_like_ad_cheap(stripped, author):
        return False
    if len(stripped) < MIN_TEXT_LEN:
        return False
    if not re.search(r"[a-zA-Zа-яА-ЯёЁ]", stripped):
        return False

    # Admit on geo hit
    if detect_direction(stripped) is not None:
        return True

    # Admit on lexicon term (word-boundary, case-insensitive)
    low = stripped.lower()
    for term in lexicon_terms:
        if re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", low):
            return True

    return False


# ── Core collection ────────────────────────────────────────────────────────────

def collect_probe(session: Session, probe: IntelProbe, provider) -> int:
    """Collect posts for a single IntelProbe and persist them as IntelMention rows.

    Channel probes:
    - Iterates provider.search(query, kind, cursor) pages.
    - Skips posts shorter than MIN_TEXT_LEN after stripping #-tokens.

    Chat probes:
    - Calls provider.search_chat(query, term="", limit=50, min_id=...) once (no pagination).
    - Skips messages that fail chat_message_relevant().

    Both branches:
    - Sets direction_id PER POST via geo.detect_direction → tagging.resolve_direction_id
      (defaults to the 'unassigned' bucket). side comes from probe.side.
    - Deduplicates on (platform, post_id) via UNIQUE constraint + begin_nested savepoint.
    - Advances the probe watermark to the first post_id seen.
    - Returns the count of newly stored mentions.
    """
    new_watermark: str | None = None
    count = 0

    try:
        if probe.kind == "chat":
            # Normalize the stored query to a clean @handle (or detect invite links)
            if _is_invite_link(probe.query):
                log.warning("intel chat needs join, skipping: %s", probe.query)
                return 0

            handle = _clean_handle(probe.query)

            # Load lexicon terms once per call (word-boundary matching inside chat_message_relevant)
            lexicon_terms = [t for (t,) in session.query(IntelLexicon.term).all()]

            # Determine min_id from watermark (if it is a numeric string)
            wm = probe.watermark or ""
            min_id = int(wm) if wm.isdigit() else 0

            posts = provider.search_chat(handle, term="", limit=50, min_id=min_id)

            for post in (posts or []):
                if new_watermark is None:
                    new_watermark = post.post_id
                if probe.watermark and post.post_id == probe.watermark:
                    break

                text = post.text or ""
                author = post.author or ""

                # Hard noise filter for chat
                if not chat_message_relevant(text, author, lexicon_terms):
                    continue

                dir_id = resolve_direction_id(session, detect_direction(text))
                mention = IntelMention(
                    direction_id=dir_id,
                    platform=probe.platform,
                    post_id=post.post_id,
                    author=author,
                    side=probe.side,
                    text=text,
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

        else:
            # Channel branch — paginated, light filter only
            handle = _clean_handle(probe.query)
            cursor = None
            found_watermark = False

            while not found_watermark:
                page = provider.search(handle, probe.kind, cursor)
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

                    text = post.text or ""
                    dir_id = resolve_direction_id(session, detect_direction(text))
                    mention = IntelMention(
                        direction_id=dir_id,
                        platform=probe.platform,
                        post_id=post.post_id,
                        author=post.author or "",
                        side=probe.side,
                        text=text,
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
