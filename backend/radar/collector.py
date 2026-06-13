from __future__ import annotations
import json, logging, re
from datetime import datetime, timezone
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from .models import Brand, Mention, MentionSnapshot, Probe
from .providers.base import Post, SearchProvider
from .spam import looks_like_ad_cheap

log = logging.getLogger(__name__)

VIRAL_VIEWS  = 500_000  # views above this = viral (post passes filters regardless)
VIRAL_LIKES  = 1_500    # smaller RU market: 1.5k likes already means a post took off
MIN_TEXT_LEN = 20       # posts/comments shorter than this are noise ("огонь", "👍")
MIN_FOLLOWERS = 100     # accounts below this are hidden unless the post went viral

def _now(): return datetime.now(timezone.utc)

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
    """For RU-market brands keep Russian Cyrillic posts only. Ukrainian/Kazakh
    (also Cyrillic) are excluded by their distinctive letters; foreign-language
    posts are kept only when viral."""
    if getattr(brand, "market", "global") != "ru":
        return True
    text = post.text or ""
    if any(ch in _NON_RU_CYRILLIC for ch in text):
        return False                      # Ukrainian/Kazakh — wrong geo, drop always
    if _is_viral(post):
        return True
    clean = " ".join(w for w in text.split() if not w.startswith("#"))
    return bool(re.search(r"[а-яёА-ЯЁ]", clean))

def _matches(post: Post, brand: Brand, probe: Probe) -> bool:
    text_lower = post.text.lower()
    exclusions = [e.lower() for e in brand.exclusions_list()]
    if any(exc in text_lower for exc in exclusions):
        return False

    if not _passes_language(post, brand):
        return False

    # Channel-monitoring probes (Telegram @channels the user explicitly chose to
    # watch): the channel itself is the relevance signal, so keep every post —
    # don't require a brand/competitor keyword in the text.
    if getattr(probe, "kind", None) == "channel":
        return True

    # Note: ad/spam/length/hashtag checks are NOT a hard drop anymore — matched
    # posts are stored with is_spam=True (store-but-hide) in collect_probe.

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
    # exact hashtag (not substring) — reduces false positives on ambiguous names.
    needle = (probe.label or probe.query).lower().lstrip("#")
    post_hashtags = [h.lower().lstrip("#") for h in post.hashtags]

    def _hit(term: str) -> bool:
        term = term.lower().lstrip("#")
        if not term:
            return False
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text_lower):
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

def _upsert_mention(session: Session, post: Post, brand_id: int) -> Mention:
    stmt = (
        sqlite_insert(Mention).values(
            brand_id=brand_id, platform=post.platform, post_id=post.post_id,
            author=post.author, followers=post.followers, text=post.text,
            hashtags=json.dumps(post.hashtags), sound_id=post.sound_id,
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
    return session.query(Mention).filter_by(platform=post.platform, post_id=post.post_id).one()

def collect_probe(session: Session, probe: Probe, provider: SearchProvider) -> int:
    brand = session.get(Brand, probe.brand_id)
    if not brand: return 0
    new_watermark = None
    count         = 0
    cursor        = None
    found_watermark = False
    try:
        while not found_watermark:
            page = provider.search(probe.query, probe.kind, cursor, probe.platform)
            if not page.posts: break
            for post in page.posts:
                if new_watermark is None:
                    new_watermark = post.post_id
                if probe.watermark and post.post_id == probe.watermark:
                    found_watermark = True; break
                if not _matches(post, brand, probe): continue
                age = (_now().replace(tzinfo=None) - post.created_at.replace(tzinfo=None)).days
                if age > 7: continue
                # Cheap ad/spam rules + tiny-account floor → store-but-hide.
                spam = looks_like_ad_cheap(post.text, post.author, post.hashtags) \
                    or _below_follower_floor(post, getattr(brand, "local_mode", False))
                mention = _upsert_mention(session, post, brand.id)
                mention.source = probe.source
                mention.competitor = probe.label if probe.source == "competitor" else None
                mention.is_spam = spam
                if spam:
                    continue  # stored hidden; no snapshot, doesn't count toward pipeline volume
                session.add(MentionSnapshot(
                    mention_id=mention.id, ts=_now(),
                    likes=post.likes, views=post.views,
                    comments=post.comments, shares=post.shares,
                ))
                count += 1
            if page.next_cursor is None: break
            cursor = page.next_cursor
        if new_watermark:
            probe.watermark = new_watermark
        probe.next_run_at = _now()
        session.commit()
    except Exception:
        session.rollback()
        log.exception("Probe %s failed — watermark NOT moved", probe.id)
        raise
    return count


def collect_geo(session: Session, brand: Brand, provider: SearchProvider) -> int:
    """Best-effort: pull IG posts geotagged in the brand's city and store as niche.
    Fail-open — never raises into the main collect."""
    city = (getattr(brand, "geo", "") or "").strip()
    if not city:
        return 0
    # Topical terms: a geotagged post is only relevant if it's about the brand's
    # niche/category/sphere — otherwise location_posts is just "random city content".
    local = getattr(brand, "local_mode", False)
    terms = [t.lower() for t in (brand.niche_keywords_list() + brand.category_terms_list())]
    if local:
        terms += [t.lower() for t in brand.audience_terms_list()]
    sphere_words = [w.lower() for w in (getattr(brand, "sphere", "") or "").split() if len(w) > 3]
    def _on_topic(text: str) -> bool:
        t = text.lower()
        return any(term in t for term in terms) or any(w in t for w in sphere_words)

    count = 0
    try:
        posts = provider.fetch_location_posts(city, "instagram", limit=15)
        for post in posts:
            spam = looks_like_ad_cheap(post.text, post.author, post.hashtags) \
                or _below_follower_floor(post, local)
            clean = " ".join(w for w in post.text.split() if not w.startswith("#")).strip()
            if len(clean) < MIN_TEXT_LEN and not spam:
                spam = True
            # Off-topic city content (museums, cars, sport) → hide. In local_mode
            # relevance is decided later by client/provider persona (a real
            # client's lifestyle post won't contain a literal niche word).
            if not spam and not local and not _on_topic(post.text):
                spam = True
            mention = _upsert_mention(session, post, brand.id)
            mention.source = "niche"
            mention.is_spam = spam
            if spam:
                continue
            session.add(MentionSnapshot(
                mention_id=mention.id, ts=_now(),
                likes=post.likes, views=post.views,
                comments=post.comments, shares=post.shares,
            ))
            count += 1
        session.commit()
    except Exception:
        session.rollback()
        log.warning("collect_geo failed for brand %s city %r", brand.id, city)
    return count
