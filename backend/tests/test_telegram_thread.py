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
