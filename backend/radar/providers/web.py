from __future__ import annotations
import logging
import os
import httpx

log = logging.getLogger(__name__)

WEB_SEARCH_API_KEY = os.getenv("WEB_SEARCH_API_KEY", "")
WEB_SEARCH_URL = os.getenv("WEB_SEARCH_URL", "https://api.tavily.com/search")
WEB_MAX_RESULTS = int(os.getenv("WEB_MAX_RESULTS", "10"))


class WebSearchProvider:
    """Topic web search via Tavily. Returns [{title, url, content, published}].

    No-op (returns []) when WEB_SEARCH_API_KEY is unset or on any network error,
    so the source degrades cleanly and never crashes a scheduler pass.
    """

    def search(self, query: str, max_results: int | None = None) -> list[dict]:
        if not WEB_SEARCH_API_KEY:
            return []
        try:
            resp = httpx.post(
                WEB_SEARCH_URL,
                json={"api_key": WEB_SEARCH_API_KEY, "query": query,
                      "search_depth": "basic", "topic": "news",
                      "max_results": max_results or WEB_MAX_RESULTS},
                timeout=60,
            )
            resp.raise_for_status()
            rows = resp.json().get("results", [])
        except Exception as e:
            log.warning("web search failed: %s", type(e).__name__)
            return []
        return [{"title": r.get("title", ""), "url": r.get("url", ""),
                 "content": r.get("content", ""), "published": r.get("published_date")}
                for r in rows if r.get("url")]
