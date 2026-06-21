"""Seed: create demo account and default news topics."""
from __future__ import annotations
from sqlalchemy.orm import Session
from .models import Brand, User
from .core.auth import hash_password

DEMO_EMAIL    = "demo@echo.app"
DEMO_PASSWORD = "demo12345"

DEFAULT_TOPICS = {
    "Экономика":   ["инфляция","рубль","курс доллара","санкции","бюджет","нефть","газ","экспорт"],
    "Геополитика": ["переговоры","саммит","договор","конфликт","граница","дипломатия","НАТО","ООН"],
    "Военное":     ["обстрел","удар","БПЛА","ПВО","фронт","наступление","эвакуация","взрыв"],
}

# Vetted news-channel seeds per default topic. Best-effort handles — each is
# validated when added (a missing/renamed handle is skipped, not fatal), and the
# editable Sources panel lets users fix the list. Seeds skip the LLM gate.
TOPIC_SEED_CHANNELS = {
    "Экономика":   ["@rbc_news", "@interfaxonline", "@tass_agency", "@thebell_io",
                    "@frank_media", "@kommersant", "@rian_ru"],
    "Геополитика": ["@bbcrussian", "@meduzalive", "@dwglavnoe", "@currenttime",
                    "@rian_ru", "@tass_agency", "@kommersant"],
    "Военное":     ["@astrapress", "@bazabazon", "@breakingmash", "@bbbreaking",
                    "@rian_ru", "@bbcrussian", "@meduzalive"],
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
    """Idempotent: create global default topics for the news-mode feed (NewsTopic)."""
    import json as _j
    from .news.models import NewsTopic
    for name, kws in DEFAULT_TOPICS.items():
        if not session.query(NewsTopic).filter_by(name=name, kind="default").first():
            session.add(NewsTopic(name=name, kind="default", user_id=None,
                                  keywords=_j.dumps(kws, ensure_ascii=False),
                                  niche_keywords=_j.dumps(kws, ensure_ascii=False)))
    session.commit()
