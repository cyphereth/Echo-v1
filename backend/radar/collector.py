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
MAX_HASHTAGS = 3        # posts with more hashtags are usually low-value spam
MIN_TEXT_LEN = 20       # posts/comments shorter than this are noise ("огонь", "👍")
MIN_FOLLOWERS = 100     # accounts below this are hidden unless the post went viral

def _now(): return datetime.now(timezone.utc)

def _is_viral(post: Post) -> bool:
    return (post.likes or 0) >= VIRAL_LIKES or (post.views or 0) >= VIRAL_VIEWS

def _below_follower_floor(post: Post) -> bool:
    """Tiny account (0 < followers < 100) whose post didn't go viral. followers==0
    means 'unknown' (no data) — not penalized."""
    f = post.followers or 0
    return 0 < f < MIN_FOLLOWERS and not _is_viral(post)

def _passes_language(post: Post, brand: Brand) -> bool:
    """For RU/CIS brands keep only Cyrillic posts — unless the post is viral,
    in which case a foreign-language post is worth showing."""
    if getattr(brand, "market", "global") != "ru":
        return True
    if _is_viral(post):
        return True
    clean = " ".join(w for w in post.text.split() if not w.startswith("#"))
    return bool(re.search(r"[а-яёА-ЯЁ]", clean))

def _matches(post: Post, brand: Brand, probe: Probe) -> bool:
    text_lower = post.text.lower()
    exclusions = [e.lower() for e in brand.exclusions_list()]
    if any(exc in text_lower for exc in exclusions):
        return False

    if not _passes_language(post, brand):
        return False

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
    pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
    in_text = re.search(pattern, text_lower) is not None
    return in_text or needle in post_hashtags

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
                    or _below_follower_floor(post)
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
