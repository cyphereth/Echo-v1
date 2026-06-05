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
        # Cap at 1 page — IG pagination tokens expire immediately and cause 400.
        if cursor:
            return SearchPage(posts=[], next_cursor=None)
        kw = query.lstrip("#")
        # Try v2 first; fall back to v3/general_search on 400.
        try:
            resp = httpx.get(
                f"{BASE_URL}/api/v1/instagram/v2/fetch_hashtag_posts",
                headers=self._headers,
                params={"keyword": kw, "feed_type": "top"},
                timeout=25,
            )
            if resp.status_code == 400:
                raise httpx.HTTPStatusError("v2 400", request=resp.request, response=resp)
            resp.raise_for_status()
            body  = resp.json()
            data  = body.get("data", {}) or {}
            items = (data.get("data", {}) or {}).get("items", []) or []
            posts = [p for item in items if (p := self._safe_parse_ig(item)) is not None]
            return SearchPage(posts=posts, next_cursor=None)
        except httpx.HTTPStatusError:
            pass  # fall through to v3

        # v3/general_search fallback
        try:
            resp = httpx.get(
                f"{BASE_URL}/api/v1/instagram/v3/general_search",
                headers=self._headers,
                params={"query": kw, "enable_metadata": "True"},
                timeout=25,
            )
            resp.raise_for_status()
        except Exception as e:
            log.warning("IG v3 fallback failed for %r: %s", kw, e)
            return SearchPage(posts=[], next_cursor=None)

        body       = resp.json()
        data       = body.get("data", {}) or {}
        media_grid = data.get("media_grid", {}) or {}
        sections   = media_grid.get("sections", [])
        items = []
        for sec in sections:
            lc = sec.get("layout_content", {}) or {}
            for mw in lc.get("medias", []):
                items.append(mw.get("media", mw))
        posts = [p for item in items if (p := self._safe_parse_ig_v3(item)) is not None]
        return SearchPage(posts=posts, next_cursor=None)

    def _safe_parse_ig(self, item: dict):
        """Parse a v2 IG item dict into a Post, return None on any error."""
        try:
            return _parse_ig_post(item)
        except Exception:
            return None

    def _safe_parse_ig_v3(self, item: dict):
        """Parse a v3/general_search media item into a Post, return None on any error."""
        try:
            return _parse_ig_post_v3(item)
        except Exception:
            return None

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

    # ── Account profile + own posts ───────────────────────────────────────────
    def fetch_profile(self, username: str, platform: str = "tiktok") -> dict:
        try:
            if platform == "instagram":
                resp = httpx.get(
                    f"{BASE_URL}/api/v1/instagram/v1/fetch_user_info_by_username",
                    headers=self._headers, params={"username": username}, timeout=25,
                )
                resp.raise_for_status()
                u = ((resp.json().get("data", {}) or {}).get("user", {}) or {})
                followers = (u.get("edge_followed_by", {}) or {}).get("count", 0) or u.get("follower_count", 0) or 0
                return {
                    "name": u.get("full_name") or username,
                    "bio": u.get("biography", "") or "",
                    "followers": followers,
                    "username": u.get("username") or username,
                    "_userid": str(u.get("id") or u.get("pk") or ""),
                }
            # tiktok
            resp = httpx.get(
                f"{BASE_URL}/api/v1/tiktok/web/fetch_user_profile",
                headers=self._headers, params={"uniqueId": username}, timeout=25,
            )
            resp.raise_for_status()
            ui = (resp.json().get("data", {}) or {}).get("userInfo", {}) or {}
            user = ui.get("user", {}) or {}
            stats = ui.get("stats", {}) or {}
            return {
                "name": user.get("nickname") or username,
                "bio": user.get("signature", "") or "",
                "followers": stats.get("followerCount", 0) or 0,
                "username": user.get("uniqueId") or username,
                "_secuid": user.get("secUid", "") or "",
            }
        except Exception as e:
            log.warning("fetch_profile failed (%s/%s): %s", platform, username, e)
            return {}

    def fetch_user_posts(self, username: str, platform: str = "tiktok", limit: int = 15) -> list[Post]:
        try:
            prof = self.fetch_profile(username, platform)
            if platform == "instagram":
                uid = prof.get("_userid")
                if not uid:
                    return []
                resp = httpx.get(
                    f"{BASE_URL}/api/v1/instagram/v1/fetch_user_posts",
                    headers=self._headers, params={"user_id": uid, "count": limit}, timeout=25,
                )
                resp.raise_for_status()
                data = resp.json().get("data", {}) or {}
                items = data.get("items") or data.get("medias") or []
                return [p for it in items if (p := self._safe_parse_ig(it)) is not None][:limit]
            # tiktok
            secuid = prof.get("_secuid")
            if not secuid:
                return []
            # app/v3 is more reliable than web/fetch_user_post (which 400s often).
            resp = httpx.get(
                f"{BASE_URL}/api/v1/tiktok/app/v3/fetch_user_post_videos",
                headers=self._headers, params={"sec_user_id": secuid, "count": limit}, timeout=25,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {}) or {}
            items = data.get("aweme_list") or data.get("itemList") or []
            out = []
            for it in items:
                try:
                    out.append(_parse_tiktok_app_post(it))
                except Exception:
                    continue
            return out[:limit]
        except Exception as e:
            log.warning("fetch_user_posts failed (%s/%s): %s", platform, username, e)
            return []

    def fetch_location_posts(self, city: str, platform: str = "instagram", limit: int = 15) -> list[Post]:
        """Best-effort geo: resolve city -> IG location -> recent posts. Fail-open."""
        if platform != "instagram" or not city.strip():
            return []
        try:
            r = httpx.get(
                f"{BASE_URL}/api/v1/instagram/v2/search_locations",
                headers=self._headers, params={"keyword": city}, timeout=25,
            )
            r.raise_for_status()
            items = ((r.json().get("data", {}) or {}).get("data", {}) or {}).get("items", []) or []
            if not items:
                return []
            loc_id = items[0].get("id")
            if not loc_id:
                return []
            r2 = httpx.get(
                f"{BASE_URL}/api/v1/instagram/v2/fetch_location_posts",
                headers=self._headers, params={"location_id": loc_id}, timeout=25,
            )
            r2.raise_for_status()
            posts_items = ((r2.json().get("data", {}) or {}).get("data", {}) or {}).get("items", []) or []
            out = [p for it in posts_items if (p := self._safe_parse_ig_v3(it)) is not None]
            return out[:limit]
        except Exception as e:
            log.warning("fetch_location_posts failed for %r: %s", city, e)
            return []


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


