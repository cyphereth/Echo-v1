"""Тред несёт тип медиа родителя: модель, fetch_thread_context, _resolve_locally."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from types import SimpleNamespace


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def _m(s, post_id, reply_to=None, media=None):
    from radar.intel.models import IntelMention, IntelDirection
    # direction_id is NOT NULL — seed a direction if none exists
    d = s.query(IntelDirection).first()
    if d is None:
        d = IntelDirection(key="kursk", name="Курское")
        s.add(d)
        s.flush()
    m = IntelMention(platform="telegram", post_id=post_id, author="@u", side="ru",
                     text="t", created_at=datetime.now(timezone.utc),
                     reply_to_tg_id=reply_to, media=media,
                     direction_id=d.id)
    s.add(m); s.flush()
    return m


def test_thread_context_has_media_column():
    from radar.intel.models import IntelThreadContext
    ctx = IntelThreadContext(mention_id=1, tg_msg_id="5", role="parent", depth=1,
                             author="@a", text="x", created_at=datetime.now(timezone.utc),
                             media="photo")
    assert ctx.media == "photo"


def test_resolve_locally_copies_parent_media():
    from radar.intel import passes  # noqa регистрирует модели
    from radar.intel.context_pass import _resolve_locally
    from radar.intel.models import IntelThreadContext
    s = _sess()
    root = _m(s, "ns/10", reply_to=None, media="photo")     # родитель с фото
    reply = _m(s, "ns/11", reply_to="10")
    s.commit()
    assert _resolve_locally(s, reply) is True
    row = s.query(IntelThreadContext).filter_by(mention_id=reply.id, tg_msg_id="10").one()
    assert row.media == "photo"


def test_fetch_thread_context_includes_media():
    from radar.core.providers.telegram import TelegramProvider
    # сообщение-родитель с фото
    parent = SimpleNamespace(id=10, message="родитель", date=datetime.now(timezone.utc),
                             sender=None, sender_id=1, reply_to_msg_id=None,
                             photo=object(), video=None, document=None)
    class Client:
        def get_entity(self, h): return SimpleNamespace(id=1)
        def get_messages(self, entity, ids=None, **kw):
            if ids: return [parent]
            return []
    p = TelegramProvider(client=Client())
    out = p.fetch_thread_context("@chan", reply_to_tg_id="10", current_tg_id="11")
    assert out["parents"], "ожидался родитель"
    assert out["parents"][0]["media"] == "photo"
