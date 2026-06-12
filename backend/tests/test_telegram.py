import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from radar.providers.telegram import _parse_tg_message, _sum_reactions
from radar.providers.base import Post


class _Reaction:
    def __init__(self, count): self.count = count

class _Reactions:
    def __init__(self, counts): self.results = [_Reaction(c) for c in counts]

class _Msg:
    def __init__(self, id=1, message="Заказал суши в Тануки #тануки", views=500,
                 forwards=10, reactions=None, replies_count=3):
        self.id = id
        self.message = message
        self.views = views
        self.forwards = forwards
        self.date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.reactions = _Reactions(reactions) if reactions is not None else None
        class _R: replies = replies_count
        self.replies = _R()


def test_sum_reactions_sums_all_counts():
    assert _sum_reactions(_Msg(reactions=[3, 5, 2])) == 10

def test_sum_reactions_none_is_zero():
    assert _sum_reactions(_Msg(reactions=None)) == 0

def test_parse_tg_message_maps_core_fields():
    p = _parse_tg_message(_Msg(), "@yakitoriya", followers=12000)
    assert isinstance(p, Post)
    assert p.post_id == "1"
    assert p.platform == "telegram"
    assert p.author == "@yakitoriya"
    assert p.followers == 12000
    assert p.text.startswith("Заказал суши")
    assert p.views == 500 and p.shares == 10 and p.comments == 3
    assert p.created_at == datetime(2026, 6, 1, tzinfo=timezone.utc)

def test_parse_tg_message_extracts_hashtags():
    p = _parse_tg_message(_Msg(), "@x", followers=0)
    assert "#тануки" in p.hashtags

def test_parse_tg_message_survives_empty_text():
    m = _Msg(message=None, views=0, forwards=0)
    p = _parse_tg_message(m, "@x", followers=0)
    assert p.text == "" and p.hashtags == [] and p.views == 0


def test_search_keyword_calls_global(monkeypatch):
    from radar.providers.telegram import TelegramProvider
    calls = {}
    class FakeClient:
        def get_messages(self, entity, **kw):
            calls["entity"] = entity; calls["kw"] = kw
            return []
    p = TelegramProvider(client=FakeClient())
    page = p.search("тануки", "keyword", None, "telegram")
    assert calls["entity"] is None             # global search uses None
    assert calls["kw"].get("search") == "тануки"
    assert page.posts == [] and page.next_cursor is None


def test_search_channel_resolves_entity():
    from radar.providers.telegram import TelegramProvider
    class FakeEntity: participants_count = 100
    seen = {}
    class FakeClient:
        def get_entity(self, h): seen["handle"] = h; return FakeEntity()
        def get_messages(self, entity, **kw): seen["entity"] = entity; return []
    p = TelegramProvider(client=FakeClient())
    p.search("@yakitoriya", "channel", None, "telegram")
    assert seen["handle"] == "@yakitoriya"
    assert isinstance(seen["entity"], FakeEntity)


def test_global_search_floodwait_raises_runtime():
    import pytest
    from telethon.errors import FloodWaitError
    from radar.providers.telegram import TelegramProvider
    class FakeClient:
        def get_messages(self, entity, **kw):
            raise FloodWaitError(request=None)
    p = TelegramProvider(client=FakeClient())
    with pytest.raises(RuntimeError, match="flood wait"):
        p.search("тануки", "keyword", None, "telegram")


def test_channel_read_private_returns_empty():
    from telethon.errors import ChannelPrivateError
    from radar.providers.telegram import TelegramProvider
    class FakeClient:
        def get_entity(self, h):
            raise ChannelPrivateError(request=None)
        def get_messages(self, entity, **kw): return []
    p = TelegramProvider(client=FakeClient())
    page = p.search("@private_channel", "channel", None, "telegram")
    assert page.posts == [] and page.next_cursor is None


def test_brand_tg_channels_list():
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base, Brand
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = _S(eng)
    b = Brand(name="Tanuki", tg_channels=json.dumps(["@yakitoriya", "@sushiwok"]))
    s.add(b); s.commit()
    assert b.tg_channels_list() == ["@yakitoriya", "@sushiwok"]

def test_brand_tg_channels_default_empty():
    from radar.models import Brand
    b = Brand(name="x")
    assert b.tg_channels_list() == []


def test_get_tg_provider_none_without_credentials(monkeypatch):
    from radar import api
    monkeypatch.setattr(api, "TELEGRAM_API_ID", "")
    api._tg_provider_singleton = None
    assert api._get_tg_provider() is None

def test_post_url_telegram():
    from radar import api
    from radar.models import Mention
    m = Mention(platform="telegram", author="@yakitoriya", post_id="123",
                brand_id=1, created_at=None)
    assert api._post_url(m) == "https://t.me/yakitoriya/123"

def test_rebuild_probes_adds_tg_channel_probes(monkeypatch):
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar import api
    from radar.models import Base, Brand, Probe
    monkeypatch.setattr(api, "TELEGRAM_API_ID", "123")  # enable TG probes
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = _S(eng)
    b = Brand(name="Tanuki", keywords=json.dumps(["Тануки"]),
              competitors="[]", niche_keywords="[]", category_terms="[]",
              audience_terms="[]", tg_channels=json.dumps(["@yakitoriya"]))
    s.add(b); s.flush()
    api._rebuild_probes(s, b)
    tg = s.query(Probe).filter_by(brand_id=b.id, platform="telegram").all()
    # Telegram gets ONLY channel probes — no keyword probes (no global search).
    assert any(p.kind == "channel" and p.query == "@yakitoriya" for p in tg)
    assert all(p.kind == "channel" for p in tg)


def test_channel_probe_bypasses_keyword_filter():
    """Posts from a monitored channel are kept even without a brand keyword —
    the channel itself is the relevance signal."""
    import json
    from datetime import datetime, timezone
    from radar.collector import _matches
    from radar.providers.base import Post
    from radar.models import Brand
    b = Brand(); b.exclusions = json.dumps([]); b.market = "ru"
    class ChannelProbe: kind="channel"; source="niche"; label="@durov"; query="@durov"
    class KeywordProbe: kind="keyword"; source="niche"; label="суши"; query="суши"
    post = Post(post_id="1", platform="telegram", author="@durov", followers=9,
                text="Совершенно нерелевантный текст без ключей", hashtags=[],
                created_at=datetime.now(timezone.utc), likes=0, views=10**6,
                comments=0, shares=0)
    assert _matches(post, b, ChannelProbe()) is True      # channel → kept
    assert _matches(post, b, KeywordProbe()) is False     # keyword → needs "суши"
