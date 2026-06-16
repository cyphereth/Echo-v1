from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_session
from .models import NewsEvent, NewsTopic

router = APIRouter(prefix="/news", tags=["news"])

DEFAULT_TOPICS = [
    ("Военные действия", "военные действия БПЛА ПВО взрывы карта событий", "Военные события, ранние сигналы, ПВО, БПЛА."),
    ("Геополитика", "геополитика переговоры санкции международные отношения", "Международная повестка и политические риски."),
    ("Экономика", "экономика рынки рубль нефть инфляция ставки", "Макроэкономика, рынки, бизнес-риски."),
    ("Энергетика", "энергетика нефть газ электросети аварии", "Энергетика, инфраструктура, аварии и поставки."),
]

TYPE_RULES = [
    ("БПЛА", ("бпла", "дрон", "drone", "uav")),
    ("ПВО", ("пво", "air defense", "перехват")),
    ("Взрывы", ("взрыв", "explosion", "удар", "прилет")),
    ("Опасность", ("тревога", "опасность", "угроза", "warning")),
    ("Радар", ("радар", "мониторинг", "трек", "карта")),
]

ZONE_RULES = [
    ("Север", ("север", "брянск", "курск", "белгород")),
    ("Центр", ("москва", "центр", "центральн")),
    ("Восток", ("восток", "донецк", "луганск")),
    ("Юг", ("юг", "крым", "ростов", "краснодар")),
    ("Запад", ("запад", "львов", "польша")),
    ("Приграничье", ("границ", "border", "пригранич")),
]


def db() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


class TopicBody(BaseModel):
    name: str
    query: str = ""
    description: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc or "web"
    except Exception:
        return "web"


