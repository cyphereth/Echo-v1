from __future__ import annotations
import json, logging, os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import init_db, get_session
from .models import Brand, Probe, Mention, DraftEdit, Comment, User
from .auth import hash_password, verify_password, create_token, decode_token
from .classify import classify
from .drafts import generate_draft
from .pipeline import classify_and_draft, recent_edits
from .scoring import Snapshot, severity as calc_severity, phase as calc_phase
from .hotwatch import rescore_mention
from . import seed as seed_module

log = logging.getLogger(__name__)

TIKHUB_TOKEN = os.getenv("TIKHUB_TOKEN", "")

def _get_provider():
    if TIKHUB_TOKEN:
        from .providers.tikhub import TikHubProvider
        return TikHubProvider(TIKHUB_TOKEN)
    from .providers.mock import MockProvider
    return MockProvider()

app = FastAPI(title="Echo API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_scheduler = None


@app.on_event("startup")
def on_startup():
    init_db()
    session = get_session()
    try:
        seed_module.run(session)
        seed_module.ensure_demo_user(session)   # idempotent: demo login + backfill owners
    finally:
        session.close()

    # Background auto-collect. Harmless when idle — only runs probes for brands
    # with auto_collect=True (default off), so no surprise API usage.
    global _scheduler
    if os.getenv("ENABLE_SCHEDULER", "1") == "1" and _scheduler is None:
        from .scheduler import Scheduler
        _scheduler = Scheduler(_get_provider(), tick_sec=int(os.getenv("SCHEDULER_TICK_SEC", "60")))
        _scheduler.start()
        log.info("Auto-collect scheduler started (tick=%ss)", _scheduler._tick_sec)


# ── Dependency ────────────────────────────────────────────────────────────────

def db() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


# ── Auth ──────────────────────────────────────────────────────────────────────

def current_user(authorization: str = Header(None), session: Session = Depends(db)) -> User:
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


def _owned_mention(session: Session, mention_id: int, user: User) -> Mention:
    m = session.get(Mention, mention_id)
    if not m:
        raise HTTPException(404, "Mention not found")
    _owned_brand(session, m.brand_id, user)
    return m


class AuthBody(BaseModel):
    email:    str
    password: str

def _user_card(u: User) -> dict:
    return {"id": u.id, "email": u.email}

@app.post("/auth/register")
def register(body: AuthBody, session: Session = Depends(db)):
    email = body.email.strip().lower()
    if not email or not body.password:
        raise HTTPException(400, "Email and password required")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if session.query(User).filter_by(email=email).first():
        raise HTTPException(409, "Email already registered")
    user = User(email=email, password_hash=hash_password(body.password))
    session.add(user)
    session.commit()
    return {"token": create_token(user.id, user.email), "user": _user_card(user)}

@app.post("/auth/login")
def login(body: AuthBody, session: Session = Depends(db)):
    email = body.email.strip().lower()
    user = session.query(User).filter_by(email=email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"token": create_token(user.id, user.email), "user": _user_card(user)}

@app.get("/auth/me")
def auth_me(user: User = Depends(current_user)):
    return _user_card(user)


# ── Serialization ─────────────────────────────────────────────────────────────

def _velocity(mention: Mention) -> float:
    snaps = sorted(mention.snapshots, key=lambda s: s.ts)
    if len(snaps) < 2:
        return 0.0
    dt_min = (snaps[-1].ts - snaps[-2].ts).total_seconds() / 60
    if dt_min <= 0:
        return 0.0
    return round((snaps[-1].views - snaps[-2].views) / dt_min, 1)

def _post_url(m: Mention) -> Optional[str]:
    if m.platform == "tiktok":
        return f"https://www.tiktok.com/@{m.author}/video/{m.post_id}"
    if m.platform == "instagram":
        # post_id is the shortcode for IG mentions collected via TikHub.
        return f"https://www.instagram.com/p/{m.post_id}/"
    return None

import re as _re

def _clean_list(items) -> list[str]:
    """Normalize a list of terms: split comma-joined entries, trim, drop empties, dedupe.

    Guards against AI or user input that puts several terms in one string
    (e.g. ['Aviasales, KupiBilet, Skyscanner']) which would otherwise become a
    single useless probe query.
    """
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
    """The brand lane is useless without the brand name. If no keyword already
    contains the brand name (case-insensitive), prepend it."""
    nm = (name or "").strip()
    if not nm:
        return keywords
    low = nm.lower()
    if any(low in (k or "").lower() for k in keywords):
        return keywords
    return [nm] + list(keywords)


def _parse_handle(s: str) -> str:
    """Extract a username from @name, a tiktok/instagram URL, or a raw string."""
    s = (s or "").strip()
    if not s:
        return ""
    if "/" in s:
        m = _re.search(r'(?:tiktok\.com/@|instagram\.com/)([^/?#]+)', s)
        if m:
            return m.group(1).lstrip("@")
        s = s.rstrip("/").split("/")[-1]
    return s.lstrip("@")

def _profile_with_claude(name_hint: str, bio: str, followers: int,
                         posts_text: list[str], brand_replies: list[str],
                         sentiment: dict) -> dict:
    """Distill a brand profile from scanned account content via Claude. Returns {} on failure."""
    import httpx as _httpx
    from .drafts import LLM_API_KEY, LLM_API_URL
    if not LLM_API_KEY:
        return {}

    system = (
        "Ты аналитик бренда. На основе реального контента аккаунта в соцсетях определи "
        "профиль для мониторинга упоминаний и генерации ответов. Отвечай ТОЛЬКО валидным JSON без markdown."
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
        'niche_keywords подбери ШИРОКО: тематика + индустрия + смежные интересы ЦА + '
        'intent-фразы по сфере (как люди ищут такое: для еды «где поесть», «куда сходить '
        'на выходных», «посоветуйте ресторан»).\n'
        'Определи город (geo), если бизнес локальный — иначе "". Для локального '
        'сервисного бизнеса сгенерируй category_terms (4-6 категорий ниши города), '
        'иначе [].\n'
        'Сгенерируй audience_terms — 8-12 широких тем целевой аудитории (для салона: '
        'женское, лайфстайл, мода, уют, дети, отношения, готовка, шопинг, фитнес). '
        'Для нетематических — [].\n'
        'Определи рынок: если бренд русскоязычный или ориентирован на СНГ — '
        'верни "market":"ru" и предлагай ТОЛЬКО русскоязычных конкурентов из СНГ '
        '(без иностранных). Иначе "market":"global".\n'
        'Верни JSON: {"name":"","voice_description":"","tone_examples":[],'
        '"keywords":[],"hashtags":[],"competitors":[],"niche_keywords":[],"sphere":"","geo":"","category_terms":[],"audience_terms":[],"market":""}'
    )

    def _call():
        resp = _httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
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

def _mention_card(m: Mention) -> dict:
    snaps = sorted(m.snapshots, key=lambda s: s.ts)
    snap_views = [s.views for s in snaps] if snaps else [
        round(m.views * 0.4), round(m.views * 0.7), m.views
    ]
    return {
        "id":           m.id,
        "platform":     m.platform,
        "author":       m.author,
        "followers":    m.followers,
        "created_at":   m.created_at.isoformat() + "Z" if m.created_at.tzinfo is None else m.created_at.isoformat(),
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

def _brand_card(b: Brand) -> dict:
    return {
        "id":          b.id,
        "name":        b.name,
        "keywords":      b.keywords_list(),
        "hashtags":      b.hashtags_list(),
        "exclusions":    b.exclusions_list(),
        "competitors":   b.competitors_list(),
        "niche_keywords": b.niche_keywords_list(),
        "tone_examples": b.tone_examples_list(),
        "market":        getattr(b, "market", "global") or "global",
        "sphere":        getattr(b, "sphere", "") or "",
        "geo":           getattr(b, "geo", "") or "",
        "category_terms": b.category_terms_list() if hasattr(b, "category_terms_list") else [],
        "audience_terms": b.audience_terms_list() if hasattr(b, "audience_terms_list") else [],
        "followers":      getattr(b, "followers", 0) or 0,
        "local_mode":     bool(getattr(b, "local_mode", False)),
        "auto_collect":  bool(b.auto_collect),
        "probes":        [{"id": p.id, "query": p.query, "kind": p.kind, "source": p.source, "platform": p.platform} for p in b.probes],
    }


# ── Probe building ────────────────────────────────────────────────────────────

# Monitor each term on every supported platform — one probe per (term, platform).
MONITORED_PLATFORMS = ("tiktok", "instagram")


def _rebuild_probes(session: Session, brand: Brand) -> None:
    """Replace a brand's probes from its current keywords / competitors / niche."""
    session.query(Probe).filter_by(brand_id=brand.id).delete()
    geo = (getattr(brand, "geo", "") or "").strip()
    # City is appended only to audience-discovery probes (category + niche) —
    # brand & named-competitor mentions don't depend on the city.
    def geoq(term):
        return f"{term} {geo}" if geo else term
    for pf in MONITORED_PLATFORMS:
        for kw in brand.keywords_list():
            session.add(Probe(brand_id=brand.id, platform=pf, kind="keyword", source="brand", query=kw))
        for comp in brand.competitors_list():
            session.add(Probe(brand_id=brand.id, platform=pf, kind="keyword", source="competitor", label=comp, query=comp))
        for cat in brand.category_terms_list():
            session.add(Probe(brand_id=brand.id, platform=pf, kind="keyword", source="competitor", label=cat, query=geoq(cat)))
        for term in brand.niche_keywords_list():
            session.add(Probe(brand_id=brand.id, platform=pf, kind="keyword", source="niche", label=term, query=geoq(term)))
        # Small local brands: broad city-audience probes (женское Казань, мода Казань).
        if getattr(brand, "local_mode", False) and geo:
            for term in brand.audience_terms_list():
                session.add(Probe(brand_id=brand.id, platform=pf, kind="keyword", source="niche", label=term, query=f"{term} {geo}"))
    session.flush()


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Brands ────────────────────────────────────────────────────────────────────

@app.get("/brands")
def list_brands(user: User = Depends(current_user), session: Session = Depends(db)):
    return [_brand_card(b) for b in session.query(Brand).filter_by(user_id=user.id).all()]

@app.get("/brands/{brand_id}")
def get_brand(brand_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    return _brand_card(_owned_brand(session, brand_id, user))


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

@app.post("/brands/{brand_id}/config")
def update_brand_config(brand_id: int, body: BrandConfigBody, user: User = Depends(current_user), session: Session = Depends(db)):
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
    if body.keywords       is not None: b.keywords       = json.dumps(_ensure_name_in_keywords(body.name or b.name, _clean_list(body.keywords)))
    # Rebuild probes (brand + competitor + niche) so collect picks up every source
    if any(v is not None for v in (body.keywords, body.competitors, body.niche_keywords, body.category_terms, body.geo, body.audience_terms, body.local_mode)):
        _rebuild_probes(session, b)
    session.commit()
    return _brand_card(b)


# ── AI Brand Suggest ──────────────────────────────────────────────────────────

def _extract_suggest_json(blocks: list[dict]) -> dict:
    """Pull the brand-suggest JSON out of Claude's response content blocks.
    With the web_search tool the model emits server_tool_use / web_search_tool_result
    blocks and writes its final JSON in the LAST text block.
    Raises ValueError if no text block; json.JSONDecodeError if the final block
    is not valid JSON (suggest_brand catches both and retries)."""
    texts = [b["text"] for b in blocks if b.get("type") == "text" and b.get("text")]
    if not texts:
        raise ValueError("no text block in suggest response")
    text = texts[-1].strip()
    text = text.lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(text)


def _build_suggest_payload(name: str) -> dict:
    """Anthropic Messages request for brand suggestion: web_search tool + a prompt
    that asks for large, relevance-validated term lists."""
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
        f'РАНЖИРУЙ все термины по релевантности и ОТСЕКАЙ явно нерелевантное '
        f'(омонимы, мусор, не относящееся к бренду). '
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


# Upstream statuses worth retrying when calling the suggest LLM.
_SUGGEST_TRANSIENT_STATUS = {429, 500, 502, 503, 504, 529}

def _is_transient_suggest_error(exc: Exception) -> bool:
    """True if a /brands/suggest call failure is worth retrying: parse errors
    (empty/partial body), network/timeout errors, or transient HTTP statuses.
    Non-transient failures (e.g. 400 bad request) fail fast."""
    import httpx
    if isinstance(exc, (json.JSONDecodeError, KeyError, ValueError, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _SUGGEST_TRANSIENT_STATUS
    return False

def _suggest_with_retry(call, attempts: int = 3):
    """Run `call`, retrying transient failures up to `attempts` times. Re-raises
    the last error after exhausting retries, or immediately on a non-transient one."""
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


class SuggestBody(BaseModel):
    name: str

@app.post("/brands/suggest")
def suggest_brand(body: SuggestBody, user: User = Depends(current_user)):
    """Call Claude to suggest keywords/hashtags/competitors/niche for a brand name."""
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


class PreviewBody(BaseModel):
    keywords:  list[str] = []
    platforms: list[str] = ["tiktok", "instagram"]

@app.post("/brands/preview")
def preview_brand(body: PreviewBody, user: User = Depends(current_user)):
    """Search TikHub with given keywords and return up to 5 real posts. Nothing is stored in DB."""
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


class ScanBody(BaseModel):
    tiktok:    str = ""
    instagram: str = ""

@app.post("/brands/profile-scan")
def profile_scan(body: ScanBody, user: User = Depends(current_user)):
    """Scan brand's own accounts → Claude-distilled profile for onboarding."""
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

    profile = _profile_with_claude(name_hint, bio, followers, posts_text, brand_replies, sentiment)
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

@app.post("/onboarding")
def onboarding(body: OnboardingBody, user: User = Depends(current_user), session: Session = Depends(db)):
    existing = session.query(Brand).filter_by(user_id=user.id).first()
    if existing:
        raise HTTPException(409, "Brand already exists")
    b = Brand(
        user_id=user.id,
        name=body.name,
        keywords=json.dumps(_ensure_name_in_keywords(body.name, _clean_list(body.keywords))),
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
    return _brand_card(b)


# ── Collect (trigger TikHub search now) ───────────────────────────────────────

def _run_collect(brand_id: int) -> dict:
    """Search TikHub for all brand keywords, classify and store results."""
    from .collector import collect_probe
    from .models import MentionSnapshot

    session = get_session()
    try:
        brand = session.get(Brand, brand_id)
        if not brand:
            return {"error": "brand not found"}

        provider = _get_provider()
        # collector.py uses upsert (on_conflict_do_update) — no pre-delete needed.
        # Deleting before collect means losing all data if TikHub rate-limits mid-run.
        probes = session.query(Probe).filter_by(brand_id=brand_id).all()

        # If no probes yet, build them (brand + competitor + niche) on the fly
        if not probes:
            _rebuild_probes(session, brand)
            probes = session.query(Probe).filter_by(brand_id=brand_id).all()

        total = 0
        for probe in probes:
            try:
                log.info("Collecting probe '%s' via %s", probe.query, provider.__class__.__name__)
                count = collect_probe(session, probe, provider)
                log.info("Probe '%s' → %d new mentions", probe.query, count)
                total += count
            except Exception as e:
                log.warning("Probe '%s' failed: %s", probe.query, e)

        # Best-effort geo: IG posts geotagged in the brand's city (fail-open).
        try:
            from .collector import collect_geo
            total += collect_geo(session, brand, provider)
        except Exception as e:
            log.warning("collect_geo failed: %s", e)

        # Classify + draft (shared with the scheduler)
        result = classify_and_draft(session, brand_id)
        return {"collected": total, **result}
    finally:
        session.close()


@app.post("/brands/{brand_id}/collect")
def collect_brand(brand_id: int, background_tasks: BackgroundTasks, user: User = Depends(current_user), session: Session = Depends(db)):
    b = _owned_brand(session, brand_id, user)
    background_tasks.add_task(_run_collect, brand_id)
    return {"status": "collecting", "brand": b.name, "using_tikhub": bool(TIKHUB_TOKEN)}


class AutoCollectBody(BaseModel):
    enabled: bool

@app.post("/brands/{brand_id}/autocollect")
def set_autocollect(brand_id: int, body: AutoCollectBody, user: User = Depends(current_user), session: Session = Depends(db)):
    b = _owned_brand(session, brand_id, user)
    b.auto_collect = body.enabled
    # Make sure probes exist so the scheduler has something to run
    if body.enabled and not b.probes:
        _rebuild_probes(session, b)
    session.commit()
    return {"auto_collect": b.auto_collect}


# ── Inbox ─────────────────────────────────────────────────────────────────────

@app.get("/inbox")
def inbox(brand_id: int, include_hidden: int = 0, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_brand(session, brand_id, user)
    q = (
        session.query(Mention)
        .filter(Mention.brand_id == brand_id, Mention.status != "rejected")
    )
    if not include_hidden:
        q = q.filter(Mention.is_spam.is_(False))
    mentions = q.order_by(Mention.severity.desc()).all()
    pr  = [_mention_card(m) for m in mentions if m.lane == "pr"]
    smm = [_mention_card(m) for m in mentions if m.lane in ("smm", "none")]
    return {"pr": pr, "smm": smm}


# ── Mentions ──────────────────────────────────────────────────────────────────

@app.get("/mentions/{mention_id}")
def get_mention(mention_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    return _mention_card(_owned_mention(session, mention_id, user))


class ActionBody(BaseModel):
    action: str                 # approve | reject | pr
    draft:  Optional[str] = None

@app.post("/mentions/{mention_id}/action")
def post_action(mention_id: int, body: ActionBody, user: User = Depends(current_user), session: Session = Depends(db)):
    m = _owned_mention(session, mention_id, user)

    if body.action == "approve":
        original = m.draft
        if body.draft and body.draft != m.draft:
            session.add(DraftEdit(
                mention_id=m.id, brand_id=m.brand_id,
                category=m.category,
                original=original or "",
                edited=body.draft,
            ))
        m.draft  = body.draft or m.draft
        m.status = "sent"

    elif body.action == "reject":
        m.status = "rejected"

    elif body.action == "pr":
        m.lane      = "pr"
        m.status    = "new"
        m.draft_flag = None

    else:
        raise HTTPException(400, f"Unknown action: {body.action}")

    from .engagement import log_engagement
    _action_map = {"approve": "approved", "reject": "rejected", "pr": "pr"}
    log_engagement(session, brand_id=m.brand_id, mention_id=m.id, comment_id=None,
                   action=_action_map.get(body.action, body.action),
                   actor=getattr(user, "email", "") or "", text=m.draft)
    session.commit()
    return {"ok": True}


@app.post("/mentions/{mention_id}/regenerate")
def regenerate_draft(mention_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    m = _owned_mention(session, mention_id, user)
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


# ── Comments ──────────────────────────────────────────────────────────────────

MAX_COMMENT_DRAFTS = int(os.getenv("MAX_COMMENT_DRAFTS", "10"))
_STATUS_OUT = {"sent": "approved", "posted": "posted", "skipped": "skipped", "pending": "pending"}


def _minutes_ago(dt: datetime) -> int:
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 60))


def _comment_card(c: Comment) -> dict:
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


def _fetch_and_store_comments(session: Session, mention: Mention) -> int:
    """Pull comments from the provider, classify sentiment, draft relevant replies, store."""
    provider = _get_provider()
    fetched  = provider.fetch_comments(mention.post_id, None, mention.platform)
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
    # Tiny-account floor for comments: 0 < followers < 100 → hide (off in local_mode).
    # followers==0 (no data, common for comments) is not penalized.
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
    fetched.sort(key=lambda fc: fc.likes, reverse=True)
    for fc in new:
        is_spam = cheap_spam.get(fc.comment_id) or ad_spam.get(fc.comment_id, False)
        sentiment = classify(fc.text).tone
        draft = draft_flag = opp_reason = None
        is_opp = False

        if is_spam:
            pass  # stored hidden, no draft
        elif is_comp_niche and not engaged:
            # Honest engagement: one brand reply per thread, prefilter cheaply,
            # then let Claude decide and write an openly-branded reply. Skip
            # near-duplicate drafts so the brand never repeats a canned line.
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
            # brand-lane: reply to negative comments as before
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


@app.get("/mentions/{mention_id}/comments")
def get_comments(mention_id: int, refresh: int = 0, include_hidden: int = 0, user: User = Depends(current_user), session: Session = Depends(db)):
    m = _owned_mention(session, mention_id, user)
    if refresh or not m.comment_rows:
        try:
            _fetch_and_store_comments(session, m)
        except Exception:
            log.exception("Comment fetch failed for mention %s", mention_id)
        session.refresh(m)
    rows = m.comment_rows if include_hidden else [c for c in m.comment_rows if not getattr(c, "is_spam", False)]
    return [_comment_card(c) for c in rows]


@app.get("/opportunities")
def opportunities(brand_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    """All opportunity comments (competitor/niche intercepts) for a brand, grouped
    by their source mention — feeds the Queue's 'Возможности' view."""
    _owned_brand(session, brand_id, user)
    rows = (
        session.query(Comment).join(Mention)
        .filter(Mention.brand_id == brand_id, Comment.is_opportunity.is_(True),
                Comment.is_spam.is_(False))
        .order_by(Comment.likes.desc())
        .all()
    )
    out = []
    for c in rows:
        m = c.mention
        card = _comment_card(c)
        card.update({
            "mention_id": m.id,
            "post_title": (m.text[:80] + "…") if len(m.text) > 80 else m.text,
            "platform":   m.platform,
            "source":     m.source or "competitor",
            "competitor": m.competitor,
            "post_url":   _post_url(m),
        })
        out.append(card)
    return out


class CommentActionBody(BaseModel):
    action: str                 # approve | posted | skip
    draft:  Optional[str] = None

@app.post("/comments/{comment_id}/action")
def comment_action(comment_id: int, body: CommentActionBody, user: User = Depends(current_user), session: Session = Depends(db)):
    c = session.get(Comment, comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    mention = _owned_mention(session, c.mention_id, user)
    actor = getattr(user, "email", "") or ""
    from .engagement import log_engagement
    if body.action == "approve":
        if body.draft and body.draft != c.draft:
            session.add(DraftEdit(
                mention_id=c.mention_id, brand_id=mention.brand_id if mention else None,
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


@app.post("/comments/{comment_id}/regenerate")
def regenerate_comment(comment_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    c = session.get(Comment, comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    _owned_mention(session, c.mention_id, user)
    mention = session.get(Mention, c.mention_id)
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


# ── Debug ─────────────────────────────────────────────────────────────────────

@app.get("/debug/tikhub")
def debug_tikhub(keyword: str = "озон", platform: str = "tiktok"):
    provider = _get_provider()
    try:
        page = provider.search(keyword, "keyword", None, platform)
        return {
            "provider":   provider.__class__.__name__,
            "platform":   platform,
            "token_set":  bool(TIKHUB_TOKEN),
            "posts_found": len(page.posts),
            "sample":     [{"id": p.post_id, "text": p.text[:80], "views": p.views} for p in page.posts[:5]],
        }
    except Exception as e:
        return {"error": str(e), "provider": provider.__class__.__name__, "platform": platform}


# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/search")
def search(query: str, user: User = Depends(current_user), session: Session = Depends(db)):
    results = (
        session.query(Mention).join(Brand)
        .filter(Brand.user_id == user.id, Mention.text.ilike(f"%{query}%"))
        .limit(20)
        .all()
    )
    return [_mention_card(m) for m in results]


# ── Analytics ─────────────────────────────────────────────────────────────────

WEEKDAYS_RU    = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
PLATFORM_NAMES = {"tiktok": "TikTok", "instagram": "Instagram", "telegram": "Telegram"}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@app.get("/analytics")
def analytics(brand_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_brand(session, brand_id, user)
    mentions = (
        session.query(Mention)
        .filter(Mention.brand_id == brand_id, Mention.status != "rejected")
        .all()
    )
    now  = datetime.now(timezone.utc)
    wk   = now - timedelta(days=7)
    prev = now - timedelta(days=14)
    created = lambda m: _aware(m.created_at) or now

    last7 = [m for m in mentions if created(m) >= wk]
    prev7 = [m for m in mentions if prev <= created(m) < wk]
    neg7, neg_prev = [m for m in last7 if m.tone == "negative"], [m for m in prev7 if m.tone == "negative"]

    sent_comments = (
        session.query(Comment).join(Mention)
        .filter(Mention.brand_id == brand_id, Comment.status == "sent").count()
    )
    sent_total = sum(1 for m in mentions if m.status == "sent") + sent_comments
    hot = sum(1 for m in mentions if m.is_hot)

    def _d(cur, prev, good_up=True):
        diff = cur - prev
        return {"delta": f"{'+' if diff >= 0 else ''}{diff}", "up": (diff >= 0) == good_up}

    stats = [
        {"key": "total", "label": "Упоминаний за 7 дней", "value": str(len(last7)), **_d(len(last7), len(prev7))},
        {"key": "neg",   "label": "Негативных",           "value": str(len(neg7)), **_d(len(neg7), len(neg_prev), good_up=False)},
        {"key": "sent",  "label": "Ответов отправлено",   "value": str(sent_total), "delta": f"+{sent_total}", "up": True},
        {"key": "hot",   "label": "Горячих сейчас",       "value": str(hot), "delta": f"{hot}", "up": hot == 0},
    ]

    # Sentiment by day (oldest → newest)
    days = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]
    series = {"days": [], "neg": [], "pos": [], "neu": []}
    for d in days:
        on_day = [m for m in mentions if created(m).date() == d]
        series["days"].append(WEEKDAYS_RU[d.weekday()])
        series["neg"].append(sum(1 for m in on_day if m.tone == "negative"))
        series["pos"].append(sum(1 for m in on_day if m.tone == "positive"))
        series["neu"].append(sum(1 for m in on_day if m.tone == "neutral"))

    # Platform split
    pcounts: dict[str, int] = defaultdict(int)
    for m in mentions:
        pcounts[m.platform] += 1
    ptotal = sum(pcounts.values()) or 1
    platforms = [
        {"key": p, "name": PLATFORM_NAMES.get(p, p.title()), "pct": round(c * 100 / ptotal)}
        for p, c in sorted(pcounts.items(), key=lambda x: -x[1])
    ]

    # Competitor breakdown
    comp: dict[str, dict] = defaultdict(lambda: {"mentions": 0, "neg": 0})
    for m in mentions:
        if m.source == "competitor" and m.competitor:
            comp[m.competitor]["mentions"] += 1
            if m.tone == "negative":
                comp[m.competitor]["neg"] += 1
    competitors = []
    for name, d in sorted(comp.items(), key=lambda x: -x[1]["mentions"]):
        negpct = round(d["neg"] * 100 / d["mentions"]) if d["mentions"] else 0
        competitors.append({"name": name, "mentions": d["mentions"], "neg": negpct,
                            "trend": "up" if negpct >= 50 else "down"})

    # Top negative brand mentions
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
        "has_data": len(mentions) > 0,
        "stats": stats,
        "series": series,
        "platforms": platforms,
        "competitors": competitors,
        "top_negative": top_negative,
    }
