"""SocialCrawl provider (socialcrawl.dev).

One API key, unified envelope across platforms: every response is
{success, platform, endpoint, data:{...}, credits_remaining}. Auth is the
`x-api-key` header. Posts/comments share a normalized shape, so a single parser
covers TikTok and Instagram.

Mapped to the same SearchProvider interface as TikHubProvider so it's a drop-in
swap via _get_provider().
"""
import logging, os, re
from datetime import datetime, timezone
from typing import Optional

import httpx

from .base import SearchProvider, SearchPage, Post, Comment

log = logging.getLogger(__name__)

BASE_URL = "https://www.socialcrawl.dev/v1"
SOCIALCRAWL_TOKEN = os.getenv("SOCIALCRAWL_TOKEN", "")

_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


def _ts(unix_seconds) -> datetime:
    """SocialCrawl returns published_at as unix seconds. Fall back to now()."""
    try:
        return datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)


def _parse_post(item: dict) -> Post:
    """Map a SocialCrawl search/feed item to a Post. Search wraps the payload in
    {"post": {...}, "computed": {...}}; user-post feeds may return it unwrapped."""
    post = item.get("post", item)
    content    = post.get("content", {}) or {}
    author     = post.get("author", {}) or {}
    engagement = post.get("engagement", {}) or {}
    text = content.get("text", "") or ""
    return Post(
        post_id    = str(post.get("id", "")),
        platform   = "instagram" if "instagram" in str(post.get("url", "")) else "tiktok",
        author     = author.get("username", "") or "",
        followers  = int(author.get("follower_count") or author.get("followers") or 0),
        text       = text,
        hashtags   = _HASHTAG_RE.findall(text),
        created_at = _ts(post.get("published_at")),
        likes      = int(engagement.get("likes") or 0),
        views      = int(engagement.get("views") or 0),
        comments   = int(engagement.get("comments") or 0),
        shares     = int(engagement.get("shares") or 0),
        sound_id   = None,
    )


def _parse_comment(item: dict) -> Comment:
    c = item.get("comment", item)
    author     = c.get("author", {}) or {}
    engagement = c.get("engagement", {}) or {}
    return Comment(
        comment_id = str(c.get("id", "")),
        author     = author.get("username", "") or "",
        followers  = int(author.get("follower_count") or author.get("followers") or 0),
        text       = c.get("text", "") or "",
        likes      = int(engagement.get("likes") or 0),
        created_at = _ts(c.get("published_at")),
    )


class SocialCrawlProvider(SearchProvider):
    """SocialCrawl-backed provider. `platform` selects the endpoint family."""

    def __init__(self, token: str = SOCIALCRAWL_TOKEN):
        self._headers = {"x-api-key": token, "User-Agent": "echo-radar/1.0"}

    def _get(self, path: str, params: dict) -> dict:
        resp = httpx.get(f"{BASE_URL}{path}", headers=self._headers,
                         params=params, timeout=40)
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success", True):
            err = (body.get("error") or {}).get("message", "unknown")
            raise RuntimeError(f"SocialCrawl error: {err}")
        return body.get("data", {}) or {}

    # ── Search ──────────────────────────────────────────────────────────────
    def search(self, query: str, kind: str, cursor: Optional[str], platform: str = "tiktok") -> SearchPage:
        if platform == "instagram":
            return self._search_instagram(query, cursor)
        return self._search_tiktok(query, cursor)

    def _search_tiktok(self, query: str, cursor: Optional[str]) -> SearchPage:
        params = {"query": query}
        if cursor:
            params["cursor"] = cursor
        try:
            data = self._get("/tiktok/search", params)
        except Exception as e:
            raise RuntimeError(f"SocialCrawl TikTok search failed for {query!r}: {e}")
        posts = [_parse_post(it) for it in (data.get("items") or [])]
        return SearchPage(posts=posts, next_cursor=data.get("next_cursor"))

    def _search_instagram(self, query: str, cursor: Optional[str]) -> SearchPage:
        # IG keyword discovery is hashtag-based, mirroring the TikHub provider.
        params = {"hashtag": query.lstrip("#")}
        if cursor:
            params["cursor"] = cursor
        try:
            data = self._get("/instagram/search/hashtag", params)
        except Exception as e:
            log.warning("SocialCrawl IG search failed for %r: %s", query, e)
            return SearchPage(posts=[], next_cursor=None)
        posts = [_parse_post(it) for it in (data.get("items") or [])]
        return SearchPage(posts=posts, next_cursor=data.get("next_cursor"))

    # ── Comments ────────────────────────────────────────────────────────────
    # The pipeline calls fetch_comments(post_id, ...), but SocialCrawl wants the
    # post URL. TikTok accepts any handle in the path (a dummy @x works), and IG
    # uses the shortcode URL — both reconstructable from post_id alone.
    def fetch_comments(self, post_id: str, cursor: Optional[str], platform: str = "tiktok") -> list[Comment]:
        if platform == "instagram":
            url = f"https://www.instagram.com/p/{post_id}/"
            path = "/instagram/post/comments"
        else:
            url = f"https://www.tiktok.com/@x/video/{post_id}"
            path = "/tiktok/post/comments"
        params = {"url": url}
        if cursor:
            params["cursor"] = cursor
        try:
            data = self._get(path, params)
        except Exception as e:
            log.warning("SocialCrawl %s comments failed for %s: %s", platform, post_id, e)
            return []
        return [_parse_comment(it) for it in (data.get("items") or [])]

    # ── Profile (onboarding scan) ─────────────────────────────────────────────
    def fetch_profile(self, username: str, platform: str = "tiktok") -> dict:
        handle = username.lstrip("@")
        path = "/instagram/profile" if platform == "instagram" else "/tiktok/profile"
        try:
            data = self._get(path, {"handle": handle})
        except Exception as e:
            log.warning("SocialCrawl %s profile failed for %s: %s", platform, handle, e)
            return {}
        a = data.get("author", data) or {}
        stats = data.get("stats", {}) or a.get("stats", {}) or {}
        return {
            "name":      a.get("display_name") or a.get("full_name") or handle,
            "bio":       a.get("bio") or a.get("biography") or "",
            "followers": int(a.get("follower_count") or stats.get("followers") or 0),
            "username":  a.get("username") or handle,
        }

    def fetch_user_posts(self, username: str, platform: str = "tiktok", limit: int = 15) -> list[Post]:
        handle = username.lstrip("@")
        path = "/instagram/profile/posts" if platform == "instagram" else "/tiktok/profile/videos"
        try:
            data = self._get(path, {"handle": handle})
        except Exception as e:
            log.warning("SocialCrawl %s user posts failed for %s: %s", platform, handle, e)
            return []
        items = data.get("items") or data.get("videos") or data.get("posts") or []
        out = []
        for it in items[:limit]:
            try:
                out.append(_parse_post(it))
            except Exception:
                continue
        return out
