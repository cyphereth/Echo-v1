"""Brand-domain API router.

Ports ALL brand @app. endpoints from radar/api.py into an APIRouter bound to
brand-domain models (Brand, BrandMention, BrandComment, BrandStory, BrandReport, …)
and radar.brand.* modules.

Mount with: app.include_router(brand_router)

Endpoints ported (formerly @app. in radar/api.py):
  GET  /brands
  GET  /brands/{brand_id}
  POST /brands/{brand_id}/config
  POST /brands/suggest
  POST /brands/preview
  POST /brands/profile-scan
  POST /onboarding
  POST /brands/{brand_id}/collect
  POST /brands/{brand_id}/autocollect
  GET  /inbox               (brand_id path only; topic_id path stays in legacy)
  GET  /mentions/{mention_id}
  POST /mentions/{mention_id}/action
  POST /mentions/{mention_id}/regenerate
  GET  /mentions/{mention_id}/comments
  GET  /opportunities
  POST /comments/{comment_id}/action
  POST /comments/{comment_id}/regenerate
  GET  /debug/tikhub
  GET  /search
  GET  /analytics
  POST /explore/city
  GET  /explore/cities
  POST /brands/{brand_id}/digest
  GET  /brands/{brand_id}/digests
  GET  /stories             (brand_id path only)
  GET  /stories/{story_id}  (brand stories)
  POST /stories/recompute
  POST /stories/{story_id}/summarize  (brand — LLM summary, no credibility)
  POST /stories/{story_id}/assess     (brand — kept for API shape compat; 501 — BrandStory has no credibility columns)

SHARED-ENDPOINT NOTES:
  /inbox: legacy had topic_id + brand_id in same handler. Topic path is in
    news.api router. Brand path is here. The legacy shared endpoint in
    radar/api.py is DELETED. 422 (missing query param) is the right response
    when neither brand_id nor topic_id is supplied.
  /stories: same split as /inbox — topic path in news.api, brand path here.

ADDITIVE: legacy radar/api.py untouched until the app.include_router line is
added by the same task step.
"""
from __future__ import annotations

import json
import logging
import os
import re as _re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..core.auth import decode_token
from ..models import User, CityReport
from .models import (
    Brand, BrandProbe, BrandMention, BrandMentionSnapshot,
    BrandComment, BrandDraftEdit, BrandStory, BrandStoryPoint,
    BrandIncident, BrandReport,
)
from .pipeline import classify_and_draft, recent_edits, fetch_new_comments
from .drafts import generate_draft
from .hotwatch import rescore_mention
from .engagement import log_engagement

log = logging.getLogger(__name__)

TIKHUB_TOKEN      = os.getenv("TIKHUB_TOKEN", "")
SOCIALCRAWL_TOKEN = os.getenv("SOCIALCRAWL_TOKEN", "")
TELEGRAM_API_ID   = os.getenv("TELEGRAM_API_ID", "")

_tg_provider_singleton = None

router = APIRouter(tags=["brand"])


# ---------------------------------------------------------------------------
# Provider helpers (mirrors radar/api.py)
# ---------------------------------------------------------------------------

def _get_tg_provider():
    global _tg_provider_singleton
    if not TELEGRAM_API_ID:
        return None
    if _tg_provider_singleton is None:
        try:
            from ..core.providers.telegram import TelegramProvider
            _tg_provider_singleton = TelegramProvider()
        except Exception:
            log.exception("Telegram provider init failed")
            return None
    return _tg_provider_singleton


def _get_provider():
    if SOCIALCRAWL_TOKEN:
        from ..core.providers.socialcrawl import SocialCrawlProvider
        return SocialCrawlProvider(SOCIALCRAWL_TOKEN)
    if TIKHUB_TOKEN:
        from ..core.providers.tikhub import TikHubProvider
        return TikHubProvider(TIKHUB_TOKEN)
    from ..core.providers.mock import MockProvider
    return MockProvider()


# ---------------------------------------------------------------------------
# Dependency: session + auth
# ---------------------------------------------------------------------------

