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

class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, kind: str, cursor: Optional[str]) -> SearchPage: ...
