"""Brand-domain daily digest generation.

Ports the brand branch of ``radar/digests.py::build_daily_digest`` to operate
on ``BrandStory`` / ``BrandStoryPoint`` / ``BrandReport`` for a single brand_id.

The LLM prompt and window logic are IDENTICAL to the legacy implementation so
the digest body format is unchanged.  Only the ORM classes differ.

ADDITIVE: legacy radar/digests.py is untouched.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..core import llm
from .models import BrandStory, BrandStoryPoint, BrandReport

TOP_N  = int(os.getenv("DIGEST_TOP_N", "5"))
WINDOW = timedelta(hours=int(os.getenv("DIGEST_WINDOW_H", "24")))

# Identical system prompt to legacy digests.py — same UX, same language.
_SYSTEM = (
    "Ты — аналитик медиамониторинга бренда. По переданным агрегатам составь краткую "
    "утреннюю сводку на русском языке. Для каждого сюжета: тема → динамика → "
    "ключевые источники → риски → рекомендованное действие. Пиши по делу, без воды."
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _top_stories(session: Session, brand_id: int) -> list[BrandStory]:
    since = datetime.now(timezone.utc) - WINDOW
    return (
        session.query(BrandStory)
        .filter(
            BrandStory.brand_id == brand_id,
            BrandStory.status == "active",
            BrandStory.last_seen_at >= since,
        )
        .order_by(BrandStory.is_anomaly.desc(), BrandStory.post_count.desc())
        .limit(TOP_N)
        .all()
    )


def _aggregate(session: Session, stories: list[BrandStory]) -> str:
    lines = []
    for st in stories:
        pts = (
            session.query(BrandStoryPoint)
            .filter(BrandStoryPoint.story_id == st.id)
            .order_by(BrandStoryPoint.bucket_start)
            .all()
        )
        sents = [p.avg_sentiment for p in pts if p.avg_sentiment is not None]
        avg = sum(sents) / len(sents) if sents else 0.0
        flag = " [АНОМАЛИЯ]" if st.is_anomaly else ""
        lines.append(
            f"- Сюжет «{st.title}»{flag}: {st.post_count} упоминаний, "
            f"средняя тональность {avg:.2f}, точек динамики {len(pts)}."
        )
    return "Топ-сюжеты за период:\n" + "\n".join(lines)


def build_brand_digest(session: Session, brand_id: int) -> BrandReport | None:
    """Generate and store a BrandReport digest for the brand's top active stories.

    Returns the BrandReport (not yet committed — caller must commit), or None
    if there are no active stories in the window.
    Raises ``llm.LLMNotConfigured`` if no key (caller maps to 503).
    """
    stories = _top_stories(session, brand_id)
    if not stories:
        return None
    body = llm.complete(_SYSTEM, _aggregate(session, stories), max_tokens=1024)
    report = BrandReport(brand_id=brand_id, kind="digest", body=body)
    session.add(report)
    session.flush()
    return report
