import os
from .models import IntelDirection

DEFAULT_DIRECTIONS = [
    # RU border regions + Crimea
    ("bryansk",      "Брянская обл."),
    ("belgorod",     "Белгородская обл."),
    ("kursk",        "Курская обл."),
    ("voronezh",     "Воронежская обл."),
    ("oryol",        "Орловская обл."),
    ("rostov",       "Ростовская обл."),
    ("crimea",       "Крым"),
    # UA directions / fronts
    ("sumy",         "Сумское"),
    ("chernihiv",    "Черниговское"),
    ("kharkiv",      "Харьковское"),
    ("luhansk",      "Луганское (ЛНР)"),
    ("donetsk",      "Донецкое (ДНР)"),
    ("zaporizhzhia", "Запорожское"),
    ("kherson",      "Херсонское"),
    ("dnipro",       "Днепропетровское"),
    ("kyiv",         "Киевское"),
]


def ensure_sources_seed_loaded(session) -> dict:
    from .intake import ingest_sources
    path = os.path.join(os.path.dirname(__file__), "data", "sources.seed.txt")
    if not os.path.exists(path):
        return {"added": 0, "updated": 0}
    return ingest_sources(session, path)


def ensure_lexicon_seed_loaded(session) -> dict:
    """Idempotent: ingest radar/intel/data/keywords.seed.json if it exists.

    Called every startup — safe to re-run, only updates existing rows.
    Returns {"added": N, "updated": M}.
    """
    from .intake import ingest_lexicon_json
    path = os.path.join(os.path.dirname(__file__), "data", "keywords.seed.json")
    if not os.path.exists(path):
        return {"added": 0, "updated": 0}
    return ingest_lexicon_json(session, path)


def ensure_unassigned_direction(session) -> IntelDirection:
    d = session.query(IntelDirection).filter_by(key="unassigned").first()
    if d is None:
        d = IntelDirection(key="unassigned", name="Без направления")
        session.add(d)
        session.commit()
    return d


def ensure_default_directions(session) -> None:
    existing = {k for (k,) in session.query(IntelDirection.key).all()}
    for key, name in DEFAULT_DIRECTIONS:
        if key not in existing:
            session.add(IntelDirection(key=key, name=name))
    session.commit()
    ensure_unassigned_direction(session)
