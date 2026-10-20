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


async def send_question(chat_id: str, text: str, buttons: list[tuple[str, str]]) -> None:
    """A message with one row of inline buttons, as `(label, callback_data)`.

    A tap arrives at the webhook as a `callback_query` carrying the data —
    see `telegram_commands.handle_update`. `callback_data` is at most 64
    bytes, which is why what goes in it is an action and an id, never text.
    """
    if not settings.telegram_bot_token:
        return
    keyboard = [[{"text": label, "callback_data": data} for label, data in buttons]]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{API_BASE}/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "reply_markup": {"inline_keyboard": keyboard}},
        )
        resp.raise_for_status()


async def settle_question(
    chat_id: str, message_id: int, callback_id: str, text: str
) -> None:
    """Answer a button tap: stop its spinner, and replace the question with
    what became of it — which also takes the buttons away, so a second tap
    on an answered question is impossible rather than merely harmless."""
    if not settings.telegram_bot_token:
        return
    base = f"{API_BASE}/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{base}/answerCallbackQuery", json={"callback_query_id": callback_id})
        resp = await client.post(
            f"{base}/editMessageText",
            json={"chat_id": chat_id, "message_id": message_id, "text": text},
        )
        resp.raise_for_status()
