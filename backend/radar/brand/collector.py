"""Brand-domain probe collector.

Lifts the BRAND branch of radar/collector.py::collect_probe and reparameterizes it
against BrandProbe / BrandMention / BrandMentionSnapshot.  No Scope, no topic path.
"""
from __future__ import annotations
import json, logging, re
from functools import lru_cache
from datetime import datetime, timezone, timedelta
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from .models import Brand, BrandMention, BrandMentionSnapshot, BrandProbe
from ..core.providers.base import Post, SearchProvider
from ..core.spam import looks_like_ad_cheap

log = logging.getLogger(__name__)

VIRAL_VIEWS   = 500_000
VIRAL_LIKES   = 1_500
MIN_FOLLOWERS = 100

# Russian morphology — lets domain terms match inflected forms ("ресторане",
# "ресторанов" → "ресторан"). pymorphy3 is the Py3.11+ fork (pymorphy2 needs the
# removed pkg_resources); fall back to exact matching if neither is importable.
def _load_morph():
    for mod in ("pymorphy2", "pymorphy3"):
        try:
            return __import__(mod).MorphAnalyzer()
        except Exception:
            continue
    log.info("pymorphy not available — term matching falls back to exact word match")
    return None

_MORPH   = _load_morph()
_WORD_RE = re.compile(r"\w+", re.UNICODE)

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

def _now(): return datetime.now(timezone.utc)

def _word_in(text: str, term: str) -> bool:
    """Whole-word (boundary) match of `term` within `text` (both already lowercased)."""
    if not term:
        return False
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text))

def _is_viral(post: Post) -> bool:
    return (post.likes or 0) >= VIRAL_LIKES or (post.views or 0) >= VIRAL_VIEWS

def _below_follower_floor(post: Post, local_mode: bool = False) -> bool:
    """Tiny account (0 < followers < 100) whose post didn't go viral. followers==0
    means 'unknown' (no data) — not penalized. In local_mode the floor is off:
    ordinary city residents (few followers) ARE the local audience."""
    if local_mode:
        return False
    f = post.followers or 0
    return 0 < f < MIN_FOLLOWERS and not _is_viral(post)

# Letters unique to Ukrainian (і ї є ґ) or Kazakh (ә ғ қ ң ө ұ ү һ і) — never used
# in Russian. Their presence means the post is NOT Russian-market, even though it's
# Cyrillic. Geo is geo: a viral Ukrainian/Kazakh post is still the wrong country.
_NON_RU_CYRILLIC = set("іїєґІЇЄҐәғқңөұүһəҒҚҢӨҰҮҺ")

def _passes_language(post: Post, brand: Brand) -> bool:
    """For RU-market brands keep Russian Cyrillic posts only."""
    if getattr(brand, "market", "global") != "ru":
        return True
    text = post.text or ""
    if any(ch in _NON_RU_CYRILLIC for ch in text):
        return False
    if _is_viral(post):
        return True
    clean = " ".join(w for w in text.split() if not w.startswith("#"))
    return bool(re.search(r"[а-яёА-ЯЁ]", clean))

def _matches(post: Post, brand: Brand, probe: BrandProbe) -> bool:
    text_lower = post.text.lower()
    exclusions = [e.lower() for e in brand.exclusions_list()]
    if any(exc in text_lower for exc in exclusions):
        return False

    if not _passes_language(post, brand):
        return False

    # Channel-monitoring probes (Telegram @channels the user explicitly chose to
    # watch): the channel itself is the relevance signal, so keep every post.
    if getattr(probe, "kind", None) == "channel":
        return True

    if probe.source == "brand":
        keywords      = [k.lower() for k in brand.keywords_list()]
        hashtags      = [h.lower().lstrip("#") for h in brand.hashtags_list()]
        post_hashtags = [h.lower().lstrip("#") for h in post.hashtags]
        # Strip hashtags from text so keyword match requires mention in caption body.
        text_no_tags  = " ".join(w for w in post.text.split() if not w.startswith("#")).lower()
        return (
            any(kw in text_no_tags for kw in keywords) or
            any(ht in post_hashtags for ht in hashtags)
        )

    # competitor / niche: require the term as a whole word/phrase in text (word
    # boundaries avoid substring collisions like "вб" inside "обувь") OR as an
    # exact hashtag — reduces false positives on ambiguous names.
    needle = (probe.label or probe.query).lower().lstrip("#")
    post_hashtags = [h.lower().lstrip("#") for h in post.hashtags]

    def _hit(term: str) -> bool:
        term = term.lower().lstrip("#")
        if not term:
            return False
        if _word_in(text_lower, term):
            return True
        return any(term == h or term in h for h in post_hashtags)

    if not _hit(needle):
        return False
    # Geo-appended probe (query carries a city beyond the label): require the
    # city too, so "макияж Казань" doesn't match generic Kazan city content.
    label = (probe.label or "").lower()
    query = (probe.query or "").lower()
    if label and query and query != label:
        city = query.replace(label, "").strip()
        if city and not _hit(city):
            return False
    return True


