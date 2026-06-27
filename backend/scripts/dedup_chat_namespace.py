"""Одноразовый ремонт БД после фикса namespace чатов.

1. Схлопывает дубли одного сообщения, сохранённого и в marked ('-100<id>/m'),
   и в unmarked ('<id>/m') namespace (баг до chat_namespace).
2. Бэкфилл: сбрасывает context_fetched у реплаев с оборванной цепочкой, чтобы
   следующий тик enrich_context пере-собрал ветку с правильным namespace.

По умолчанию --dry-run (печатает план). Реальные изменения — только с --apply.
Бэкенд перезапускает ассистент, не пользователь.
"""
from __future__ import annotations
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from radar.models import Base
import radar.intel.models  # noqa – регистрирует модели
from radar.intel.models import IntelMention, IntelThreadContext
from radar.core.providers.telegram import chat_namespace


def _split(post_id: str):
    """('-100123/567') -> ('-100123', '567'); голый id -> (post_id, '')."""
    if "/" not in post_id:
        return post_id, ""
    ns, msgid = post_id.rsplit("/", 1)
    return ns, msgid


def _canonical_ns(ns: str) -> str:
    """unmarked-форма namespace; для '@user'/'user' остаётся как есть."""
    return chat_namespace(None, ns) if ns.lstrip("-").isdigit() else ns


def find_namespace_dupes(session: Session):
    """Пары (keep, drop): одно сообщение чата в двух namespace-формах.

    Группируем по (canonical_ns, msgid). В группе >1 записи keep — с непустым
    thread-контекстом, иначе с меньшим id; остальные — drop."""
    groups: dict[tuple, list[IntelMention]] = {}
    for m in session.query(IntelMention).filter(IntelMention.post_id.like("%/%")).all():
        ns, msgid = _split(m.post_id)
        if not msgid:
            continue
        key = (_canonical_ns(ns), msgid)
        groups.setdefault(key, []).append(m)

    pairs = []
    for members in groups.values():
        if len(members) < 2:
            continue
        # разные post_id внутри группы = реальный namespace-дубль
        if len({m.post_id for m in members}) < 2:
            continue
        ctx_counts = {
            m.id: session.query(IntelThreadContext)
            .filter_by(mention_id=m.id).count()
            for m in members
        }
        def _is_canonical(m: IntelMention) -> bool:
            ns, msgid = _split(m.post_id)
            return ns == _canonical_ns(ns)
        keep = max(members, key=lambda m: (ctx_counts[m.id], _is_canonical(m), -m.id))
        for drop in members:
            if drop.id != keep.id:
                pairs.append((keep, drop))
    return pairs


def collapse_dupe(session: Session, keep: IntelMention, drop: IntelMention) -> None:
    """Перевесить контекст и ссылки с drop на keep, удалить drop."""
    (session.query(IntelThreadContext)
        .filter_by(mention_id=drop.id)
        .update({IntelThreadContext.mention_id: keep.id}, synchronize_session=False))
    (session.query(IntelMention)
        .filter_by(reply_to_id=drop.id)
        .update({IntelMention.reply_to_id: keep.id}, synchronize_session=False))
    (session.query(IntelMention)
        .filter_by(thread_root_id=drop.id)
        .update({IntelMention.thread_root_id: keep.id}, synchronize_session=False))
    session.delete(drop)


def reset_broken_chains(session: Session, limit: int = 200) -> int:
    """Сбросить context_fetched у реплаев с оборванной цепочкой (нет reply_to_id),
    чтобы enrich_context пере-собрал ветку. Возвращает число затронутых."""
    rows = (session.query(IntelMention)
            .filter(IntelMention.reply_to_tg_id.isnot(None),
                    IntelMention.reply_to_id.is_(None),
                    IntelMention.context_fetched.is_(True))
            .limit(limit).all())
    for m in rows:
        m.context_fetched = False
    return len(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ремонт namespace-дублей и оборванных reply-цепочек")
    ap.add_argument("--db", default="echo_radar.db", help="путь к SQLite БД")
    ap.add_argument("--apply", action="store_true", help="выполнить (иначе dry-run)")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run", help="явный dry-run (по умолчанию)")
    ap.add_argument("--backfill-limit", type=int, default=200)
    args = ap.parse_args(argv)

    eng = create_engine(f"sqlite:///{args.db}")
    Base.metadata.create_all(eng)
    session = Session(eng)
    try:
        pairs = find_namespace_dupes(session)
        print(f"namespace-дублей найдено: {len(pairs)}")
        for keep, drop in pairs:
            print(f"  keep={keep.post_id}(id={keep.id})  drop={drop.post_id}(id={drop.id})")

        if args.apply:
            for keep, drop in pairs:
                collapse_dupe(session, keep, drop)
            n = reset_broken_chains(session, args.backfill_limit)
            session.commit()
            print(f"схлопнуто пар: {len(pairs)}; сброшено оборванных цепочек: {n}")
        else:
            n = (session.query(IntelMention)
                 .filter(IntelMention.reply_to_tg_id.isnot(None),
                         IntelMention.reply_to_id.is_(None),
                         IntelMention.context_fetched.is_(True))
                 .limit(args.backfill_limit).count())
            print(f"[dry-run] к бэкфиллу оборванных цепочек: {n}. Запусти с --apply.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
