"""Seed: create demo account only. No brands, no mentions."""
from __future__ import annotations
from sqlalchemy.orm import Session
from .models import Brand, User
from .auth import hash_password

DEMO_EMAIL    = "demo@echo.app"
DEMO_PASSWORD = "demo12345"


def run(session: Session) -> None:
    """Startup hooks that must run after FastAPI app exists."""
    from .api import app, _get_tg_provider
    from .news import router as news_router
    app.state.get_tg_provider = _get_tg_provider
    if not getattr(app.state, "news_router_registered", False):
        app.include_router(news_router)
        app.state.news_router_registered = True


def ensure_demo_user(session: Session) -> User:
    """Idempotent: create demo login and attach orphan brands to it."""
    user = session.query(User).filter_by(email=DEMO_EMAIL).first()
    if not user:
        user = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD))
        session.add(user)
        session.flush()
    for b in session.query(Brand).filter(Brand.user_id.is_(None)).all():
        b.user_id = user.id
    session.commit()
    return user

