# Intel Thread Context — Design Spec
**Date:** 2026-06-25  
**Module:** Intel (разведка) only  
**Scope:** Reply chains and thread siblings for Telegram chat messages stored as `IntelMention`

---

## Problem

When a user replies to a message in a monitored Telegram chat, we store only the reply text — stripped of its parent. Fragments like «да, согласен» or «у нас так же» are meaningless without context. The same applies to mid-thread messages whose root and siblings are missing.

---

## Goals

1. Store the **parent chain** (up to root) for every IntelMention that is a reply.
2. Store **thread siblings** (messages sharing the same parent).
3. Render a **collapsible inline thread** in the StoryDetail events list in the UI.

---

## Data Model

### `IntelMention` — 3 new columns

```python
reply_to_tg_id:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)
# Telegram msg.reply_to_msg_id — raw TG id of the parent message

reply_to_id:     Mapped[Optional[int]] = mapped_column(ForeignKey("intel_mentions.id"), nullable=True)
# FK to IntelMention parent — filled only when the parent also passed the relevance filter

thread_root_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("intel_mentions.id"), nullable=True)
# FK to IntelMention thread root — filled by context_pass when root is in the index

context_fetched: Mapped[bool] = mapped_column(Boolean, default=False)
# True once context_pass has attempted to fetch context for this mention (even if empty)
# Prevents endless retries when parent message is deleted or unreachable
```

Migration: `ALTER TABLE intel_mentions ADD COLUMN reply_to_tg_id TEXT; ADD COLUMN reply_to_id INTEGER REFERENCES intel_mentions(id); ADD COLUMN thread_root_id INTEGER REFERENCES intel_mentions(id); ADD COLUMN context_fetched INTEGER NOT NULL DEFAULT 0;`

### New table `IntelThreadContext`

Stores raw context messages that do **not** pass the relevance filter (e.g. a thread root "что тут у вас?").

```python
class IntelThreadContext(Base):
    __tablename__ = "intel_thread_context"
    __table_args__ = (UniqueConstraint("mention_id", "tg_msg_id"),)

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    mention_id:  Mapped[int]           = mapped_column(ForeignKey("intel_mentions.id"), nullable=False)
    tg_msg_id:   Mapped[str]           = mapped_column(Text, nullable=False)
    role:        Mapped[str]           = mapped_column(Text, nullable=False)   # "parent" | "sibling"
    depth:       Mapped[int]           = mapped_column(Integer, default=0)     # 0=direct parent, 1=grandparent, …; 0 for siblings
    author:      Mapped[str]           = mapped_column(Text, default="")
    text:        Mapped[str]           = mapped_column(Text, default="")
    created_at:  Mapped[datetime]      = mapped_column(nullable=False)
```

The `IntelMention` index stays clean — only relevance-filtered military messages.

---

## Collection Changes

### `telegram.py` — `TelegramProvider`

1. `_parse_tg_chat_message` extracts `reply_to_tg_id`:
   ```python
   reply_to_tg_id = str(msg.reply_to_msg_id) if getattr(msg, "reply_to_msg_id", None) else None
   ```
   Added to `Post` dataclass as optional field.

2. New method `fetch_thread_context(handle, reply_to_tg_id, current_tg_id, depth_limit=5, sibling_limit=10) -> dict`:
   - **Parent chain (up):** recursively call `get_messages(entity, ids=reply_to_tg_id)` — walk up via each message's `reply_to_msg_id` until no parent or `depth_limit` reached. Returns list of `(msg, depth)`.
   - **Siblings (lateral):** once root is found, call `get_messages(entity, reply_to=root_tg_id, limit=sibling_limit)` — excludes `current_tg_id`. Returns list of msgs.
   - Respects existing `_throttle()` / flood-wait handling — raises `TelegramFloodWait` to caller.

### `intel/collector.py` — chat branch

When storing an `IntelMention` from a chat message: set `mention.reply_to_tg_id = post.reply_to_tg_id` if present. Leave `reply_to_id` and `thread_root_id` as `None` — resolved by context pass.

### New `intel/context_pass.py` — `enrich_context(session, provider, batch_size=50)`

