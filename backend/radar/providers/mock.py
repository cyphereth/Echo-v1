from datetime import datetime, timedelta, timezone
from typing import Optional
from .base import Comment, Post, SearchPage, SearchProvider

PAGE_SIZE = 5
# Rotating sentiment cues so mock collect produces a realistic spread.
_FLAVORS = [
    "это просто кошмар, курьер опоздал и всё холодное",
    "честно, вкусно и быстро, рекомендую всем",
    "ну такое, ничего особенного, нейтрально",
    "обман и развод, верните деньги, ужасно",
    "обожаю, лучшее что пробовал, огонь 🔥",
]

class MockProvider(SearchProvider):
    def __init__(self, total_pages: int = 3):
        self.total_pages = total_pages

    def search(self, query: str, kind: str, cursor: Optional[str]) -> SearchPage:
        page = int(cursor) if cursor is not None else 0
        if page >= self.total_pages:
            return SearchPage(posts=[], next_cursor=None)
        start = page * PAGE_SIZE
        now = datetime.now(timezone.utc)
        posts = [Post(
            post_id=f"{query}_post_{start+i}",
            platform="tiktok",
            author=f"user_{start+i}",
            followers=(start + i + 1) * 1000,
            text=f"Упоминание {query}: {_FLAVORS[(start + i) % len(_FLAVORS)]}",
            hashtags=[query],
            created_at=now - timedelta(hours=start + i + 1),
            likes=(start + i + 1) * 120,
            views=(start + i + 1) * 5000,
            comments=(start + i + 1) * 30,
            shares=(start + i + 1) * 8,
        ) for i in range(PAGE_SIZE)]
        next_cursor = str(page + 1) if page + 1 < self.total_pages else None
        return SearchPage(posts=posts, next_cursor=next_cursor)

    def fetch_comments(self, post_id: str, cursor: Optional[str]) -> list[Comment]:
        now = datetime.now(timezone.utc)
        return [Comment(
            comment_id=f"{post_id}_c{i}",
            author=f"commenter_{i}",
            followers=(i + 1) * 500,
            text=f"Комментарий {i}: {_FLAVORS[i % len(_FLAVORS)]}",
            likes=(i + 1) * 15,
            created_at=now - timedelta(minutes=(i + 1) * 7),
        ) for i in range(6)]
