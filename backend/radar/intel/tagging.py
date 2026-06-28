from __future__ import annotations
from .models import IntelDirection
from . import seed

def resolve_direction_id(session, key: str | None) -> int:
    """Resolve a direction key to its id. Unknown/None -> the 'unassigned' bucket
    (seeded on demand). Direction rows are seeded by intel.seed."""
    if key:
        d = session.query(IntelDirection).filter_by(key=key).first()
        if d is not None:
            return d.id
    return seed.ensure_unassigned_direction(session).id


def tag_geo(session, probe, text: str) -> tuple[int, str | None]:
    """Resolve (direction_id, subject) for a post from `probe`.

    Text wins — both for the oblast AND the city: if the post text names a settlement
    that becomes the subject. If the text names only an oblast (region-level stem), the
    source's curator-set subject is attached when it does not contradict the text (same
    oblast). A repost about a different region thus gets no false city. When the text
    names no place at all, fall back to the source's oblast + locality.
    """
    from .geo import detect_place
    subject = getattr(probe, "subject", None)
    src_dir = getattr(probe, "direction_id", None)
    key, city = detect_place(text)
    if key:
        dir_id = resolve_direction_id(session, key)
        same = bool(src_dir) and dir_id == src_dir
        # text's own city wins; else the source's subject only if the same oblast
        return dir_id, (city or (subject if same else None))
    # Text named no place — fall back to the source's oblast + locality.
    dir_id = src_dir or resolve_direction_id(session, None)
    return dir_id, subject


def retag_unassigned_geo(session, limit: int = 4000) -> int:
    """Re-tag 'unassigned' mentions using the (expanded) geo gazetteer — deterministic,
    no LLM. Run after the gazetteer grows so already-stored posts that now match a
    settlement/region get their direction set. Returns the number re-tagged."""
    from .models import IntelMention
    from .geo import detect_direction
    uid = seed.ensure_unassigned_direction(session).id
    rows = (session.query(IntelMention).filter(IntelMention.direction_id == uid)
            .order_by(IntelMention.id.desc()).limit(limit).all())
    changed = 0
    for m in rows:
        key = detect_direction(m.text)
        if key:
            m.direction_id = resolve_direction_id(session, key)
            changed += 1
    if changed:
        session.commit()
    return changed


def _llm_classify(text: str, keys: list[str], glossary: str) -> str | None:
    """Ask the LLM which direction key the text belongs to, or None. Raises
    LLMNotConfigured if no key — caller treats that as 'skip'."""
    from ..core.llm import complete
    system = ("Ты классифицируешь сообщение по направлению фронта. "
              "Верни РОВНО один ключ из списка или 'none'. Глоссарий сленга:\n" + glossary)
    user = f"Ключи: {', '.join(keys)}\nСообщение: {text}\nКлюч:"
    out = (complete(system, user, max_tokens=8) or "").strip().lower()
    return out if out in keys else None


def retag_unassigned(session, limit: int = 50) -> int:
    from .models import IntelMention, IntelLexicon
    from .geo import GEO_KEYWORDS
    from ..core.llm import LLMNotConfigured
    uid = seed.ensure_unassigned_direction(session).id
    rows = (session.query(IntelMention).filter(IntelMention.direction_id == uid)
            .order_by(IntelMention.id.desc()).limit(limit).all())
    if not rows:
        return 0
    glossary = "\n".join(f"{t} = {m}" for (t, m) in session.query(IntelLexicon.term, IntelLexicon.meaning).all())
    keys = list(GEO_KEYWORDS.keys())
    changed = 0
    try:
        for m in rows:
            key = _llm_classify(m.text, keys, glossary)
            if key:
                m.direction_id = resolve_direction_id(session, key)
                changed += 1
    except LLMNotConfigured:
        session.rollback()
        return 0
    session.commit()
    return changed
