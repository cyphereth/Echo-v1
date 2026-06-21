"""Brand-domain engagement guardrails + audit logging.

Rebound from radar/engagement.py to BrandComment / BrandEngagementLog.
Legacy radar/engagement.py is left byte-for-byte intact.
"""
from __future__ import annotations
import re
from typing import Optional
from sqlalchemy.orm import Session


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_reply(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for dedup comparison."""
    t = (text or "").lower()
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


def is_duplicate_reply(candidate: str, recent: list[str], threshold: float = 0.85) -> bool:
    """True if `candidate` is at/above `threshold` word-overlap (Jaccard) with any
    recent reply. Prevents the brand from posting the same canned line repeatedly."""
    cand = set(normalize_reply(candidate).split())
    if not cand:
        return False
    for r in recent:
        prev = set(normalize_reply(r).split())
        if not prev:
            continue
        overlap = len(cand & prev) / len(cand | prev)
        if overlap >= threshold:
            return True
    return False


def thread_already_engaged(session: Session, mention_id: int) -> bool:
    """True if the brand has already approved/posted a reply under this brand mention —
    one brand reply per thread keeps engagement from looking like flooding."""
    from .models import BrandComment
    return (
        session.query(BrandComment)
        .filter(BrandComment.mention_id == mention_id,
                BrandComment.status.in_(("sent", "posted")))
        .first()
        is not None
    )


def log_engagement(session: Session, *, brand_id: Optional[int], mention_id: int,
                   comment_id: Optional[int], action: str, actor: str,
                   text: Optional[str]) -> None:
    """Append an audit row. Caller commits."""
    from .models import BrandEngagementLog
    session.add(BrandEngagementLog(
        brand_id=brand_id, mention_id=mention_id, comment_id=comment_id,
        action=action, actor=actor, text=text or "",
    ))
