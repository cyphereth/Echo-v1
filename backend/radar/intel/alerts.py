"""Intel alerts: detect story/direction bursts and persist deduplicated IntelAlert rows.

Runs inside the ticker (passes.run_intel_tick) after clustering + anomaly detection.
A per-(scope, ref, kind) cooldown collapses one sustained burst into a single alert.
"""
from __future__ import annotations
import os
import logging
from datetime import datetime, timezone, timedelta

from ..models import _now
from .models import IntelAlert

log = logging.getLogger("radar.intel.alerts")

ALERT_COOLDOWN_H = int(os.getenv("ALERT_COOLDOWN_H", "6"))


def _recent_exists(session, scope, kind, *, direction_id=None, story_id=None) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_H)
    q = (session.query(IntelAlert)
         .filter(IntelAlert.scope == scope, IntelAlert.kind == kind,
                 IntelAlert.fired_at >= cutoff))
    if scope == "story":
        q = q.filter(IntelAlert.story_id == story_id)
    else:
        q = q.filter(IntelAlert.direction_id == direction_id)
    return session.query(q.exists()).scalar()


def _emit(session, scope, kind, *, title, message, magnitude,
          direction_id=None, story_id=None):
    """Insert an alert unless one of the same (scope, ref, kind) fired within the
    cooldown. Returns the new IntelAlert or None when suppressed."""
    if _recent_exists(session, scope, kind, direction_id=direction_id, story_id=story_id):
        return None
    alert = IntelAlert(scope=scope, kind=kind, title=title or "", message=message or "",
                       magnitude=float(magnitude or 0.0),
                       direction_id=direction_id, story_id=story_id, fired_at=_now())
    session.add(alert)
    session.flush()
    return alert
