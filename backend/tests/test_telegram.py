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


def test_parse_tg_comment_maps_fields():
    from datetime import datetime, timezone
    from radar.providers.telegram import _parse_tg_comment
    from radar.providers.base import Comment as C
    class S: username="vasya"; first_name="Вася"
    class M:
        id=55; message="а где заказать роллы?"; date=datetime(2026,6,1,tzinfo=timezone.utc)
        sender=S(); sender_id=1; reactions=None
    c=_parse_tg_comment(M())
    assert isinstance(c,C) and c.comment_id=="55" and c.author=="@vasya"
    assert c.text.startswith("а где")


def test_tg_fetch_comments_no_channel_returns_empty():
    from radar.providers.telegram import TelegramProvider
    p=TelegramProvider(client=object())
    assert p.fetch_comments("123", None, "telegram", channel=None) == []


def test_tg_fetch_comments_reads_replies():
    from datetime import datetime, timezone
    from radar.providers.telegram import TelegramProvider
    class S: username=None; first_name="Аня"
    class M:
        id=7; message="закажу в тануки"; date=datetime(2026,6,2,tzinfo=timezone.utc)
        sender=S(); sender_id=9; reactions=None
    seen={}
    class FakeClient:
        def get_entity(self,h): seen["h"]=h; return object()
        def get_messages(self,e,**kw): seen["kw"]=kw; return [M()]
    p=TelegramProvider(client=FakeClient())
    out=p.fetch_comments("100", None, "telegram", channel="@kudaeda")
    assert seen["h"]=="@kudaeda" and seen["kw"].get("reply_to")==100
    assert len(out)==1 and out[0].author=="Аня"


# ── Chat/group monitoring (search messages inside discovered group chats) ──

def test_search_chat_returns_posts_with_sender_and_composite_id():
    from datetime import datetime, timezone
    from radar.providers.telegram import TelegramProvider
    class Sender: username = "ivan"
    class Msg:
        id = 42; message = "посоветуйте где поесть в москве?"
        views = 0; forwards = 0; reactions = None; replies = None
        date = datetime(2026, 6, 13, tzinfo=timezone.utc); sender = Sender()
    class Ent: participants_count = 5000
    class FakeClient:
        def get_entity(self, h): return Ent()
        def get_messages(self, entity, **kw): return [Msg()]
    p = TelegramProvider(client=FakeClient())
    posts = p.search_chat("@foodmsk", "поесть", limit=10)
    assert len(posts) == 1
    assert posts[0].post_id == "foodmsk/42"   # globally-unique composite id
    assert posts[0].author == "@ivan"          # the message sender, not the chat
    assert posts[0].platform == "telegram"


def test_search_chat_unavailable_returns_empty():
    from telethon.errors import ChannelPrivateError
    from radar.providers.telegram import TelegramProvider
    class FakeClient:
        def get_entity(self, h): raise ChannelPrivateError(request=None)
        def get_messages(self, *a, **k): return []
    p = TelegramProvider(client=FakeClient())
    assert p.search_chat("@x", "поесть") == []


def test_post_url_telegram_chat_uses_composite_path():
    from types import SimpleNamespace
    from radar.api import _post_url
    m = SimpleNamespace(platform="telegram", author="@ivan", post_id="foodmsk/42")
    assert _post_url(m) == "https://t.me/foodmsk/42"


def test_post_url_telegram_channel_unchanged():
    from types import SimpleNamespace
    from radar.api import _post_url
    m = SimpleNamespace(platform="telegram", author="@sysoevfm", post_id="123")
    assert _post_url(m) == "https://t.me/sysoevfm/123"