def db() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def current_user(
    authorization: str = Header(None), session: Session = Depends(db)
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = decode_token(authorization.split(" ", 1)[1])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    user = session.get(User, payload.get("uid"))
    if not user:
        raise HTTPException(401, "User not found")
    return user


def _owned_brand(session: Session, brand_id: int, user: User) -> Brand:
    b = session.get(Brand, brand_id)
    if not b:
        raise HTTPException(404, "Brand not found")
    if b.user_id is not None and b.user_id != user.id:
        raise HTTPException(403, "Forbidden")
    return b


def _owned_mention(session: Session, mention_id: int, user: User) -> BrandMention:
    m = session.get(BrandMention, mention_id)
    if not m:
        raise HTTPException(404, "Mention not found")
    _owned_brand(session, m.brand_id, user)
    return m


def _owned_brand_story(
    session: Session, story_id: int, user: User
) -> BrandStory:
    st = session.get(BrandStory, story_id)
    if st is None:
        raise HTTPException(404, "Story not found")
    _owned_brand(session, st.brand_id, user)
    return st


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class BrandConfigBody(BaseModel):
    name:           Optional[str]       = None
    keywords:       Optional[list[str]] = None
    hashtags:       Optional[list[str]] = None
    exclusions:     Optional[list[str]] = None
    competitors:    Optional[list[str]] = None
    niche_keywords: Optional[list[str]] = None
    tone_examples:  Optional[list[str]] = None
    market:         Optional[str]       = None
    sphere:         Optional[str]       = None
    geo:            Optional[str]       = None
    category_terms: Optional[list[str]] = None
    audience_terms: Optional[list[str]] = None
    followers:      Optional[int]       = None
    local_mode:     Optional[bool]      = None
    tg_channels:    Optional[list[str]] = None


class SuggestBody(BaseModel):
    name: str


class PreviewBody(BaseModel):
    keywords:  list[str] = []
    platforms: list[str] = ["tiktok", "instagram"]


class ScanBody(BaseModel):
    tiktok:    str = ""
    instagram: str = ""


class OnboardingBody(BaseModel):
    name:           str
    keywords:       list[str] = []
    hashtags:       list[str] = []
    competitors:    list[str] = []
    niche_keywords: list[str] = []
    tone_examples:  list[str] = []
    market:         str = "global"
    sphere:         str = ""
    geo:            str = ""
    category_terms: list[str] = []
    audience_terms: list[str] = []
    followers:      int = 0
    local_mode:     bool = False


class AutoCollectBody(BaseModel):
    enabled: bool


class ActionBody(BaseModel):
    action: str
    draft:  Optional[str] = None


class CommentActionBody(BaseModel):
    action: str
    draft:  Optional[str] = None


class ExploreCityBody(BaseModel):
    city:    str
    refresh: bool = False


class ReportOut(BaseModel):
    id:         int
    kind:       str
    body:       str
    created_at: datetime
    story_id:   int | None = None


class BrandStoryOut(BaseModel):
    id:           int
    title:        str
    status:       str
    is_anomaly:   bool
    post_count:   int
    last_seen_at: datetime
    avg_sentiment: float | None = None
    # BrandStory is lean — no source_count/verified/credibility columns.
    # Fields below are kept with defaults so the frontend receives the same
    # shape as the legacy StoryOut (Phase 6 can rely on these fields).
    source_count:     int  = 0
    verified:         bool = False
    credibility:      str  = "unrated"
    credibility_note: str  = ""
    summary:          str  = ""


class BrandStoryPointOut(BaseModel):
    bucket_start:  datetime
    mention_count: int
    avg_sentiment: float | None
    source_count:  int


class BrandIncidentOut(BaseModel):
    id:           int
    title:        str
    sentiment:    float
    post_count:   int
    last_seen_at: datetime


class SourceRefOut(BaseModel):
    author:     str
    first_seen: datetime
    count:      int


class BrandStoryDetailOut(BrandStoryOut):
    points:    list[BrandStoryPointOut]
    incidents: list[BrandIncidentOut]
    sources:   list[SourceRefOut] = []


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

MONITORED_PLATFORMS = ("tiktok", "instagram")


def _clean_list(items) -> list[str]:
    out: list[str] = []
    seen = set()
    for raw in (items or []):
        for part in str(raw).split(","):
            t = part.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return out


def _ensure_name_in_keywords(name: str, keywords: list[str]) -> list[str]:
    nm = (name or "").strip()
    if not nm:
        return keywords
    low = nm.lower()
    if any(low in (k or "").lower() for k in keywords):
        return keywords
    return [nm] + list(keywords)


def _parse_handle(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if "/" in s:
        m = _re.search(r'(?:tiktok\.com/@|instagram\.com/)([^/?#]+)', s)
        if m:
            return m.group(1).lstrip("@")
        s = s.rstrip("/").split("/")[-1]
    return s.lstrip("@")


def _rebuild_probes(session: Session, brand: Brand) -> None:
    """Replace brand probes from current keywords/competitors/niche.
    Preserves auto-discovered chat probes (kind chat/chat_linked)."""
    (session.query(BrandProbe)
     .filter(BrandProbe.brand_id == brand.id,
             BrandProbe.kind.notin_(("chat", "chat_linked")))
     .delete(synchronize_session=False))
    geo = (getattr(brand, "geo", "") or "").strip()

    def geoq(term):
        return f"{term} {geo}" if geo else term

    for pf in MONITORED_PLATFORMS:
        for kw in brand.keywords_list():
            session.add(BrandProbe(brand_id=brand.id, platform=pf, kind="keyword",
                                   source="brand", query=kw))
        for comp in brand.competitors_list():
            session.add(BrandProbe(brand_id=brand.id, platform=pf, kind="keyword",
                                   source="competitor", label=comp, query=comp))
        for cat in brand.category_terms_list():
            session.add(BrandProbe(brand_id=brand.id, platform=pf, kind="keyword",
                                   source="competitor", label=cat, query=geoq(cat)))
        for term in brand.niche_keywords_list():
            session.add(BrandProbe(brand_id=brand.id, platform=pf, kind="keyword",
                                   source="niche", label=term, query=geoq(term)))
        if getattr(brand, "local_mode", False) and geo:
            for term in brand.audience_terms_list():
                session.add(BrandProbe(brand_id=brand.id, platform=pf, kind="keyword",
                                       source="niche", label=term,
                                       query=f"{term} {geo}"))
    if TELEGRAM_API_ID:
        for handle in brand.tg_channels_list():
            session.add(BrandProbe(brand_id=brand.id, platform="telegram",
                                   kind="channel", source="niche",
                                   label=handle, query=handle))
    session.flush()


def _post_url(m: BrandMention) -> Optional[str]:
    if m.platform == "tiktok":
        return f"https://www.tiktok.com/@{m.author}/video/{m.post_id}"
    if m.platform == "instagram":
        return f"https://www.instagram.com/p/{m.post_id}/"
    if m.platform == "telegram":
        pid = m.post_id or ""
        if "/" in pid:
            ns = pid.split("/", 1)[0]
            return f"https://t.me/c/{pid}" if ns.isdigit() else f"https://t.me/{pid}"
        return f"https://t.me/{(m.author or '').lstrip('@')}/{pid}"
    return None


def _velocity(mention: BrandMention) -> float:
    snaps = sorted(mention.snapshots, key=lambda s: s.ts) if hasattr(mention, "snapshots") else []
    if len(snaps) < 2:
        return 0.0
    dt_min = (snaps[-1].ts - snaps[-2].ts).total_seconds() / 60
    if dt_min <= 0:
        return 0.0
    return round((snaps[-1].views - snaps[-2].views) / dt_min, 1)


def _mention_card(m: BrandMention) -> dict:
    snaps = sorted(m.snapshots, key=lambda s: s.ts) if hasattr(m, "snapshots") and m.snapshots else []
    snap_views = [s.views for s in snaps] if snaps else [
        round(m.views * 0.4), round(m.views * 0.7), m.views
    ]
    return {
        "id":           m.id,
        "platform":     m.platform,
        "author":       m.author,
        "followers":    m.followers,
        "created_at":   (m.created_at.isoformat() + "Z"
                         if m.created_at.tzinfo is None else m.created_at.isoformat()),
        "text":         m.text,
        "severity":     m.severity,
        "phase":        m.phase,
        "tone":         m.tone,
        "confidence":   m.confidence,
        "category":     m.category,
        "lane":         m.lane or "none",
        "source":       m.source or "brand",
        "competitor":   m.competitor,
        "opportunity":  m.opportunity,
        "is_hot":       m.is_hot,
        "views":        m.views,
        "likes":        m.likes,
        "comments":     m.comments,
        "post_id":      m.post_id,
        "url":          _post_url(m),
        "velocity":     _velocity(m),
        "draft":        m.draft,
        "draft_flag":   m.draft_flag,
        "status":       m.status,
        "snapshots":    [{"views": v} for v in snap_views],
    }


def _brand_card(b: Brand, session: Optional[Session] = None) -> dict:
    probes = []
    if session is not None:
        bp_rows = session.query(BrandProbe).filter_by(brand_id=b.id).all()
        probes = [{"id": p.id, "query": p.query, "kind": p.kind,
                   "source": p.source, "platform": p.platform} for p in bp_rows]
    return {
        "id":             b.id,
        "name":           b.name,
        "keywords":       b.keywords_list(),
        "hashtags":       b.hashtags_list(),
        "exclusions":     b.exclusions_list(),
        "competitors":    b.competitors_list(),
        "niche_keywords": b.niche_keywords_list(),
        "tone_examples":  b.tone_examples_list(),
        "market":         getattr(b, "market", "global") or "global",
        "sphere":         getattr(b, "sphere", "") or "",
        "geo":            getattr(b, "geo", "") or "",
        "category_terms": b.category_terms_list() if hasattr(b, "category_terms_list") else [],
        "audience_terms": b.audience_terms_list() if hasattr(b, "audience_terms_list") else [],
        "tg_channels":    b.tg_channels_list() if hasattr(b, "tg_channels_list") else [],
        "followers":      getattr(b, "followers", 0) or 0,
        "local_mode":     bool(getattr(b, "local_mode", False)),
        "auto_collect":   bool(b.auto_collect),
        "probes":         probes,
    }


def _story_fields(session: Session, st: BrandStory) -> dict:
    avg = (session.query(func.avg(BrandStoryPoint.avg_sentiment))
           .filter(BrandStoryPoint.story_id == st.id).scalar())
    return dict(
        id=st.id, title=st.title, status=st.status, is_anomaly=st.is_anomaly,
        post_count=st.post_count, last_seen_at=st.last_seen_at, avg_sentiment=avg,
        # Lean brand story — no source_count/verified/credibility columns:
        source_count=0, verified=False, credibility="unrated",
        credibility_note="", summary=st.summary,
    )


def _story_sources(session: Session, story_id: int) -> list[SourceRefOut]:
    rows = (
        session.query(BrandMention.author,
                      func.min(BrandMention.created_at),
                      func.count(BrandMention.id))
        .join(BrandIncident, BrandMention.incident_id == BrandIncident.id)
        .filter(BrandIncident.story_id == story_id,
                BrandMention.author.isnot(None))
        .group_by(BrandMention.author)
        .all()
    )
    refs = [SourceRefOut(author=a, first_seen=fs, count=c)
            for (a, fs, c) in rows if (a or "").strip()]
    refs.sort(key=lambda r: r.first_seen)
    return refs


# ---------------------------------------------------------------------------
# Comment helpers
# ---------------------------------------------------------------------------

_STATUS_OUT = {"sent": "approved", "posted": "posted", "skipped": "skipped", "pending": "pending"}


def _minutes_ago(dt: datetime) -> int:
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 60))


