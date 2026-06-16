# Telegram Provider Design Spec

**Date:** 2026-06-12
**Status:** Approved
**Branch:** `feat/telegram-provider`

## Goal

Add Telegram as a monitoring source alongside TikTok and Instagram. Brand managers see Telegram channel posts and group messages mentioning their brand in the same Feed/Queue as TikTok/Instagram content — no new UI paradigm needed.

## Non-Goals (YAGNI)

- No real-time / live-stream monitoring (poll-based like TikTok, not webhook)
- No private channels/groups
- No message sending / reply posting from Echo (read-only)
- No Telegram Bot API (requires bot to be a member of every chat)

## Architecture

`TelegramProvider` is a parallel source — **not** a replacement for TikHub/SocialCrawl. `_get_provider()` is unchanged; a separate `_get_tg_provider()` returns the TG provider when credentials are set. The collector, classifier, spam filter, and draft pipeline all work without changes — Telegram posts become `Mention` rows with `platform="telegram"`.

```
TELEGRAM_API_ID / TELEGRAM_API_HASH in .env
        ↓
_get_tg_provider() → TelegramProvider (Telethon client)
        ↓
Probes with platform="telegram"
  kind="keyword"  → client.get_messages(None, search=query)  [global search]
  kind="channel"  → client.get_messages(entity, limit=N)     [channel read]
        ↓
collector.collect_probe() → Post → Mention (platform="telegram")
        ↓
classify_and_draft() — unchanged
```

## Two Collection Modes

### 1. Global search (keyword/competitor/niche probes)
`TelegramProvider.search(query, kind, cursor, platform="telegram")` calls `client.get_messages(None, search=query, limit=20, offset_id=int(cursor or 0))`. Returns posts from public channels and groups matching the query. Mirrors TikTok keyword search semantics.

### 2. Channel/group monitoring
Probes with `kind="channel"` and `query="@channel_username"` read latest posts from a specific public channel or group. The user adds `@username` handles in brand Settings under a new "Telegram-каналы" field. These become `source="competitor"` or `source="niche"` probes depending on which list they're in.

## Files

| File | Action | What |
|---|---|---|
| `backend/radar/providers/telegram.py` | Create | `TelegramProvider(SearchProvider)` |
| `backend/radar/tg_auth.py` | Create | One-shot interactive session creator |
| `backend/radar/models.py` | Modify | Add `tg_channels: str` field to `Brand` |
| `backend/radar/db.py` | Modify | Migration row for `tg_channels` column |
| `backend/radar/api.py` | Modify | `_get_tg_provider()`, wire TG probes in `_rebuild_probes`, add TG collect to `_run_collect` |
| `backend/radar/collector.py` | Modify | `platform="telegram"` support in `_passes_language` and `collect_probe` |
| `backend/.env` | Modify | Add `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` |
| `backend/tg_session.session` | Runtime | Telethon session file — add to `.gitignore` |
| `echo-app/src/components/app/Settings.jsx` | Modify | "Telegram-каналы" field |
| `backend/tests/test_telegram.py` | Create | Unit tests (mocked Telethon) |

## TelegramProvider Implementation

```python
class TelegramProvider(SearchProvider):
    """Telethon-backed provider. Session file must exist (created via tg_auth.py)."""

    def __init__(self):
        from telethon.sync import TelegramClient
        self._client = TelegramClient(
            SESSION_FILE,  # backend/tg_session.session
            int(os.getenv("TELEGRAM_API_ID", "")),
            os.getenv("TELEGRAM_API_HASH", ""),
        )
        self._client.connect()

    def search(self, query, kind, cursor, platform="telegram") -> SearchPage:
        if kind == "channel":
            return self._read_channel(query, cursor)
        return self._global_search(query, cursor)

    def _global_search(self, query, cursor) -> SearchPage:
        # client.get_messages(None, search=query) — public global search
        ...

    def _read_channel(self, username, cursor) -> SearchPage:
        # client.get_messages(entity, limit=20, offset_id=cursor)
        ...
```

### Post mapping from Telethon Message

```python
Post(
    post_id    = str(msg.id),
    platform   = "telegram",
    author     = author_handle,      # see note below — "@yakitoriya"
    followers  = getattr(entity, "participants_count", 0) or 0,
    text       = msg.message or "",
    hashtags   = re.findall(r"#\w+", msg.message or ""),
    created_at = msg.date,           # already tz-aware
    likes      = _sum_reactions(msg),
    views      = msg.views or 0,
    comments   = getattr(getattr(msg, "replies", None), "replies", 0) or 0,
    shares     = msg.forwards or 0,
)
```

`_sum_reactions(msg)` sums all reaction counts from `msg.reactions.results` if present.

