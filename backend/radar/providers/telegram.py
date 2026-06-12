"""Telegram provider via Telethon. Parallel source to TikHub/SocialCrawl.

Requires a session file created once via `python -m radar.tg_auth`. The parser
(`_parse_tg_message`) is a pure function so it can be tested without a live client.
"""
import logging, os, re
from typing import Optional

from .base import SearchProvider, SearchPage, Post

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


class TelegramProvider(SearchProvider):
    """Telethon-backed. Pass `client` for tests; otherwise a real client is built
    and connected against the session file."""

    def __init__(self, client=None):
        if client is not None:
            self._client = client
        else:
            from telethon.sync import TelegramClient
            self._client = TelegramClient(SESSION_FILE, int(API_ID), API_HASH)
            self._client.connect()

    def search(self, query: str, kind: str, cursor: Optional[str], platform: str = "telegram") -> SearchPage:
        if kind == "channel":
            return self._read_channel(query, cursor)
        return self._global_search(query, cursor)

    def _global_search(self, query: str, cursor: Optional[str]) -> SearchPage:
        from telethon.errors import FloodWaitError
        offset_id = int(cursor) if cursor else 0
        try:
            msgs = self._client.get_messages(None, search=query, limit=20, offset_id=offset_id)
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
        from telethon.errors import FloodWaitError, ChannelPrivateError
        offset_id = int(cursor) if cursor else 0
        handle = username if username.startswith("@") else f"@{username}"
        try:
            entity = self._client.get_entity(handle)
            msgs = self._client.get_messages(entity, limit=20, offset_id=offset_id)
        except FloodWaitError as e:
            log.warning("Telegram flood wait %ds", e.seconds)
            raise RuntimeError(f"Telegram flood wait {e.seconds}s")
        except ChannelPrivateError:
            log.warning("Telegram channel private/unavailable: %s", handle)
            return SearchPage(posts=[], next_cursor=None)
        followers = getattr(entity, "participants_count", 0) or 0
        posts = [_parse_tg_message(m, handle, followers) for m in msgs if getattr(m, "id", None)]
        next_cursor = str(min(m.id for m in msgs)) if len(msgs) >= 20 else None
        return SearchPage(posts=posts, next_cursor=next_cursor)