def _comment_card(c: BrandComment) -> dict:
    return {
        "id":             c.id,
        "author":         c.author,
        "followers":      c.followers,
        "text":           c.text,
        "sentiment":      c.sentiment,
        "likes":          c.likes,
        "minsAgo":        _minutes_ago(c.created_at),
        "suggestedReply": c.draft,
        "draft_flag":     c.draft_flag,
        "is_opportunity": bool(getattr(c, "is_opportunity", False)),
        "opportunity":    getattr(c, "opportunity", None),
        "status":         _STATUS_OUT.get(c.status, "pending"),
    }


def _fetch_and_store_comments_for_mention(
    session: Session, mention: BrandMention
) -> int:
    from .pipeline import fetch_and_store_comments
    return fetch_and_store_comments(session, mention, _get_provider(), _get_tg_provider())


# ---------------------------------------------------------------------------
# City explorer helpers (same as radar/api.py — shared CityReport model)
# ---------------------------------------------------------------------------

CITY_REPORT_TTL_DAYS = int(os.getenv("CITY_REPORT_TTL_DAYS", "7"))


def _city_report_card(r) -> dict:
    return {
        "city":         r.city,
        "display_city": r.display_city,
        "summary":      json.loads(r.summary or "{}"),
        "post_count":   r.post_count,
        "platforms":    r.platforms.split(",") if r.platforms else [],
        "created_at":   r.created_at.isoformat() if r.created_at else None,
    }


def _run_city_explore(city: str) -> None:
    from .. import explore
    session = get_session()
    try:
        key, _ = explore.normalize_city(city)
        agg, n, platforms = explore.run_city_search(_get_provider(), city)
        if n == 0:
            log.warning("city explore: no posts for %r", city)
            return
        summary = explore.summarize_city(city, agg)
        if not summary:
            log.warning("city explore: LLM summary failed for %r", city)
            return
        row = CityReport(city=key, display_city=city.strip(),
                         summary=json.dumps(summary, ensure_ascii=False),
                         post_count=n, platforms=",".join(platforms))
        session.add(row); session.commit()
        log.info("city explore: stored report for %r (%d posts)", city, n)
    except Exception:
        log.exception("city explore failed for %r", city)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Suggest helpers (same logic as radar/api.py — kept verbatim for parity)
# ---------------------------------------------------------------------------

_SUGGEST_TRANSIENT_STATUS = {429, 500, 502, 503, 504, 529}


