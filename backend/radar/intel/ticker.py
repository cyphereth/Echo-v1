"""Lightweight periodic intel processor + source poller.

Runs the full intel cycle on a slow interval, single-threaded, so SQLite stays
uncontended:
  1. POLL due IntelProbes via the shared Telegram client — this is what makes a
     source added through the UI start producing automatically: a new probe's
     next_run_at defaults to now, so it's "due" and gets read on the next tick
     (public channels are read WITHOUT joining). Bounded to MAX_INTEL_SOURCES_PER_RUN
     per tick; each source re-polled ~hourly via its interval_sec.
  2. PROCESS: cluster new mentions (realtime + polled) into stories, rebuild timeline
     buckets, run anomaly detection — keeps Горит сейчас / Сигналы / Крупнейшие сюжеты
     fresh while the heavy brand scheduler stays disabled.
"""
from __future__ import annotations

import logging
import os
import threading

from ..core.db import get_session

log = logging.getLogger("radar.intel.ticker")

INTEL_TICK_SEC = int(os.getenv("INTEL_TICK_SEC", "180"))


class IntelTicker:
    def __init__(self, interval_sec: int = INTEL_TICK_SEC):
        self.interval = max(30, interval_sec)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="intel-ticker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        from .passes import run_intel_tick
        # First pass after one interval (let startup settle); then every interval.
        while not self._stop.wait(self.interval):
            # Shared singleton — the SAME client the realtime listener uses (one TG
            # session file). None if Telegram isn't configured → process-only fallback.
            tg = None
            try:
                from ..brand.api import _get_tg_provider
                tg = _get_tg_provider()
                # Heal a dropped connection (e.g. after the Mac slept) so polling AND
                # the realtime update stream resume within one tick instead of staying
                # frozen until the next manual restart.
                if tg is not None and hasattr(tg, "ensure_connected"):
                    tg.ensure_connected()
            except Exception:
                log.exception("intel ticker: could not get/heal TG provider (process-only)")
            session = get_session()
            try:
                run_intel_tick(session, tg_provider=tg)  # poll due sources + process
            except Exception:
                log.exception("intel tick failed (will retry next interval)")
                session.rollback()
            finally:
                session.close()