def _upsert_mention(session: Session, post: Post, brand_id: int, platform: str | None = None) -> BrandMention:
    plat = platform or getattr(post, "platform", "unknown")
    stmt = (
        sqlite_insert(BrandMention).values(
            brand_id=brand_id,
            platform=plat, post_id=post.post_id,
            author=post.author, followers=post.followers, text=post.text,
            hashtags=json.dumps(post.hashtags),
            sound_id=getattr(post, "sound_id", None),
            created_at=post.created_at, likes=post.likes, views=post.views,
            comments=post.comments, shares=post.shares, updated_at=_now(),
        ).on_conflict_do_update(
            index_elements=["platform", "post_id"],
            set_={
                "likes": post.likes, "views": post.views,
                "comments": post.comments, "shares": post.shares,
                "followers": post.followers, "updated_at": _now(),
            },
        )
    )
    session.execute(stmt)
    session.flush()
    return session.query(BrandMention).filter_by(platform=plat, post_id=post.post_id).one()


def collect_probe(session: Session, probe: BrandProbe, provider) -> int:
    """Collect posts for one BrandProbe.

    - Resolves the probe's Brand; returns 0 if brand was deleted.
    - Applies brand relevance gate (_matches: language + keyword/hashtag match).
    - Deduplicates on (platform, post_id) via UNIQUE constraint (upsert).
    - Applies follower floor + spam rules; stores spam as hidden (no snapshot).
    - Advances the probe watermark to the first post_id seen this run.
    - Returns the count of non-spam mentions stored this pass.
    """
    brand = session.get(Brand, probe.brand_id)
    if brand is None:
        return 0

    new_watermark   = None
    count           = 0
    cursor          = None
    found_watermark = False

    try:
        while not found_watermark:
            page = provider.search(probe.query, probe.kind, cursor)
            if not page.posts:
                break
            for post in page.posts:
                if new_watermark is None:
                    new_watermark = post.post_id
                if probe.watermark and post.post_id == probe.watermark:
                    found_watermark = True
                    break

                # Relevance gate: language + keyword/hashtag/channel match.
                if not _matches(post, brand, probe):
                    continue

                # Age gate (same as legacy collect_probe: 7-day window).
                age = (_now().replace(tzinfo=None) - post.created_at.replace(tzinfo=None)).days
                if age > 7:
                    continue

                # Cheap ad/spam rules + tiny-account floor (floor only for niche/competitor).
                spam = looks_like_ad_cheap(post.text, post.author, post.hashtags)
                if probe.source in ("competitor", "niche"):
                    spam = spam or _below_follower_floor(post, getattr(brand, "local_mode", False))

                mention = _upsert_mention(session, post, brand.id, platform=probe.platform)
                mention.source     = probe.source
                mention.competitor = probe.label if probe.source == "competitor" else None
                mention.is_spam    = spam
                if spam:
                    continue  # stored hidden; no snapshot, doesn't count toward pipeline volume

                session.add(BrandMentionSnapshot(
                    mention_id=mention.id, ts=_now(),
                    likes=post.likes, views=post.views,
                    comments=post.comments, shares=post.shares,
                ))
                count += 1

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
        log.exception("BrandProbe %s failed — watermark NOT moved", probe.id)
        raise

    return count