def _is_transient_suggest_error(exc: Exception) -> bool:
    import httpx
    if isinstance(exc, (json.JSONDecodeError, KeyError, ValueError,
                        httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _SUGGEST_TRANSIENT_STATUS
    return False


def _suggest_with_retry(call, attempts: int = 3):
    last_err = None
    for i in range(attempts):
        try:
            return call()
        except Exception as e:
            if not _is_transient_suggest_error(e):
                raise
            last_err = e
            log.warning("suggest_brand attempt %d/%d failed: %s", i + 1, attempts, e)
    raise last_err


def _extract_suggest_json(blocks: list[dict]) -> dict:
    texts = [b["text"] for b in blocks if b.get("type") == "text" and b.get("text")]
    if not texts:
        raise ValueError("no text block in suggest response")
    text = texts[-1].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(text)


def _build_suggest_payload(name: str) -> dict:
    system = (
        "Ты эксперт по SMM и мониторингу брендов в русскоязычных соцсетях "
        "(TikTok, Instagram). Сначала ИЩИ информацию о бренде в интернете "
        "(чем занимается, реальные конкуренты, как о нём пишут), затем дай ответ. "
        "Финальный ответ — ТОЛЬКО валидный JSON без пояснений и markdown-блоков."
    )
    user_msg = (
        f'Изучи бренд "{name}" через веб-поиск и его сферу деятельности, затем '
        f'подбери для мониторинга в TikTok и Instagram МАКСИМАЛЬНО ШИРОКО: '
        f'keywords — 20-30 (вариации названия рус/лат, продукты, фирменные термины); '
        f'niche_keywords — 15-25 (тематика индустрии + смежные интересы ЦА + intent-фразы '
        f'по сфере: как люди ищут такое, напр. для еды «где поесть», «куда сходить на '
        f'выходных», «посоветуйте ресторан»); '
        f'competitors — 10-15 ТОЛЬКО реально существующих компаний, '
        f'подтверждённых веб-поиском (никаких выдуманных); '
        f'audience_terms — 15-20 широких тем целевой аудитории. '
        f'Определи ДНК бренда — сферу и интересы аудитории 1-2 фразами (поле "sphere"). '
        f'Определи город (geo), если это локальный бизнес (салон/клиника в конкретном '
        f'городе) — иначе "". Если это локальный СЕРВИСНЫЙ бизнес — сгенерируй '
        f'category_terms (4-6 категорий ниши города); для федеральных/онлайн брендов '
        f'category_terms=[]. '
        f'Определи рынок: если бренд русскоязычный или ориентирован на СНГ — '
        f'верни "market":"ru" и предлагай ТОЛЬКО русскоязычных конкурентов из СНГ; '
        f'иначе "market":"global". '
        f'РАНЖИРУЙ все термины по релевантности и ОТСЕКАЙ явно нерелевантное. '
        f'Ответ строго в JSON: {{"keywords":[],"hashtags":[],"competitors":[],'
        f'"niche_keywords":[],"sphere":"","geo":"","category_terms":[],'
        f'"audience_terms":[],"market":""}}'
    )
    return {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 4000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }


def _profile_with_claude(name_hint, bio, followers, posts_text,
                          brand_replies, sentiment) -> dict:
    import httpx as _httpx
    from .drafts import LLM_API_KEY, LLM_API_URL
    if not LLM_API_KEY:
        return {}
    system = (
        "Ты аналитик бренда. На основе реального контента аккаунта в соцсетях определи "
        "профиль для мониторинга упоминаний и генерации ответов. "
        "Отвечай ТОЛЬКО валидным JSON без markdown."
    )
    posts_block   = "\n".join(f"- {t[:200]}" for t in posts_text[:15]) or "(нет постов)"
    replies_block = "\n".join(f"- {r[:200]}" for r in brand_replies[:5]) or "(нет ответов бренда)"
    user_msg = (
        f"Профиль: {name_hint}, {bio[:200]}, {followers} подписчиков\n"
        f"Посты бренда:\n{posts_block}\n"
        f"Реальные ответы бренда на комментарии:\n{replies_block}\n"
        f"Тональность аудитории: {sentiment.get('positive',0)} поз / "
        f"{sentiment.get('negative',0)} нег / {sentiment.get('neutral',0)} нейтр\n\n"
        'keywords — варианты НАЗВАНИЯ бренда (рус + латиница, включая хэндл и частые '
        'написания), а НЕ нишевые слова. niche_keywords — это про тематику.\n'
        'Определи ДНК бренда — сферу и интересы аудитории 1-2 фразами (поле "sphere"). '
        'Верни JSON: {"name":"","voice_description":"","tone_examples":[],'
        '"keywords":[],"hashtags":[],"competitors":[],"niche_keywords":[],"sphere":"","geo":"","category_terms":[],"audience_terms":[],"market":""}'
    )

    def _call():
        resp = _httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 600,
                  "system": system, "messages": [{"role": "user", "content": user_msg}]},
            timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(text)

    try:
        return _call()
    except (json.JSONDecodeError, KeyError):
        try:
            return _call()
        except Exception as e:
            log.warning("_profile_with_claude retry failed: %s", e)
            return {}
    except Exception as e:
        log.warning("_profile_with_claude failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Analytics constants
# ---------------------------------------------------------------------------

WEEKDAYS_RU    = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
PLATFORM_NAMES = {"tiktok": "TikTok", "instagram": "Instagram", "telegram": "Telegram"}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ---------------------------------------------------------------------------
# ── Brands ──────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.get("/brands")
def list_brands(user: User = Depends(current_user), session: Session = Depends(db)):
    return [_brand_card(b, session) for b in session.query(Brand).filter_by(user_id=user.id).all()]


@router.get("/brands/{brand_id}")
def get_brand(brand_id: int, user: User = Depends(current_user),
              session: Session = Depends(db)):
    return _brand_card(_owned_brand(session, brand_id, user), session)


@router.post("/brands/{brand_id}/config")
def update_brand_config(brand_id: int, body: BrandConfigBody,
                        user: User = Depends(current_user),
                        session: Session = Depends(db)):
    b = _owned_brand(session, brand_id, user)
    if body.name           is not None: b.name           = body.name
    if body.hashtags       is not None: b.hashtags       = json.dumps(_clean_list(body.hashtags))
    if body.exclusions     is not None: b.exclusions     = json.dumps(_clean_list(body.exclusions))
    if body.competitors    is not None: b.competitors    = json.dumps(_clean_list(body.competitors))
    if body.niche_keywords is not None: b.niche_keywords = json.dumps(_clean_list(body.niche_keywords))
    if body.tone_examples  is not None: b.tone_examples  = json.dumps(body.tone_examples)
    if body.market         is not None: b.market         = body.market
    if body.sphere         is not None: b.sphere         = body.sphere
    if body.geo            is not None: b.geo            = body.geo
    if body.category_terms is not None: b.category_terms = json.dumps(_clean_list(body.category_terms))
    if body.audience_terms is not None: b.audience_terms = json.dumps(_clean_list(body.audience_terms))
    if body.followers      is not None: b.followers      = body.followers
    if body.local_mode     is not None: b.local_mode     = body.local_mode
    if body.tg_channels    is not None: b.tg_channels    = json.dumps(_clean_list(body.tg_channels))
    if body.keywords       is not None:
        b.keywords = json.dumps(_ensure_name_in_keywords(
            body.name or b.name, _clean_list(body.keywords)))
    if any(v is not None for v in (body.keywords, body.competitors, body.niche_keywords,
                                   body.category_terms, body.geo, body.audience_terms,
                                   body.local_mode, body.tg_channels)):
        _rebuild_probes(session, b)
    session.commit()
    return _brand_card(b, session)


# ---------------------------------------------------------------------------
# ── AI Brand Suggest ─────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.post("/brands/suggest")
def suggest_brand(body: SuggestBody, user: User = Depends(current_user)):
    import httpx
    from .drafts import LLM_API_KEY, LLM_API_URL
    if not LLM_API_KEY:
        raise HTTPException(503, "LLM_API_KEY not configured")

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json=_build_suggest_payload(body.name),
            timeout=120,
        )
        resp.raise_for_status()
        return _extract_suggest_json(resp.json().get("content", []))

    try:
        data = _suggest_with_retry(_call)
    except Exception as e:
        log.warning("suggest_brand failed: %s", e)
        raise HTTPException(502, "AI suggestion failed")

    return {
        "keywords":       data.get("keywords", []),
        "hashtags":       data.get("hashtags", []),
        "competitors":    data.get("competitors", []),
        "niche_keywords": data.get("niche_keywords", []),
        "sphere":         data.get("sphere", "") or "",
        "geo":            data.get("geo", "") or "",
        "category_terms": data.get("category_terms", []),
        "audience_terms": data.get("audience_terms", []),
        "market":         data.get("market") or "global",
    }


@router.post("/brands/preview")
def preview_brand(body: PreviewBody, user: User = Depends(current_user)):
    provider = _get_provider()
    posts = []
    seen = set()
    for kw in body.keywords[:2]:
        for pf in body.platforms[:2]:
            if len(posts) >= 5:
                break
            try:
                page = provider.search(kw, "keyword", None, pf)
                for p in page.posts[:3]:
                    if p.post_id not in seen:
                        seen.add(p.post_id)
                        posts.append({
                            "post_id":  p.post_id,
                            "platform": p.platform,
                            "author":   p.author,
                            "views":    p.views,
                            "likes":    p.likes,
                            "text":     p.text[:120],
                        })
            except Exception as e:
                log.warning("preview_brand search failed kw=%s pf=%s: %s", kw, pf, e)
    return {"posts": posts[:5]}


@router.post("/brands/profile-scan")
def profile_scan(body: ScanBody, user: User = Depends(current_user)):
    provider = _get_provider()
    platforms = []
    if body.tiktok.strip():
        platforms.append(("tiktok", _parse_handle(body.tiktok)))
    if body.instagram.strip():
        platforms.append(("instagram", _parse_handle(body.instagram)))
    if not platforms:
        raise HTTPException(400, "Provide at least one account")

    name_hint, bio, followers = "", "", 0
    posts_text: list[str] = []
    brand_replies: list[str] = []
    sentiment = {"positive": 0, "negative": 0, "neutral": 0}
    scanned = {"tiktok": False, "instagram": False}

    for platform, handle in platforms:
        if not handle:
            continue
        prof = provider.fetch_profile(handle, platform)
        if not prof:
            continue
        scanned[platform] = True
        name_hint = name_hint or prof.get("name", "")
        bio = bio or prof.get("bio", "")
        followers = max(followers, prof.get("followers", 0))
        posts = provider.fetch_user_posts(handle, platform, limit=15)
        posts_text.extend(p.text for p in posts if p.text)
        top = sorted(posts, key=lambda p: (p.likes + p.views), reverse=True)[:3]
        for p in top:
            for c in provider.fetch_comments(p.post_id, None, platform):
                if c.author.lower() == handle.lower():
                    brand_replies.append(c.text)
                t = c.text.lower()
                if any(w in t for w in ("отлично", "супер", "спасибо", "люблю", "класс", "👍", "❤")):
                    sentiment["positive"] += 1
                elif any(w in t for w in ("ужас", "плохо", "обман", "верните", "кошмар", "👎")):
                    sentiment["negative"] += 1
                else:
                    sentiment["neutral"] += 1

    if not any(scanned.values()):
        raise HTTPException(422, "No accounts could be read")

    profile = _profile_with_claude(name_hint, bio, followers, posts_text,
                                    brand_replies, sentiment)
    return {
        "name":              profile.get("name") or name_hint,
        "voice_description": profile.get("voice_description", ""),
        "tone_examples":     profile.get("tone_examples", []) or brand_replies[:3],
        "keywords":          profile.get("keywords", []),
        "hashtags":          profile.get("hashtags", []),
        "competitors":       profile.get("competitors", []),
        "niche_keywords":    profile.get("niche_keywords", []),
        "sphere":            profile.get("sphere", "") or "",
        "geo":               profile.get("geo", "") or "",
        "category_terms":    profile.get("category_terms", []),
        "audience_terms":    profile.get("audience_terms", []),
        "followers":         followers,
        "market":            profile.get("market") or "global",
        "audience_sentiment": sentiment,
        "scanned":           scanned,
    }


# ---------------------------------------------------------------------------
# ── Onboarding ───────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.post("/onboarding")
def onboarding(body: OnboardingBody, user: User = Depends(current_user),
               session: Session = Depends(db)):
    existing = session.query(Brand).filter_by(user_id=user.id).first()
    if existing:
        raise HTTPException(409, "Brand already exists")
    b = Brand(
        user_id=user.id,
        name=body.name,
        keywords=json.dumps(_ensure_name_in_keywords(
            body.name, _clean_list(body.keywords))),
        hashtags=json.dumps(_clean_list(body.hashtags)),
        competitors=json.dumps(_clean_list(body.competitors)),
        niche_keywords=json.dumps(_clean_list(body.niche_keywords)),
        tone_examples=json.dumps(body.tone_examples),
        market=body.market or "global",
        sphere=body.sphere or "",
        geo=body.geo or "",
        category_terms=json.dumps(_clean_list(body.category_terms)),
        audience_terms=json.dumps(_clean_list(body.audience_terms)),
        followers=body.followers or 0,
        local_mode=bool(body.local_mode or (0 < (body.followers or 0) <= 1000 and bool(body.geo))),
        auto_collect=True,
    )
    session.add(b)
    session.flush()
    _rebuild_probes(session, b)
    session.commit()
    return _brand_card(b, session)


# ---------------------------------------------------------------------------
# ── Collect ──────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def _run_collect(brand_id: int) -> dict:
    from .collector import collect_probe, collect_geo, ensure_chats_discovered, collect_chats
    session = get_session()
    try:
        brand = session.get(Brand, brand_id)
        if not brand:
            return {"error": "brand not found"}
        provider   = _get_provider()
        tg_provider = _get_tg_provider()

        probes = session.query(BrandProbe).filter_by(brand_id=brand_id).all()
        if not probes:
            _rebuild_probes(session, brand)
            probes = session.query(BrandProbe).filter_by(brand_id=brand_id).all()

        total = 0
        for probe in probes:
            prov = tg_provider if probe.platform == "telegram" else provider
            if prov is None:
                continue
            try:
                log.info("Collecting probe '%s'", probe.query)
                count = collect_probe(session, probe, prov)
                log.info("Probe '%s' → %d new mentions", probe.query, count)
                total += count
            except Exception as e:
                log.warning("Probe '%s' failed: %s", probe.query, e)

        try:
            total += collect_geo(session, brand, provider)
        except Exception as e:
            log.warning("collect_geo failed: %s", e)

        try:
            ensure_chats_discovered(session, brand, tg_provider)
            total += collect_chats(session, brand, tg_provider)
        except Exception as e:
            log.warning("collect_chats failed: %s", e)

        result = classify_and_draft(session, brand_id)
        comments = fetch_new_comments(session, brand_id, provider, tg_provider)
        return {"collected": total, "comments": comments, **result}
    finally:
        session.close()


@router.post("/brands/{brand_id}/collect")
def collect_brand(brand_id: int, background_tasks: BackgroundTasks,
                  user: User = Depends(current_user),
                  session: Session = Depends(db)):
    b = _owned_brand(session, brand_id, user)
    background_tasks.add_task(_run_collect, brand_id)
    return {"status": "collecting", "brand": b.name, "using_tikhub": bool(TIKHUB_TOKEN)}


@router.post("/brands/{brand_id}/autocollect")
def set_autocollect(brand_id: int, body: AutoCollectBody,
                    user: User = Depends(current_user),
                    session: Session = Depends(db)):
    b = _owned_brand(session, brand_id, user)
    b.auto_collect = body.enabled
    if body.enabled and not session.query(BrandProbe).filter_by(brand_id=b.id).first():
        _rebuild_probes(session, b)
    session.commit()
    return {"auto_collect": b.auto_collect}


# ---------------------------------------------------------------------------
# ── Inbox (brand_id path) ────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.get("/inbox")
def inbox(brand_id: int, include_hidden: int = 0,
          user: User = Depends(current_user),
          session: Session = Depends(db)):
    """Brand inbox. brand_id is required (422 if missing)."""
    _owned_brand(session, brand_id, user)
    q = (
        session.query(BrandMention)
        .filter(BrandMention.brand_id == brand_id,
                BrandMention.status != "rejected")
    )
    if not include_hidden:
        q = q.filter(BrandMention.is_spam.is_(False))
    mentions = q.order_by(BrandMention.severity.desc()).all()

    from ..collector import NICHE_FRESH_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NICHE_FRESH_HOURS)

    def _fresh_enough(m: BrandMention) -> bool:
        if m.source != "niche":
            return True
        created = m.created_at if m.created_at.tzinfo else m.created_at.replace(tzinfo=timezone.utc)
        return created >= cutoff

    mentions = [m for m in mentions if _fresh_enough(m)]
    pr  = [_mention_card(m) for m in mentions if m.lane == "pr"]
    smm = [_mention_card(m) for m in mentions if m.lane in ("smm", "none", None)]
    return {"pr": pr, "smm": smm}


