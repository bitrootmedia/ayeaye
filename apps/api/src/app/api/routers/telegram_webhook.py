"""Telegram calls this when someone messages the bot.

Not organisation-scoped and not user-authenticated — Telegram has no idea
what either of those are, and there is no session cookie or access token on
this request. Registered with Telegram once via `setWebhook`, pointed at
`{SITE_URL}/api/telegram/webhook` (see README) — everything after that is
this route being called by Telegram's own servers.

`DNS-rebinding`-style host checks don't apply here the way they do for MCP:
the actual command handling in `services/telegram_commands.py` resolves a
chat id to a linked account itself, the identical narrow authority an
invite link already has.
"""

import logging

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.services import telegram_commands

logger = logging.getLogger("app.api.routers.telegram_webhook")

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(request: Request, db: DbSession):
    """Always 200s. Telegram retries a webhook call that doesn't, and
    there is nothing here worth retrying — a malformed update, an unlinked
    chat or a command that doesn't parse is not a transient failure. See
    `services/telegram_commands.py`'s own docstring for the full reasoning,
    including why that means no `update_id` de-duplication either."""
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    try:
        await telegram_commands.handle_update(db, update)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("could not handle a Telegram update: %s", exc)

    return {"ok": True}