```
1. Query: IntelMention WHERE reply_to_tg_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM intel_thread_context WHERE mention_id = IntelMention.id)
   LIMIT batch_size

2. For each mention:
   a. Parse chat handle from post_id format: "chathandle/msgid" → handle, tg_msg_id
   b. Call provider.fetch_thread_context(handle, mention.reply_to_tg_id, tg_msg_id)
   c. On TelegramFloodWait: log and skip mention (it will be retried next pass)
   d. Store parents: IntelThreadContext(mention_id, tg_msg_id, role="parent", depth=N, ...)
   e. Store siblings: IntelThreadContext(mention_id, tg_msg_id, role="sibling", depth=0, ...)
   f. Resolve reply_to_id: look up IntelMention WHERE post_id ends with "/{reply_to_tg_id}"
   g. Resolve thread_root_id: look up IntelMention WHERE post_id ends with "/{root_tg_id}"
   h. Commit

3. Return count of enriched mentions.
```

`enrich_context` is called from `passes.py` (or the scheduler) after `collect_probe` completes for chat probes.

---

## API

### New endpoint

```
GET /intel/mention/{mention_id}/context
→ 404 if mention not found
→ 200:
{
  "mention_id": 123,
  "reply_chain": [          // sorted root→direct_parent (depth descending)
    {"tg_msg_id": "...", "depth": 2, "author": "@x", "text": "...", "created_at": "..."},
    {"tg_msg_id": "...", "depth": 1, "author": "@y", "text": "...", "created_at": "..."},
    {"tg_msg_id": "...", "depth": 0, "author": "@z", "text": "...", "created_at": "..."}
  ],
  "siblings": [             // sorted by created_at asc
    {"tg_msg_id": "...", "author": "@w", "text": "...", "created_at": "..."}
  ]
}
```

### `aggregate.event(m)` change

Add two fields to the existing event payload:
- `"is_reply": bool` — `True` when `reply_to_tg_id IS NOT NULL`
- `"reply_to_tg_id": str | null`

This lets the frontend know which events have context available without a separate request.

---

## UI (`IntelStories.jsx` → `StoryDetail`)

### Trigger

In the «События» `CollapsibleSection`, each event row that has `is_reply: true` shows a small «↑ контекст» button.

### Behaviour

- Click «↑ контекст» → `GET /intel/mention/{id}/context` → inline block expands **above** the current message
- Second click → collapses
- State is local per card (`useState` inside the event row component) — no global state needed
- Loading state: show a spinner or «…» while fetching

### Visual layout (inline, no new screen)

```
┌─────────────────────────────────────────┐
│  🧵 @root_author · "корень треда..."    │  depth=N — muted (#4A6378), left-indent
│     └─ @parent · "..."                  │  depth=1
│        └─ @direct_parent · "..."        │  depth=0 (#6A8499)
├─────────────────────────────────────────┤
│  ★ ТЕКУЩЕЕ СООБЩЕНИЕ (подсвечено)       │  standard eventRow style (#D8E4F0)
├─────────────────────────────────────────┤
│  @sibling · "..."                       │  muted, no indent
│  @sibling2 · "..."                      │
└─────────────────────────────────────────┘
```

Styling follows existing `eventRow` CSS class. Context rows use `color: #4A6378`, current row stays `#D8E4F0`. A thin left border (`border-left: 2px solid #2BB3C7`) on the context block visually separates it from the rest of the event list.

---

## Error Handling

- `fetch_thread_context` on `TelegramFloodWait`: skip the mention in this pass, retry next run — watermark is NOT affected.
- `fetch_thread_context` on any other exception (private chat, message deleted): log warning, store zero context rows — the mention is considered "enriched" with empty context so it's not retried endlessly. Achieved by inserting a sentinel row with `role="none"` OR by adding a boolean `context_fetched` column to `IntelMention`. **Decision: use `context_fetched: bool = False` column on `IntelMention`** — cleaner than sentinel rows.
- API `/intel/mention/{id}/context`: if `IntelThreadContext` rows don't exist yet (enrich not run), return empty `reply_chain` and `siblings` arrays — no 404.

---

## What Is NOT in Scope

- News/Brand modules — untouched.
- Channel probes — channel posts don't have reply threads; only chat probes generate `reply_to_tg_id`.
- Realtime SSE stream context enrichment — context is enriched in the scheduled pass, not live.
- Persisting full thread history beyond `depth_limit=5` / `sibling_limit=10`.
