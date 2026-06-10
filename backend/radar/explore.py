"""City Explorer pipeline: build city queries, aggregate posts, LLM-summarize.

Standalone audience research — no brand coupling. SocialCrawl has no native geo
search, so "by city" means keyword/hashtag search for city terms.
"""
import json, logging, os
from typing import Optional

log = logging.getLogger(__name__)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.anthropic.com/v1/messages")


def normalize_city(city: str) -> tuple[str, str]:
    """Return (key, hashtag). key = trimmed lowercase; hashtag = key without
    spaces/hyphens (for IG hashtag search and cache key)."""
    key = (city or "").strip().lower()
    hashtag = key.replace(" ", "").replace("-", "")
    return key, hashtag


def build_city_queries(city: str) -> list[tuple[str, str, str]]:
    """(platform, kind, query) tuples — small set to bound credit cost (~4)."""
    _, hashtag = normalize_city(city)
    c = city.strip()
    return [
        ("tiktok", "keyword", c),
        ("tiktok", "keyword", f"куда сходить {c}"),
        ("tiktok", "keyword", f"что попробовать {c}"),
        ("instagram", "hashtag", hashtag),
    ]
