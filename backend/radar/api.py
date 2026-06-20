from __future__ import annotations
import logging, os
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .core.db import init_db, get_session
from .models import User
from .core.auth import hash_password, verify_password, create_token, decode_token
from .news.api import router as news_router
from .brand.api import router as brand_router
from . import seed as seed_module

log = logging.getLogger(__name__)

app = FastAPI(title="Echo API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(news_router)
app.include_router(brand_router)

_scheduler = None


@app.on_event("startup")
def on_startup():
    init_db()
    session = get_session()
    try:
        seed_module.run(session)
        seed_module.ensure_demo_user(session)   # idempotent: demo login + backfill owners
        seed_module.ensure_default_topics(session)
    finally:
        session.close()

    # Background auto-collect. Harmless when idle — only runs probes for brands
    # with auto_collect=True (default off), so no surprise API usage.
    global _scheduler
    if os.getenv("ENABLE_SCHEDULER", "1") == "1" and _scheduler is None:
        from .core.scheduler import Scheduler
        from .brand.api import _get_provider, _get_tg_provider
        web_provider = None
        if os.getenv("WEB_SEARCH_API_KEY"):
            from .core.providers.web import WebSearchProvider
            web_provider = WebSearchProvider()
        _scheduler = Scheduler(_get_provider(), tick_sec=int(os.getenv("SCHEDULER_TICK_SEC", "60")),
                               tg_provider=_get_tg_provider(), web_provider=web_provider)
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


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── (brand endpoints moved to radar.brand.api router) ─────────────────────────
# ── (news  endpoints moved to radar.news.api  router) ─────────────────────────

# SENTINEL — keep this comment to mark the split point for Phase 5 teardown.

