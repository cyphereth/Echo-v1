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


def aggregate_posts(posts: list, limit: int = 40) -> list[dict]:
    """Dedupe by post_id, rank by engagement, cap, return compact dicts."""
    seen, uniq = set(), []
    for p in posts:
        if p.post_id in seen:
            continue
        seen.add(p.post_id)
        uniq.append(p)
    uniq.sort(key=lambda p: (p.likes or 0) + (p.views or 0) // 100, reverse=True)
    return [{
        "text": (p.text or "")[:280],
        "likes": p.likes or 0,
        "views": p.views or 0,
        "hashtags": p.hashtags or [],
    } for p in uniq[:limit]]


def run_city_search(provider, city: str) -> tuple[list[dict], int, list[str]]:
    """Run every city query; skip platforms that error. Returns
    (aggregated_posts, raw_post_count, platforms_with_results)."""
    all_posts, platforms = [], set()
    for platform, kind, query in build_city_queries(city):
        try:
            page = provider.search(query, kind, None, platform)
        except Exception as e:
            log.warning("city search failed (%s/%s %r): %s", platform, kind, query, e)
            continue
        if page.posts:
            platforms.add(platform)
            all_posts.extend(page.posts)
    return aggregate_posts(all_posts), len(all_posts), sorted(platforms)
