from __future__ import annotations
import json, logging, re
from datetime import datetime, timezone
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from .models import Brand, Mention, MentionSnapshot, Probe
from .providers.base import Post, SearchProvider

log = logging.getLogger(__name__)

VIRAL_VIEWS  = 500_000  # views above this = viral (post passes filters regardless)
VIRAL_LIKES  = 1_500    # smaller RU market: 1.5k likes already means a post took off
MAX_HASHTAGS = 3        # posts with more hashtags are usually low-value spam
MIN_TEXT_LEN = 20       # posts/comments shorter than this are noise ("огонь", "👍")

def _now(): return datetime.now(timezone.utc)

def _is_viral(post: Post) -> bool:
    return (post.likes or 0) >= VIRAL_LIKES or (post.views or 0) >= VIRAL_VIEWS

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

    # Hashtag spam: >3 hashtags usually means a low-value post — drop unless viral.
    if len(post.hashtags) > MAX_HASHTAGS and not _is_viral(post):
        return False

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

    # competitor / niche: the probe query already targets the term, so we only
    # require that the search label/query actually shows up in the post text.
    needle = (probe.label or probe.query).lower().lstrip("#")
    return needle in text_lower or any(needle in h.lower().lstrip("#") for h in post.hashtags)

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
                clean = " ".join(w for w in post.text.split() if not w.startswith("#")).strip()
                if len(clean) < MIN_TEXT_LEN: continue
                mention = _upsert_mention(session, post, brand.id)
                mention.source = probe.source
                mention.competitor = probe.label if probe.source == "competitor" else None
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
