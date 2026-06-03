import logging, random, time, threading
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from .db import get_session
from .models import Brand, Probe

log = logging.getLogger(__name__)
INTERVAL_HOT    = 300
INTERVAL_NORMAL = 3600
INTERVAL_QUIET  = 7200
NIGHT_START_UTC = 21
NIGHT_END_UTC   = 6
NIGHT_MULTIPLIER = 2.0
MAX_CALLS        = 10
BUCKET_PERIOD    = 60

class TokenBucket:
    def __init__(self, max_calls=MAX_CALLS, period=BUCKET_PERIOD):
        self._max    = max_calls
        self._period = period
        self._tokens = max_calls
        self._last   = time.monotonic()
        self._lock   = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now     = time.monotonic()
                elapsed = now - self._last
                new     = int(elapsed / self._period * self._max)
                if new > 0:
                    self._tokens = min(self._max, self._tokens + new)
                    self._last   = now
                if self._tokens > 0:
                    self._tokens -= 1
                    return
            time.sleep(1)

def adaptive_interval(probe: Probe, new_mentions: int) -> int:
    if new_mentions > 5:   interval = INTERVAL_HOT
    elif new_mentions > 0: interval = INTERVAL_NORMAL
    else:                  interval = INTERVAL_QUIET
    hour = datetime.now(timezone.utc).hour
    if hour >= NIGHT_START_UTC or hour < NIGHT_END_UTC:
        interval = int(interval * NIGHT_MULTIPLIER)
    jitter = random.randint(-int(interval * 0.1), int(interval * 0.1))
    return interval + jitter

class Scheduler:
    def __init__(self, provider, tick_sec: int = 60):
        self._provider  = provider
        self._tick_sec  = tick_sec
        self._bucket    = TokenBucket()
        self._running   = False
        self._timer     = None

    def start(self):
        self._running = True
        self._tick()

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.cancel()

    def _tick(self):
        if not self._running: return
        try:
            self._run_once()
        except Exception:
            log.exception("Scheduler tick failed")
        finally:
            if self._running:
                self._timer = threading.Timer(self._tick_sec, self._tick)
                self._timer.daemon = True
                self._timer.start()

    def _run_once(self):
        session = get_session()
        try:
            # Only probes of brands that opted into auto-collect are due.
            due = (
                session.query(Probe).join(Brand)
                .filter(
                    Probe.next_run_at <= datetime.now(timezone.utc),
                    Brand.auto_collect.is_(True),
                )
                .all()
            )
            touched: set[int] = set()
            for probe in due:
                self._bucket.acquire()
                try:
                    from .collector import collect_probe
                    count    = collect_probe(session, probe, self._provider)
                    interval = adaptive_interval(probe, count)
                    probe.next_run_at  = datetime.now(timezone.utc) + timedelta(seconds=interval)
                    probe.interval_sec = interval
                    session.commit()
                    if count:
                        touched.add(probe.brand_id)
                except Exception:
                    log.exception("Probe %s failed", probe.id)
            # Classify + draft for brands that got new mentions this tick.
            for brand_id in touched:
                try:
                    from .pipeline import classify_and_draft
                    classify_and_draft(session, brand_id)
                except Exception:
                    log.exception("Pipeline failed for brand %s", brand_id)
        finally:
            session.close()