# ---------------------------------------------------------------------------
# ── Mentions ─────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.get("/mentions/{mention_id}")
def get_mention(mention_id: int, user: User = Depends(current_user),
                session: Session = Depends(db)):
    return _mention_card(_owned_mention(session, mention_id, user))


@router.post("/mentions/{mention_id}/action")
def post_action(mention_id: int, body: ActionBody,
                user: User = Depends(current_user),
                session: Session = Depends(db)):
    m = _owned_mention(session, mention_id, user)
    if body.action == "approve":
        original = m.draft
        if body.draft and body.draft != m.draft:
            session.add(BrandDraftEdit(
                mention_id=m.id, brand_id=m.brand_id,
                category=m.category,
                original=original or "", edited=body.draft,
            ))
        m.draft  = body.draft or m.draft
        m.status = "sent"
    elif body.action == "reject":
        m.status = "rejected"
    elif body.action == "pr":
        m.lane       = "pr"
        m.status     = "new"
        m.draft_flag = None
    else:
        raise HTTPException(400, f"Unknown action: {body.action}")
    _action_map = {"approve": "approved", "reject": "rejected", "pr": "pr"}
    log_engagement(session, brand_id=m.brand_id, mention_id=m.id, comment_id=None,
                   action=_action_map.get(body.action, body.action),
                   actor=getattr(user, "email", "") or "", text=m.draft)
    session.commit()
    return {"ok": True}


