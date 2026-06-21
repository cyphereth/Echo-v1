from __future__ import annotations
from .models import IntelProbe, IntelLexicon

_SIDES = {"ru", "ua"}
_KINDS = {"channel", "chat"}

def ingest_sources(session, path: str) -> dict:
    added = updated = 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            query, side, kind = parts[0], parts[1].lower(), parts[2].lower()
            if side not in _SIDES or kind not in _KINDS or not query:
                continue
            p = session.query(IntelProbe).filter_by(query=query).first()
            if p is None:
                session.add(IntelProbe(platform="telegram", kind=kind, query=query, side=side))
                added += 1
            else:
                p.side, p.kind = side, kind
                updated += 1
    session.commit()
    return {"added": added, "updated": updated}

def ingest_lexicon(session, path: str) -> dict:
    added = updated = 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            term = parts[0].lower()
            meaning = parts[1] if len(parts) > 1 else ""
            category = parts[2] if len(parts) > 2 else None
            if not term:
                continue
            row = session.query(IntelLexicon).filter_by(term=term).first()
            if row is None:
                session.add(IntelLexicon(term=term, meaning=meaning, category=category))
                added += 1
            else:
                row.meaning, row.category = meaning, category
                updated += 1
    session.commit()
    return {"added": added, "updated": updated}

if __name__ == "__main__":
    import sys
    from .seed import ensure_default_directions  # noqa
    from ..core.db import get_session
    cmd, path = sys.argv[1], sys.argv[2]
    with get_session() as s:
        out = ingest_sources(s, path) if cmd == "sources" else ingest_lexicon(s, path)
        print(out)
