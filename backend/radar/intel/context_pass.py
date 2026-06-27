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


_MAX_LOCAL_DEPTH = 12


def _handle_for(mention: IntelMention) -> str:
    """The Telegram handle to resolve a mention's thread against.

    Chat messages carry a composite post_id ('namespace/msgid') whose prefix is the
    handle. Channel posts carry a bare numeric post_id, so the channel @username lives
    in the author field instead. Either way the result is something get_entity accepts.
    """
    if "/" in (mention.post_id or ""):
        handle = mention.post_id.rsplit("/", 1)[0]
    else:
        handle = (mention.author or "").strip()
    if handle and not handle.startswith("@") and not handle.startswith("#"):
        handle = f"@{handle}"
    return handle


def _parent_post_id(mention: IntelMention, tg_id: str) -> str:
    """The post_id a parent/ancestor with Telegram id `tg_id` would have, in the same
    namespace as `mention`. Chats are namespaced ('ns/id'); channels are bare ('id')."""
    if "/" in (mention.post_id or ""):
        namespace = mention.post_id.rsplit("/", 1)[0]
        return f"{namespace}/{tg_id}"
    return str(tg_id)


def _resolve_locally(session: Session, mention: IntelMention) -> bool:
    """Build the reply chain for `mention` from mentions already in the DB.

    The parent of a reply is usually a post we already collected from the same
    channel. When that's true we can assemble the whole chain without a single
    Telegram round-trip: walk up via reply_to_tg_id within the same namespace,
    materialise IntelThreadContext "parent" rows, and resolve reply_to_id /
    thread_root_id. Returns True when the immediate parent was found locally
    (chain fully resolved); False means we must fall back to the network fetch.

    Works for both shapes: chat messages (composite 'ns/msgid' post_id) and channel
    posts (bare numeric post_id, namespace implied by the author/channel). Siblings are
    intentionally not resolved here — they're secondary and would require a chat scan.
    The reply chain is what the UI renders prominently.
    """
    parent_post_id = _parent_post_id(mention, mention.reply_to_tg_id)
    parent = (
        session.query(IntelMention)
        .filter(IntelMention.post_id == parent_post_id)
        .first()
    )
    if parent is None:
        return False  # parent not local → caller fetches from Telegram

    mention.reply_to_id = parent.id

    chain: list[IntelMention] = []
    node = parent
    seen: set[str] = set()
    depth = 1
    while node is not None and depth <= _MAX_LOCAL_DEPTH:
        if node.post_id in seen:  # guard against malformed self/loop references
            break
        seen.add(node.post_id)
        chain.append(node)
        if not node.reply_to_tg_id:
            break
        next_post_id = _parent_post_id(mention, node.reply_to_tg_id)
        node = (
            session.query(IntelMention)
            .filter(IntelMention.post_id == next_post_id)
            .first()
        )
        depth += 1

    for d, anc in enumerate(chain, start=1):
        _, anc_tg_id = _parse_handle_and_msg_id(anc.post_id)
        ctx = IntelThreadContext(
            mention_id=mention.id,
            tg_msg_id=anc_tg_id,
            role="parent",
            depth=d,
            author=anc.author or "",
            text=anc.text or "",
            created_at=anc.created_at,
        )
        sp = session.begin_nested()
        try:
            session.add(ctx)
            session.flush()
            sp.commit()
        except IntegrityError:
            sp.rollback()

    # Цепочка полна ТОЛЬКО если верхний достигнутый узел реально корневой
    # (у него нет родителя). Если хвост оборван (родитель не в БД) — оставляем
    # context_fetched=False, чтобы сетевой enrich_context дочинил ветку и нашёл
    # настоящий корень. reply_to_id (прямой родитель) уже проставлен выше.
    top = chain[-1]
    if not top.reply_to_tg_id:
        mention.thread_root_id = top.id
        mention.context_fetched = True
        session.commit()
        return True
    session.commit()  # сохраняем reply_to_id + materialised parent-rows
    return False


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
        # Fast path: parent already in our DB → assemble chain locally, no network.
        try:
            if _resolve_locally(session, mention):
                enriched += 1
                continue
        except Exception:
            log.exception("context_pass: local resolve failed for mention %s — falling back", mention.id)
            session.rollback()

        _, current_tg_id = _parse_handle_and_msg_id(mention.post_id)
        handle = _handle_for(mention)
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

        if result is None:
            log.warning("context_pass: fetch returned None for mention %s — skipping", mention.id)
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

        # Resolve reply_to_id and thread_root_id from index. Parent/root post_ids are
        # built in the mention's own namespace (composite for chats, bare for channels).
        if mention.reply_to_tg_id:
            parent_post_id = _parent_post_id(mention, mention.reply_to_tg_id)
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
            root_post_id = _parent_post_id(mention, root_tg_id)
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
