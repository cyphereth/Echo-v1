"""Telegram provider via Telethon. Parallel source to TikHub/SocialCrawl.

Requires a session file created once via `python -m radar.tg_auth`. The parser
(`_parse_tg_message`) is a pure function so it can be tested without a live client.
"""
import asyncio, logging, os, re, threading
from typing import Optional

from .base import SearchProvider, SearchPage, Post, Comment

log = logging.getLogger(__name__)

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

    def __init__(self, client=None):
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
            self._client = TelegramClient(SESSION_FILE, int(API_ID), API_HASH, loop=self._loop)
            self._await(self._client.connect())

    def _await(self, result):
        """Real client methods return coroutines — drive them on the dedicated loop
        thread and block for the result. Injected test clients return plain values."""
        if self._loop is not None:
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
            raise RuntimeError(f"Telegram flood wait {e.seconds}s")
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
            raise RuntimeError(f"Telegram flood wait {e.seconds}s")
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
            raise RuntimeError(f"Telegram flood wait {e.seconds}s")
        except Exception as e:
            # No discussion group, comments closed, invalid msg id, etc. — skip.
            log.warning("Telegram comments unavailable (%s/%s): %s", handle, post_id, type(e).__name__)
            return []
        return [_parse_tg_comment(m) for m in msgs if getattr(m, "id", None)]
