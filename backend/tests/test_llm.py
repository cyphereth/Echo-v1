import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest


def test_complete_raises_without_key(monkeypatch):
    import radar.core.llm as L
    monkeypatch.setattr(L, "LLM_API_KEY", "")
    with pytest.raises(L.LLMNotConfigured):
        L.complete("sys", "user")


def test_complete_parses_text_block(monkeypatch):
    import radar.core.llm as L
    monkeypatch.setattr(L, "LLM_API_KEY", "sk-test")

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"content": [{"type": "text", "text": "  hello  "}]}

    captured = {}
    def _post(url, headers, json, timeout):
        captured["url"] = url; captured["json"] = json; captured["headers"] = headers
        return _Resp()
    monkeypatch.setattr(L.httpx, "post", _post)

    out = L.complete("SYS", "USER", max_tokens=99)
    assert out == "hello"
    assert captured["json"]["system"] == "SYS"
    assert captured["json"]["messages"] == [{"role": "user", "content": "USER"}]
    assert captured["json"]["max_tokens"] == 99
    assert captured["headers"]["x-api-key"] == "sk-test"
