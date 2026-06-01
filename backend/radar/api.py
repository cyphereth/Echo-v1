from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import init_db, get_session
from .models import Brand, Mention, DraftEdit
from . import seed as seed_module

log = logging.getLogger(__name__)

app = FastAPI(title="Echo Radar API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    session = get_session()
    try:
        seed_module.run(session)
    finally:
        session.close()


# ── Dependency ────────────────────────────────────────────────────────────────

def db() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


# ── Serialization ─────────────────────────────────────────────────────────────

def _velocity(mention: Mention) -> float:
    snaps = sorted(mention.snapshots, key=lambda s: s.ts)
    if len(snaps) < 2:
        return 0.0
    dt_min = (snaps[-1].ts - snaps[-2].ts).total_seconds() / 60
    if dt_min <= 0:
        return 0.0
    return round((snaps[-1].views - snaps[-2].views) / dt_min, 1)

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
        "is_hot":       m.is_hot,
        "views":        m.views,
        "velocity":     _velocity(m),
        "draft":        m.draft,
        "draft_flag":   m.draft_flag,
        "status":       m.status,
        "snapshots":    [{"views": v} for v in snap_views],
    }

def _brand_card(b: Brand) -> dict:
    return {
        "id":       b.id,
        "name":     b.name,
        "keywords": b.keywords_list(),
        "hashtags": b.hashtags_list(),
        "probes":   [{"id": p.id, "query": p.query, "kind": p.kind, "platform": p.platform} for p in b.probes],
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Brands ────────────────────────────────────────────────────────────────────

@app.get("/brands")
def list_brands(session: Session = Depends(db)):
    return [_brand_card(b) for b in session.query(Brand).all()]

@app.get("/brands/{brand_id}")
def get_brand(brand_id: int, session: Session = Depends(db)):
    b = session.get(Brand, brand_id)
    if not b:
        raise HTTPException(404, "Brand not found")
    return _brand_card(b)


class BrandConfigBody(BaseModel):
    keywords:  Optional[list[str]] = None
    hashtags:  Optional[list[str]] = None
    exclusions: Optional[list[str]] = None

@app.post("/brands/{brand_id}/config")
def update_brand_config(brand_id: int, body: BrandConfigBody, session: Session = Depends(db)):
    b = session.get(Brand, brand_id)
    if not b:
        raise HTTPException(404, "Brand not found")
    if body.keywords  is not None: b.keywords   = json.dumps(body.keywords)
    if body.hashtags  is not None: b.hashtags   = json.dumps(body.hashtags)
    if body.exclusions is not None: b.exclusions = json.dumps(body.exclusions)
    session.commit()
    return _brand_card(b)


class OnboardingBody(BaseModel):
    name:      str
    keywords:  list[str] = []
    hashtags:  list[str] = []

@app.post("/onboarding")
def onboarding(body: OnboardingBody, session: Session = Depends(db)):
    b = Brand(
        name=body.name,
        keywords=json.dumps(body.keywords),
        hashtags=json.dumps(body.hashtags),
    )
    session.add(b)
    session.commit()
    return _brand_card(b)


# ── Inbox ─────────────────────────────────────────────────────────────────────

@app.get("/inbox")
def inbox(brand_id: int, session: Session = Depends(db)):
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
def get_mention(mention_id: int, session: Session = Depends(db)):
    m = session.get(Mention, mention_id)
    if not m:
        raise HTTPException(404, "Mention not found")
    return _mention_card(m)


class ActionBody(BaseModel):
    action: str                 # approve | reject | pr
    draft:  Optional[str] = None

@app.post("/mentions/{mention_id}/action")
def post_action(mention_id: int, body: ActionBody, session: Session = Depends(db)):
    m = session.get(Mention, mention_id)
    if not m:
        raise HTTPException(404, "Mention not found")

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


# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/search")
def search(query: str, session: Session = Depends(db)):
    results = (
        session.query(Mention)
        .filter(Mention.text.ilike(f"%{query}%"))
        .limit(20)
        .all()
    )
    return [_mention_card(m) for m in results]