def _published(value) -> datetime:
    if value:
        raw = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d",):
            try:
                return datetime.strptime(str(value)[:10], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return _now()


def _classify_type(text: str) -> str:
    low = (text or "").lower()
    for label, terms in TYPE_RULES:
        if any(t in low for t in terms):
            return label
    return "Сигнал"


def _classify_zone(text: str) -> str:
    low = (text or "").lower()
    for label, terms in ZONE_RULES:
        if any(t in low for t in terms):
            return label
    return "Глобально"


def _confidence(text: str, source: str) -> float:
    score = 0.45
    low = (text or "").lower()
    if any(w in low for w in ("подтверд", "официаль", "reported", "confirmed")):
        score += 0.22
    if any(w in low for w in ("несколько", "источник", "канал", "сообщают")):
        score += 0.16
    if source:
        score += 0.08
    return min(score, 0.96)


def _severity(text: str) -> float:
    low = (text or "").lower()
    severe = sum(1 for w in ("взрыв", "удар", "опасность", "атака", "пво", "бпла", "санкции", "авария") if w in low)
    return min(1.0, 0.25 + severe * 0.18)


def ensure_default_topics(session: Session) -> None:
    existing = {r.name for r in session.query(NewsTopic).all()}
    for name, query, description in DEFAULT_TOPICS:
        if name not in existing:
            session.add(NewsTopic(name=name, query=query, description=description))
    session.commit()


def topic_card(topic: NewsTopic) -> dict:
    return {
        "id": topic.id,
        "name": topic.name,
        "query": topic.query,
        "description": topic.description,
        "status": topic.status,
    }


def event_card(event: NewsEvent) -> dict:
    return {
        "id": event.id,
        "topic_id": event.topic_id,
        "time": _aware(event.occurred_at).strftime("%H:%M"),
        "occurred_at": _aware(event.occurred_at).isoformat(),
        "type": event.event_type,
        "zone": event.zone or "Глобально",
        "title": event.title,
        "text": event.text,
        "source": event.source,
        "url": event.source_url,
        "sources": event.source_count,
        "confidence": round((event.confidence or 0) * 100),
        "severity": event.severity or 0,
        "tone": "high" if (event.severity or 0) >= 0.7 else "medium" if (event.severity or 0) >= 0.45 else "low",
    }


def _store_web_result(session: Session, topic: NewsTopic, row: dict) -> bool:
    url = row.get("url") or ""
    if not url:
        return False
    text = f"{row.get('title', '')}. {row.get('content', '')}".strip()
    existing = session.query(NewsEvent).filter_by(topic_id=topic.id, source_url=url).first()
    if existing:
        existing.source_count = max(existing.source_count or 1, 1)
        existing.confidence = max(existing.confidence or 0.0, _confidence(text, existing.source))
        return False
    event = NewsEvent(
        topic_id=topic.id,
        event_type=_classify_type(text),
        zone=_classify_zone(text),
        title=(row.get("title") or text[:90] or topic.name)[:160],
        text=text[:1200],
        source=_domain(url),
        source_url=url,
        source_count=1,
        confidence=_confidence(text, _domain(url)),
        severity=_severity(text),
        occurred_at=_published(row.get("published")),
    )
    session.add(event)
    return True


def _tg_url(post) -> str:
    pid = str(getattr(post, "post_id", "") or "")
    author = (getattr(post, "author", "") or "").lstrip("@")
    if "/" in pid:
        ns = pid.split("/", 1)[0]
        return f"https://t.me/c/{pid}" if ns.isdigit() else f"https://t.me/{pid}"
    if author:
        return f"https://t.me/{author}/{pid}"
    return f"telegram:{hashlib.sha1((author + pid + (getattr(post, 'text', '') or '')).encode()).hexdigest()[:16]}"


def _store_tg_post(session: Session, topic: NewsTopic, post) -> bool:
    url = _tg_url(post)
    text = getattr(post, "text", "") or ""
    if not text.strip():
        return False
    existing = session.query(NewsEvent).filter_by(topic_id=topic.id, source_url=url).first()
    if existing:
        existing.source_count = max(existing.source_count or 1, 1)
        existing.confidence = max(existing.confidence or 0.0, _confidence(text, getattr(post, "author", "")))
        return False
    event = NewsEvent(
        topic_id=topic.id,
        event_type=_classify_type(text),
        zone=_classify_zone(text),
        title=(text[:120] or topic.name),
        text=text[:1200],
        source=getattr(post, "author", "") or "telegram",
        source_url=url,
        source_count=1,
        confidence=_confidence(text, getattr(post, "author", "")),
        severity=_severity(text),
        occurred_at=_aware(getattr(post, "created_at", None) or _now()),
    )
    session.add(event)
    return True


def collect_topic(topic_id: int, tg_provider=None) -> dict:
    from .providers.web import WebSearchProvider

    session = get_session()
    try:
        ensure_default_topics(session)
        topic = session.get(NewsTopic, topic_id)
        if not topic:
            return {"error": "topic not found"}
        provider = WebSearchProvider()
        rows = provider.search(topic.query or topic.name, max_results=20)
        added_web = sum(1 for row in rows if _store_web_result(session, topic, row))
        added_tg = 0
        if tg_provider is not None:
            try:
                page = tg_provider.search(topic.query or topic.name, "keyword", None, "telegram")
                added_tg = sum(1 for post in page.posts if _store_tg_post(session, topic, post))
            except Exception:
                added_tg = 0
        session.commit()
        return {"topic_id": topic.id, "fetched": len(rows), "added": added_web + added_tg,
                "added_web": added_web, "added_tg": added_tg}
    finally:
        session.close()


@router.get("/topics")
def list_topics(session: Session = Depends(db)):
    ensure_default_topics(session)
    rows = session.query(NewsTopic).order_by(NewsTopic.id).all()
    return [topic_card(r) for r in rows]


@router.post("/topics")
def create_topic(body: TopicBody, session: Session = Depends(db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Topic name is required")
    existing = session.query(NewsTopic).filter_by(name=name).first()
    if existing:
        return topic_card(existing)
    topic = NewsTopic(name=name, query=body.query.strip() or name, description=body.description.strip())
    session.add(topic)
    session.commit()
    return topic_card(topic)


@router.post("/collect")
def collect_news(topic_id: int, background_tasks: BackgroundTasks, request: Request, session: Session = Depends(db)):
    ensure_default_topics(session)
    topic = session.get(NewsTopic, topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    get_tg = getattr(request.app.state, "get_tg_provider", None)
    tg_provider = get_tg() if get_tg else None
    background_tasks.add_task(collect_topic, topic_id, tg_provider)
    return {"status": "collecting", "topic": topic.name}


@router.get("/events")
def list_events(topic_id: int | None = None, q: str = "", limit: int = 100, session: Session = Depends(db)):
    ensure_default_topics(session)
    query = session.query(NewsEvent)
    if topic_id:
        query = query.filter(NewsEvent.topic_id == topic_id)
    if q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter((NewsEvent.title.ilike(needle)) | (NewsEvent.text.ilike(needle)))
    rows = query.order_by(NewsEvent.occurred_at.desc()).limit(min(limit, 200)).all()
    return [event_card(r) for r in rows]


@router.get("/summary")
def summary(topic_id: int | None = None, session: Session = Depends(db)):
    ensure_default_topics(session)
    topic = session.get(NewsTopic, topic_id) if topic_id else session.query(NewsTopic).order_by(NewsTopic.id).first()
    if not topic:
        raise HTTPException(404, "Topic not found")
    since = _now() - timedelta(hours=24)
    events = (session.query(NewsEvent)
              .filter(NewsEvent.topic_id == topic.id, NewsEvent.occurred_at >= since)
              .order_by(NewsEvent.occurred_at.desc())
              .limit(200).all())
    all_events = events or (session.query(NewsEvent)
                            .filter(NewsEvent.topic_id == topic.id)
                            .order_by(NewsEvent.occurred_at.desc())
                            .limit(200).all())
    zones = defaultdict(lambda: {"score": 0, "events": 0})
    types = Counter()
    sources = set()
    for event in all_events:
        z = event.zone or "Глобально"
        zones[z]["events"] += 1
        zones[z]["score"] = max(zones[z]["score"], int((event.severity or 0) * 100))
        types[event.event_type] += 1
        if event.source:
            sources.add(event.source)
    zone_rows = [
        {"name": name, "score": max(data["score"], min(100, data["events"] * 12)), "events": data["events"]}
        for name, data in zones.items()
    ]
    return {
        "topic": topic_card(topic),
        "stats": {
            "events": len(all_events),
            "sources": len(sources),
            "clusters": max(1 if all_events else 0, len(types)),
            "confidence": round(sum((e.confidence or 0) for e in all_events) * 100 / len(all_events)) if all_events else 0,
        },
        "types": [{"type": k, "count": v} for k, v in types.most_common()],
        "zones": sorted(zone_rows, key=lambda r: -r["score"]),
        "events": [event_card(e) for e in all_events[:80]],
        "window": {"from": since.isoformat(), "to": _now().isoformat()},
    }
