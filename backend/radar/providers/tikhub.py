import logging, os
from datetime import datetime, timezone
from typing import Optional
import httpx
from .base import Comment, Post, SearchProvider, SearchPage

log = logging.getLogger(__name__)
TIKHUB_TOKEN = os.getenv("TIKHUB_TOKEN", "")
BASE_URL = "https://api.tikhub.io"


def _now():
    return datetime.now(timezone.utc)


class TikHubProvider(SearchProvider):
    """One TikHub token, two platforms. `platform` selects the endpoint family;
    TikTok and Instagram have different paths and response shapes, so each gets
    its own search/comments path and its own parser."""

    def __init__(self, token: str = TIKHUB_TOKEN):
        self._headers = {"Authorization": f"Bearer {token}"}

    # ── dispatch ────────────────────────────────────────────────────────────
    def search(self, query: str, kind: str, cursor: Optional[str], platform: str = "tiktok") -> SearchPage:
        if platform == "instagram":
            return self._search_instagram(query, cursor)
        return self._search_tiktok(query, cursor)

    def fetch_comments(self, post_id: str, cursor: Optional[str], platform: str = "tiktok") -> list[Comment]:
        if platform == "instagram":
            return self._comments_instagram(post_id, cursor)
        return self._comments_tiktok(post_id, cursor)

    # ── TikTok ──────────────────────────────────────────────────────────────
    def _search_tiktok(self, query: str, cursor: Optional[str]) -> SearchPage:
        offset = int(cursor) if cursor else 0
        try:
            resp = httpx.get(
                f"{BASE_URL}/api/v1/tiktok/web/fetch_general_search",
                headers=self._headers,
                params={"keyword": query, "count": 20, "offset": offset},
                timeout=20,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"TikHub error {e.response.status_code}: {e.response.text[:200]}")

        body     = resp.json()
        raw_list = body.get("data", {}).get("data", [])
        posts    = []
        for item in raw_list:
            try:
                video = item.get("item", item)
                if item.get("type") != 1 and "id" not in video:
                    continue
                posts.append(_parse_tiktok_post(video))
            except Exception:
                continue

        has_more    = len(raw_list) >= 20
        next_cursor = str(offset + len(raw_list)) if has_more else None
        return SearchPage(posts=posts, next_cursor=next_cursor)

    def _comments_tiktok(self, post_id: str, cursor: Optional[str]) -> list[Comment]:
        offset = int(cursor) if cursor else 0
        try:
            resp = httpx.get(
                f"{BASE_URL}/api/v1/tiktok/web/fetch_video_comments",
                headers=self._headers,
                params={"aweme_id": post_id, "count": 20, "cursor": offset},
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as e:
            log.warning("TikHub TikTok comments fetch failed for %s: %s", post_id, e)
            return []

        body = resp.json()
        data = body.get("data", body)
        raw  = data.get("comments") or data.get("comment_list") or []
        out  = []
        for c in raw:
            try:
                out.append(_parse_tiktok_comment(c))
            except Exception:
                continue
        return out

    # ── Instagram ───────────────────────────────────────────────────────────
    def _search_instagram(self, query: str, cursor: Optional[str]) -> SearchPage:
        # Instagram has no free-text post search — monitoring is hashtag-based.
        # The brand/competitor/niche term is used as the hashtag keyword.
        params = {"keyword": query.lstrip("#"), "feed_type": "top"}
        # IG pagination tokens from this endpoint expire quickly and cause 400
        # on retry — cap at 1 page per probe run to avoid stale token errors.
        if cursor:
            return SearchPage(posts=[], next_cursor=None)
        try:
            resp = httpx.get(
                f"{BASE_URL}/api/v1/instagram/v2/fetch_hashtag_posts",
                headers=self._headers,
                params=params,
                timeout=25,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"TikHub IG error {e.response.status_code}: {e.response.text[:200]}")

        body  = resp.json()
        data  = body.get("data", {}) or {}
        items = (data.get("data", {}) or {}).get("items", []) or []
        posts = []
        for item in items:
            try:
                posts.append(_parse_ig_post(item))
            except Exception:
                continue
        next_cursor = data.get("pagination_token") or None
        return SearchPage(posts=posts, next_cursor=next_cursor)

    def _comments_instagram(self, post_id: str, cursor: Optional[str]) -> list[Comment]:
        # post_id is the IG shortcode (see _parse_ig_post) — also accepted as a URL.
        params = {"code_or_url": post_id, "sort_by": "recent"}
        if cursor:
            params["pagination_token"] = cursor
        try:
            resp = httpx.get(
                f"{BASE_URL}/api/v1/instagram/v2/fetch_post_comments",
                headers=self._headers,
                params=params,
                timeout=25,
            )
            resp.raise_for_status()
        except Exception as e:
            log.warning("TikHub IG comments fetch failed for %s: %s", post_id, e)
            return []

        body  = resp.json()
        items = ((body.get("data", {}) or {}).get("data", {}) or {}).get("items", []) or []
        out   = []
        for c in items:
            try:
                out.append(_parse_ig_comment(c))
            except Exception:
                continue
        return out


# ── parsers: TikTok ─────────────────────────────────────────────────────────
def _parse_tiktok_comment(c: dict) -> Comment:
    user = c.get("user", {}) or {}
    return Comment(
        comment_id=str(c.get("cid") or c.get("comment_id") or c.get("id", "")),
        author=user.get("nickname") or user.get("unique_id") or str(user.get("uid", "anon")),
        followers=user.get("follower_count", 0) or 0,
        text=c.get("text") or c.get("content", ""),
        likes=c.get("digg_count", 0) or 0,
        created_at=datetime.fromtimestamp(c.get("create_time", 0) or 0, tz=timezone.utc),
    )


def _parse_tiktok_post(item: dict) -> Post:
    author = item.get("author", {})
    stats  = item.get("stats", item.get("statistics", {}))
    hashtags = [
        ch.get("title") or ch.get("hashtagName", "")
        for ch in item.get("challenges", [])
        if ch.get("title") or ch.get("hashtagName")
    ]
    if not hashtags:
        hashtags = [
            te.get("hashtagName", "")
            for te in item.get("textExtra", [])
            if te.get("hashtagName")
        ]
    return Post(
        post_id=str(item.get("id", "")),
        platform="tiktok",
        author=author.get("uniqueId") or author.get("unique_id") or str(author.get("id", "")),
        followers=author.get("stats", {}).get("followerCount", 0),
        text=item.get("desc", ""),
        hashtags=hashtags,
        created_at=datetime.fromtimestamp(item.get("createTime", 0), tz=timezone.utc),
        likes=stats.get("diggCount", 0),
        views=stats.get("playCount", 0),
        comments=stats.get("commentCount", 0),
        shares=stats.get("shareCount", 0),
        sound_id=str(item.get("music", {}).get("id", "") or ""),
    )


# ── parsers: Instagram ────────────────────────────────────────────────────────
def _parse_ig_post(item: dict) -> Post:
    user = item.get("user", {}) or {}
    text = item.get("caption_text", "") or ""
    hashtags = [h for h in (item.get("caption_hashtags") or []) if h]
    if not hashtags:
        hashtags = [w.lstrip("#") for w in text.split() if w.startswith("#")]
    ts = item.get("taken_at_ts") or 0
    # Store the shortcode as post_id: it builds the post URL and is what the
    # comments endpoint expects (code_or_url).
    return Post(
        post_id=str(item.get("code") or item.get("id", "")),
        platform="instagram",
        author=user.get("username") or str(user.get("id", "")),
        followers=user.get("follower_count") or 0,
        text=text,
        hashtags=hashtags,
        created_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else _now(),
        likes=item.get("like_count") or 0,
        views=item.get("play_count") or item.get("view_count") or 0,
        comments=item.get("comment_count") or 0,
        shares=0,            # Instagram API does not expose share counts
        sound_id=None,
    )


def _parse_ig_comment(c: dict) -> Comment:
    user = c.get("user", {}) or {}
    ts = c.get("created_at_utc") or c.get("created_at") or 0
    return Comment(
        comment_id=str(c.get("id") or c.get("pk", "")),
        author=user.get("username") or str(user.get("id", "anon")),
        followers=user.get("follower_count") or 0,
        text=c.get("text", ""),
        likes=c.get("comment_like_count") or c.get("like_count") or 0,
        created_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else _now(),
    )
