import logging
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence
from sqlalchemy.orm import Session
from .models import Mention, MentionSnapshot
from .scoring import Snapshot, phase, severity

log = logging.getLogger(__name__)
HOT_SEVERITY_THRESHOLD = 50.0
COOL_PHASE = "declining"

def rescore_mention(session: Session, mention: Mention) -> None:
    snaps = [
        Snapshot(s.views, s.likes, s.comments, s.shares)
        for s in sorted(mention.snapshots, key=lambda s: s.ts)
    ]
    is_neg = mention.category in ("viral_negative", "complaint") if mention.category else False
    mention.severity = severity(snaps, followers=mention.followers, is_negative=is_neg)
    mention.phase    = phase(snaps)
    mention.is_hot   = (
        False if mention.phase == COOL_PHASE
        else mention.severity >= HOT_SEVERITY_THRESHOLD
    )
    mention.updated_at = datetime.now(timezone.utc)

def hotwatch_tick(
    session: Session,
    provider,
    brand_ids: Optional[Sequence[int]] = None,
    acquire: Optional[Callable[[], None]] = None,
) -> int:
    """Re-poll every hot mention and rescore it.

    `brand_ids` scopes the sweep to specific brands (e.g. only auto-collect
    brands) so we don't spend API budget on opted-out users. `acquire` is an
    optional rate-limit gate called once per provider request.
    """
    q = session.query(Mention).filter_by(is_hot=True)
    if brand_ids is not None:
        if not brand_ids:
            return 0
        q = q.filter(Mention.brand_id.in_(list(brand_ids)))
    hot = q.all()
    for mention in hot:
        try:
            # TikTok re-search refreshes live metrics; Instagram has no
            # per-post re-search via hashtag, so we just rescore its history.
            if mention.platform == "tiktok":
                if acquire:
                    acquire()
                page = provider.search(mention.post_id, "keyword", None, mention.platform)
                if page.posts:
                    post = page.posts[0]
                    session.add(MentionSnapshot(
                        mention_id=mention.id,
                        ts=datetime.now(timezone.utc),
                        likes=post.likes, views=post.views,
                        comments=post.comments, shares=post.shares,
                    ))
                    session.flush()
                    mention.likes    = post.likes
                    mention.views    = post.views
                    mention.comments = post.comments
                    mention.shares   = post.shares
            rescore_mention(session, mention)
        except Exception:
            log.exception("Hot-watch failed for mention %s", mention.id)
    session.commit()
    return len(hot)
