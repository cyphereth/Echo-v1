"""Telegram provider via Telethon. Parallel source to TikHub/SocialCrawl.

Requires a session file created once via `python -m radar.tg_auth`. The parser
(`_parse_tg_message`) is a pure function so it can be tested without a live client.
"""
import asyncio, logging, os, re, threading, time
from typing import Optional

from .base import SearchProvider, SearchPage, Post, Comment

log = logging.getLogger(__name__)


class TelegramFloodWait(RuntimeError):
    """Raised when Telegram returns a flood-wait longer than the provider's
    threshold. Carries ``.seconds`` so callers can back off / abort the cycle
    instead of hammering on. Subclasses RuntimeError so existing broad handlers
    still catch it."""
    def __init__(self, seconds: int):
        self.seconds = seconds
        super().__init__(f"Telegram flood wait {seconds}s")


SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "tg_session")
API_ID   = os.getenv("TELEGRAM_API_ID", "")
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

_HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)


def _sum_reactions(msg) -> int:
    """Sum all reaction counts on a Telethon message; 0 if none."""
    reactions = getattr(msg, "reactions", None)
    if not reactions:
        return 0
    results = getattr(reactions, "results", None) or []
    return sum(int(getattr(r, "count", 0) or 0) for r in results)


def _parse_tg_message(msg, author_handle: str, followers: int) -> Post:
    """Map a Telethon Message to a Post. `author_handle` is the channel @username,
    `followers` the channel participant count (both resolved by the caller)."""
    text = getattr(msg, "message", None) or ""
    replies = getattr(msg, "replies", None)
    return Post(
        post_id    = str(msg.id),
        platform   = "telegram",
        author     = author_handle,
        followers  = int(followers or 0),
        text       = text,
        hashtags   = _HASHTAG_RE.findall(text),
        created_at = msg.date,
        likes      = _sum_reactions(msg),
        views      = int(getattr(msg, "views", 0) or 0),
        comments   = int(getattr(replies, "replies", 0) or 0) if replies else 0,
        shares     = int(getattr(msg, "forwards", 0) or 0),
        sound_id   = None,
    )


def _parse_tg_chat_message(msg, namespace: str, fallback_author: str) -> Post:
    """Map a message from inside a group chat to a Post. Unlike a channel post, the
    author is the individual member who wrote it; post_id is namespaced (by the chat's
    @username, or its numeric id for username-less groups) so message ids from different
    chats never collide (the unique key is (platform, post_id))."""
    text   = getattr(msg, "message", None) or ""
    sender = getattr(msg, "sender", None)
    uname  = getattr(sender, "username", None) if sender else None
    author = f"@{uname}" if uname else fallback_author
    ns     = str(namespace).lstrip("@")
    return Post(
        post_id    = f"{ns}/{msg.id}",
        platform   = "telegram",
        author     = author,
        followers  = 0,
        text       = text,
        hashtags   = _HASHTAG_RE.findall(text),
        created_at = msg.date,
        likes      = _sum_reactions(msg),
        views      = int(getattr(msg, "views", 0) or 0),
        comments   = 0,
        shares     = int(getattr(msg, "forwards", 0) or 0),
        sound_id   = None,
    )


def _parse_tg_comment(msg) -> Comment:
    """Map a Telethon discussion reply to a Comment. Author is the commenter's
    @username, or their display name / id when no public username."""
    sender = getattr(msg, "sender", None)
    uname = getattr(sender, "username", None)
    if uname:
        author = f"@{uname}"
    else:
        author = (getattr(sender, "first_name", None)
                  or str(getattr(msg, "sender_id", "") or "user"))
    return Comment(
        comment_id = str(msg.id),
        author     = author,
        followers  = 0,
        text       = getattr(msg, "message", None) or "",
        likes      = _sum_reactions(msg),
        created_at = msg.date,
    )