def _parse_tiktok_app_post(item: dict) -> Post:
    """Parse a TikTok app/v3 aweme item (different shape than the web format)."""
    author = item.get("author", {}) or {}
    stats  = item.get("statistics", {}) or {}
    hashtags = [
        te.get("hashtag_name", "")
        for te in item.get("text_extra", [])
        if te.get("hashtag_name")
    ]
    ts = item.get("create_time", 0) or 0
    return Post(
        post_id=str(item.get("aweme_id", "")),
        platform="tiktok",
        author=author.get("unique_id") or author.get("nickname") or str(author.get("uid", "")),
        followers=author.get("follower_count", 0) or 0,
        text=item.get("desc", "") or "",
        hashtags=hashtags,
        created_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else _now(),
        likes=stats.get("digg_count", 0) or 0,
        views=stats.get("play_count", 0) or 0,
        comments=stats.get("comment_count", 0) or 0,
        shares=stats.get("share_count", 0) or 0,
        sound_id=None,
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


def _parse_ig_post_v3(item: dict) -> Post:
    """Parse a v3/general_search media item (different field layout than v2)."""
    user    = item.get("user", {}) or {}
    caption = item.get("caption") or {}
    if isinstance(caption, dict):
        text = caption.get("text", "") or ""
    else:
        text = str(caption) if caption else ""
    hashtags = [w.lstrip("#") for w in text.split() if w.startswith("#")]
    ts = item.get("taken_at") or 0
    return Post(
        post_id=str(item.get("code") or item.get("pk") or item.get("id", "")),
        platform="instagram",
        author=user.get("username") or str(user.get("pk", "")),
        followers=user.get("follower_count") or 0,
        text=text,
        hashtags=hashtags,
        created_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else _now(),
        likes=item.get("like_count") or 0,
        views=item.get("play_count") or item.get("view_count") or 0,
        comments=item.get("comment_count") or 0,
        shares=0,
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
