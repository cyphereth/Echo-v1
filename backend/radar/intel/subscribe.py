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


def run(provider) -> dict:
    """Join every not-yet-joined source via `provider`. Returns a counts summary.

    Sources recorded in the state file are skipped, so a re-run after a flood-wait
    makes forward progress without re-joining (which would waste the daily cap)."""
    session = get_session()
    try:
        _by_user, join_handles, invite_links = build_source_map(session)
    finally:
        session.close()

    done = _load_done()
    counts = {"channels_ok": 0, "channels_fail": 0, "invites_ok": 0, "invites_fail": 0,
              "skipped": 0, "total_channels": len(join_handles), "total_invites": len(invite_links)}

    try:
        for i, handle in enumerate(join_handles, 1):
            if handle in done:
                counts["skipped"] += 1
                continue
            try:
                ok = provider.join_channel(handle)
            except TelegramFloodWait as e:
                log.warning("flood-wait %ds at %s — stopping sweep, re-run later", e.seconds, handle)
                counts["stopped_at"] = handle
                counts["flood_seconds"] = e.seconds
                return counts
            if ok:
                counts["channels_ok"] += 1
                done.add(handle)
            else:
                counts["channels_fail"] += 1
            print(f"[{i}/{len(join_handles)}] channel {handle}: {'ok' if ok else 'FAIL'}")

        for j, (link, _side, _kind) in enumerate(invite_links, 1):
            if link in done:
                counts["skipped"] += 1
                continue
            try:
                ok = provider.join_invite(link)
            except TelegramFloodWait as e:
                log.warning("flood-wait %ds at %s — stopping sweep, re-run later", e.seconds, link)
                counts["stopped_at"] = link
                counts["flood_seconds"] = e.seconds
                return counts
            if ok:
                counts["invites_ok"] += 1
                done.add(link)
            else:
                counts["invites_fail"] += 1
            print(f"[invite {j}/{len(invite_links)}] {link}: {'ok' if ok else 'FAIL'}")
    finally:
        _save_done(done)

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