def _mem_session_tg():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def test_collect_chats_stores_topical_and_intent_messages_as_niche():
    import json
    from datetime import datetime, timezone
    from radar.models import Brand, Probe, Mention
    from radar.collector import collect_chats
    from radar.providers.base import Post

    s = _mem_session_tg()
    b = Brand(name="Тануки", sphere="рестораны доставка еды",
              niche_keywords=json.dumps(["ресторан", "суши"]),
              category_terms="[]", audience_terms="[]", geo="Москва")
    s.add(b); s.flush()
    s.add(Probe(brand_id=b.id, platform="telegram", kind="chat",
                query="@foodmsk", source="niche", label="Еда МСК",
                next_run_at=datetime.now(timezone.utc), interval_sec=3600))
    s.commit()

    def mk(pid, text, author="@u"):
        return Post(post_id=pid, platform="telegram", author=author, followers=0,
                    text=text, hashtags=[], created_at=datetime.now(timezone.utc),
                    likes=0, views=0, comments=0, shares=0)

    class FakeProvider:
        def search_chat(self, handle, term, limit=20):
            # one intent question, one topical, one pure noise
            return [mk("foodmsk/1", "посоветуйте где поесть в москве?"),
                    mk("foodmsk/2", "лучший ресторан суши на районе это огонь"),
                    mk("foodmsk/3", "ага")]
        def search(self, *a, **k): return None

    n = collect_chats(s, b, FakeProvider())
    stored = s.query(Mention).filter_by(brand_id=b.id, is_spam=False).all()
    texts = {m.post_id for m in stored}
    assert "foodmsk/1" in texts          # intent question kept
    assert "foodmsk/2" in texts          # topical (ресторан/суши) kept
    assert "foodmsk/3" not in texts      # short noise dropped
    assert all(m.source == "niche" for m in stored)
    assert n >= 2


# ── Graph-based discovery (recommendations + linked discussion groups) ──

def test_channel_recommendations_returns_usernames():
    from radar.providers.telegram import TelegramProvider
    class Ch:
        def __init__(self, u): self.username = u
    class Rec:
        chats = [Ch("restaurantmoscow"), Ch("foodandwine"), Ch(None)]  # None dropped
    class FakeClient:
        def get_entity(self, h): return object()
        def __call__(self, req): return Rec()
    p = TelegramProvider(client=FakeClient())
    out = p.channel_recommendations("@kudaeda", limit=10)
    assert out == ["@restaurantmoscow", "@foodandwine"]


def test_linked_chat_returns_username_megagroup():
    from radar.providers.telegram import TelegramProvider
    class Linked:
        id = 555; username = "restosnobonline"; megagroup = True
        title = "Restosnob Chat"; participants_count = 4000
    class FullChat:
        linked_chat_id = 555
    class Full:
        full_chat = FullChat(); chats = [Linked()]
    class FakeClient:
        def get_entity(self, h): return object()
        def __call__(self, req): return Full()
    p = TelegramProvider(client=FakeClient())
    out = p.linked_chat("@restosnob")
    assert out["handle"] == "@restosnobonline"
    assert out["participants"] == 4000


def test_linked_chat_none_when_no_discussion_group():
    from radar.providers.telegram import TelegramProvider
    class FullChat: linked_chat_id = None
    class Full:
        full_chat = FullChat(); chats = []
    class FakeClient:
        def get_entity(self, h): return object()
        def __call__(self, req): return Full()
    p = TelegramProvider(client=FakeClient())
    assert p.linked_chat("@sysoevfm") is None


def test_ensure_chats_discovered_grows_graph_from_seed_channels():
    import json
    from radar.models import Brand, Probe
    from radar.collector import ensure_chats_discovered

    s = _mem_session_tg()
    b = Brand(name="Тануки", sphere="рестораны",
              tg_channels=json.dumps(["@kudaeda"]),
              niche_keywords="[]", category_terms="[]", audience_terms="[]")
    s.add(b); s.flush(); s.commit()

    class FakeProvider:
        def channel_recommendations(self, handle, limit=10):
            return ["@restaurantmoscow"] if handle == "@kudaeda" else []
        def linked_chat(self, handle):
            table = {"@kudaeda": {"handle": "@kudaedatalks", "title": "Talks", "participants": 9000},
                     "@restaurantmoscow": {"handle": "@mosrestchat", "title": "Chat", "participants": 3000}}
            return table.get(handle)

    n = ensure_chats_discovered(s, b, FakeProvider())
    chats = {p.query for p in s.query(Probe).filter_by(kind="chat").all()}
    assert chats == {"@kudaedatalks", "@mosrestchat"}   # seed's + recommendation's linked groups
    assert n == 2


# ── Sphere-agnostic: works for any vertical the client picks, not just food ──

