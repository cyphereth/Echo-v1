"""Enrich IntelMention rows that are replies with their parent chain and siblings.

Called after collect_probe (in passes.py). Fetches context lazily — only for mentions
not yet enriched (context_fetched=False). On TelegramFloodWait the mention is skipped
and retried next run. On any other error context_fetched is set True to avoid retry loops.
"""
from __future__ import annotations
import logging
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .models import IntelMention, IntelThreadContext

log = logging.getLogger(__name__)


def _parse_handle_and_msg_id(post_id: str) -> tuple[str, str]:
    """Split 'chathandle/123' → ('@chathandle', '123').

    For numeric handles like '#-1001234567/123' (private group via id) the '#' prefix
    is preserved so TelegramProvider.get_entity can resolve it.
    """
    if "/" not in post_id:
        return post_id, post_id
    handle, msg_id = post_id.rsplit("/", 1)
    if not handle.startswith("@") and not handle.startswith("#"):
        handle = f"@{handle}"
    return handle, msg_id


def enrich_context(session: Session, provider, batch_size: int = 50) -> int:
    """Fetch and store thread context for unprocessed reply mentions.

    Returns the count of mentions that were successfully enriched.
    """
    from ..core.providers.telegram import TelegramFloodWait

    pending = (
        session.query(IntelMention)
        .filter(
            IntelMention.reply_to_tg_id.isnot(None),
            IntelMention.context_fetched.is_(False),
        )
        .limit(batch_size)
        .all()
    )

    enriched = 0
    for mention in pending:
        handle, current_tg_id = _parse_handle_and_msg_id(mention.post_id)
        try:
            result = provider.fetch_thread_context(
                handle,
                reply_to_tg_id=mention.reply_to_tg_id,
                current_tg_id=current_tg_id,
            )
        except TelegramFloodWait as e:
            log.warning("context_pass flood-wait %ds — aborting batch", getattr(e, "seconds", "?"))
            session.commit()
            return enriched
        except Exception:
            log.exception("context_pass: fetch failed for mention %s — marking done", mention.id)
            mention.context_fetched = True
            session.commit()
            continue

        for p in result.get("parents", []):
            ctx = IntelThreadContext(
                mention_id=mention.id,
                tg_msg_id=p["tg_msg_id"],
                role="parent",
                depth=p["depth"],
                author=p.get("author", ""),
                text=p.get("text", ""),
                created_at=p["created_at"],
            )
            sp = session.begin_nested()
            try:
                session.add(ctx)
                session.flush()
                sp.commit()
            except IntegrityError:
                sp.rollback()

        for sib in result.get("siblings", []):
            ctx = IntelThreadContext(
                mention_id=mention.id,
                tg_msg_id=sib["tg_msg_id"],
                role="sibling",
                depth=0,
                author=sib.get("author", ""),
                text=sib.get("text", ""),
                created_at=sib["created_at"],
            )
            sp = session.begin_nested()
            try:
                session.add(ctx)
                session.flush()
                sp.commit()
            except IntegrityError:
                sp.rollback()

        # Resolve reply_to_id and thread_root_id from index
        # Extract namespace from mention.post_id (format: "namespace/msgid")
        namespace = mention.post_id.rsplit("/", 1)[0]

        if mention.reply_to_tg_id:
            parent_post_id = f"{namespace}/{mention.reply_to_tg_id}"
            parent_in_index = (
                session.query(IntelMention)
                .filter(IntelMention.post_id == parent_post_id)
                .first()
            )
            if parent_in_index:
                mention.reply_to_id = parent_in_index.id

        parents = result.get("parents", [])
        if parents:
            root_tg_id = parents[-1]["tg_msg_id"]
            root_post_id = f"{namespace}/{root_tg_id}"
            root_in_index = (
                session.query(IntelMention)
                .filter(IntelMention.post_id == root_post_id)
                .first()
            )
            if root_in_index:
                mention.thread_root_id = root_in_index.id

        mention.context_fetched = True
        session.commit()
        enriched += 1

    return enriched
