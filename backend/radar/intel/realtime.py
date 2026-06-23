"""Intel-domain realtime listener.

Subscribes to Telegram's update stream (events.NewMessage) on the SAME long-lived
Telethon client the polling provider already runs, so monitored channels/chats land
as IntelMention rows the instant they're published — no waiting for the next poll.

Two halves, both pure-testable:
- build_source_map(session): turn IntelProbe rows into a {username -> side/kind} lookup
  plus the join handles / invite links (used only when auto-join is enabled).
- store_realtime_post(session, post, side, kind, lexicon_terms): apply the SAME
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

from sqlalchemy.exc import IntegrityError

from ..core.db import get_session
from ..core.providers.telegram import _parse_tg_message, _parse_tg_chat_message
from .models import IntelLexicon, IntelMention, IntelProbe
from .geo import detect_direction
from .tagging import resolve_direction_id
from .collector import (
    MIN_TEXT_LEN,
    _clean_handle,
    _is_invite_link,
    keyword_or_geo_relevant,
    chat_message_relevant,
)

log = logging.getLogger("radar.intel.realtime")


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
        by_user[handle] = {"side": p.side, "kind": p.kind, "handle": "@" + handle}
        join_handles.append("@" + handle)
    return by_user, join_handles, invite_links


# ── Persistence ─────────────────────────────────────────────────────────────────

def store_realtime_post(session, post, side, kind, lexicon_terms) -> bool:
    """Persist one parsed Post as an IntelMention, or skip it.

    Applies the same gate the poller uses (chat_message_relevant for chats; length +
    keyword/geo for channels), tags a direction, and dedups on (platform, post_id) via
    a savepoint. Returns True if a new row was stored. Caller commits.
    """
    text = post.text or ""
    author = post.author or ""

    if kind == "chat":
        if not chat_message_relevant(text, author, lexicon_terms):
            return False
    else:
        clean = " ".join(w for w in text.split() if not w.startswith("#")).strip()
        if len(clean) < MIN_TEXT_LEN:
            return False
        if not keyword_or_geo_relevant(text, lexicon_terms):
            return False

    dir_id = resolve_direction_id(session, detect_direction(text))
    mention = IntelMention(
        direction_id=dir_id,
        platform=post.platform or "telegram",
        post_id=post.post_id,
        author=author,
        side=side,
        text=text,
        url=getattr(post, "url", None),
        views=getattr(post, "views", 0) or 0,
        created_at=post.created_at,
    )
    sp = session.begin_nested()
    try:
        session.add(mention)
        session.flush()
        sp.commit()
        return True
    except IntegrityError:
        sp.rollback()
        return False


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
        self._lexicon: list[str] = []

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
            self._lexicon = [t for (t,) in session.query(IntelLexicon.term).all()]
        finally:
            session.close()

        if not self._by_user:
            log.warning("intel realtime: no sources configured — not listening")
            return False
        if not self._lexicon:
            log.warning("intel realtime: lexicon empty — channel posts kept only on geo match")

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

        side, kind = info["side"], info["kind"]
        msg = event.message
        try:
            if kind == "chat":
                ns = username or str(getattr(event, "chat_id", "chat"))
                post = _parse_tg_chat_message(msg, ns, "@" + username if username else "@chat")
            else:
                followers = getattr(chat, "participants_count", 0) or 0
                handle = "@" + username if username else str(getattr(event, "chat_id", "tg"))
                post = _parse_tg_message(msg, handle, followers)
        except Exception:
            log.exception("intel realtime: failed to parse message")
            return

        session = get_session()
        try:
            if store_realtime_post(session, post, side, kind, self._lexicon):
                session.commit()
                log.info("intel realtime stored %s (%s)", post.post_id, side)
            else:
                session.rollback()
        except Exception:
            session.rollback()
            log.exception("intel realtime: store failed for %s", post.post_id)
        finally:
            session.close()

    def _subscribe(self, join_handles: list[str], invite_links: list[tuple]) -> None:
        prov = self.provider
        for handle in join_handles:
            try:
                if hasattr(prov, "join_channel"):
                    prov.join_channel(handle)
            except Exception:
                log.warning("intel realtime: join failed for %s", handle)
        for link, _side, _kind in invite_links:
            try:
                if hasattr(prov, "join_invite"):
                    prov.join_invite(link)
            except Exception:
                log.warning("intel realtime: invite join failed for %s", link)
        log.info("intel realtime: subscribe sweep done (%d channels, %d invites)",
                 len(join_handles), len(invite_links))
