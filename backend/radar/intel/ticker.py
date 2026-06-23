"""Lightweight periodic intel processor.

The realtime listener writes new IntelMention rows the instant a source publishes, but
clustering (incidents/stories), timeline buckets, and anomaly detection only run inside
run_intel_tick. With the heavy brand scheduler disabled, nothing would advance those —
so stories / Горит сейчас / Сигналы would freeze. This ticker runs ONLY the processing
half of the tick (no TG re-poll: tg_provider=None) on a slow interval, single-threaded,
so SQLite stays uncontended.
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
            session = get_session()
            try:
                run_intel_tick(session, tg_provider=None)  # process-only, no TG re-poll
            except Exception:
                log.exception("intel tick failed (will retry next interval)")
                session.rollback()
            finally:
                session.close()
