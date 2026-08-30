"""Talking to the Telegram Bot API.

`httpx` directly — see `pyproject.toml`'s own note on why it's now a direct
dependency rather than supertokens-python's transitive one. `settings.
telegram_bot_token` empty is the "feature is off" state everywhere in this
module: every function here becomes a silent no-op, the identical contract
`SMTP_HOST` empty already holds for the mailer.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("app.services.telegram")

API_BASE = "https://api.telegram.org"


async def send_message(chat_id: str, text: str) -> None:
    if not settings.telegram_bot_token:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_BASE}/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        resp.raise_for_status()