def test_discover_channels_filters_username_and_sorts_by_size():
    from radar.providers.telegram import TelegramProvider
    class Ch:
        def __init__(self, u, n): self.username = u; self.participants_count = n; self.title = "t"
    class Found:
        chats = [Ch("small", 200), Ch(None, 9999), Ch("big", 5000)]
    class FakeClient:
        def __call__(self, req): return Found()
    p = TelegramProvider(client=FakeClient())
    out = p.discover_channels("электроника", limit=10)
    assert [c["handle"] for c in out] == ["@big", "@small"]  # username-less dropped, biggest first


def test_ensure_chats_discovered_bootstraps_seeds_for_brand_without_channels():
    import json
    from radar.models import Brand, Probe
    from radar.collector import ensure_chats_discovered

    s = _mem_session_tg()
    # An online electronics shop — NO curated tg_channels, only sphere/niche.
    b = Brand(name="ТехноМаг", sphere="интернет-магазин электроники",
              tg_channels="[]", niche_keywords=json.dumps(["смартфон"]),
              category_terms="[]", audience_terms="[]", geo="")
    s.add(b); s.flush(); s.commit()

    class FakeProvider:
        def discover_channels(self, q, limit=20):
            return [{"handle": "@techchan", "title": "Всё про смартфон и гаджеты", "participants": 8000}]
        def channel_recommendations(self, handle, limit=10):
            return []
        def linked_chat(self, handle):
            return {"handle": "@techchat", "title": "Чат техно", "participants": 4000} \
                if handle == "@techchan" else None

    n = ensure_chats_discovered(s, b, FakeProvider())
    chats = {p.query for p in s.query(Probe).filter_by(kind="chat").all()}
    assert chats == {"@techchat"}   # discovered a seed channel by sphere, took its chat
    assert n == 1


def test_collect_chats_captures_non_food_shopping_intent():
    import json
    from datetime import datetime, timezone
    from radar.models import Brand, Probe, Mention
    from radar.collector import collect_chats
    from radar.providers.base import Post

    s = _mem_session_tg()
    b = Brand(name="ТехноМаг", sphere="электроника гаджеты",
              niche_keywords=json.dumps(["смартфон"]),
              category_terms="[]", audience_terms="[]", geo="")
    s.add(b); s.flush()
    s.add(Probe(brand_id=b.id, platform="telegram", kind="chat", query="@techchat",
                source="niche", label="Чат техно",
                next_run_at=datetime.now(timezone.utc), interval_sec=3600))
    s.commit()

    def mk(pid, text):
        return Post(post_id=pid, platform="telegram", author="@u", followers=0,
                    text=text, hashtags=[], created_at=datetime.now(timezone.utc),
                    likes=0, views=0, comments=0, shares=0)

    class FakeProvider:
        def search_chat(self, handle, term, limit=20):
            return [mk("techchat/1", "посоветуйте какой смартфон выбрать до 30 тысяч?"),
                    mk("techchat/2", "ага")]
        def search(self, *a, **k): return None

    collect_chats(s, b, FakeProvider())
    kept = {m.post_id for m in s.query(Mention).filter_by(brand_id=b.id, is_spam=False).all()}
    assert "techchat/1" in kept     # shopping recommendation intent captured (no food terms)
    assert "techchat/2" not in kept


# ── Username-less linked discussion groups (addressed via the parent channel) ──

def test_linked_chat_returns_id_when_group_has_no_username():
    from radar.providers.telegram import TelegramProvider
    class Linked:
        id = 777; username = None; megagroup = True
        title = "Кудаеда Talks"; participants_count = 9000
    class FullChat: linked_chat_id = 777
    class Full:
        full_chat = FullChat(); chats = [Linked()]
    class FakeClient:
        def get_entity(self, h): return object()
        def __call__(self, req): return Full()
    p = TelegramProvider(client=FakeClient())
    out = p.linked_chat("@kudaeda")
    assert out["handle"] is None          # no public username
    assert out["id"] == 777               # but addressable by id via the parent
    assert out["via"] == "@kudaeda"


