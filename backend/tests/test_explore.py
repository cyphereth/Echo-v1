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
from radar.core.providers.base import Post


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
    from radar.core.providers.base import SearchPage
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


def test_aggregate_posts_caps_at_limit():
    from radar.explore import aggregate_posts
    posts = [_post(str(i), f"post {i}", likes=i) for i in range(50)]
    out = aggregate_posts(posts)
    assert len(out) == 40                      # capped at default limit
    assert out[0]["likes"] == 49               # highest engagement first


def test_summarize_city_retries_once_then_succeeds(monkeypatch):
    import radar.explore as ex
    monkeypatch.setattr(ex, "LLM_API_KEY", "k")
    good = '{"overview":"second try"}'
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        return _fake_llm_response("not json!!" if calls["n"] == 1 else good)

    monkeypatch.setattr(ex.httpx, "post", flaky)
    out = ex.summarize_city("Москва", [{"text": "x"}])
    assert calls["n"] == 2                      # retried exactly once
    assert out["overview"] == "second try"


def test_summarize_city_returns_empty_when_retry_also_fails(monkeypatch):
    import radar.explore as ex
    monkeypatch.setattr(ex, "LLM_API_KEY", "k")
    monkeypatch.setattr(ex.httpx, "post", lambda *a, **k: _fake_llm_response("still not json"))
    assert ex.summarize_city("Москва", [{"text": "x"}]) == {}


def _mem_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_city_report_roundtrip():
    from radar.models import CityReport
    s = _mem_session()
    s.add(CityReport(city="москва", display_city="Москва", summary='{"overview":"x"}',
                     post_count=12, platforms="tiktok,instagram"))
    s.commit()
    r = s.query(CityReport).filter_by(city="москва").one()
    assert r.display_city == "Москва" and r.post_count == 12
    assert r.created_at is not None


class _BG:
    """Minimal stand-in for FastAPI BackgroundTasks — records scheduled tasks."""
    def __init__(self): self.tasks = []
    def add_task(self, fn, *a, **k): self.tasks.append((fn, a, k))


def test_explore_city_uses_cache(monkeypatch):
    from datetime import datetime, timezone
    import radar.brand.api as api
    from radar.models import CityReport
    s = _mem_session()
    s.add(CityReport(city="москва", display_city="Москва",
                     summary='{"overview":"cached"}', post_count=5, platforms="tiktok",
                     created_at=datetime.now(timezone.utc)))
    s.commit()

    class U: id = 1; email = "u@x.com"
    def boom(*a, **k): raise AssertionError("provider must not be called on fresh cache")
    monkeypatch.setattr(api, "_get_provider", boom)
    bg = _BG()
    out = api.explore_city(api.ExploreCityBody(city="Москва"), bg, user=U(), session=s)
    assert out["cached"] is True
    assert out["summary"]["overview"] == "cached"
    assert bg.tasks == []                       # cache hit → no background work


def test_explore_city_missing_schedules_background():
    import radar.brand.api as api
    s = _mem_session()
    class U: id = 1; email = "u@x.com"
    bg = _BG()
    out = api.explore_city(api.ExploreCityBody(city="Казань"), bg, user=U(), session=s)
    assert out["status"] == "collecting"
    assert len(bg.tasks) == 1
    fn, args, _ = bg.tasks[0]
    assert fn is api._run_city_explore and args == ("Казань",)


def test_explore_city_refresh_schedules_background_even_if_cached():
    from datetime import datetime, timezone
    import radar.brand.api as api
    from radar.models import CityReport
    s = _mem_session()
    s.add(CityReport(city="москва", display_city="Москва",
                     summary='{"overview":"old"}', post_count=1, platforms="tiktok",
                     created_at=datetime.now(timezone.utc)))
    s.commit()
    class U: id = 1; email = "u@x.com"
    bg = _BG()
    out = api.explore_city(api.ExploreCityBody(city="Москва", refresh=True), bg, user=U(), session=s)
    assert out["status"] == "collecting"        # refresh bypasses fresh cache
    assert len(bg.tasks) == 1


def test_run_city_explore_stores_report(monkeypatch):
    import json
    import radar.brand.api as api
    from radar.models import CityReport
    s = _mem_session()
    monkeypatch.setattr(api, "get_session", lambda: s)
    monkeypatch.setattr(api, "_get_provider", lambda: object())
    monkeypatch.setattr("radar.explore.run_city_search",
                        lambda provider, city: ([{"text": "p"}], 7, ["tiktok", "instagram"]))
    monkeypatch.setattr("radar.explore.summarize_city",
                        lambda city, posts: {"overview": "fresh"})
    api._run_city_explore("Казань")
    row = s.query(CityReport).filter_by(city="казань").one()
    assert row.post_count == 7
    assert json.loads(row.summary)["overview"] == "fresh"
