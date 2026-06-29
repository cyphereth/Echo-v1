"""Intel-domain realtime listener.

Subscribes to Telegram's update stream (events.NewMessage) on the SAME long-lived
Telethon client the polling provider already runs, so monitored channels/chats land
as IntelMention rows the instant they're published — no waiting for the next poll.

Two halves, both pure-testable:
- build_source_map(session): turn IntelProbe rows into a {username -> side/kind} lookup
  plus the join handles / invite links (used only when auto-join is enabled).
- store_realtime_post(session, post, side, kind, lexicon_tiers): apply the SAME
  relevance gate + dedup the poller uses and persist one IntelMention. post_id comes
  from the provider's own parsers, so a post seen by BOTH realtime and polling
  collapses to one row via the (platform, post_id) unique key.

Telethon only delivers NewMessage for dialogs the account is subscribed to. The
listener therefore covers whatever the curator's account already follows and filters
to the monitored set. Optional auto-join (ENABLE_INTEL_REALTIME_JOIN=1) subscribes to
the rest — that's the Feature-A bolt-on, off by default to avoid a join storm at boot.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from sqlalchemy.exc import IntegrityError

from ..core.db import get_session
from ..core.providers.telegram import (
    _parse_tg_message, _parse_tg_chat_message, chat_namespace,
)
from .models import IntelMention, IntelProbe
from .tagging import tag_geo
from .collector import (
    MIN_TEXT_LEN,
    _clean_handle,
    _is_invite_link,
    _geo_hit,
    keyword_relevant,
    chat_message_relevant,
    load_lexicon_tiers,
    _write_m2m_for_mention,
)
from .translate import maybe_translate
from .spam_filter import load_spam, load_keywords, is_spam_text, blocked_by_word

log = logging.getLogger("radar.intel.realtime")

# How often the running listener re-reads the keyword lexicon from the DB, so edits to
# the filter take effect live without a backend restart (the poller already reloads
# per-call; this gives the realtime path the same freshness within the TTL).
LEXICON_TTL_SEC = 60.0


# ── Source map ──────────────────────────────────────────────────────────────────

def build_source_map(session):
    """Read IntelProbe rows into the structures the listener needs.

    Returns (by_user, join_handles, invite_links):
    - by_user: {username_lower: {"side", "kind", "handle"}} — the lookup an incoming
      event is matched against (event.chat.username, case-insensitive).
    - join_handles: ["@name", ...] public sources to JoinChannelRequest (auto-join).
    - invite_links: [(raw_link, side, kind), ...] private sources to ImportChatInvite.
    """
    by_user: dict[str, dict] = {}
    join_handles: list[str] = []
    invite_links: list[tuple] = []
    for p in session.query(IntelProbe).all():
        raw = p.query or ""
        if _is_invite_link(raw):
            invite_links.append((raw, p.side, p.kind))
            continue
        handle = _clean_handle(raw).lstrip("@").lower()
        if not handle:
            continue
        by_user[handle] = {"side": p.side, "kind": p.kind, "handle": "@" + handle,
                           "subject": p.subject, "direction_id": p.direction_id}
        join_handles.append("@" + handle)
    return by_user, join_handles, invite_links


# ── Persistence ─────────────────────────────────────────────────────────────────

def store_realtime_post(session, post, side, kind, lexicon_tiers,
                        spam_words=None, spam_examples=None, keywords=None,
                        subject=None, src_direction_id=None) -> bool:
    """Persist one parsed Post as an IntelMention, or skip it.

    Applies the same gate the poller uses (chat_message_relevant for chats; length +
    keyword/geo for channels, OR'd with curator-managed positive keywords), drops
    curator-marked spam (стоп-слово или дословный дубль примера — пост не пишется в БД
    вообще, не попадает ни в ленту, ни в сюжеты), tags a direction, and dedups on
    (platform, post_id) via a savepoint. Returns True if a new row was stored. Caller
    commits.
    """
    # Перевод uk→ru ДО гейтов: лексикон/гео-фильтры русскоязычные, а часть
    # источников (каналы тревог) пишут по-украински. Поллер уже так делает
    # (collector.py); realtime раньше писал текст как есть — отсюда непереведённые
    # посты в свежей ленте. Перевод сетевой, но вызывается off-loop (см. _on_message).
    text = maybe_translate(post.text or "")
    author = post.author or ""

    geo_hit = _geo_hit(text)
    if kind == "chat":
        if not chat_message_relevant(text, author, lexicon_tiers, keywords or (),
                                     geo_hit=geo_hit):
            return False
    else:
        # Curator-keyword hit overrides the length gate (short replies/comments), same as
        # the poller. Lexicon admission still requires the post to clear MIN_TEXT_LEN.
        kw_hit = blocked_by_word(text, keywords or ())
        if not kw_hit:
            clean = " ".join(w for w in text.split() if not w.startswith("#")).strip()
            if len(clean) < MIN_TEXT_LEN:
                return False
            if not keyword_relevant(text, lexicon_tiers, geo_hit=geo_hit):
                return False

    # Антиспам: дословный дубль примера или стоп-слово — выкидываем до записи.
    if is_spam_text(text, spam_words, spam_examples):
        return False

    # Та же гео-привязка, что и у поллера (collector.py): текст решает область, а
    # subject/область источника подставляются как fallback, если текст не назвал место
    # (или назвал ту же область). Иначе live-посты теряли местоположение канала.
    from types import SimpleNamespace
    probe = SimpleNamespace(subject=subject, direction_id=src_direction_id)
    dir_id, subject = tag_geo(session, probe, text)
    mention = IntelMention(
        direction_id=dir_id,
        subject=subject,
        platform=post.platform or "telegram",
        post_id=post.post_id,
        author=author,
        side=side,
        text=text,
        url=getattr(post, "url", None),
        views=getattr(post, "views", 0) or 0,
        created_at=post.created_at,
        reply_to_tg_id=getattr(post, "reply_to_tg_id", None),
        media=getattr(post, "media", None),
    )
    sp = session.begin_nested()
    try:
        session.add(mention)
        session.flush()
        sp.commit()
    except IntegrityError:
        sp.rollback()
        return False

    # Привязка к направлениям через m2m (intel_mention_directions) — ТАК ЖЕ, как поллер
    # (collector._write_m2m_for_mention): direction_id поста = "source", совпавшие
    # гео-термины = "geo". Без этого живые посты не попадают в колонки Ленты v2, которая
    # читает именно m2m, а не одиночный mention.direction_id. Ошибки тут не валят запись.
    try:
        _write_m2m_for_mention(session, mention)
    except Exception:
        log.exception("realtime: m2m direction write failed for %s", mention.post_id)

    # Мгновенное обогащение треда: если родитель уже в БД, собираем цепочку прямо
    # сейчас (без сети) — кнопка «в ответ на» появляется в ту же секунду, не ждём
    # тика. Родителя нет локально → context_fetched остаётся False, подтянет
    # сетевой enrich_context на следующем тике. Ошибки не валят запись поста.
    if mention.reply_to_tg_id:
        from .context_pass import _resolve_locally
        try:
            _resolve_locally(session, mention)
        except Exception:
            log.exception("realtime: local thread resolve failed for %s", mention.post_id)
            session.rollback()
    return True


# ── Listener ────────────────────────────────────────────────────────────────────

class IntelRealtime:
    """Registers a NewMessage handler on the provider's live client + loop.

    Lifecycle: start() builds the source map, optionally joins sources in a background
    thread, then attaches the handler. stop() detaches it. The handler runs on the
    provider's event-loop thread; each event opens a short-lived session, stores, and
    closes — keeping SQLite writes serialized to single rows.
    """

    def __init__(self, provider):
        self.provider = provider
        self._handler = None
        self._by_user: dict[str, dict] = {}
        self._id_map: dict[int, dict] = {}
        self._lexicon: dict[str, str] = {}
        self._spam_words: list[str] = []
        self._spam_examples: list[str] = []
        self._keywords: list[str] = []
        self._lex_loaded_at: float = 0.0
        # Single-flight guard so a burst of replies spawns at most one network
        # context-enrich pass at a time (keeps SQLite writes serialized, avoids floods).
        self._enrich_lock = threading.Lock()

    def start(self) -> bool:
        client = getattr(self.provider, "_client", None)
        loop = getattr(self.provider, "_loop", None)
        if client is None or loop is None:
            log.warning("intel realtime: provider has no live client/loop — skipped")
            return False

        from telethon import events

        session = get_session()
        try:
            self._by_user, join_handles, invite_links = build_source_map(session)
            self._lexicon = load_lexicon_tiers(session)
            self._spam_words, self._spam_examples = load_spam(session)
            self._keywords = load_keywords(session)
        finally:
            session.close()
        self._lex_loaded_at = time.monotonic()

        if not self._by_user:
            log.warning("intel realtime: no sources configured — not listening")
            return False
        if not self._lexicon:
            log.warning("intel realtime: lexicon empty — keyword filter will drop everything")

        if os.getenv("ENABLE_INTEL_REALTIME_JOIN", "0") == "1":
            threading.Thread(
                target=self._subscribe, args=(join_handles, invite_links),
                name="intel-realtime-join", daemon=True,
            ).start()

        async def _handler(event):
            await self._on_message(event)

        self._handler = _handler
        client.add_event_handler(_handler, events.NewMessage())
        log.info("intel realtime listening on %d sources (lexicon=%d terms)",
                 len(self._by_user), len(self._lexicon))
        return True

    def stop(self) -> None:
        client = getattr(self.provider, "_client", None)
        if client is not None and self._handler is not None:
            try:
                client.remove_event_handler(self._handler)
            except Exception:
                log.exception("intel realtime: failed to remove handler")
        self._handler = None

    # -- internals --

    def _refresh_lexicon(self) -> None:
        """Reload the keyword lexicon AND spam lists from the DB if the TTL has elapsed,
        so live edits to the filter/antispam take effect without restarting the backend."""
        if time.monotonic() - self._lex_loaded_at < LEXICON_TTL_SEC:
            return
        session = get_session()
        try:
            self._lexicon = load_lexicon_tiers(session)
            self._spam_words, self._spam_examples = load_spam(session)
            self._keywords = load_keywords(session)
        finally:
            session.close()
        self._lex_loaded_at = time.monotonic()

    def _lookup(self, username: str, chat_id) -> dict | None:
        info = self._by_user.get((username or "").lower())
        if info is None and chat_id is not None:
            info = self._id_map.get(chat_id)
        return info

    async def _on_message(self, event) -> None:
        try:
            chat = await event.get_chat()
        except Exception:
            return
        username = (getattr(chat, "username", None) or "").lower()
        info = self._lookup(username, getattr(event, "chat_id", None))
        if info is None:
            return

        # Remember the numeric id so a username-less source still matches next time.
        if getattr(event, "chat_id", None) is not None:
            self._id_map.setdefault(event.chat_id, info)

        self._refresh_lexicon()
        side, kind = info["side"], info["kind"]
        msg = event.message
        try:
            if kind == "chat":
                ns = chat_namespace(username, getattr(event, "chat_id", None))
                post = _parse_tg_chat_message(msg, ns, "@" + username if username else "@chat")
            else:
                followers = getattr(chat, "participants_count", 0) or 0
                handle = "@" + username if username else str(getattr(event, "chat_id", "tg"))
                post = _parse_tg_message(msg, handle, followers)
        except Exception:
            log.exception("intel realtime: failed to parse message")
            return

        # store_realtime_post does a synchronous uk→ru translate (network) before the
        # relevance gates. Run it off the Telethon event-loop thread so a burst of
        # translatable posts doesn't stall update processing for everyone else.
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            stored = await loop.run_in_executor(
                None, self._store_sync, post, side, kind,
                info.get("subject"), info.get("direction_id"),
            )
        except Exception:
            log.exception("intel realtime: store failed for %s", post.post_id)
            return

        if stored:
            log.info("intel realtime stored %s (%s)", post.post_id, side)
            # If this is a reply whose parent wasn't already local (so
            # store_realtime_post couldn't assemble the chain offline), pull the
            # thread from Telegram NOW instead of waiting up to a full tick
            # (INTEL_TICK_SEC) for the poller's enrich pass.
            if getattr(post, "reply_to_tg_id", None):
                self._kick_enrich()

    def _store_sync(self, post, side, kind, subject=None, src_direction_id=None) -> bool:
        """Open a short-lived session, store the post (translate + gates + dedup),
        commit, and report whether a new row landed. Runs in an executor thread."""
        session = get_session()
        try:
            if store_realtime_post(session, post, side, kind, self._lexicon,
                                   self._spam_words, self._spam_examples, self._keywords,
                                   subject, src_direction_id):
                session.commit()
                return True
            session.rollback()
            return False
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _kick_enrich(self) -> None:
        """Drain pending reply-thread context in a background thread.

        Runs OFF the Telethon event-loop thread on purpose: provider._await blocks on
        run_coroutine_threadsafe(...).result(), which would deadlock if called from the
        loop thread itself. The single-flight lock means a burst of replies triggers one
        pass (it picks up every pending reply via the context_fetched=False query), not
        one network storm per message.
        """
        if not self._enrich_lock.acquire(blocking=False):
            return  # a pass is already running; it will pick up this reply too

        def _run():
            try:
                from .context_pass import enrich_context
                session = get_session()
                try:
                    n = enrich_context(session, self.provider, batch_size=20)
                    if n:
                        log.info("intel realtime: enriched %d reply thread(s) on arrival", n)
                except Exception:
                    log.exception("intel realtime: on-arrival enrich failed")
                finally:
                    session.close()
            finally:
                self._enrich_lock.release()

        threading.Thread(target=_run, name="intel-rt-enrich", daemon=True).start()

    def _subscribe(self, join_handles: list[str], invite_links: list[tuple]) -> None:
        # Delegate to the shared sweep: it SKIPS already-joined sources (subscribed.json)
        # and stops cleanly on a long flood-wait, so it only spends the join budget on
        # sources not yet subscribed — finishing the remainder across runs rather than
        # re-attempting the ones already done. Args ignored; subscribe.run rebuilds them.
        try:
            from .subscribe import run as run_subscribe
            summary = run_subscribe(self.provider)
            log.info("intel realtime: subscribe sweep summary %s", summary)
        except Exception:
            log.exception("intel realtime: subscribe sweep failed")