def test_search_linked_chat_resolves_group_via_parent_channel():
    from datetime import datetime, timezone
    from radar.providers.telegram import TelegramProvider
    class Sender: username = "vasya"
    class Msg:
        id = 9; message = "посоветуйте куда сходить?"; views = 0; forwards = 0
        reactions = None; replies = None; date = datetime(2026, 6, 13, tzinfo=timezone.utc)
        sender = Sender()
    class Linked: id = 777
    class FullChat: linked_chat_id = 777
    class Full:
        full_chat = FullChat(); chats = [Linked()]
    seen = {}
    class FakeClient:
        def get_entity(self, h): return object()
        def __call__(self, req): return Full()
        def get_messages(self, entity, **kw):
            seen["entity"] = entity; seen["kw"] = kw; return [Msg()]
    p = TelegramProvider(client=FakeClient())
    posts = p.search_linked_chat("@kudaeda", "посоветуйте", limit=10)
    assert isinstance(seen["entity"], Linked)         # searched the linked group, not the channel
    assert posts[0].post_id == "777/9"                # namespaced by the group's internal id
    assert posts[0].author == "@vasya"


def test_post_url_telegram_internal_id_chat():
    from types import SimpleNamespace
    from radar.api import _post_url
    m = SimpleNamespace(platform="telegram", author="@vasya", post_id="777/9")
    assert _post_url(m) == "https://t.me/c/777/9"     # numeric namespace -> private-group link


def test_collect_chats_handles_linked_kind_probes():
    import json
    from datetime import datetime, timezone
    from radar.models import Brand, Probe, Mention
    from radar.collector import collect_chats
    from radar.providers.base import Post

    s = _mem_session_tg()
    b = Brand(name="Тануки", sphere="рестораны", niche_keywords=json.dumps(["ресторан"]),
              category_terms="[]", audience_terms="[]", geo="")
    s.add(b); s.flush()
    s.add(Probe(brand_id=b.id, platform="telegram", kind="chat_linked", query="@kudaeda",
                source="niche", label="Talks",
                next_run_at=datetime.now(timezone.utc), interval_sec=3600))
    s.commit()

    def mk(pid, text):
        return Post(post_id=pid, platform="telegram", author="@u", followers=0, text=text,
                    hashtags=[], created_at=datetime.now(timezone.utc),
                    likes=0, views=0, comments=0, shares=0)

    class FakeProvider:
        def search_linked_chat(self, parent, term, limit=20):
            return [mk("777/1", "посоветуйте хороший ресторан в центре?")]
        def search_chat(self, *a, **k): return []
    n = collect_chats(s, b, FakeProvider())
    kept = {m.post_id for m in s.query(Mention).filter_by(brand_id=b.id, is_spam=False).all()}
    assert "777/1" in kept and n == 1


# ── Relevance: word-boundary matching (no "кафе" inside "кафедральный") ──

def test_term_hit_word_boundary_rejects_substring_false_positive():
    from radar.collector import _term_hit
    assert _term_hit("Вьетнамское кафе", ["кафе"])              # real word
    assert not _term_hit("Брянский кафедральный собор", ["кафе"])  # substring → reject
    assert _term_hit("лучший ресторан города", ["ресторан"])


def test_ensure_chats_discovered_bootstrap_filters_offtopic_by_title():
    import json
    from radar.models import Brand, Probe
    from radar.collector import ensure_chats_discovered
    s = _mem_session_tg()
    b = Brand(name="Дача", sphere="ресторан кафе гриль", tg_channels="[]",
              niche_keywords=json.dumps(["ресторан", "кафе"]),
              category_terms="[]", audience_terms="[]", geo="Брянск")
    s.add(b); s.flush(); s.commit()

    class FakeProvider:
        def discover_channels(self, q, limit=20):
            return [{"handle": "@cafe_br", "title": "Вьетнамское кафе Брянск", "participants": 800},
                    {"handle": "@sobor",   "title": "Кафедральный собор Брянск", "participants": 5000}]
        def channel_recommendations(self, handle, limit=10): return []
        def linked_chat(self, handle):
            return {"handle": f"{handle}_chat", "id": 1, "via": handle, "title": "Chat", "participants": 200}
    ensure_chats_discovered(s, b, FakeProvider())
    chats = {p.query for p in s.query(Probe).filter_by(kind="chat").all()}
    assert chats == {"@cafe_br_chat"}    # cathedral filtered out by title relevance
