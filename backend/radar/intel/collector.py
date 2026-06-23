"""Intel-domain probe collector.

Lifts the channel-probe branch of radar/news/collector.py and reparameterizes it
against IntelDirection / IntelProbe / IntelMention.  No Scope, no global niche-keyword
gating (intel probes are curated-channel reads — length filter + dedup + watermark only).

Chat probes additionally apply a hard noise filter (chat_message_relevant) before storing.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import IntelLexicon, IntelMention, IntelProbe
from .geo import detect_direction
from .tagging import resolve_direction_id
from ..core.spam import looks_like_ad_cheap

log = logging.getLogger(__name__)

# ── Text constants ─────────────────────────────────────────────────────────────

MIN_TEXT_LEN = 20  # posts shorter than this after stripping #-tokens are noise

# Time window: collect only RECENT posts. On the FIRST collection a probe has no
# watermark, so without a cutoff the loop would paginate the channel's entire history
# (connection drops + unmanageable clustering). Channels return newest-first, so once
# we hit a post older than the window we stop. Live intelligence wants fresh news only.
INTEL_COLLECT_WINDOW_HOURS = int(os.getenv("INTEL_COLLECT_WINDOW_HOURS", "36"))

# Hard safety cap on posts per source per tick (guards a hyper-active channel that
# posts thousands within the time window). Time window is the primary control.
MAX_POSTS_PER_SOURCE = int(os.getenv("MAX_POSTS_PER_SOURCE", "300"))


def _aware(dt):
    """Return dt as a tz-aware UTC datetime (treat naive as UTC)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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


# Ambiguous lexicon terms: real military hardware in the user's list, but also
# everyday weather words. A post whose ONLY keyword hits are these and that reads
# like a weather report is dropped (false-positive guard). Geo is NOT an admit path.
AMBIGUOUS_WEATHER_TERMS = {"град", "смерч", "торнадо"}
_WEATHER_CONTEXT = (
    "погод", "синоптик", "метеор", "прогноз", "осадк", "ливень", "ливн",
    "температур", "градус", "гроза", "грозов", "дожд", "снегопад", "снег ",
    "облачн", "потепл", "похолод", "циклон", "антициклон", "штормовое предупрежд",
)


def matched_terms(text: str, lexicon_terms) -> list[str]:
    """Lexicon terms appearing in text at a word boundary (lowercased, case-insensitive)."""
    low = (text or "").strip().lower()
    out = []
    for term in lexicon_terms:
        if re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", low):
            out.append(term.lower())
    return out


def _looks_like_weather(text: str) -> bool:
    low = (text or "").lower()
    return any(ctx in low for ctx in _WEATHER_CONTEXT)


def keyword_relevant(text: str, lexicon_terms) -> bool:
    """Return True if text contains a military lexicon term.

    KEYWORD-ONLY: a geo-direction match is NOT an admit path (detect_direction is used
    solely for direction TAGGING elsewhere). The ``lexicon_terms`` iterable is loaded
    once per :func:`collect_probe` call — no per-message DB queries.

    Weather false-positive guard: if every matched term is an ambiguous weather word
    (град/смерч/торнадо) AND the text reads like a weather report, drop it.
    """
    hits = matched_terms(text, lexicon_terms)
    if not hits:
        return False
    non_ambiguous = [t for t in hits if t not in AMBIGUOUS_WEATHER_TERMS]
    if not non_ambiguous and _looks_like_weather(text):
        return False
    return True


def chat_message_relevant(text: str, author: str, lexicon_terms: tuple = ()) -> bool:
    """Return True if a chat message is worth storing as an IntelMention.

    Hard drop conditions (any → False):
    - looks_like_ad_cheap(text, author) — universal spam/seller signal
    - text shorter than MIN_TEXT_LEN after stripping
    - no alphabetic word in the text

    Admit: delegated to keyword_relevant (military keyword present, weather-guarded).
    """
    stripped = (text or "").strip()

    # Hard drops
    if looks_like_ad_cheap(stripped, author):
        return False
    if len(stripped) < MIN_TEXT_LEN:
        return False
    if not re.search(r"[a-zA-Zа-яА-ЯёЁ]", stripped):
        return False

    return keyword_relevant(stripped, lexicon_terms)


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
        # Load lexicon terms once per call — shared by both channel and chat branches.
        # Word-boundary matching is done inside keyword_relevant / chat_message_relevant.
        lexicon_terms = [t for (t,) in session.query(IntelLexicon.term).all()]
        if not lexicon_terms:
            log.warning("intel lexicon is empty — channel posts kept only on geo match (run lexicon seed)")

        if probe.kind == "chat":
            # Normalize the stored query to a clean @handle (or detect invite links)
            if _is_invite_link(probe.query):
                log.warning("intel chat needs join, skipping: %s", probe.query)
                return 0

            handle = _clean_handle(probe.query)

            # Determine min_id from watermark (if it is a numeric string)
            wm = probe.watermark or ""
            min_id = int(wm) if wm.isdigit() else 0

            posts = provider.search_chat(handle, term="", limit=50, min_id=min_id)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=INTEL_COLLECT_WINDOW_HOURS)

            for post in (posts or []):
                if new_watermark is None:
                    new_watermark = post.post_id
                if probe.watermark and post.post_id == probe.watermark:
                    break

                # Time window — skip messages older than the window.
                created = _aware(post.created_at)
                if created is not None and created < cutoff:
                    continue

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
            seen = 0
            cutoff = datetime.now(timezone.utc) - timedelta(hours=INTEL_COLLECT_WINDOW_HOURS)

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
                    # Time window — posts are newest-first, so once one is older than the
                    # window, everything after it is too. Stop. (Primary volume control.)
                    created = _aware(post.created_at)
                    if created is not None and created < cutoff:
                        found_watermark = True
                        break
                    # Hard safety cap (guards a hyper-active channel within the window).
                    seen += 1
                    if seen > MAX_POSTS_PER_SOURCE:
                        found_watermark = True
                        break

                    # Length gate — drop media-only/very-short posts.
                    clean = " ".join(
                        w for w in (post.text or "").split()
                        if not w.startswith("#")
                    ).strip()
                    if len(clean) < MIN_TEXT_LEN:
                        continue

                    # Keyword relevance gate — keep only military-relevant posts
                    # (geo is used for tagging below, not as an admit path).
                    text = post.text or ""
                    if not keyword_relevant(text, lexicon_terms):
                        continue

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
