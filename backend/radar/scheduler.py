import logging, random, time, threading
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from .db import get_session
from .models import Brand, Probe

log = logging.getLogger(__name__)
INTERVAL_HOT    = 300
INTERVAL_NORMAL = 3600
INTERVAL_QUIET  = 7200
INTERVAL_CHATS  = 1800   # group-chat monitoring cadence (discover + search)
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

def _run_brand_pipeline(session, brand_id, provider, tg_provider):
    import radar.pipeline as _pipeline
    import radar.stories as _stories
    _pipeline.classify_and_draft(session, brand_id)
    _pipeline.fetch_new_comments(session, brand_id, provider, tg_provider)
    _stories.update_stories(session, brand_id)


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
    def __init__(self, provider, tick_sec: int = 60, tg_provider=None):
        self._provider     = provider
        self._tg_provider  = tg_provider   # routes platform="telegram" probes; None = skip them
        self._tick_sec     = tick_sec
        self._bucket       = TokenBucket()
        self._running      = False
        self._timer        = None
        self._last_hotwatch = 0.0
        self._last_chats    = 0.0
        self._chats_thread  = None   # background worker for the chat-monitoring pass

    def start(self):
        self._running = True
        # Schedule the first tick on a background timer instead of running it
        # inline — running _run_once() synchronously here would block FastAPI
        # startup on slow TikHub calls and the server would never bind its port.
        self._timer = threading.Timer(self._tick_sec, self._tick)
        self._timer.daemon = True
        self._timer.start()

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
            # kind="chat" probes are collected via the brand-level collect_chats pass
            # (term search), not the generic per-probe loop, so exclude them here.
            due = (
                session.query(Probe).join(Brand)
                .filter(
                    Probe.next_run_at <= datetime.now(timezone.utc),
                    Brand.auto_collect.is_(True),
                    Probe.kind.notin_(("chat", "chat_linked")),
                )
                .all()
            )
            touched: set[int] = set()
            for probe in due:
                prov = self._tg_provider if probe.platform == "telegram" else self._provider
                if prov is None:
                    continue  # telegram probe but TG provider unavailable — skip
                self._bucket.acquire()
                try:
                    from .collector import collect_probe
                    count    = collect_probe(session, probe, prov)
                    interval = adaptive_interval(probe, count)
                    probe.next_run_at  = datetime.now(timezone.utc) + timedelta(seconds=interval)
                    probe.interval_sec = interval
                    session.commit()
                    if count:
                        touched.add(probe.brand_id)
                except Exception:
                    log.exception("Probe %s failed", probe.id)
            # Classify + draft for brands that got new mentions this tick, then
            # auto-fetch comments on fresh competitor/niche mentions (opportunity pipeline).
            for brand_id in touched:
                try:
                    _run_brand_pipeline(session, brand_id, self._provider, self._tg_provider)
                except Exception:
                    log.exception("Pipeline failed for brand %s", brand_id)
            # Re-poll hot mentions on their own (faster) cadence, scoped to
            # auto-collect brands so opted-out users cost no API calls.
            self._maybe_hotwatch(session)
            # Group-chat monitoring on its own (slower) cadence.
            self._maybe_collect_chats(session)
        finally:
            session.close()

    def _maybe_collect_chats(self, session: Session):
        # Chat discovery + search is slow (throttled Telegram calls + LLM), so run it on
        # its own worker thread — blocking the tick thread would starve hotwatch and
        # normal probe collection. One worker at a time; it owns its own DB session.
        if self._tg_provider is None:
            return
        if time.monotonic() - self._last_chats < INTERVAL_CHATS:
            return
        if self._chats_thread is not None and self._chats_thread.is_alive():
            return  # previous chat pass still running — don't pile up
        self._last_chats = time.monotonic()
        self._chats_thread = threading.Thread(target=self._collect_chats_worker, daemon=True)
        self._chats_thread.start()

    def _collect_chats_worker(self):
        session = get_session()
        try:
            from .collector import ensure_chats_discovered, collect_chats
            brands = session.query(Brand).filter(Brand.auto_collect.is_(True)).all()
            for b in brands:
                ensure_chats_discovered(session, b, self._tg_provider)
                n = collect_chats(session, b, self._tg_provider)
                if n:
                    _run_brand_pipeline(session, b.id, self._provider, self._tg_provider)
                    log.info("Chat monitor: %d new niche message(s) for brand %s", n, b.id)
        except Exception:
            log.exception("Chat monitor worker failed")
        finally:
            session.close()

    def _maybe_hotwatch(self, session: Session):
        if time.monotonic() - self._last_hotwatch < INTERVAL_HOT:
            return
        self._last_hotwatch = time.monotonic()
        try:
            brand_ids = [
                b.id for b in
                session.query(Brand.id).filter(Brand.auto_collect.is_(True))
            ]
            from .hotwatch import hotwatch_tick
            n = hotwatch_tick(
                session, self._provider,
                brand_ids=brand_ids, acquire=self._bucket.acquire,
            )
            if n:
                log.info("Hot-watch re-polled %d mention(s)", n)
        except Exception:
            log.exception("Hot-watch tick failed")
