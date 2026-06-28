from __future__ import annotations
import re

# direction key -> geo terms (seed; operator-extensible). Keys MUST match seeded IntelDirection keys.
GEO_KEYWORDS: dict[str, list[str]] = {
    "kursk":        ["курск", "суджа", "суджи", "суджей", "глушково", "коренево", "льгов"],
    "zaporizhzhia": ["запорож", "орехов", "работино", "каменское", "пологи", "токмак"],
    "kharkiv":      ["харьков", "купянск", "волчанск", "липцы"],
    "donetsk":      ["донецк", "авдеев", "бахмут", "артёмовск", "артемовск", "горловк", "марьинк"],
    "kherson":      ["херсон", "днепр", "каховк", "берислав", "антоновск"],
}

def detect_direction(text: str) -> str | None:
    """Return the direction key whose geo terms appear in `text` (case-insensitive,
    word-boundary), or None. First match wins (dict order)."""
    if not text:
        return None
    low = text.lower()
    for key, terms in GEO_KEYWORDS.items():
        for t in terms:
            if re.search(r"(?<!\w)" + re.escape(t), low):
                return key
    return None