@router.post("/mentions/{mention_id}/regenerate")
def regenerate_draft(mention_id: int, user: User = Depends(current_user),
                     session: Session = Depends(db)):
    m     = _owned_mention(session, mention_id, user)
    brand = session.get(Brand, m.brand_id)
    dr = generate_draft(
        m.text, m.category or "neutral", m.tone, m.confidence or 0.0,
        brand.tone_examples_list() if brand else [],
        recent_edits(session, m.brand_id),
        source=m.source, competitor=m.competitor,
        brand_name=brand.name if brand else None,
    )
    if not dr:
        raise HTTPException(503, "Draft generation unavailable — set LLM_API_KEY in backend/.env")
    m.draft, m.draft_flag = dr.text, dr.flag
    session.commit()
    return {"draft": m.draft, "draft_flag": m.draft_flag}


@router.get("/mentions/{mention_id}/comments")
def get_comments(mention_id: int, refresh: int = 0, include_hidden: int = 0,
                 user: User = Depends(current_user),
                 session: Session = Depends(db)):
    m = _owned_mention(session, mention_id, user)
    if refresh or not m.comment_rows:
        try:
            _fetch_and_store_comments_for_mention(session, m)
        except Exception:
            log.exception("Comment fetch failed for mention %s", mention_id)
        session.refresh(m)
    rows = (m.comment_rows if include_hidden
            else [c for c in m.comment_rows if not getattr(c, "is_spam", False)])
    return [_comment_card(c) for c in rows]


# ---------------------------------------------------------------------------
# ── Opportunities ────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.get("/opportunities")
def opportunities(brand_id: int, user: User = Depends(current_user),
                  session: Session = Depends(db)):
    _owned_brand(session, brand_id, user)
    rows = (
        session.query(BrandComment).join(BrandMention)
        .filter(BrandMention.brand_id == brand_id,
                BrandComment.is_opportunity.is_(True),
                BrandComment.is_spam.is_(False))
        .order_by(BrandComment.likes.desc())
        .all()
    )
    out = []
    for c in rows:
        mm = c.mention
        card = _comment_card(c)
        card.update({
            "mention_id": mm.id,
            "post_title": (mm.text[:80] + "…") if len(mm.text) > 80 else mm.text,
            "platform":   mm.platform,
            "source":     mm.source or "competitor",
            "competitor": mm.competitor,
            "post_url":   _post_url(mm),
        })
        out.append(card)
    return out


