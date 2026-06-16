import logging, os, random, time, threading
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from .db import get_session
from .models import Brand, Probe

log = logging.getLogger(__name__)
INTERVAL_HOT    = 300
INTERVAL_NORMAL = 3600
INTERVAL_QUIET  = 7200
INTERVAL_CHATS  = 1800   # group-chat monitoring cadence (discover + search)
ENABLE_DIGESTS      = os.getenv("ENABLE_DIGESTS", "0") == "1"   # opt-in; default OFF (no surprise paid LLM calls)
INTERVAL_DIGEST     = int(os.getenv("DIGEST_INTERVAL_SEC", "86400"))  # once per ~24h
INTERVAL_WEB    = int(os.getenv("INTERVAL_WEB", "3600"))   # web-source cadence
INTERVAL_NEWS   = int(os.getenv("INTERVAL_NEWS", "900"))   # independent news-intel cadence
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
    # Story clustering is additive and best-effort: it triggers the heavy
    # embedding-model load on first use, so a failure (no network/disk/OOM) must
    # NOT poison the core classify/draft pipeline. Degrade to "no stories this tick".
    try:
        _stories.update_stories(session, brand_id)
    except Exception:
        log.exception("update_stories failed for brand %s (story layer skipped)", brand_id)


def _run_web_pass(session, web_provider):
    """Search the web per auto-collect brand and feed results into the pipeline."""
    import radar.collector as _collector
    import radar.pipeline as _pipeline
    import radar.stories as _stories
    from .models import Brand
    for b in session.query(Brand).filter(Brand.auto_collect.is_(True)).all():
        try:
            n = _collector.collect_web(session, b, web_provider)
        except Exception:
            log.exception("collect_web failed for brand %s", b.id)
            continue
        if n:
            try:
                _pipeline.classify_and_draft(session, b.id)
                _stories.update_stories(session, b.id)
            except Exception:
                log.exception("web pipeline failed for brand %s", b.id)


def _run_news_pass(session, tg_provider=None):
    """Collect independent news-intelligence topics. Best-effort and public-mode safe."""
    import radar.news as _news
    from .models import NewsTopic
    _news.ensure_default_topics(session)
    topics = session.query(NewsTopic).filter(NewsTopic.status == "active").all()
    for topic in topics:
        try:
            result = _news.collect_topic(topic.id, tg_provider=tg_provider)
            if result.get("added"):
                log.info("News pass: topic=%s added=%s", topic.id, result["added"])
        except Exception:
            log.exception("News pass failed for topic %s", topic.id)


def _run_digest_pass(session):
    """Generate a daily digest for each auto-collect brand. Best-effort."""
    import radar.digests as _digests
    from .llm import LLMNotConfigured
    from .models import Brand
    brands = session.query(Brand).filter(Brand.auto_collect.is_(True)).all()
    for b in brands:
        try:
            if _digests.build_daily_digest(session, b.id):
                session.commit()
                log.info("Daily digest generated for brand %s", b.id)
        except LLMNotConfigured:
            return  # no key configured — stop this pass
        except Exception:
            log.exception("Digest pass failed for brand %s", b.id)


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
    def __init__(self, provider, tick_sec: int = 60, tg_provider=None, web_provider=None):
        self._provider     = provider
        self._tg_provider  = tg_provider   # routes platform="telegram" probes; None = skip them
        self._web_provider = web_provider
        self._tick_sec     = tick_sec
        self._bucket       = TokenBucket()
        self._running      = False
        self._timer        = None
        self._last_hotwatch = 0.0
        self._last_chats    = 0.0
        self._last_digest   = 0.0
        self._last_web      = 0.0
        self._last_news     = 0.0
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
            self._maybe_daily_digest(session)
            self._maybe_collect_web(session)
            self._maybe_collect_news(session)
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

    def _maybe_daily_digest(self, session):
        if not ENABLE_DIGESTS:
            return
        if time.monotonic() - self._last_digest < INTERVAL_DIGEST:
            return
        self._last_digest = time.monotonic()
        _run_digest_pass(session)

    def _maybe_collect_web(self, session):
        if self._web_provider is None:
            return
        if time.monotonic() - self._last_web < INTERVAL_WEB:
            return
        self._last_web = time.monotonic()
        _run_web_pass(session, self._web_provider)

    def _maybe_collect_news(self, session):
        if self._web_provider is None:
            return
        if time.monotonic() - self._last_news < INTERVAL_NEWS:
            return
        self._last_news = time.monotonic()
        _run_news_pass(session, tg_provider=self._tg_provider)

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

