from __future__ import annotations
import os, logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from .models import IntelProbe
from . import collector

log = logging.getLogger("radar.intel.passes")
MAX_INTEL_SOURCES_PER_RUN = int(os.getenv("MAX_INTEL_SOURCES_PER_RUN", "12"))

def run_intel_collect(session: Session, tg_provider) -> None:
    if tg_provider is None:
        return
    from ..core.providers.telegram import TelegramFloodWait
    now = datetime.now(timezone.utc)
    due = (session.query(IntelProbe)
           .filter(IntelProbe.next_run_at <= now)
           .order_by(IntelProbe.next_run_at.asc())
           .limit(MAX_INTEL_SOURCES_PER_RUN).all())
    for probe in due:
        try:
            collector.collect_probe(session, probe, tg_provider)
            probe.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=probe.interval_sec or 3600)
            session.commit()
        except TelegramFloodWait as e:
            log.warning("intel collect flood-wait, aborting batch: %s", e)
            return
        except Exception:
            log.exception("intel source %s failed", probe.id)
            session.rollback()
            # Advance next_run_at even on failure so a broken source doesn't
            # stay "due" forever and consume a cap slot every tick.
            probe.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=probe.interval_sec or 3600)
            session.commit()
