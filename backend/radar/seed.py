"""Seed: create demo account only. No brands, no mentions."""
from __future__ import annotations
from sqlalchemy.orm import Session
from .models import Brand, User
from .auth import hash_password

DEMO_EMAIL    = "demo@echo.app"
DEMO_PASSWORD = "demo12345"

DEFAULT_TOPICS = {
    "Экономика":   ["инфляция","рубль","курс доллара","санкции","бюджет","нефть","газ","экспорт"],
    "Геополитика": ["переговоры","саммит","договор","конфликт","граница","дипломатия","НАТО","ООН"],
    "Военное":     ["обстрел","удар","БПЛА","ПВО","фронт","наступление","эвакуация","взрыв"],
}


def run(session: Session) -> None:
    """No-op: mock data removed. Real data comes from live collection."""
    pass


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


def ensure_default_topics(session: Session) -> None:
    """Idempotent: create global default topics for the news-mode feed."""
    import json as _j
    from .models import Topic
    for name, kws in DEFAULT_TOPICS.items():
        if not session.query(Topic).filter_by(name=name, kind="default").first():
            session.add(Topic(name=name, kind="default", user_id=None,
                              keywords=_j.dumps(kws, ensure_ascii=False),
                              niche_keywords=_j.dumps(kws, ensure_ascii=False)))
    session.commit()
