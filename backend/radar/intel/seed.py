"""Intel seed: default directions (with geo match-terms), sources, and lexicon.

`ensure_default_directions` re-runs fully when GEO_DICT_VERSION is bumped
(tracked in a metadata row keyed by '__geo_dict_version__').
"""
import os
import json
from .models import IntelDirection, IntelMentionDirection
from .geo_dict import DEFAULT_DIRECTIONS, GEO_DICT_VERSION

_META_KEY = "__geo_dict_version__"


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
    # Version guard: if a previous seed wrote a different version, refresh.
    meta = session.query(IntelDirection).filter_by(key=_META_KEY).first()
    stored_version = int(meta.name) if meta and (meta.name or "").isdigit() else 0
    refresh = stored_version != GEO_DICT_VERSION

    canonical = {key for (key, *_rest) in DEFAULT_DIRECTIONS}
    existing = {d.key: d for d in session.query(IntelDirection).all()}
    for key, name, kind, region_key, terms in DEFAULT_DIRECTIONS:
        d = existing.get(key)
        if d is None:
            session.add(IntelDirection(
                key=key, name=name, kind=kind, region_key=region_key,
                geo_terms=json.dumps(terms, ensure_ascii=False)))
        elif refresh:
            d.name = name
            d.kind = kind
            d.region_key = region_key
            d.geo_terms = json.dumps(terms, ensure_ascii=False)

    if refresh:
        # Prune orphaned seed directions: keys renamed/removed between versions
        # (e.g. old "dnipro"→"dnipropetrovsk", "donetsk"→"dnr") otherwise linger
        # as duplicate columns. Custom user directions (kind="custom"), the meta
        # row and "unassigned" are never touched.
        protected = {_META_KEY, "unassigned"}
        for d in list(existing.values()):
            if d.key in canonical or d.key in protected or d.kind == "custom":
                continue
            # Drop m2m mention links first to satisfy FK, then the direction.
            session.query(IntelMentionDirection).filter_by(
                direction_id=d.id).delete(synchronize_session=False)
            session.delete(d)

        if meta is None:
            session.add(IntelDirection(key=_META_KEY, name=str(GEO_DICT_VERSION),
                                       kind="meta", geo_terms="[]"))
        else:
            meta.name = str(GEO_DICT_VERSION)
    session.commit()
    ensure_unassigned_direction(session)