**Resolving `author_handle` and `entity`:** for **channel-read** mode the entity is already known (the `@username` we queried). For **global search** mode, each message belongs to a different chat — resolve via `msg.chat` / `getattr(msg.chat, "username", None)` (Telethon attaches the chat when `get_messages(None, search=...)` is used). Fall back to `str(msg.peer_id.channel_id)` when there's no public username. `followers` comes from `getattr(msg.chat, "participants_count", 0)`.

### Cursor / pagination

`cursor` = string of the `offset_id` (lowest message id seen so far). `next_cursor = str(min(msg.id for msg in page))` if page is full (20 msgs), else `None`.

### Connection management

`TelegramProvider` keeps one persistent `TelegramClient` connection per instance. `_get_tg_provider()` returns a module-level singleton (avoids reconnecting on every collect). Telethon's sync client is thread-safe for read operations.

### Rate limiting

Telethon raises `FloodWaitError(seconds)` when rate-limited. Wrap every call:
```python
except FloodWaitError as e:
    log.warning("Telegram flood wait %ds", e.seconds)
    raise RuntimeError(f"Telegram flood wait {e.seconds}s")
```
The collector's per-probe `try/except` (in `_run_collect`) catches any exception and skips that probe gracefully — the message text is only logged, not parsed, so any wording is fine.

## Session Creation (`tg_auth.py`)

One-time interactive script:
```bash
cd backend && python -m radar.tg_auth
```
Prompts for the code sent to the phone, optionally 2FA password. Saves `tg_session.session`. After this the provider works autonomously — no phone number needed at runtime.

Credentials stored in `.env`:
```
TELEGRAM_API_ID=<your_api_id>
TELEGRAM_API_HASH=<your_api_hash>
TELEGRAM_PHONE=<your_phone>
```

## Brand Model Changes

Add `tg_channels: str` (JSON list, default `"[]"`) to `Brand`:
```python
tg_channels: Mapped[str] = mapped_column(Text, default="[]")
```
Helper: `brand.tg_channels_list() → list[str]` — list of `@username` strings.

`_rebuild_probes()` creates `Probe(platform="telegram", kind="channel", source="competitor", query=handle)` for each handle in `brand.tg_channels_list()`. Also creates standard keyword probes for `platform="telegram"` (same keywords/competitors/niche as TikTok).

## Collector Changes

`_passes_language` already filters by `market=ru`. Add Telegram to the platform check — TG posts are often Russian, filter logic is the same (Cyrillic check + viral threshold).

`collect_probe` is platform-agnostic — no changes needed beyond supporting `kind="channel"` in `TelegramProvider.search()`.

`_rebuild_probes` gains TG entries:
```python
MONITORED_PLATFORMS = ("tiktok", "instagram", "telegram")  # add telegram
```
But only if `TELEGRAM_API_ID` is set in env.

## Frontend Changes (Settings.jsx)

Add a "Telegram-каналы" text area in brand settings (same pattern as existing keywords/competitors fields). Placeholder: `@yakitoriya, @sushiwok_official`. Saved via `POST /brands/{id}/config`. No other UI changes — TG mentions appear in Feed/Queue with a Telegram icon (add `telegram` to `icons.jsx`).

## Feed display

`Mention.platform = "telegram"` — the frontend already renders platform icons via `<Icon name={platform} />`. Add a Telegram SVG to `icons.jsx`.

`_post_url` in `api.py`: for telegram, construct `https://t.me/{author_without_@}/{post_id}` — strip a leading `@` from `author` (e.g. author `@yakitoriya`, post_id `123` → `https://t.me/yakitoriya/123`). Works for public channels.

## Error Handling

- Session file missing → `_get_tg_provider()` returns `None`; `_run_collect` skips TG probes silently with a log warning.
- `FloodWaitError` → treated as transient, probe skipped (same as TikHub 429).
- `ChannelPrivateError` → mark probe inactive, log warning.
- Invalid phone number at auth time → `tg_auth.py` prints error, user re-runs with correct number.

## Testing (no real Telethon connection)

`backend/tests/test_telegram.py` — monkeypatch `telethon.sync.TelegramClient` to return mock messages. Test:
- `_parse_tg_message` maps Telethon Message → Post correctly (views, reactions, forwards, date)
- `search()` with kind="keyword" calls `get_messages(None, search=query)`
- `search()` with kind="channel" calls `get_messages(entity, ...)`
- `FloodWaitError` → raises `RuntimeError` (collector skips gracefully)
- `_get_tg_provider()` returns None when `TELEGRAM_API_ID` not set

## Setup Instructions (for user)

1. Credentials already obtained (api_id=<your_api_id>, api_hash=09df…)
2. After implementation: `cd backend && python -m radar.tg_auth`
3. Enter the code Telegram sends to the phone
4. Session saved → `uvicorn` restart → TG collection active

## .gitignore additions

```
backend/tg_session.session
backend/*.session
```
