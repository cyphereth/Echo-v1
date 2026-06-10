import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from radar.explore import normalize_city, build_city_queries


def test_normalize_city_lowercase_trim():
    assert normalize_city("  Москва ") == ("москва", "москва")


def test_normalize_city_hashtag_strips_space_and_hyphen():
    assert normalize_city("Санкт-Петербург") == ("санкт-петербург", "санктпетербург")


def test_build_city_queries_shape():
    qs = build_city_queries("Москва")
    assert ("tiktok", "keyword", "Москва") in qs
    assert ("tiktok", "keyword", "куда сходить Москва") in qs
    assert ("tiktok", "keyword", "что попробовать Москва") in qs
    assert ("instagram", "hashtag", "москва") in qs
    assert len(qs) == 4


from datetime import datetime, timezone
from radar.providers.base import Post


def _post(pid, text, likes=0, views=0, tags=None):
    return Post(post_id=pid, platform="tiktok", author="a", followers=0, text=text,
                hashtags=tags or [], created_at=datetime.now(timezone.utc),
                likes=likes, views=views, comments=0, shares=0)


def test_aggregate_posts_dedup_rank_cap_truncate():
    from radar.explore import aggregate_posts
    posts = [_post("1", "x"*400, likes=5), _post("1", "dup", likes=99),
             _post("2", "hi", likes=100, views=500, tags=["#a"])]
    out = aggregate_posts(posts)
    assert len(out) == 2                      # dedup by post_id (keeps first "1")
    assert out[0]["likes"] == 100             # highest engagement first ("2")
    assert all(len(o["text"]) <= 280 for o in out)
    assert out[0]["hashtags"] == ["#a"]


def test_run_city_search_skips_failing_platform():
    from radar.explore import run_city_search
    from radar.providers.base import SearchPage
    class FakeProvider:
        def search(self, query, kind, cursor, platform):
            if platform == "instagram":
                raise RuntimeError("ig down")
            return SearchPage(posts=[_post(query, "post "+query, likes=10)], next_cursor=None)
    agg, n, platforms = run_city_search(FakeProvider(), "Москва")
    assert n > 0
    assert "tiktok" in platforms and "instagram" not in platforms


def _fake_llm_response(text):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"content": [{"type": "text", "text": text}]}
    return R()


def test_summarize_city_parses_json(monkeypatch):
    import radar.explore as ex
    monkeypatch.setattr(ex, "LLM_API_KEY", "k")
    payload = '{"overview":"ok","themes":[{"title":"Еда","description":"кафе"}],' \
              '"wants":["куда сходить"],"trends":["t"],' \
              '"sentiment":{"overall":"positive","note":"n"},"top_hashtags":["#м"]}'
    monkeypatch.setattr(ex.httpx, "post", lambda *a, **k: _fake_llm_response(payload))
    out = ex.summarize_city("Москва", [{"text": "x", "likes": 1, "views": 1, "hashtags": []}])
    assert out["overview"] == "ok"
    assert out["themes"][0]["title"] == "Еда"
    assert out["sentiment"]["overall"] == "positive"


def test_summarize_city_no_key_returns_empty(monkeypatch):
    import radar.explore as ex
    monkeypatch.setattr(ex, "LLM_API_KEY", "")
    assert ex.summarize_city("Москва", [{"text": "x"}]) == {}
