import os
from datetime import datetime, timezone
from typing import Optional
import httpx
from .base import Post, SearchPage, SearchProvider

TIKHUB_TOKEN = os.getenv("TIKHUB_TOKEN", "")
BASE_URL = "https://api.tikhub.io"

class TikHubProvider(SearchProvider):
    def __init__(self, token: str = TIKHUB_TOKEN):
        self._headers = {"Authorization": f"Bearer {token}"}

    def search(self, query: str, kind: str, cursor: Optional[str]) -> SearchPage:
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
                posts.append(_parse_post(video))
            except Exception:
                continue

        has_more   = len(raw_list) >= 20
        next_cursor = str(offset + len(raw_list)) if has_more else None
        return SearchPage(posts=posts, next_cursor=next_cursor)


def _parse_post(item: dict) -> Post:
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
