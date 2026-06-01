import logging
from datetime import datetime, timezone
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

def hotwatch_tick(session: Session, provider) -> int:
    hot = session.query(Mention).filter_by(is_hot=True).all()
    for mention in hot:
        try:
            page = provider.search(mention.post_id, "keyword", None)
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