# ---------------------------------------------------------------------------
# ── Comments ─────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.post("/comments/{comment_id}/action")
def comment_action(comment_id: int, body: CommentActionBody,
                   user: User = Depends(current_user),
                   session: Session = Depends(db)):
    c = session.get(BrandComment, comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    mention = _owned_mention(session, c.mention_id, user)
    actor = getattr(user, "email", "") or ""
    if body.action == "approve":
        if body.draft and body.draft != c.draft:
            session.add(BrandDraftEdit(
                mention_id=c.mention_id,
                brand_id=mention.brand_id if mention else None,
                category="comment", original=c.draft or "", edited=body.draft,
            ))
        c.draft  = body.draft or c.draft
        c.status = "sent"
        log_engagement(session, brand_id=mention.brand_id if mention else None,
                       mention_id=c.mention_id, comment_id=c.id,
                       action="approved", actor=actor, text=c.draft)
    elif body.action == "posted":
        c.draft  = body.draft or c.draft
        c.status = "posted"
        log_engagement(session, brand_id=mention.brand_id if mention else None,
                       mention_id=c.mention_id, comment_id=c.id,
                       action="posted", actor=actor, text=c.draft)
    elif body.action == "skip":
        c.status = "skipped"
        log_engagement(session, brand_id=mention.brand_id if mention else None,
                       mention_id=c.mention_id, comment_id=c.id,
                       action="skipped", actor=actor, text=c.draft)
    else:
        raise HTTPException(400, f"Unknown action: {body.action}")
    session.commit()
    return {"ok": True}


@router.post("/comments/{comment_id}/regenerate")
def regenerate_comment(comment_id: int, user: User = Depends(current_user),
                       session: Session = Depends(db)):
    c = session.get(BrandComment, comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    mention = _owned_mention(session, c.mention_id, user)
    brand   = session.get(Brand, mention.brand_id) if mention else None
    dr = generate_draft(
        c.text, "comment", c.sentiment, 0.9,
        brand.tone_examples_list() if brand else [],
        recent_edits(session, mention.brand_id) if mention else [],
        source=mention.source if mention else "brand",
        competitor=mention.competitor if mention else None,
        brand_name=brand.name if brand else None,
    )
    if not dr:
        raise HTTPException(503, "Draft generation unavailable — set LLM_API_KEY in backend/.env")
    c.draft, c.draft_flag = dr.text, dr.flag
    session.commit()
    return {"draft": c.draft, "draft_flag": c.draft_flag}


# ---------------------------------------------------------------------------
# ── Debug ────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.get("/debug/tikhub")
def debug_tikhub(keyword: str = "озон", platform: str = "tiktok"):
    provider = _get_provider()
    try:
        page = provider.search(keyword, "keyword", None, platform)
        return {
            "provider":    provider.__class__.__name__,
            "platform":    platform,
            "token_set":   bool(TIKHUB_TOKEN),
            "posts_found": len(page.posts),
            "sample": [{"id": p.post_id, "text": p.text[:80], "views": p.views}
                       for p in page.posts[:5]],
        }
    except Exception as e:
        return {"error": str(e), "provider": provider.__class__.__name__,
                "platform": platform}


# ---------------------------------------------------------------------------
# ── Search ───────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.get("/search")
def search(query: str, user: User = Depends(current_user),
           session: Session = Depends(db)):
    results = (
        session.query(BrandMention).join(Brand)
        .filter(Brand.user_id == user.id, BrandMention.text.ilike(f"%{query}%"))
        .limit(20)
        .all()
    )
    return [_mention_card(m) for m in results]


# ---------------------------------------------------------------------------
# ── Analytics ────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.get("/analytics")
def analytics(brand_id: int, user: User = Depends(current_user),
              session: Session = Depends(db)):
    _owned_brand(session, brand_id, user)
    mentions = (
        session.query(BrandMention)
        .filter(BrandMention.brand_id == brand_id,
                BrandMention.status != "rejected")
        .all()
    )
    now  = datetime.now(timezone.utc)
    wk   = now - timedelta(days=7)
    prev = now - timedelta(days=14)
    created = lambda m: _aware(m.created_at) or now

    last7 = [m for m in mentions if created(m) >= wk]
    prev7 = [m for m in mentions if prev <= created(m) < wk]
    neg7      = [m for m in last7 if m.tone == "negative"]
    neg_prev  = [m for m in prev7 if m.tone == "negative"]

    sent_comments = (
        session.query(BrandComment).join(BrandMention)
        .filter(BrandMention.brand_id == brand_id,
                BrandComment.status.in_(("sent", "posted"))).count()
    )
    sent_total = sum(1 for m in mentions if m.status == "sent") + sent_comments
    hot = sum(1 for m in mentions if m.is_hot)

    def _d(cur, prev_val, good_up=True):
        diff = cur - prev_val
        return {"delta": f"{'+' if diff >= 0 else ''}{diff}",
                "up": (diff >= 0) == good_up}

    stats = [
        {"key": "total", "label": "Упоминаний за 7 дней", "value": str(len(last7)),
         **_d(len(last7), len(prev7))},
        {"key": "neg",   "label": "Негативных",           "value": str(len(neg7)),
         **_d(len(neg7), len(neg_prev), good_up=False)},
        {"key": "sent",  "label": "Ответов отправлено",   "value": str(sent_total),
         "delta": f"+{sent_total}", "up": True},
        {"key": "hot",   "label": "Горячих сейчас",       "value": str(hot),
         "delta": f"{hot}", "up": hot == 0},
    ]

    days = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]
    series = {"days": [], "neg": [], "pos": [], "neu": []}
    for d in days:
        on_day = [m for m in mentions if created(m).date() == d]
        series["days"].append(WEEKDAYS_RU[d.weekday()])
        series["neg"].append(sum(1 for m in on_day if m.tone == "negative"))
        series["pos"].append(sum(1 for m in on_day if m.tone == "positive"))
        series["neu"].append(sum(1 for m in on_day if m.tone == "neutral"))

    pcounts: dict[str, int] = defaultdict(int)
    for m in mentions:
        pcounts[m.platform] += 1
    ptotal = sum(pcounts.values()) or 1
    platforms_out = [
        {"key": p, "name": PLATFORM_NAMES.get(p, p.title()),
         "pct": round(c * 100 / ptotal)}
        for p, c in sorted(pcounts.items(), key=lambda x: -x[1])
    ]

    comp: dict[str, dict] = defaultdict(lambda: {"mentions": 0, "neg": 0})
    for m in mentions:
        if m.source == "competitor" and m.competitor:
            comp[m.competitor]["mentions"] += 1
            if m.tone == "negative":
                comp[m.competitor]["neg"] += 1
    competitors_out = []
    for name, d in sorted(comp.items(), key=lambda x: -x[1]["mentions"]):
        negpct = round(d["neg"] * 100 / d["mentions"]) if d["mentions"] else 0
        competitors_out.append({"name": name, "mentions": d["mentions"],
                                 "neg": negpct,
                                 "trend": "up" if negpct >= 50 else "down"})

    top = sorted(
        [m for m in mentions if m.source == "brand" and m.tone == "negative"],
        key=lambda m: -(m.severity or 0),
    )[:4]
    top_negative = [{
        "id": m.id,
        "title": (m.text[:80] + "…") if len(m.text) > 80 else m.text,
        "author": m.author, "platform": m.platform, "views": m.views,
        "severity": round(m.severity or 0), "negativeCommentPct": 72,
    } for m in top]

    return {
        "has_data":    len(mentions) > 0,
        "stats":       stats,
        "series":      series,
        "platforms":   platforms_out,
        "competitors": competitors_out,
        "top_negative": top_negative,
    }


# ---------------------------------------------------------------------------
# ── City Explorer ────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.post("/explore/city")
def explore_city(body: ExploreCityBody, background_tasks: BackgroundTasks,
                 user: User = Depends(current_user),
                 session: Session = Depends(db)):
    from .. import explore
    key, _ = explore.normalize_city(body.city)
    if not key:
        raise HTTPException(400, "City is required")
    if not body.refresh:
        latest = (session.query(CityReport).filter_by(city=key)
                  .order_by(CityReport.created_at.desc()).first())
        if latest:
            created = latest.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created).days
            if age_days < CITY_REPORT_TTL_DAYS:
                return {**_city_report_card(latest), "cached": True}
    background_tasks.add_task(_run_city_explore, body.city)
    return {"status": "collecting", "city": body.city.strip(),
            "message": "Сбор запущен, обновите страницу через 30–60 секунд"}


