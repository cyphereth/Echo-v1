from __future__ import annotations
import os, logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from .models import IntelProbe
from . import collector

log = logging.getLogger("radar.intel.passes")
MAX_INTEL_SOURCES_PER_RUN = int(os.getenv("MAX_INTEL_SOURCES_PER_RUN", "12"))

def _ensure_joined(probe: IntelProbe, tg_provider, session: Session) -> bool:
    """Join a channel/chat before collecting if not already a member.

    For invite links: join_invite() returns the resolved @username or #{id};
    we overwrite probe.query so future ticks use the stable handle instead of
    the invite link (invite links can expire; @usernames don't).

    Returns False if this probe was a duplicate of an already-tracked source
    (resolved to the same query as another probe) and was therefore deleted —
    the caller must then skip collecting it.
    """
    q = probe.query or ""
    try:
        if collector._is_invite_link(q):
            resolved = tg_provider.join_invite(q)
            if resolved and resolved != q:
                # Different invite links can resolve to the SAME chat (#id) or
                # @handle. If another probe already tracks the resolved target,
                # this one is a duplicate — drop it instead of creating a dup row.
                dup = (session.query(IntelProbe)
                       .filter(IntelProbe.query == resolved, IntelProbe.id != probe.id)
                       .first())
                if dup is not None:
                    log.info("intel probe %s: invite resolves to %s, already tracked by probe %s — deleting duplicate",
                             probe.id, resolved, dup.id)
                    session.delete(probe)
                    session.commit()
                    return False
                log.info("intel probe %s: invite resolved to %s — updating query", probe.id, resolved)
                probe.query = resolved
                session.commit()
        else:
            handle = collector._clean_handle(q)
            if handle:
                tg_provider.join_channel(handle)
    except Exception:
        log.warning("join failed for probe %s (%s) — will still attempt collect", probe.id, q)
    return True


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
            if not _ensure_joined(probe, tg_provider, session):
                continue  # duplicate probe was deleted — nothing to collect
            collector.collect_probe(session, probe, tg_provider)
            probe.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=probe.interval_sec or 3600)
            session.commit()
        except TelegramFloodWait as e:
            log.warning("intel collect flood-wait, aborting batch: %s", e)
            return
        except Exception:
            log.exception("intel source %s failed", probe.id)
            session.rollback()
            probe.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=probe.interval_sec or 3600)
            session.commit()


def run_intel_tick(session, tg_provider, web_provider=None, embed=None) -> None:
    """One intel cycle: collect -> LLM retag -> cluster each touched direction."""
    from . import tagging, stories
    from .models import IntelMention
    run_intel_collect(session, tg_provider)
    # Enrich reply mentions with parent chain + siblings (separate pass, non-blocking).
    if tg_provider is not None:
        try:
            from .context_pass import enrich_context
            enrich_context(session, tg_provider, batch_size=50)
        except Exception:
            log.exception("intel context enrichment failed (skipped)")
            session.rollback()
    # Deterministic geo re-tagging (settlement/region gazetteer) — no LLM. Picks up
    # already-stored 'unassigned' posts that now match an expanded gazetteer entry.
    try:
        tagging.retag_unassigned_geo(session)
    except Exception:
        log.exception("intel geo retag failed (skipped)")
        session.rollback()
    dir_ids = [d for (d,) in session.query(IntelMention.direction_id)
               .filter(IntelMention.incident_id.is_(None), IntelMention.direction_id.isnot(None)).distinct().all() if d]
    for did in dir_ids:
        try:
            stories.update_stories(session, did, embed=embed)
            session.commit()
        except Exception:
            log.exception("intel clustering failed for direction %s", did)
            session.rollback()

    from . import alerts
    try:
        alerts.scan(session)
        session.commit()
    except Exception:
        log.exception("intel alert scan failed")
        session.rollback()
