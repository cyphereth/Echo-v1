"""One-time Telegram session creator.

Run interactively: `cd backend && python -m radar.tg_auth`
Enter the login code Telegram sends to TELEGRAM_PHONE (and 2FA password if set).
Saves the session next to the provider so TelegramProvider works autonomously.
"""
import os
from dotenv import load_dotenv

load_dotenv()

from telethon.sync import TelegramClient

SESSION_FILE = os.path.join(os.path.dirname(__file__), "tg_session")


def main():
    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    phone = os.getenv("TELEGRAM_PHONE", "")
    if not (api_id and api_hash and phone):
        print("Set TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE in backend/.env first.")
        return
    with TelegramClient(SESSION_FILE, int(api_id), api_hash) as client:
        client.start(phone=phone)
        me = client.get_me()
        print(f"✅ Session saved. Logged in as: {me.username or me.first_name} (id={me.id})")


if __name__ == "__main__":
    main()
