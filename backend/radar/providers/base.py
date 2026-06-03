from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Post:
    post_id:    str
    platform:   str
    author:     str
    followers:  int
    text:       str
    hashtags:   list[str]
    created_at: datetime
    likes:      int
    views:      int
    comments:   int
    shares:     int
    sound_id:   Optional[str] = None

@dataclass
class SearchPage:
    posts:       list[Post]
    next_cursor: Optional[str]

@dataclass
class Comment:
    comment_id: str
    author:     str
    followers:  int
    text:       str
    likes:      int
    created_at: datetime

class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, kind: str, cursor: Optional[str], platform: str = "tiktok") -> SearchPage: ...

    def fetch_comments(self, post_id: str, cursor: Optional[str], platform: str = "tiktok") -> list["Comment"]:
        """Fetch comments for a post. Providers that don't support it return []."""
        return []