@router.get("/explore/cities")
def explore_cities(user: User = Depends(current_user),
                   session: Session = Depends(db)):
    rows = session.query(CityReport).order_by(CityReport.created_at.desc()).all()
    seen, out = set(), []
    for r in rows:
        if r.city in seen:
            continue
        seen.add(r.city)
        out.append({"city": r.city, "display_city": r.display_city,
                    "post_count": r.post_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None})
        if len(out) >= 30:
            break
    return out


# ---------------------------------------------------------------------------
# ── Digests ──────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.post("/brands/{brand_id}/digest", response_model=ReportOut)
def create_digest(brand_id: int, user: User = Depends(current_user),
                  session: Session = Depends(db)):
    _owned_brand(session, brand_id, user)
    from .digests import build_brand_digest
    from ..core.llm import LLMNotConfigured
    try:
        report = build_brand_digest(session, brand_id)
    except LLMNotConfigured:
        raise HTTPException(503, "Digest generation unavailable — set LLM_API_KEY in backend/.env")
    if report is None:
        raise HTTPException(404, "No active stories to summarize")
    session.commit()
    return ReportOut(id=report.id, kind=report.kind, body=report.body,
                     created_at=report.created_at, story_id=report.story_id)


@router.get("/brands/{brand_id}/digests", response_model=list[ReportOut])
def list_digests(brand_id: int, user: User = Depends(current_user),
                 session: Session = Depends(db)):
    _owned_brand(session, brand_id, user)
    rows = (session.query(BrandReport)
            .filter(BrandReport.brand_id == brand_id, BrandReport.kind == "digest")
            .order_by(BrandReport.created_at.desc()).limit(50).all())
    return [ReportOut(id=r.id, kind=r.kind, body=r.body,
                      created_at=r.created_at, story_id=r.story_id) for r in rows]


# ---------------------------------------------------------------------------
# ── Brand Stories (brand_id path) ────────────────────────────────────────────
# ---------------------------------------------------------------------------

@router.get("/stories", response_model=list[BrandStoryOut])
def list_brand_stories(brand_id: int,
                       user: User = Depends(current_user),
                       session: Session = Depends(db)):
    """List active BrandStories for a brand. brand_id is required."""
    _owned_brand(session, brand_id, user)
    rows = (
        session.query(BrandStory)
        .filter(BrandStory.brand_id == brand_id, BrandStory.status == "active")
        .order_by(BrandStory.is_anomaly.desc(), BrandStory.last_seen_at.desc())
        .all()
    )
    return [BrandStoryOut(**_story_fields(session, st)) for st in rows]


@router.get("/stories/{story_id}", response_model=BrandStoryDetailOut)
def get_brand_story(story_id: int, user: User = Depends(current_user),
                    session: Session = Depends(db)):
    st = _owned_brand_story(session, story_id, user)
    points = (session.query(BrandStoryPoint)
              .filter(BrandStoryPoint.story_id == story_id)
              .order_by(BrandStoryPoint.bucket_start).all())
    incidents = (session.query(BrandIncident)
                 .filter(BrandIncident.story_id == story_id)
                 .order_by(BrandIncident.last_seen_at.desc()).all())
    return BrandStoryDetailOut(
        **_story_fields(session, st),
        points=[BrandStoryPointOut(
            bucket_start=p.bucket_start, mention_count=p.mention_count,
            avg_sentiment=p.avg_sentiment, source_count=p.source_count,
        ) for p in points],
        incidents=[BrandIncidentOut(
            id=i.id, title=i.title, sentiment=i.sentiment,
            post_count=i.post_count, last_seen_at=i.last_seen_at,
        ) for i in incidents],
        sources=_story_sources(session, story_id),
    )


@router.post("/stories/recompute")
def recompute_brand_stories(brand_id: int,
                             user: User = Depends(current_user),
                             session: Session = Depends(db)):
    """Trigger brand story clustering for a brand (manual, best-effort)."""
    _owned_brand(session, brand_id, user)
    from .stories import update_stories
    update_stories(session, brand_id)
    return {"ok": True, "brand_id": brand_id}


@router.post("/stories/{story_id}/summarize", response_model=BrandStoryOut)
def summarize_brand_story(story_id: int, user: User = Depends(current_user),
                          session: Session = Depends(db)):
    """LLM 'what happened' summary for one BrandStory (manual, opt-in).
    Uses the same credibility.summarize_story path as legacy but on BrandStory.
    503 if no LLM key.
    """
    st = _owned_brand_story(session, story_id, user)
    from .. import credibility
    from ..core.llm import LLMNotConfigured
    try:
        credibility.summarize_story(session, st)
    except LLMNotConfigured:
        raise HTTPException(503, "LLM not configured")
    session.commit()
    return BrandStoryOut(**_story_fields(session, st))


@router.post("/stories/{story_id}/assess", response_model=BrandStoryOut)
def assess_brand_story(story_id: int, user: User = Depends(current_user),
                       session: Session = Depends(db)):
    """LLM credibility assessment for one BrandStory.

    BrandStory has no credibility columns — this endpoint keeps the API shape
    for frontend compatibility but is a no-op (returns 501).
    Phase 6 can gate this button on brand vs. topic story type.
    """
    raise HTTPException(501, "Credibility assessment not available for brand stories "
                             "(BrandStory has no credibility columns)")
