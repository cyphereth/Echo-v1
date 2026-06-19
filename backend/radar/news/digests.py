"""News-domain daily digest builder.

Ported from the topic branch of ``radar/digests.py::build_daily_digest``,
rebound to the news ORM models (NewsStory / NewsStoryPoint / NewsReport)
and the core LLM wrapper (``radar.core.llm``).

Operates for a single *topic_id*; returns a ``NewsReport``.
LLM prompt and window logic are identical to the legacy digest.

ADDITIVE: legacy ``radar/digests.py`` is left byte-for-byte unchanged;
this module is the news-domain sibling.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..core import llm
from .models import NewsStory, NewsStoryPoint, NewsReport

TOP_N  = int(os.getenv("DIGEST_TOP_N", "5"))
WINDOW = timedelta(hours=int(os.getenv("DIGEST_WINDOW_H", "24")))

_SYSTEM = (
    "Ты — аналитик медиамониторинга бренда. По переданным агрегатам составь краткую "
    "утреннюю сводку на русском языке. Для каждого сюжета: тема → динамика → "
    "ключевые источники → риски → рекомендованное действие. Пиши по делу, без воды."
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _top_stories(session: Session, topic_id: int) -> list[NewsStory]:
    since = datetime.now(timezone.utc) - WINDOW
    return (
        session.query(NewsStory)
        .filter(
            NewsStory.topic_id == topic_id,
            NewsStory.status == "active",
            NewsStory.last_seen_at >= since,
        )
        .order_by(NewsStory.is_anomaly.desc(), NewsStory.post_count.desc())
        .limit(TOP_N)
        .all()
    )


def _aggregate(session: Session, stories: list[NewsStory]) -> str:
    lines = []
    for st in stories:
        pts = (
            session.query(NewsStoryPoint)
            .filter(NewsStoryPoint.story_id == st.id)
            .order_by(NewsStoryPoint.bucket_start)
            .all()
        )
        flag = " [АНОМАЛИЯ]" if st.is_anomaly else ""
        lines.append(
            f"- Сюжет «{st.title}»{flag}: {st.post_count} упоминаний, "
            f"точек динамики {len(pts)}."
        )
    return "Топ-сюжеты за период:\n" + "\n".join(lines)


def build_topic_digest(session: Session, topic_id: int) -> NewsReport | None:
    """Generate and store a digest NewsReport for *topic_id*'s top stories.

    Returns the NewsReport, or None if there are no active stories in the window.
    Raises llm.LLMNotConfigured if no key (caller maps to 503).
    """
    stories = _top_stories(session, topic_id)
    if not stories:
        return None
    body = llm.complete(_SYSTEM, _aggregate(session, stories), max_tokens=1024)
    report = NewsReport(topic_id=topic_id, kind="digest", body=body)
    session.add(report)
    session.flush()
    return report
