"""Регресс: realtime и поллер дают ОДИН post_id для одного сообщения чата без @username.
Иначе (platform, post_id) не дедупит -> дубли + рвётся reply-цепочка."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from types import SimpleNamespace


def _msg(mid):
    return SimpleNamespace(
        id=mid, message="по складу прилёт, вторичная детонация",
        date=datetime.now(timezone.utc), sender=None, reply_to_msg_id=None,
        views=0, forwards=0,
    )


def test_realtime_and_poller_agree_on_namespace_username_less():
    from radar.core.providers.telegram import _parse_tg_chat_message, chat_namespace

    marked_chat_id = -1001234567890   # как отдаёт Telethon event.chat_id
    unmarked = "1234567890"           # как хранит probe.query: '#1234567890'

    # Поллер: namespace из resolved-entity (username=None, id=unmarked peer)
    poller_ns = chat_namespace(None, 1234567890)
    poller_post = _parse_tg_chat_message(_msg(567), poller_ns, "#1234567890")

    # Realtime: namespace из marked event.chat_id, username отсутствует
    rt_ns = chat_namespace(None, marked_chat_id)
    rt_post = _parse_tg_chat_message(_msg(567), rt_ns, "@chat")

    assert poller_ns == unmarked
    assert rt_ns == unmarked
    assert rt_post.post_id == poller_post.post_id == "1234567890/567"
