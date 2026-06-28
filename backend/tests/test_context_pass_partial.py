"""RC-B: неполная локальная цепочка не должна помечаться завершённой —
иначе сетевой догруз её не дочинит и thread_root_id будет неверным."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = Session(eng)
    from radar.intel import seed
    seed.ensure_default_directions(s)
    s.commit()
    return s


def _m(s, post_id, reply_to=None):
    from radar.intel.models import IntelMention, IntelDirection
    d = s.query(IntelDirection).first()
    m = IntelMention(direction_id=d.id, platform="telegram", post_id=post_id, author="@u", side="ru",
                     text="t", created_at=datetime.now(timezone.utc),
                     reply_to_tg_id=reply_to)
    s.add(m); s.flush()
    return m


def test_complete_chain_marks_done_with_root():
    """Родитель локален и сам корневой -> цепочка полная: done + thread_root_id."""
    from radar.intel import passes  # noqa – регистрирует модели
    from radar.intel.context_pass import _resolve_locally
    s = _sess()
    root = _m(s, "ns/10", reply_to=None)          # настоящий корень (нет родителя)
    reply = _m(s, "ns/11", reply_to="10")          # ответ на корень
    s.commit()

    ok = _resolve_locally(s, reply)
    assert ok is True
    assert reply.reply_to_id == root.id
    assert reply.thread_root_id == root.id
    assert reply.context_fetched is True


def test_partial_chain_not_marked_done():
    """Прямой родитель локален, но ЕГО родителя в БД нет -> хвост оборван.
    Не помечаем завершённой и не ставим thread_root_id — дочинит сеть."""
    from radar.intel import passes  # noqa
    from radar.intel.context_pass import _resolve_locally
    s = _sess()
    parent = _m(s, "ns/20", reply_to="5")          # ссылается на 5, которого нет в БД
    reply = _m(s, "ns/21", reply_to="20")
    s.commit()

    ok = _resolve_locally(s, reply)
    assert ok is False, "оборванная цепочка не считается разрешённой локально"
    assert reply.reply_to_id == parent.id, "прямой родитель всё равно проставлен"
    assert reply.thread_root_id is None, "корень неизвестен — не выдумываем"
    assert reply.context_fetched is False, "сеть должна дочинить хвост"
