"""Interactive Telegram login — creates the Telethon session the provider reads.

Telegram sends a login code to your account; this prompts for it (and your 2FA
password, if set), then writes the session file the app uses. Run it yourself —
it needs interactive input:

    cd backend && python3 -m radar.tg_login

Once it prints "Session saved", restart the backend and the topic TG pass will
collect live.
"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from telethon.sync import TelegramClient  # noqa: E402  (sync wrapper for a CLI script)
from radar.core.providers.telegram import SESSION_FILE, API_ID, API_HASH  # noqa: E402


def main() -> None:
    if not (API_ID and API_HASH):
        raise SystemExit("TELEGRAM_API_ID / TELEGRAM_API_HASH missing in backend/.env")
    phone = os.getenv("TELEGRAM_PHONE", "").strip() or None
    with TelegramClient(SESSION_FILE, int(API_ID), API_HASH) as client:
        client.start(phone=phone)
        me = client.get_me()
        handle = f"@{me.username}" if me.username else "(no username)"
        print(f"\n✓ Logged in as {me.first_name} {handle} id={me.id}")
        print(f"✓ Session saved to {os.path.abspath(SESSION_FILE)}.session")


if __name__ == "__main__":
    main()
