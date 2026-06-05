"""Shared post-collect processing: classify mentions + draft replies.

Used by both the manual collect endpoint and the background scheduler, so the
two paths stay in sync. Kept app-free to avoid an api <-> scheduler import cycle.
"""
from __future__ import annotations
import os
from typing import Optional
from sqlalchemy.orm import Session

from .classify import classify
from .drafts import generate_draft
from .hotwatch import rescore_mention
from .models import Brand, Mention, DraftEdit

MAX_DRAFTS_PER_COLLECT = int(os.getenv("MAX_DRAFTS_PER_COLLECT", "50"))


def opportunity_for(m: Mention) -> Optional[str]:
    if m.source == "competitor":
        who = m.competitor or "конкурента"
        return f"Аудитория обсуждает {who} — момент предложить ваш бренд как альтернативу."
    if m.source == "niche":
        return "Тематическая аудитория без упоминания бренда — хороший момент зайти нативно."
    return None


def recent_edits(session: Session, brand_id: int) -> list[dict]:
    """Last few human edits to drafts — fed back to the LLM to mirror the team's style."""
    rows = (
        session.query(DraftEdit)
        .filter_by(brand_id=brand_id)
        .order_by(DraftEdit.created_at.desc())
        .limit(5)
        .all()
    )
    return [{"original": e.original, "edited": e.edited} for e in rows]


def classify_and_draft(session: Session, brand_id: int) -> dict:
    """Classify every unclassified mention for a brand, then draft the top-N by severity."""
    brand = session.get(Brand, brand_id)
    if not brand:
        return {"classified": 0, "drafted": 0}

    unclassified = (
        session.query(Mention)
        .filter(Mention.brand_id == brand_id, Mention.category.is_(None),
                Mention.is_spam.is_(False))
        .all()
    )
    # Level-2 ad filter: Claude flags promotional-tone posts the cheap rules missed.
    from .spam import classify_ads_batch
    if unclassified:
        flags = classify_ads_batch([m.text for m in unclassified])
        kept = []
        for m, is_ad in zip(unclassified, flags):
            if is_ad:
                m.is_spam = True
            else:
                kept.append(m)
        session.commit()
        unclassified = kept

    for m in unclassified:
        result = classify(m.text, m.views, m.likes)
        m.tone        = result.tone
        m.category    = result.category
        m.lane        = result.lane
        m.confidence  = result.confidence
        m.opportunity = opportunity_for(m)
        rescore_mention(session, m)
    # Commit classification immediately so the write lock is released before the
    # slow per-mention Claude draft calls below — otherwise the transaction is
    # held for minutes and other writers (onboarding, manual collect) get
    # "database is locked".
    session.commit()

    tone_examples = brand.tone_examples_list()
    edits         = recent_edits(session, brand_id)
    drafted = 0
    for m in sorted(unclassified, key=lambda x: x.severity or 0, reverse=True)[:MAX_DRAFTS_PER_COLLECT]:
        # generate_draft is a slow network call — done outside any open
        # transaction; we commit each draft individually right after.
        dr = generate_draft(
            m.text, m.category or "neutral", m.tone, m.confidence or 0.0,
            tone_examples, edits,
            source=m.source, competitor=m.competitor, brand_name=brand.name,
        )
        if dr:
            m.draft, m.draft_flag = dr.text, dr.flag
            session.commit()
            drafted += 1

    return {"classified": len(unclassified), "drafted": drafted}
