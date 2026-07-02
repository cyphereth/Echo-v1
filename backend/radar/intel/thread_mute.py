"""Мут тредов: куратор глушит ветку обсуждения, и её последующие ответы больше
не попадают в ленту. Ключ — множество tg-сообщений ветки в рамках namespace чата
(post_id = "ns/msgid"). Набор растёт каскадно: приходит ответ на замученное
сообщение → его msgid тоже пишется в набор, поэтому ответы на любую глубину
продолжают отсекаться. Мут необратим (как спам-пример). Ретро-скрытие уже
сохранённых ответов НЕ делаем — глушим только будущие входящие.
"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from .models import IntelMention, IntelThreadContext, IntelThreadMute


def _split(post_id: str | None) -> tuple[str, str] | None:
    """('ns', 'msgid') из post_id вида 'ns/msgid'. Каналы (numeric post_id без
    '/') тредов не имеют — None."""
    if not post_id or "/" not in post_id:
        return None
    ns, msgid = post_id.rsplit("/", 1)
    return ns, msgid


def add_muted(session, platform: str, ns: str, tg_msg_id: str) -> None:
    """Добавить одно сообщение в набор замученной ветки (idempotent)."""
    if not ns or not tg_msg_id:
        return
    row = IntelThreadMute(platform=platform, ns=ns, tg_msg_id=str(tg_msg_id))
    sp = session.begin_nested()
    try:
        session.add(row)
        session.flush()
        sp.commit()
    except IntegrityError:
        sp.rollback()  # уже в наборе


def is_muted(session, platform: str, ns: str, tg_msg_id: str | None) -> bool:
    if not ns or not tg_msg_id:
        return False
    return (session.query(IntelThreadMute.id)
            .filter_by(platform=platform, ns=ns, tg_msg_id=str(tg_msg_id))
            .first() is not None)


def gate_muted(session, post, platform: str) -> bool:
    """Гейт для ingest. True → пост принадлежит замученной ветке, дропаем.
    Побочный эффект: если дропаем, пишем msgid этого поста в набор, чтобы ответы
    на него дальше по цепочке тоже ловились (каскад)."""
    parts = _split(getattr(post, "post_id", None))
    rid = getattr(post, "reply_to_tg_id", None)
    if not parts or not rid:
        return False
    ns, msgid = parts
    if is_muted(session, platform, ns, rid):
        add_muted(session, platform, ns, msgid)   # каскад
        return True
    return False


def mute_thread(session, mention_id: int) -> int:
    """Замутить тред по mention_id. В набор кидаем: msgid самого упоминания, его
    reply_to (непосредственный родитель) и все tg_msg_id из его thread_context
    (цепочка родителей + соседи). Возвращает число новых строк намерения (грубо).
    Дальнейший рост — каскадом на ingest. Ретро-скрытие не делаем."""
    m = session.get(IntelMention, mention_id)
    if m is None:
        return 0
    parts = _split(m.post_id)
    if not parts:
        return 0
    ns, msgid = parts
    platform = m.platform or "telegram"

    seeds: set[str] = {msgid}
    if m.reply_to_tg_id:
        seeds.add(str(m.reply_to_tg_id))
    for tc in (session.query(IntelThreadContext.tg_msg_id)
               .filter_by(mention_id=mention_id).all()):
        if tc[0]:
            seeds.add(str(tc[0]))

    for s in seeds:
        add_muted(session, platform, ns, s)
    return len(seeds)
