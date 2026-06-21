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
