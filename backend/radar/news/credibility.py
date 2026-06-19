"""News-domain credibility assessment + story summarisation.

Copied from ``radar/credibility.py`` and rebound to the news ORM models
(NewsStory / NewsIncident / NewsMention) and the core LLM wrapper
(``radar.core.llm``).

ADDITIVE: legacy ``radar/credibility.py`` is left byte-for-byte unchanged;
this module is the news-domain sibling.
"""
from __future__ import annotations
import json
import re

from sqlalchemy.orm import Session

from ..core import llm
from .models import NewsStory, NewsIncident, NewsMention

VALID = {"credible", "suspect"}

_SYSTEM = (
    "Ты — аналитик независимой верификации новостей. По набору сообщений об одном "
    "сюжете оцени, есть ли признаки фейка, пропаганды или манипуляции "
    "(единственный источник, эмоциональное давление, отсутствие конкретики, "
    "противоречия, признаки вброса). Ответь СТРОГО одним JSON-объектом без markdown: "
    '{"verdict": "credible" | "suspect", "note": "<краткое обоснование на русском>"}. '
    "verdict=credible — если выглядит как обычная фактическая новость; "
    "verdict=suspect — если есть признаки недостоверности."
)


def _story_evidence(session: Session, story: NewsStory, max_mentions: int = 8) -> str:
    incidents = (session.query(NewsIncident)
                 .filter(NewsIncident.story_id == story.id)
                 .order_by(NewsIncident.post_count.desc()).all())
    mentions = (session.query(NewsMention)
                .join(NewsIncident, NewsMention.incident_id == NewsIncident.id)
                .filter(NewsIncident.story_id == story.id)
                .limit(max_mentions).all())
    lines = [f"Сюжет: «{story.title}» (источников: {story.source_count})."]
    if incidents:
        lines.append("Инциденты: " + "; ".join(i.title for i in incidents[:5]))
    lines.append("Сообщения:")
    for m in mentions:
        src = (m.author or "?")
        text = (m.text or "").strip().replace("\n", " ")
        lines.append(f"- [{src}] {text[:200]}")
    return "\n".join(lines)


def _parse(raw: str) -> tuple[str, str]:
    """Extract (verdict, note) from the model's reply; lenient. Unparseable or
    out-of-vocab verdict → ('unrated', <trimmed raw>)."""
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            verdict = str(obj.get("verdict", "")).strip().lower()
            note = str(obj.get("note", "")).strip()
            if verdict in VALID:
                return verdict, note
        except (ValueError, TypeError):
            pass
    return "unrated", (raw or "").strip()[:300]


_SUMMARY_SYSTEM = (
    "Ты — новостной редактор. По набору сообщений об одном событии напиши краткую "
    "фактическую сводку «что произошло» на русском: 1–2 предложения, только факты, "
    "без оценок и воды."
)


def summarize_story(session: Session, story: NewsStory) -> NewsStory:
    """LLM 'what happened' summary for one NewsStory → story.summary.
    Raises llm.LLMNotConfigured when no key (caller → 503)."""
    story.summary = llm.complete(
        _SUMMARY_SYSTEM, _story_evidence(session, story), max_tokens=200
    ).strip()
    session.flush()
    return story


def assess_credibility(session: Session, story: NewsStory) -> NewsStory:
    """LLM fake-detection for one NewsStory. Sets story.credibility +
    credibility_note. Raises llm.LLMNotConfigured when no key (caller → 503)."""
    raw = llm.complete(_SYSTEM, _story_evidence(session, story), max_tokens=400)
    verdict, note = _parse(raw)
    story.credibility = verdict
    story.credibility_note = note
    session.flush()
    return story
