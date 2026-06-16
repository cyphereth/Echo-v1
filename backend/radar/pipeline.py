"""Shared post-collect processing: classify mentions + draft replies.

Used by both the manual collect endpoint and the background scheduler, so the
two paths stay in sync. Kept app-free to avoid an api <-> scheduler import cycle.
"""
from __future__ import annotations
import os, logging
from typing import Optional
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

from .classify import classify
from .drafts import generate_draft
from .hotwatch import rescore_mention
from .models import Brand, Mention, DraftEdit, Comment

MAX_DRAFTS_PER_COLLECT  = int(os.getenv("MAX_DRAFTS_PER_COLLECT", "50"))
MAX_COMMENT_DRAFTS      = int(os.getenv("MAX_COMMENT_DRAFTS", "10"))
# Cap how many freshly-collected mentions get their comments auto-fetched per run,
# so a big collection doesn't fan out into hundreds of provider+LLM calls at once.
MAX_COMMENT_FETCH_PER_COLLECT = int(os.getenv("MAX_COMMENT_FETCH_PER_COLLECT", "40"))


# Sphere-neutral recommendation-seeking cues — work for any vertical the client picks
# (restaurants "куда сходить", a shop "что выбрать / какой лучше / где купить",
# a service "к кому пойти / посоветуйте мастера"). The brand's niche terms supply the
# domain; these cues only detect the *asking-for-a-recommendation* intent.
_INTENT_CUES = ("посовет", "подскажите", "что выбрать", "какой лучше", "что лучше",
                "стоит ли", "который лучше", "где купить", "где заказать",
                "куда", "к кому", "что попробовать")
# Imperative asks that signal a recommendation request on their own — no "?" needed
# ("посоветуйте хороший ресторан", "помогите выбрать смартфон").
_INTENT_STRONG = ("посоветуйте", "посоветуете", "подскажите", "помогите выбрать",
                  "нужен совет", "ищу совет")

def _looks_like_intent(text: str) -> bool:
    """Recommendation-seeking post — sphere-agnostic. Fires on an imperative ask, or on
    a question mark plus a softer recommendation cue."""
    t = (text or "").lower()
    if any(c in t for c in _INTENT_STRONG):
        return True
    return "?" in t and any(c in t for c in _INTENT_CUES)


def opportunity_for(m: Mention) -> Optional[str]:
    if m.source == "competitor":
        who = m.competitor or "конкурента"
        return f"Аудитория обсуждает {who} — момент предложить ваш бренд как альтернативу."
    if m.source == "niche":
        if _looks_like_intent(m.text):
            return "Человек просит рекомендацию / выбирает — отличный момент предложить бренд нативно."
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
    # Level-2 relevance filter. Brand-lane mentions matched a brand keyword, so they are
    # kept unless they are an off-topic homonym (default-keep disambiguation). Niche and
    # competitor lanes, where broad terms catch random content, go through the sphere
    # noise judge.
    from .spam import classify_ads_batch, disambiguate_brand_batch
    if unclassified:
        sphere = getattr(brand, "sphere", "") or ""
        brand_ms = [m for m in unclassified if m.source == "brand"]
        other_ms = [m for m in unclassified if m.source != "brand"]
        noise = set()
        if brand_ms:
            off = disambiguate_brand_batch([m.text for m in brand_ms],
                                           brand_name=brand.name, sphere=sphere)
            for m, is_off in zip(brand_ms, off):
                if is_off:
                    m.is_spam = True
                    noise.add(id(m))
        if other_ms:
            flags = classify_ads_batch([m.text for m in other_ms], sphere=sphere)
            for m, is_ad in zip(other_ms, flags):
                if is_ad:
                    m.is_spam = True
                    noise.add(id(m))
        kept = [m for m in unclassified if id(m) not in noise]
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

    # Local mode: a salon wants CLIENTS in the audience feed, not other masters.
    # Route service-providers in the niche lane over to the competitor lane.
    if getattr(brand, "local_mode", False):
        from .spam import looks_like_provider_cheap, classify_providers_batch
        niche_ms = [m for m in unclassified if m.source == "niche"]
        if niche_ms:
            cheap = {id(m): looks_like_provider_cheap(m.text, m.author) for m in niche_ms}
            undecided = [m for m in niche_ms if not cheap[id(m)]]
            flags = classify_providers_batch([m.text for m in undecided])
            ai = {id(m): bool(f) for m, f in zip(undecided, flags)}
            for m in niche_ms:
                if cheap[id(m)] or ai.get(id(m)):
                    m.source = "competitor"
                    m.competitor = m.author
            session.commit()

    tone_examples = brand.tone_examples_list()
    edits         = recent_edits(session, brand_id)
    drafted = 0
    # Draft opportunity mentions first (niche/competitor intent), then by severity —
    # intent questions in chats have low engagement metrics but are the highest-value
    # moment to engage, so they must not be crowded out by viral posts.
    def _draft_priority(x):
        return (1 if x.opportunity else 0, x.severity or 0)
    for m in sorted(unclassified, key=_draft_priority, reverse=True)[:MAX_DRAFTS_PER_COLLECT]:
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


