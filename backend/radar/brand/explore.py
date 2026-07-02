"""City Explorer pipeline: build city queries, aggregate posts, LLM-summarize.

Standalone audience research — no brand coupling. SocialCrawl has no native geo
search, so "by city" means keyword/hashtag search for city terms.
"""
import httpx
import json, logging, os

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


_SUMMARY_SCHEMA = ('{"overview":"","themes":[{"title":"","description":""}],'
                   '"wants":[],"trends":[],"sentiment":{"overall":"neutral","note":""},'
                   '"top_hashtags":[]}')


def summarize_city(city: str, agg_posts: list[dict]) -> dict:
    """Claude summary of city interests. Returns the schema dict, or {} on no-key/error."""
    if not LLM_API_KEY:
        return {}
    sample = "\n".join(f"- {p['text']} (likes {p.get('likes',0)})" for p in agg_posts[:40])
    system = (
        "Ты аналитик соцсетей. По постам, упоминающим город, опиши интересы местной "
        "аудитории. Отвечай ТОЛЬКО валидным JSON без markdown."
    )
    user = (
        f"Город: {city}. Посты:\n{sample}\n\n"
        f"Сделай сводку интересов: о чём говорят, что хотят/ищут, тренды, общее настроение. "
        f"Строго JSON по форме: {_SUMMARY_SCHEMA}"
    )

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 900,
                  "system": system, "messages": [{"role": "user", "content": user}]},
            timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = json.loads(text)
        return {
            "overview":     data.get("overview", "") or "",
            "themes":       data.get("themes", []) or [],
            "wants":        data.get("wants", []) or [],
            "trends":       data.get("trends", []) or [],
            "sentiment":    data.get("sentiment", {}) or {},
            "top_hashtags": data.get("top_hashtags", []) or [],
        }

    try:
        return _call()
    except (json.JSONDecodeError, KeyError):
        try:
            return _call()
        except Exception as e:
            log.warning("summarize_city retry failed: %s", e); return {}
    except Exception as e:
        log.warning("summarize_city failed: %s", e); return {}