class TelegramProvider(SearchProvider):
    """Telethon-backed. Pass `client` for tests; otherwise an async client is built
    on a provider-owned event loop so it works from any worker thread (collect runs
    in a FastAPI background thread / scheduler thread, not the loop that built it)."""

    # Throttle ALL Telegram calls to avoid flood-waits (discovery/collect can fan out
    # into hundreds of get_entity/GetFullChannel/get_messages calls). _await is the
    # single chokepoint every API call passes through.
    _MIN_CALL_INTERVAL = float(os.getenv("TG_MIN_CALL_INTERVAL", "0.35"))  # ~3 calls/sec
    # Floods longer than this raise (we skip the item) instead of Telethon silently
    # sleeping for minutes — that's what hung a run for 2h before.
    _FLOOD_THRESHOLD = int(os.getenv("TG_FLOOD_THRESHOLD", "15"))

    def __init__(self, client=None):
        self._call_lock = threading.Lock()
        self._last_call = 0.0
        if client is not None:
            # Test injection: methods return plain values, no loop/thread needed.
            self._client = client
            self._loop = None
        else:
            from telethon import TelegramClient  # async client
            # Run the Telethon client on a dedicated loop in its own thread, so calls
            # work from any caller thread (FastAPI startup loop, background tasks,
            # scheduler) via run_coroutine_threadsafe — avoids "loop already running"
            # and cross-thread connection errors.
            self._loop = asyncio.new_event_loop()
            t = threading.Thread(target=self._loop.run_forever, daemon=True)
            t.start()
            self._client = TelegramClient(SESSION_FILE, int(API_ID), API_HASH, loop=self._loop,
                                          flood_sleep_threshold=self._FLOOD_THRESHOLD)
            self._await(self._client.connect())

    def ensure_connected(self) -> bool:
        """Reconnect the client if the socket dropped (e.g. after the Mac sleeps the
        Telethon connection dies as 'Cannot send requests while disconnected' and does
        not always self-heal). Cheap to call often — no-op when already connected.
        Returns True if connected after the attempt. Test clients (no loop) are no-ops."""
        if self._loop is None:
            return True
        try:
            if self._client.is_connected():
                return True
        except Exception:
            pass
        try:
            asyncio.run_coroutine_threadsafe(self._client.connect(), self._loop).result(timeout=30)
            ok = self._client.is_connected()
            if ok:
                log.info("Telegram client reconnected")
            return ok
        except Exception:
            log.warning("Telegram reconnect attempt failed")
            return False

    def _throttle(self):
        """Block until at least _MIN_CALL_INTERVAL has passed since the previous call,
        so the provider never bursts into a flood-wait."""
        with self._call_lock:
            wait = self._MIN_CALL_INTERVAL - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _await(self, result):
        """Real client methods return coroutines — drive them on the dedicated loop
        thread and block for the result. Injected test clients return plain values."""
        if self._loop is not None:
            self._throttle()
            return asyncio.run_coroutine_threadsafe(result, self._loop).result(timeout=60)
        return result

    def search(self, query: str, kind: str, cursor: Optional[str], platform: str = "telegram") -> SearchPage:
        if kind == "channel":
            return self._read_channel(query, cursor)
        return self._global_search(query, cursor)

    def _global_search(self, query: str, cursor: Optional[str]) -> SearchPage:
        from telethon.errors import FloodWaitError
        offset_id = int(cursor) if cursor else 0
        try:
            msgs = self._await(self._client.get_messages(None, search=query, limit=20, offset_id=offset_id))
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        posts = []
        for m in msgs:
            chat = getattr(m, "chat", None)
            uname = getattr(chat, "username", None)
            handle = f"@{uname}" if uname else str(getattr(getattr(m, "peer_id", None), "channel_id", "tg"))
            followers = getattr(chat, "participants_count", 0) or 0
            try:
                posts.append(_parse_tg_message(m, handle, followers))
            except Exception:
                continue
        next_cursor = str(min(m.id for m in msgs)) if len(msgs) >= 20 else None
        return SearchPage(posts=posts, next_cursor=next_cursor)

    def _read_channel(self, username: str, cursor: Optional[str]) -> SearchPage:
        from telethon.errors import FloodWaitError, ChannelPrivateError, UsernameNotOccupiedError
        offset_id = int(cursor) if cursor else 0
        handle = username if username.startswith("@") else f"@{username}"
        try:
            entity = self._await(self._client.get_entity(handle))
            msgs = self._await(self._client.get_messages(entity, limit=20, offset_id=offset_id))
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        except (ChannelPrivateError, UsernameNotOccupiedError, ValueError) as e:
            # Channel private, banned, or the @handle simply doesn't exist — skip cleanly.
            log.warning("Telegram channel unavailable (%s): %s", handle, type(e).__name__)
            return SearchPage(posts=[], next_cursor=None)
        followers = getattr(entity, "participants_count", 0) or 0
        posts = [_parse_tg_message(m, handle, followers) for m in msgs if getattr(m, "id", None)]
        next_cursor = str(min(m.id for m in msgs)) if len(msgs) >= 20 else None
        return SearchPage(posts=posts, next_cursor=next_cursor)

    def fetch_comments(self, post_id: str, cursor: Optional[str],
                       platform: str = "telegram", channel: Optional[str] = None) -> list:
        """Comments on a channel post are replies in the channel's linked discussion
        group. Needs the channel handle + post id. Returns [] when comments are
        disabled or the channel/post is unavailable."""
        from telethon.errors import FloodWaitError
        if not channel:
            return []
        handle = channel if channel.startswith("@") else f"@{channel}"
        try:
            entity = self._await(self._client.get_entity(handle))
            msgs = self._await(self._client.get_messages(
                entity, reply_to=int(post_id), limit=30))
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        except Exception as e:
            # No discussion group, comments closed, invalid msg id, etc. — skip.
            log.warning("Telegram comments unavailable (%s/%s): %s", handle, post_id, type(e).__name__)
            return []
        return [_parse_tg_comment(m) for m in msgs if getattr(m, "id", None)]

    def discover_channels(self, query: str, limit: int = 30) -> list[dict]:
        """Find public channels/groups matching a query (sphere/niche term), biggest
        first — used to bootstrap seed channels for a brand that hasn't curated any.
        Sphere-agnostic: the caller passes the brand's own sphere/niche terms."""
        from telethon.tl.functions.contacts import SearchRequest
        from telethon.errors import FloodWaitError
        try:
            res = self._await(self._client(SearchRequest(q=query, limit=limit)))
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        except Exception as e:
            log.warning("Telegram channel discovery failed (%r): %s", query, type(e).__name__)
            return []
        out = []
        for ch in getattr(res, "chats", []) or []:
            u = getattr(ch, "username", None)
            if not u:
                continue
            out.append({
                "handle": f"@{u}",
                "title": getattr(ch, "title", "") or "",
                "participants": int(getattr(ch, "participants_count", 0) or 0),
            })
        out.sort(key=lambda c: -c["participants"])
        return out[:limit]

    def channel_recommendations(self, handle: str, limit: int = 10) -> list[str]:
        """Telegram's "similar channels" for a channel — returns the @usernames of
        recommended channels. Used to grow a curated seed set into a wider, on-topic
        graph of channels (whose linked chats we then monitor)."""
        from telethon.tl.functions.channels import GetChannelRecommendationsRequest
        from telethon.errors import FloodWaitError
        h = handle if handle.startswith("@") else f"@{handle}"
        try:
            ent = self._await(self._client.get_entity(h))
            rec = self._await(self._client(GetChannelRecommendationsRequest(channel=ent)))
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        except Exception as e:
            log.warning("Telegram recommendations failed (%s): %s", h, type(e).__name__)
            return []
        out = []
        for ch in (getattr(rec, "chats", []) or [])[:limit]:
            u = getattr(ch, "username", None)
            if u:
                out.append(f"@{u}")
        return out

    def linked_chat(self, handle: str) -> Optional[dict]:
        """The discussion group linked to a channel — where the channel's audience
        actually talks ("куда сходить?"). Returns {handle, id, via, title, participants}:
        `handle` is the group's @username when public (clean to address/link), else None
        and the group is reachable by `id` via its parent channel `via`. None if the
        channel has no linked group at all."""
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.errors import FloodWaitError
        h = handle if handle.startswith("@") else f"@{handle}"
        try:
            ent  = self._await(self._client.get_entity(h))
            full = self._await(self._client(GetFullChannelRequest(ent)))
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        except Exception as e:
            log.warning("Telegram linked-chat lookup failed (%s): %s", h, type(e).__name__)
            return None
        lid = getattr(full.full_chat, "linked_chat_id", None)
        if not lid:
            return None
        linked = next((c for c in full.chats if getattr(c, "id", None) == lid), None)
        if not linked:
            return None
        uname = getattr(linked, "username", None)
        return {
            "handle": f"@{uname}" if uname else None,
            "id": lid,
            "via": h,
            "title": getattr(linked, "title", "") or "",
            "participants": int(getattr(linked, "participants_count", 0) or 0),
        }

    def join_channel(self, handle: str) -> bool:
        """Subscribe the account to a public channel/group so its messages start
        arriving on the realtime update stream. Idempotent — already-joined is a no-op.
        Returns True on success (or already-member), False if the channel is
        unavailable. Raises TelegramFloodWait so the caller can back off."""
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.errors import (
            FloodWaitError, UserAlreadyParticipantError, InviteRequestSentError,
        )
        h = handle if handle.startswith("@") else f"@{handle}"
        try:
            ent = self._await(self._client.get_entity(h))
            self._await(self._client(JoinChannelRequest(ent)))
            return True
        except UserAlreadyParticipantError:
            return True
        except InviteRequestSentError:
            # Moderated group — a join request was submitted and awaits admin approval.
            # Treat as done so we don't keep re-requesting; membership (and realtime
            # delivery) starts once an admin approves.
            log.info("Telegram join request sent, awaiting approval (%s)", h)
            return True
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        except Exception as e:
            log.warning("Telegram join failed (%s): %s", h, type(e).__name__)
            return False

    def join_invite(self, link: str) -> bool:
        """Join a private chat via its invite link (t.me/+HASH or t.me/joinchat/HASH)
        so its messages arrive on the realtime stream. Idempotent. Returns True on
        success (or already-member); raises TelegramFloodWait on flood."""
        from telethon.tl.functions.messages import ImportChatInviteRequest
        from telethon.errors import (
            FloodWaitError, UserAlreadyParticipantError, InviteHashExpiredError,
            InviteHashInvalidError,
        )
        raw = (link or "").strip()
        # Extract the invite hash from t.me/+HASH or t.me/joinchat/HASH
        if "/+" in raw:
            invite_hash = raw.split("/+", 1)[1]
        elif "joinchat/" in raw:
            invite_hash = raw.split("joinchat/", 1)[1]
        else:
            invite_hash = raw.lstrip("+")
        invite_hash = invite_hash.strip("/").split("?", 1)[0]
        if not invite_hash:
            return False
        try:
            self._await(self._client(ImportChatInviteRequest(invite_hash)))
            return True
        except UserAlreadyParticipantError:
            return True
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        except (InviteHashExpiredError, InviteHashInvalidError) as e:
            log.warning("Telegram invite invalid (%s): %s", raw, type(e).__name__)
            return False
        except Exception as e:
            log.warning("Telegram invite join failed (%s): %s", raw, type(e).__name__)
            return False

    def search_chat(self, handle: str, term: str, limit: int = 20, min_id: int = 0) -> list[Post]:
        """Server-side search inside one public group for `term`, newest first.
        `min_id` returns only messages newer than that id (the chat's watermark), so
        already-seen messages aren't re-fetched. Returns [] if the chat is private,
        gone, or has no new matches."""
        from telethon.errors import FloodWaitError, ChannelPrivateError, UsernameNotOccupiedError
        h = handle if handle.startswith("@") else f"@{handle}"
        try:
            entity = self._await(self._client.get_entity(h))
            msgs = self._await(self._client.get_messages(entity, search=term, limit=limit, min_id=min_id))
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        except (ChannelPrivateError, UsernameNotOccupiedError, ValueError) as e:
            log.warning("Telegram chat unavailable (%s): %s", h, type(e).__name__)
            return []
        return [_parse_tg_chat_message(m, h, h) for m in msgs if getattr(m, "id", None)]

    def search_linked_chat(self, parent_handle: str, term: str, limit: int = 20, min_id: int = 0) -> list[Post]:
        """Search the discussion group LINKED to a (public) channel, for groups that have
        no public @username. The parent channel is always resolvable, so we reach the
        group through it. `min_id` skips already-seen messages. Messages are namespaced
        by the group's internal id."""
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.errors import FloodWaitError
        h = parent_handle if parent_handle.startswith("@") else f"@{parent_handle}"
        try:
            ent  = self._await(self._client.get_entity(h))
            full = self._await(self._client(GetFullChannelRequest(ent)))
            lid  = getattr(full.full_chat, "linked_chat_id", None)
            if not lid:
                return []
            linked = next((c for c in full.chats if getattr(c, "id", None) == lid), None)
            if not linked:
                return []
            msgs = self._await(self._client.get_messages(linked, search=term, limit=limit, min_id=min_id))
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise TelegramFloodWait(e.seconds)
        except Exception as e:
            log.warning("Telegram linked-chat search failed (%s): %s", h, type(e).__name__)
            return []
        return [_parse_tg_chat_message(m, lid, h) for m in msgs if getattr(m, "id", None)]