def fetch_and_store_comments(session: Session, mention: Mention,
                             provider, tg_provider) -> int:
    """Pull comments from the right provider, classify sentiment, draft relevant
    replies, store. Provider-agnostic so both the API endpoint and the collection
    pipeline can call it (app-free — no api import cycle)."""
    if mention.platform == "telegram":
        # A chat message (composite post_id "chat/msgid") IS the mention itself — it has
        # no channel-style reply thread to pull, so skip it.
        if "/" in (mention.post_id or ""):
            return 0
        # Telegram comments are discussion-group replies — fetched by the TG provider,
        # which needs the channel handle (mention.author) plus the post id.
        if tg_provider is None:
            log.warning("Telegram provider unavailable — cannot fetch comments for mention %s", mention.id)
            return 0
        fetched = tg_provider.fetch_comments(mention.post_id, None, "telegram",
                                             channel=mention.author)
    else:
        if provider is None:
            log.warning("Provider unavailable — cannot fetch comments for mention %s", mention.id)
            return 0
        fetched = provider.fetch_comments(mention.post_id, None, mention.platform)
    if not fetched:
        return 0

    brand         = session.get(Brand, mention.brand_id)
    tone_examples = brand.tone_examples_list() if brand else []
    edits         = recent_edits(session, mention.brand_id)
    existing      = {c.comment_id for c in mention.comment_rows}

    from .drafts import _is_opportunity_candidate, evaluate_opportunity
    from .spam import looks_like_ad_cheap, classify_ads_batch
    from .engagement import thread_already_engaged, is_duplicate_reply
    engaged = thread_already_engaged(session, mention.id)
    sent_replies = [c.draft for c in mention.comment_rows
                    if c.draft and c.status in ("sent", "posted")]
    is_comp_niche = mention.source in ("competitor", "niche")

    # New comments only; cheap spam rules first, then one batched Claude ad-check.
    from .collector import MIN_FOLLOWERS
    local = bool(getattr(brand, "local_mode", False))
    new = [fc for fc in fetched if fc.comment_id not in existing]
    cheap_spam = {
        fc.comment_id: looks_like_ad_cheap(fc.text, fc.author, [])
                       or (not local and 0 < (fc.followers or 0) < MIN_FOLLOWERS)
        for fc in new
    }
    survivors = [fc for fc in new if not cheap_spam[fc.comment_id]]
    ad_flags = classify_ads_batch([fc.text for fc in survivors],
                                  sphere=getattr(brand, "sphere", "") or "")
    ad_spam = {fc.comment_id: bool(flag) for fc, flag in zip(survivors, ad_flags)}

    stored, drafted = 0, 0
    # Spend the limited draft budget (MAX_COMMENT_DRAFTS) on the highest-engagement
    # comments first — iterate `new` sorted by likes (sorting `fetched` was a no-op
    # since the loop runs over the separately-built `new` list).
    for fc in sorted(new, key=lambda fc: fc.likes, reverse=True):
        is_spam = cheap_spam.get(fc.comment_id) or ad_spam.get(fc.comment_id, False)
        sentiment = classify(fc.text).tone
        draft = draft_flag = opp_reason = None
        is_opp = False

        if is_spam:
            pass  # stored hidden, no draft
        elif is_comp_niche and not engaged:
            if _is_opportunity_candidate(fc.text, sentiment) and drafted < MAX_COMMENT_DRAFTS:
                ev = evaluate_opportunity(
                    fc.text, mention.source, mention.competitor,
                    brand.name if brand else None,
                )
                reply = ev.get("reply")
                if ev.get("is_opportunity") and reply and not is_duplicate_reply(reply, sent_replies):
                    draft      = reply
                    opp_reason = ev.get("reason") or None
                    is_opp     = True
                    drafted   += 1
                    engaged    = True  # cap to one fresh draft per thread per fetch
        elif sentiment == "negative" and drafted < MAX_COMMENT_DRAFTS:
            dr = generate_draft(
                fc.text, "comment", sentiment, 0.9, tone_examples, edits,
                source=mention.source, competitor=mention.competitor,
                brand_name=brand.name if brand else None,
            )
            if dr:
                draft, draft_flag = dr.text, dr.flag
                drafted += 1

        session.add(Comment(
            mention_id=mention.id, comment_id=fc.comment_id, author=fc.author,
            followers=fc.followers, text=fc.text, likes=fc.likes,
            sentiment=sentiment, draft=draft, draft_flag=draft_flag,
            is_opportunity=is_opp, opportunity=opp_reason, is_spam=is_spam,
            created_at=fc.created_at,
        ))
        stored += 1
    session.commit()
    return stored


def fetch_new_comments(session: Session, brand_id: int, provider, tg_provider) -> int:
    """Post-collection step: auto-fetch comments for freshly-collected competitor/niche
    mentions that don't have comments yet. This is where the opportunity pipeline lives —
    audience comments on competitor/niche posts become engagement opportunities. Brand-lane
    comments stay on-demand (fetched lazily when a mention is opened) to bound cost."""
    candidates = (
        session.query(Mention)
        .filter(Mention.brand_id == brand_id,
                Mention.is_spam.is_(False),
                Mention.source.in_(("competitor", "niche")),
                # Chat messages (composite post_id "ns/msgid") are standalone — they
                # have no channel-style reply thread, so don't even select them.
                ~Mention.post_id.like("%/%"),
                ~Mention.comment_rows.any())
        .order_by(Mention.first_seen.desc())
        .limit(MAX_COMMENT_FETCH_PER_COLLECT)
        .all()
    )
    total = 0
    for m in candidates:
        try:
            total += fetch_and_store_comments(session, m, provider, tg_provider)
        except Exception:
            log.exception("Comment fetch failed for mention %s", m.id)
            session.rollback()
    return total
