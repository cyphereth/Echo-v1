"""Auth API router — /auth/register, /auth/login, /auth/me.

Extracted from radar/api.py (Phase 5 teardown). Mount with:
    app.include_router(auth_router)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_session
from .auth import hash_password, verify_password, create_token, decode_token
from ..models import User

router = APIRouter()


# ── Dependency ────────────────────────────────────────────────────────────────

def db() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


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


# ── Schemas ───────────────────────────────────────────────────────────────────

class AuthBody(BaseModel):
    email:    str
    password: str


def _user_card(u: User) -> dict:
    return {"id": u.id, "email": u.email}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/auth/register")
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


@router.post("/auth/login")
def login(body: AuthBody, session: Session = Depends(db)):
    email = body.email.strip().lower()
    user = session.query(User).filter_by(email=email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"token": create_token(user.id, user.email), "user": _user_card(user)}


@router.get("/auth/me")
def auth_me(user: User = Depends(current_user)):
    return _user_card(user)
