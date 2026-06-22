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
    from .models import IntelMention, IntelLexicon, IntelDirection
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
