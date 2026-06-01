from datetime import datetime, timezone
from typing import Optional
from .base import Post, SearchPage, SearchProvider

PAGE_SIZE = 5

class MockProvider(SearchProvider):
    def __init__(self, total_pages: int = 3):
        self.total_pages = total_pages

    def search(self, query: str, kind: str, cursor: Optional[str]) -> SearchPage:
        page = int(cursor) if cursor is not None else 0
        if page >= self.total_pages:
            return SearchPage(posts=[], next_cursor=None)
        start = page * PAGE_SIZE
        posts = [Post(
            post_id=f"{query}_post_{start+i}",
            platform="tiktok",
            author=f"user_{start+i}",
            followers=(start + i) * 1000,
            text=f"Упоминание {query} #{start+i}",
            hashtags=[query],
            created_at=datetime(2024, 1, 1, 12, start + i, tzinfo=timezone.utc),
            likes=(start + i) * 10,
            views=(start + i) * 500,
            comments=(start + i) * 2,
            shares=start + i,
        ) for i in range(PAGE_SIZE)]
        next_cursor = str(page + 1) if page + 1 < self.total_pages else None
        return SearchPage(posts=posts, next_cursor=next_cursor)
