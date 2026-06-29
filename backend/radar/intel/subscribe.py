"""Subscribe the account to every intel source so the realtime listener receives them.

Telegram only delivers NewMessage updates for dialogs the account is a member of.
This sweep joins every public channel/chat (JoinChannelRequest) and every private
invite link (ImportChatInviteRequest) in IntelProbe, throttled by the provider.

Run once after adding sources (or after enabling realtime):

    cd backend && python3 -m radar.intel.subscribe

Idempotent — already-joined sources are no-ops. Stops early on a long flood-wait so
it never hammers Telegram; just re-run later to finish the rest. Telegram also caps
joins per day, so a very large list may need a couple of runs across days.
"""
from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv

# Load .env BEFORE importing the Telegram provider — it reads API_ID/API_HASH from
# the environment at import time, so the values must be present first.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from ..core.db import init_db, get_session
from ..core.providers.telegram import TelegramFloodWait
from .realtime import build_source_map

log = logging.getLogger("radar.intel.subscribe")

# Persisted set of sources we've already joined, so re-runs (after a flood-wait or on
# another day) resume instead of re-spending the daily join budget on the same channels.
# Gitignored scratch — it's per-account runtime state, not code.
_STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "subscribed.json")


def _load_done() -> set[str]:
    try:
        with open(_STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, ValueError):
        return set()


def _save_done(done: set[str]) -> None:
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(done), f, ensure_ascii=False, indent=0)


# Shared, process-wide record of join targets we've already subscribed to. Both the
# manual sweep (run) and the per-tick collect pass (passes._ensure_joined) consult it,
# so a channel is JoinChannelRequest'd at most once — re-issuing joins on every tick is
# what earns the account multi-hour flood bans.
_done_cache: set[str] | None = None


def _join_key(target: str) -> str:
    """Normalize a join target to a stable key. Channels collapse to a lowercase
    handle without '@' (so '@Name', 'Name', 'https://t.me/Name' all match); invite
    links are kept verbatim (their hash is case-sensitive)."""
    t = (target or "").strip()
    if "/+" in t or "joinchat/" in t or t.startswith("+"):
        return t
    if "t.me/" in t:
        t = t.split("t.me/", 1)[1]
    return t.lstrip("@").lower()


def _cache() -> set[str]:
    global _done_cache
    if _done_cache is None:
        _done_cache = {_join_key(x) for x in _load_done()}
    return _done_cache


def already_joined(target: str) -> bool:
    return _join_key(target) in _cache()


def mark_joined(target: str) -> None:
    c = _cache()
    k = _join_key(target)
    if k not in c:
        c.add(k)
        _save_done(c)


# Telegram bans aggressive joining far harder than reading. Cap how many NEW joins a
# single sweep performs, and space them out, so a large source list is subscribed over
# several runs instead of in one burst that earns a multi-hour flood ban.
_JOIN_MAX_PER_RUN = int(os.getenv("TG_JOIN_MAX_PER_RUN", "20"))
_JOIN_INTERVAL    = float(os.getenv("TG_JOIN_INTERVAL", "20"))


def run(provider) -> dict:
    """Join up to TG_JOIN_MAX_PER_RUN not-yet-joined sources via `provider`, spaced by
    TG_JOIN_INTERVAL seconds. Returns a counts summary.

    Sources recorded in the shared state are skipped, so a re-run (after a flood-wait,
    the per-run cap, or on another day) makes forward progress without re-joining."""
    import time as _time
    session = get_session()
    try:
        _by_user, join_handles, invite_links = build_source_map(session)
    finally:
        session.close()

    counts = {"channels_ok": 0, "channels_fail": 0, "invites_ok": 0, "invites_fail": 0,
              "skipped": 0, "total_channels": len(join_handles), "total_invites": len(invite_links)}
    state = {"budget": _JOIN_MAX_PER_RUN, "joined_this_run": 0}

    def _spend(target, joiner) -> str:
        """Attempt one join. Returns: 'skip' (already a member), 'cap' (per-run budget
        spent — stop the sweep), 'ok', or 'fail'. Spaces real joins by _JOIN_INTERVAL."""
        if already_joined(target):
            counts["skipped"] += 1
            return "skip"
        if state["budget"] <= 0:
            counts["cap_reached"] = True
            return "cap"
        if state["joined_this_run"] > 0:
            _time.sleep(_JOIN_INTERVAL)  # space out only between actual join attempts
        state["budget"] -= 1
        state["joined_this_run"] += 1
        ok = joiner(target)
        if ok:
            mark_joined(target)
        return "ok" if ok else "fail"

    for i, handle in enumerate(join_handles, 1):
        try:
            r = _spend(handle, provider.join_channel)
        except TelegramFloodWait as e:
            log.warning("flood-wait %ds at %s — stopping sweep, re-run later", e.seconds, handle)
            counts["stopped_at"] = handle; counts["flood_seconds"] = e.seconds
            return counts
        if r == "cap":
            return counts
        if r == "ok":
            counts["channels_ok"] += 1
        elif r == "fail":
            counts["channels_fail"] += 1
        if r in ("ok", "fail"):
            print(f"[{i}/{len(join_handles)}] channel {handle}: {'ok' if r == 'ok' else 'FAIL'}")

    for j, (link, _side, _kind) in enumerate(invite_links, 1):
        try:
            r = _spend(link, provider.join_invite)
        except TelegramFloodWait as e:
            log.warning("flood-wait %ds at %s — stopping sweep, re-run later", e.seconds, link)
            counts["stopped_at"] = link; counts["flood_seconds"] = e.seconds
            return counts
        if r == "cap":
            return counts
        if r == "ok":
            counts["invites_ok"] += 1
        elif r == "fail":
            counts["invites_fail"] += 1
        if r in ("ok", "fail"):
            print(f"[invite {j}/{len(invite_links)}] {link}: {'ok' if r == 'ok' else 'FAIL'}")

    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    from ..core.providers.telegram import TelegramProvider
    provider = TelegramProvider()
    summary = run(provider)
    print("\n=== subscribe sweep done ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
