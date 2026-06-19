"""News-domain probe collector.

Lifts the TOPIC branch of radar/collector.py::collect_probe and reparameterizes it
against NewsTopic / NewsProbe / NewsMention.  No Scope, no brand-only concepts.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import NewsMention, NewsProbe, NewsTopic

log = logging.getLogger(__name__)

# ── Text constants (same as legacy radar/collector.py) ───────────────────────

MIN_TEXT_LEN = 20  # posts shorter than this after stripping #-tokens are noise

# ── Morphology helpers (copied from radar/collector.py for isolation) ─────────

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _load_morph():
    for mod in ("pymorphy2", "pymorphy3"):
        try:
            return __import__(mod).MorphAnalyzer()
        except Exception:
            continue
    log.info("pymorphy not available — term matching falls back to exact word match")
    return None


_MORPH = _load_morph()


@lru_cache(maxsize=50_000)
def _lemma(word: str) -> str:
    if _MORPH is None:
        return word
    try:
        return _MORPH.parse(word)[0].normal_form
    except Exception:
        return word


def _lemmas(text: str) -> set[str]:
    return {_lemma(w) for w in _WORD_RE.findall(text.lower())}


def _word_in(text: str, term: str) -> bool:
    """Whole-word (boundary) match of `term` within `text` (both already lowercased).
    Word boundaries avoid substring collisions — "кафе" in "кафедральный", "вб" in
    "обувь". Empty term never matches."""
    if not term:
        return False
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text))


def _term_hit(text: str, terms: list[str]) -> bool:
    """True if any of `terms` appears in `text` as a whole word OR an inflected form.
    Falls back to exact whole-word match when morphology is unavailable."""
    tlow = (text or "").lower()
    tl: set[str] | None = None  # text lemmas, computed once on demand
    for term in terms:
        if not term:
            continue
        tt = term.lower()
        if _word_in(tlow, tt):              # exact whole-word/phrase
            return True
        words = _WORD_RE.findall(tt)
        if not words:
            continue
        if tl is None:
            tl = _lemmas(tlow)
        if all(_lemma(w) in tl for w in words):  # inflected match
            return True
    return False


# ── Utilities ─────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hashtags_json(hashtags) -> str:
    """Normalise a hashtag field (list or JSON string) to a JSON string."""
    if isinstance(hashtags, str):
        return hashtags
    return json.dumps(hashtags or [], ensure_ascii=False)


# ── Core collection ───────────────────────────────────────────────────────────

def collect_probe(session: Session, probe: NewsProbe, provider) -> int:
    """Collect posts for a single NewsProbe and persist them as NewsMention rows.

    - Resolves the probe's NewsTopic; returns 0 if the topic was deleted.
    - Iterates provider.search(query, kind, cursor) pages.
    - Skips posts shorter than MIN_TEXT_LEN after stripping #-tokens.
    - For kind=="global": keeps only posts that hit the topic's niche keywords.
    - Deduplicates on (platform, post_id) via UNIQUE constraint.
    - Advances the probe watermark to the first post_id seen.
    - Returns the count of newly stored mentions.
    """
    topic = session.get(NewsTopic, probe.topic_id)
    if topic is None:
        return 0

    niche_terms = [t.lower() for t in topic.niche_keywords_list() if t]
    source_label = "global" if probe.kind == "global" else "channel"

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

                # Niche-keyword gate for global probes (channel probes are already on-topic).
                if probe.kind == "global" and niche_terms and not _term_hit(post.text, niche_terms):
                    continue

                # Dedup insert via (platform, post_id) UNIQUE constraint.
                mention = NewsMention(
                    topic_id=probe.topic_id,
                    platform=probe.platform,
                    post_id=post.post_id,
                    author=post.author or "",
                    followers=getattr(post, "followers", 0) or 0,
                    text=post.text or "",
                    hashtags=_hashtags_json(getattr(post, "hashtags", [])),
                    created_at=post.created_at,
                    source=source_label,
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
        log.exception("NewsProbe %s failed — watermark NOT moved", probe.id)
        raise

    return count
