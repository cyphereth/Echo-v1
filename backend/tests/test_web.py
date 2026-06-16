import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_web_search_noop_without_key(monkeypatch):
    import radar.providers.web as W
    monkeypatch.setattr(W, "WEB_SEARCH_API_KEY", "")
    assert W.WebSearchProvider().search("любая тема") == []


def test_web_search_parses_results(monkeypatch):
    import radar.providers.web as W
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
    import radar.providers.web as W
    monkeypatch.setattr(W, "WEB_SEARCH_API_KEY", "tvly-test")
    def _boom(*a, **k): raise RuntimeError("network down")
    monkeypatch.setattr(W.httpx, "post", _boom)
    assert W.WebSearchProvider().search("x") == []
