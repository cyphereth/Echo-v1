import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from radar.core.providers.base import Post
from radar.core.providers.telegram import _parse_tg_chat_message


class _Sender:
    username = "alice"

class _ChatMsg:
    def __init__(self, id=200, message="БПЛА сбили над районом", reply_to_msg_id=None):
        self.id = id
        self.message = message
        self.reply_to_msg_id = reply_to_msg_id
        self.date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.sender = _Sender()
        self.views = 0
        self.forwards = 0
        self.reactions = None


def test_parse_chat_msg_no_reply():
    p = _parse_tg_chat_message(_ChatMsg(), "mygroup", "@mygroup")
    assert p.reply_to_tg_id is None

def test_parse_chat_msg_with_reply():
    p = _parse_tg_chat_message(_ChatMsg(reply_to_msg_id=199), "mygroup", "@mygroup")
    assert p.reply_to_tg_id == "199"

def test_parse_chat_msg_post_id_format():
    p = _parse_tg_chat_message(_ChatMsg(id=200), "mygroup", "@mygroup")
    assert p.post_id == "mygroup/200"


# ---------------------------------------------------------------------------
# Task 3: fetch_thread_context
# ---------------------------------------------------------------------------
from radar.core.providers.telegram import TelegramProvider


class _FakeMsg:
    def __init__(self, id, text, reply_to_msg_id=None, sender_username="bot"):
        self.id = id
        self.message = text
        self.reply_to_msg_id = reply_to_msg_id
        self.date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.sender = type("S", (), {"username": sender_username})()
        self.reactions = None
        self.views = 0
        self.forwards = 0


class _FakeClient:
    """Simulates: msg 300 replies to 299, which replies to 298 (root). Siblings of 298: [301]."""
    def get_entity(self, h): return h
    def is_connected(self): return True
    def get_messages(self, entity, ids=None, reply_to=None, limit=None, **kw):
        db = {
            298: _FakeMsg(298, "корень треда"),
            299: _FakeMsg(299, "первый ответ", reply_to_msg_id=298),
            300: _FakeMsg(300, "БПЛА сбили", reply_to_msg_id=299),
            301: _FakeMsg(301, "подтверждаем", reply_to_msg_id=298),
        }
        if ids is not None:
            single = ids if isinstance(ids, int) else ids[0]
            return [db[single]] if single in db else []
        if reply_to is not None:
            return [m for m in db.values()
                    if m.reply_to_msg_id == reply_to and m.id != 300][:limit]
        return []


def test_fetch_thread_context_parent_chain():
    provider = TelegramProvider(client=_FakeClient())
    result = provider.fetch_thread_context("@grp", reply_to_tg_id="299", current_tg_id="300")
    parents = result["parents"]
    # depth 0 = direct parent (299), depth 1 = grandparent (298)
    assert len(parents) == 2
    depths = {p["depth"] for p in parents}
    assert depths == {0, 1}
    tg_ids = {p["tg_msg_id"] for p in parents}
    assert tg_ids == {"299", "298"}

def test_fetch_thread_context_siblings():
    provider = TelegramProvider(client=_FakeClient())
    result = provider.fetch_thread_context("@grp", reply_to_tg_id="299", current_tg_id="300")
    siblings = result["siblings"]
    # 301 replies to 298 (same root), excluding current msg 300
    assert any(s["tg_msg_id"] == "301" for s in siblings)
    assert not any(s["tg_msg_id"] == "300" for s in siblings)  # current msg excluded

def test_fetch_thread_context_no_reply():
    provider = TelegramProvider(client=_FakeClient())
    result = provider.fetch_thread_context("@grp", reply_to_tg_id=None, current_tg_id="300")
    assert result == {"parents": [], "siblings": []}
