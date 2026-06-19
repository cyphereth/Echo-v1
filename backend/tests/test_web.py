import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_web_search_noop_without_key(monkeypatch):
    import radar.core.providers.web as W
    monkeypatch.setattr(W, "WEB_SEARCH_API_KEY", "")
    assert W.WebSearchProvider().search("любая тема") == []


def test_web_search_parses_results(monkeypatch):
    import radar.core.providers.web as W
    monkeypatch.setattr(W, "WEB_SEARCH_API_KEY", "tvly-test")

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                {"title": "T1", "url": "https://a.example/x", "content": "body1",
                 "published_date": "2026-06-15"},
                {"title": "T2", "url": "https://b.example/y", "content": "body2"},
            ]}

    captured = {}
    def _post(url, json, timeout):
        captured["url"] = url; captured["json"] = json
        return _Resp()
    monkeypatch.setattr(W.httpx, "post", _post)

    out = W.WebSearchProvider().search("пожар", max_results=7)
    assert len(out) == 2
    assert out[0]["url"] == "https://a.example/x"
    assert out[0]["content"] == "body1"
    assert out[0]["published"] == "2026-06-15"
    assert out[1]["published"] is None
    assert captured["json"]["query"] == "пожар"
    assert captured["json"]["max_results"] == 7
    assert captured["json"]["api_key"] == "tvly-test"


def test_web_search_empty_on_http_error(monkeypatch):
    import radar.core.providers.web as W
    monkeypatch.setattr(W, "WEB_SEARCH_API_KEY", "tvly-test")
    def _boom(*a, **k): raise RuntimeError("network down")
    monkeypatch.setattr(W.httpx, "post", _boom)
    assert W.WebSearchProvider().search("x") == []


from datetime import datetime, timezone


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


class _FakeWeb:
    def __init__(self, rows): self.rows = rows
    def search(self, query, max_results=None): return self.rows


def test_collect_web_stores_relevant_dedup(monkeypatch):
    import radar.collector as C
    from radar.models import Brand, Mention
    from radar.scope import scope_for_brand
    s = _mem()
    b = Brand(id=1, name="Бренд", keywords='["пожар"]', niche_keywords='["пожар"]')
    s.add(b); s.commit()
    prov = _FakeWeb([
        {"title": "Пожар на заводе", "url": "https://news.ru/a", "content": "сильный пожар", "published": None},  # no date → treated as fresh
        {"title": "Погода", "url": "https://news.ru/b", "content": "солнечно и тепло", "published": None},  # irrelevant → filtered
    ])
    n = C.collect_web(s, scope_for_brand(b), prov)
    assert n == 1
    rows = s.query(Mention).filter_by(platform="web").all()
    assert len(rows) == 1
    assert rows[0].author == "news.ru"     # domain
    assert rows[0].source == "niche"
    # second run = dedup (same URL) → no new rows
    C.collect_web(s, scope_for_brand(b), prov)
    assert s.query(Mention).filter_by(platform="web").count() == 1


def test_run_web_pass_collects_for_autocollect_brands(monkeypatch):
    import radar.core.scheduler as SCH
    from radar.models import Brand
    s = _mem()
    s.add(Brand(id=1, name="a", auto_collect=True))
    s.add(Brand(id=2, name="b", auto_collect=False))   # excluded
    s.commit()
    calls = []
    monkeypatch.setattr("radar.collector.collect_web",
                        lambda sess, brand, prov: calls.append(brand.id) or 0)
    SCH._run_web_pass(s, web_provider=object())
    assert calls == [1]


def test_run_topic_web_pass_collects_for_autocollect_topics(monkeypatch):
    import radar.core.scheduler as SCH
    from radar.models import Topic
    s = _mem()
    s.add(Topic(id=1, name="Экономика", kind="default", auto_collect=True))
    s.add(Topic(id=2, name="Приват", kind="search", auto_collect=False))  # excluded
    s.commit()
    scopes = []
    monkeypatch.setattr("radar.collector.collect_web",
                        lambda sess, scope, prov: scopes.append((scope.kind, scope.id)) or 0)
    SCH._run_topic_web_pass(s, web_provider=object())
    assert scopes == [("topic", 1)]


def test_run_topic_web_pass_clusters_when_collected(monkeypatch):
    import radar.core.scheduler as SCH
    from radar.models import Topic
    s = _mem()
    s.add(Topic(id=1, name="Экономика", kind="default", auto_collect=True))
    s.commit()
    monkeypatch.setattr("radar.collector.collect_web", lambda sess, scope, prov: 3)
    clustered = []
    monkeypatch.setattr("radar.stories.update_stories",
                        lambda sess, scope: clustered.append(scope.id) or {})
    SCH._run_topic_web_pass(s, web_provider=object())
    assert clustered == [1]
