"""Intel-domain probe collector.

Lifts the channel-probe branch of radar/news/collector.py and reparameterizes it
against IntelDirection / IntelProbe / IntelMention.  No Scope, no global niche-keyword
gating (intel probes are curated-channel reads — length filter + dedup + watermark only).

Chat probes additionally apply a hard noise filter (chat_message_relevant) before storing.

After every stored mention, writes m2m rows (IntelMentionDirection) tagging the
post with ALL directions whose geo_terms match the text (plus the source/probe
direction). This powers the multi-column Feed v2.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (IntelDirection, IntelLexicon, IntelMention,
                     IntelMentionDirection, IntelProbe)
from .geo import detect_direction
from .tagging import resolve_direction_id, tag_geo
from .translate import maybe_translate
from .spam_filter import load_spam, load_keywords, blocked_by_word, classify_spam_batch, is_exact_spam
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


# Uppercase military abbreviations from the curator's glossary. Matched
# CASE-SENSITIVELY (the UPPERCASE form only) at word boundaries: their lowercase forms
# collide with ordinary Russian words — above all "ТА" (тактическая авиация) vs the
# pronoun "та", and "АА" vs an interjection. War channels always write these in caps,
# so requiring caps is both faithful to the source and false-positive-proof. Kept in
# code (not the lowercased word-lexicon) precisely so they never match in lowercase.
ABBREVIATIONS = {
    "МРШ":  "малоразмерный шар / аэростат",
    "БПЛА": "беспилотный летательный аппарат",
    "БЭК":  "безэкипажный катер",
    "КР":   "крылатая ракета",
    "ПКР":  "противокорабельная ракета (применяется и по суше)",
    "КРВБ": "крылатая ракета воздушного (авиационного) базирования",
    "ПРР":  "противорадиолокационная ракета",
    "УАБ":  "управляемая авиационная бомба",
    "РСЗО": "реактивная система залпового огня",
    "ОТРК": "оперативно-тактический ракетный комплекс (баллистика)",
    "ТА":   "тактическая авиация",
    "АА":   "армейская авиация",
}
# Longer abbreviations first so the alternation prefers КРВБ over КР, ПКР over КР, etc.
_ABBREV_RE = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(a) for a in sorted(ABBREVIATIONS, key=len, reverse=True)) + r")(?!\w)"
)


def matched_terms(text: str, lexicon_tiers) -> list[tuple[str, str]]:
    """(term, tier) pairs appearing in text at a word boundary.

    Two passes: (1) the word-lexicon (mapping term→tier), lowercased/case-insensitive;
    (2) the uppercase ABBREVIATIONS, matched case-sensitively against the ORIGINAL text
    and always tier "strong" (they are narrow military markers).
    """
    raw = (text or "").strip()
    low = raw.lower()
    out: list[tuple[str, str]] = []
    for term, tier in dict(lexicon_tiers).items():
        if re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", low):
            out.append((term.lower(), tier or "weak"))
    for ab in _ABBREV_RE.findall(raw):
        out.append((ab, "strong"))
    return out


def _looks_like_weather(text: str) -> bool:
    low = (text or "").lower()
    return any(ctx in low for ctx in _WEATHER_CONTEXT)


def keyword_relevant(text: str, lexicon_tiers, geo_hit: bool = False) -> bool:
    """Return True if text passes the tiered admission rule.

    Rule: 1 strong OR 2+ weak OR (1 weak + geo_hit). KEYWORD-ONLY: geo alone is NOT an
    admit path — geo only PROMOTES a single weak hit (geo_hit is computed by the caller
    via detect_place). The ``lexicon_tiers`` mapping is loaded once per collect_probe.

    Weather false-positive guard: if every matched term is an ambiguous weather word
    (град/смерч/торнадо) AND the text reads like a weather report, drop it.
    """
    hits = matched_terms(text, lexicon_tiers)
    if not hits:
        return False
    non_weather = [t for (t, _tier) in hits if t not in AMBIGUOUS_WEATHER_TERMS]
    if not non_weather and _looks_like_weather(text):
        return False
    strong = [t for (t, tier) in hits if tier == "strong"]
    weak = [t for (t, tier) in hits if tier == "weak"]
    if strong:
        return True
    if len(weak) >= 2:
        return True
    if len(weak) == 1 and geo_hit:
        return True
    return False


def load_lexicon_tiers(session) -> dict[str, str]:
    """Term→tier map for the admission gate. One query, loaded once per collect cycle."""
    from .models import IntelLexicon
    return {
        (t or "").lower(): (tier or "weak")
        for (t, tier) in session.query(IntelLexicon.term, IntelLexicon.tier).all()
    }


def _geo_hit(text: str) -> bool:
    """True if the text names any tracked oblast/city (promotes a single weak hit)."""
    from .geo import detect_place
    key, city = detect_place(text)
    return bool(key or city)


def chat_message_relevant(text: str, author: str, lexicon_tiers=(),
                          keywords: tuple = (), geo_hit: bool = False) -> bool:
    """Return True if a chat message is worth storing as an IntelMention.

    Hard drop conditions (any → False):
    - looks_like_ad_cheap(text, author) — universal spam/seller signal
    - text shorter than MIN_TEXT_LEN after stripping
    - no alphabetic word in the text

    Admit: military lexicon term (keyword_relevant, weather-guarded) OR a curator-managed
    positive keyword (``keywords``). A curator-keyword hit is an explicit signal, so it
    BYPASSES the length gate (replies/comments are usually short — that's why keywords
    "didn't work for replies"); the ad and alphabetic guards still win regardless.
    """
    stripped = (text or "").strip()

    # Explicit curator-keyword hit — strong signal, overrides the length noise-gate.
    kw_hit = blocked_by_word(stripped, keywords)

    # Hard drops (apply even to keyword hits — sellers/empty text are never wanted).
    # looks_like_ad_cheap also drops anything shorter than its own min_len; on a keyword
    # hit we pass min_len=0 so only the seller-name guard remains (short reply admitted).
    if kw_hit:
        if looks_like_ad_cheap(stripped, author, min_len=0):
            return False
    elif looks_like_ad_cheap(stripped, author):
        return False
    if not re.search(r"[a-zA-Zа-яА-ЯёЁ]", stripped):
        return False
    if not kw_hit and len(stripped) < MIN_TEXT_LEN:
        return False

    return kw_hit or keyword_relevant(stripped, lexicon_tiers, geo_hit=geo_hit)


# ── Feed v2 — m2m direction tagging ──────────────────────────────────────────

def _write_m2m_for_mention(session, mention) -> None:
    """Tag a freshly-flushed mention with ALL directions whose geo_terms match
    its text (plus its own direction_id as 'source'). Powers the multi-column
    Feed v2: one post can appear in several direction columns at once.

    Cheap: ~32 directions, terms loaded once per process via module-level cache.
    Dedup on (mention_id, direction_id) is enforced by UNIQUE constraint.
    """
    if mention.direction_id is None:
        return
    from .geo_match import match_directions
    text = mention.text or ""
    # Build the index once and cache it on the function. Invalidate when the
    # max direction id changes (seed ran / custom direction added) — cheap check.
    max_id = (session.query(IntelDirection.id).order_by(IntelDirection.id.desc()).first() or (0,))[0]
    cache = getattr(_write_m2m_for_mention, "_cache", None)
    if cache is None or cache[2] != max_id:
        terms_by_key, id_by_key = {}, {}
        for d in session.query(IntelDirection).filter(IntelDirection.kind != "meta").all():
            id_by_key[d.key] = d.id
            try:
                terms = json.loads(getattr(d, "geo_terms", None) or "[]")
            except (ValueError, TypeError):
                terms = []
            if terms:
                terms_by_key[d.key] = [t.lower() for t in terms]
        cache = (terms_by_key, id_by_key, max_id)
        _write_m2m_for_mention._cache = cache
    terms_by_key, id_by_key, _ = cache
    matched_keys = match_directions(text, terms_by_key)
    rows = {mention.direction_id: "source"}
    for key in matched_keys:
        did = id_by_key.get(key)
        if did is not None:
            rows.setdefault(did, "geo")
    for did, mtype in rows.items():
        session.add(IntelMentionDirection(
            mention_id=mention.id, direction_id=did, match_type=mtype))


# ── Spam-filter store helper ─────────────────────────────────────────────────

def _filter_and_store(session: Session, pending: list, examples: list) -> int:
    """Apply the LLM example-comparison layer to buffered mentions, then persist the
    survivors. `pending` is a list of unsaved IntelMention objects (already past the
    stop-word layer). Spam-flagged mentions are never written. Returns stored count."""
    if not pending:
        return 0
    flags = classify_spam_batch([m.text for m in pending], examples)
    count = 0
    for mention, is_spam in zip(pending, flags):
        # Дословный дубль примера-мусора дропаем всегда — даже если LLM-слой отключён
        # (нет ключа) и вернул False. Идентичный спам не должен попасть в БД.
        if is_spam or is_exact_spam(mention.text, examples):
            continue
        sp = session.begin_nested()
        try:
            session.add(mention)
            session.flush()
            _write_m2m_for_mention(session, mention)
            sp.commit()
            count += 1
        except IntegrityError:
            sp.rollback()  # already stored — skip, keep going
    return count


# ── Core collection ────────────────────────────────────────────────────────────

def collect_probe(session: Session, probe: IntelProbe, provider) -> int:
    """Collect posts for a single IntelProbe and persist them as IntelMention rows.

    Channel probes:
    - Iterates provider.search(query, kind, cursor) pages.

    Chat probes:
    - Calls provider.search_chat(query, term="", limit=50, min_id=...) once (no pagination).
    - Skips messages that fail chat_message_relevant().

    Both branches:
    - Sets direction_id PER POST via geo.detect_direction → tagging.resolve_direction_id
      (defaults to the 'unassigned' bucket). side comes from probe.side.
    - Deduplicates on (platform, post_id) via UNIQUE constraint + begin_nested savepoint.
    - Writes m2m rows linking the mention to its source probe direction + every
      geo-matched direction (powers the multi-column Feed v2).
    - Advances the probe watermark to the first post_id seen.
    - Returns the count of newly stored mentions.
    """
    new_watermark: str | None = None
    count = 0

    try:
        # Load lexicon tiers once per call — shared by both channel and chat branches.
        # Word-boundary matching is done inside keyword_relevant / chat_message_relevant.
        lexicon_tiers = load_lexicon_tiers(session)
        if not lexicon_tiers:
            log.warning("intel lexicon is empty — channel posts kept only on geo match (run lexicon seed)")

        # Spam filter: stop-words (fast layer) + examples (LLM layer). Loaded once.
        blocklist, spam_examples = load_spam(session)
        # Positive admission keywords (curator-managed) — OR'd into the lexicon gate.
        keywords = load_keywords(session)
        pending: list[IntelMention] = []

        if probe.kind == "chat":
            # After _ensure_joined() in passes.py the session is already a member.
            # For invite links the handle is the link itself (provider resolves it).
            handle = probe.query if _is_invite_link(probe.query) else _clean_handle(probe.query)

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

                text = maybe_translate(post.text or "")
                author = post.author or ""

                # Hard noise filter for chat
                if not chat_message_relevant(text, author, lexicon_tiers, keywords,
                                             geo_hit=_geo_hit(text)):
                    continue

                # Spam stop-word layer (fast, deterministic)
                if blocked_by_word(text, blocklist):
                    continue

                dir_id, subject = tag_geo(session, probe, text)
                pending.append(IntelMention(
                    direction_id=dir_id,
                    subject=subject,
                    platform=probe.platform,
                    post_id=post.post_id,
                    author=author,
                    side=probe.side,
                    text=text,
                    url=getattr(post, "url", None),
                    views=getattr(post, "likes", 0) or 0,
                    created_at=post.created_at,
                    reply_to_tg_id=getattr(post, "reply_to_tg_id", None),
                    media=getattr(post, "media", None),
                ))

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

                    # Keyword relevance gate — keep posts that hit the military lexicon
                    # OR a curator-managed positive keyword (geo is for tagging, not admit).
                    text = maybe_translate(post.text or "")
                    kw_hit = blocked_by_word(text, keywords)

                    # Length gate — drop media-only/very-short posts, UNLESS a curator
                    # keyword matched (explicit signal overrides the length noise-gate;
                    # short replies/comments are why keywords "didn't work for replies").
                    if not kw_hit:
                        clean = " ".join(
                            w for w in (post.text or "").split()
                            if not w.startswith("#")
                        ).strip()
                        if len(clean) < MIN_TEXT_LEN:
                            continue
                        if not keyword_relevant(text, lexicon_tiers, geo_hit=_geo_hit(text)):
                            continue

                    # Spam stop-word layer (fast, deterministic)
                    if blocked_by_word(text, blocklist):
                        continue

                    dir_id, subject = tag_geo(session, probe, text)
                    pending.append(IntelMention(
                        direction_id=dir_id,
                        subject=subject,
                        platform=probe.platform,
                        post_id=post.post_id,
                        author=post.author or "",
                        side=probe.side,
                        text=text,
                        url=getattr(post, "url", None),
                        views=getattr(post, "likes", 0) or 0,
                        created_at=post.created_at,
                        media=getattr(post, "media", None),
                    ))

                next_cursor = getattr(page, "next_cursor", None) or getattr(page, "cursor", None)
                if next_cursor is None:
                    break
                cursor = next_cursor

        # Spam example-comparison layer (LLM, fail-open) over buffered survivors,
        # then persist the non-spam ones. Spam is never written to the DB.
        count = _filter_and_store(session, pending, spam_examples)

        if new_watermark:
            probe.watermark = new_watermark
        probe.next_run_at = _now()
        session.commit()

    except Exception:
        session.rollback()
        log.exception("IntelProbe %s failed — watermark NOT moved", probe.id)
        raise

    return count
