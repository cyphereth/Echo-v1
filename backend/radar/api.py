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
        "auto_collect":  bool(b.auto_collect),
        "probes":        [{"id": p.id, "query": p.query, "kind": p.kind, "source": p.source, "platform": p.platform} for p in b.probes],
    }


# ── Probe building ────────────────────────────────────────────────────────────

# Monitor each term on every supported platform — one probe per (term, platform).
MONITORED_PLATFORMS = ("tiktok", "instagram")


def _rebuild_probes(session: Session, brand: Brand) -> None:
    """Replace a brand's probes from its current keywords / competitors / niche."""
    session.query(Probe).filter_by(brand_id=brand.id).delete()
    for pf in MONITORED_PLATFORMS:
        for kw in brand.keywords_list():
            session.add(Probe(brand_id=brand.id, platform=pf, kind="keyword", source="brand", query=kw))
        for comp in brand.competitors_list():
            session.add(Probe(brand_id=brand.id, platform=pf, kind="keyword", source="competitor", label=comp, query=comp))
        for term in brand.niche_keywords_list():
            session.add(Probe(brand_id=brand.id, platform=pf, kind="keyword", source="niche", label=term, query=term))
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

@app.post("/brands/{brand_id}/config")
def update_brand_config(brand_id: int, body: BrandConfigBody, user: User = Depends(current_user), session: Session = Depends(db)):
    b = _owned_brand(session, brand_id, user)
    if body.name           is not None: b.name           = body.name
    if body.hashtags       is not None: b.hashtags       = json.dumps(body.hashtags)
    if body.exclusions     is not None: b.exclusions     = json.dumps(body.exclusions)
    if body.competitors    is not None: b.competitors    = json.dumps(body.competitors)
    if body.niche_keywords is not None: b.niche_keywords = json.dumps(body.niche_keywords)
    if body.tone_examples  is not None: b.tone_examples  = json.dumps(body.tone_examples)
    if body.keywords       is not None: b.keywords       = json.dumps(body.keywords)
    # Rebuild probes (brand + competitor + niche) so collect picks up every source
    if any(v is not None for v in (body.keywords, body.competitors, body.niche_keywords)):
        _rebuild_probes(session, b)
    session.commit()
    return _brand_card(b)


class OnboardingBody(BaseModel):
    name:           str
    keywords:       list[str] = []
    hashtags:       list[str] = []
    competitors:    list[str] = []
    niche_keywords: list[str] = []

@app.post("/onboarding")
def onboarding(body: OnboardingBody, user: User = Depends(current_user), session: Session = Depends(db)):
    b = Brand(
        user_id=user.id,
        name=body.name,
        keywords=json.dumps(body.keywords),
        hashtags=json.dumps(body.hashtags),
        competitors=json.dumps(body.competitors),
        niche_keywords=json.dumps(body.niche_keywords),
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
        # When using real TikHub, clear stale/seeded mentions first
        if TIKHUB_TOKEN:
            session.query(Mention).filter_by(brand_id=brand_id).delete()
            session.commit()
            log.info("Cleared old mentions for brand %d before fresh collect", brand_id)
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
def inbox(brand_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    _owned_brand(session, brand_id, user)
    mentions = (
        session.query(Mention)
        .filter(Mention.brand_id == brand_id, Mention.status != "rejected")
        .order_by(Mention.severity.desc())
        .all()
    )
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
_STATUS_OUT = {"sent": "approved", "skipped": "skipped", "pending": "pending"}


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

    stored, drafted = 0, 0
    # Draft for negatives first (brand) / opportunities (competitor+niche)
    fetched.sort(key=lambda fc: fc.likes, reverse=True)
    for fc in fetched:
        if fc.comment_id in existing:
            continue
        sentiment = classify(fc.text).tone
        draft = draft_flag = None
        want_draft = (mention.source != "brand") or (sentiment == "negative")
        if want_draft and drafted < MAX_COMMENT_DRAFTS:
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
            created_at=fc.created_at,
        ))
        stored += 1
    session.commit()
    return stored


@app.get("/mentions/{mention_id}/comments")
def get_comments(mention_id: int, refresh: int = 0, user: User = Depends(current_user), session: Session = Depends(db)):
    m = _owned_mention(session, mention_id, user)
    if refresh or not m.comment_rows:
        try:
            _fetch_and_store_comments(session, m)
        except Exception:
            log.exception("Comment fetch failed for mention %s", mention_id)
        session.refresh(m)
    return [_comment_card(c) for c in m.comment_rows]


class CommentActionBody(BaseModel):
    action: str                 # approve | skip
    draft:  Optional[str] = None

@app.post("/comments/{comment_id}/action")
def comment_action(comment_id: int, body: CommentActionBody, user: User = Depends(current_user), session: Session = Depends(db)):
    c = session.get(Comment, comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    _owned_mention(session, c.mention_id, user)
    if body.action == "approve":
        if body.draft and body.draft != c.draft:
            mention = session.get(Mention, c.mention_id)
            session.add(DraftEdit(
                mention_id=c.mention_id, brand_id=mention.brand_id if mention else None,
                category="comment", original=c.draft or "", edited=body.draft,
            ))
        c.draft  = body.draft or c.draft
        c.status = "sent"
    elif body.action == "skip":
        c.status = "skipped"
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
