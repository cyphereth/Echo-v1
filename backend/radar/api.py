from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .mock_data import BRANDS, get_mentions, apply_action

app = FastAPI(title="Echo Radar API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Brands ────────────────────────────────────────────────────────────────────

@app.get("/brands")
def list_brands():
    return BRANDS


@app.get("/brands/{brand_id}")
def get_brand(brand_id: int):
    brand = next((b for b in BRANDS if b["id"] == brand_id), None)
    if not brand:
        raise HTTPException(404, "Brand not found")
    return brand


# ── Inbox ─────────────────────────────────────────────────────────────────────

@app.get("/inbox")
def inbox(brand_id: int):
    mentions = get_mentions(brand_id)
    pr  = [m for m in mentions if m["lane"] == "pr"]
    smm = [m for m in mentions if m["lane"] in ("smm", "none")]
    return {"pr": pr, "smm": smm}


# ── Mentions ──────────────────────────────────────────────────────────────────

@app.get("/mentions/{mention_id}")
def get_mention(mention_id: int):
    for m in get_mentions(1) + get_mentions(2):
        if m["id"] == mention_id:
            return m
    raise HTTPException(404, "Mention not found")


class ActionBody(BaseModel):
    action: str
    draft: str | None = None


@app.post("/mentions/{mention_id}/action")
def post_action(mention_id: int, body: ActionBody):
    ok = apply_action(mention_id, body.action, body.draft)
    if not ok:
        raise HTTPException(400, f"Unknown action: {body.action}")
    return {"ok": True}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}
