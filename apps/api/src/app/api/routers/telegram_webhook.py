"""Telegram calls this when someone messages the bot.

Not organisation-scoped and not user-authenticated — Telegram has no idea
what either of those are, and there is no session cookie or access token on
this request. Registered with Telegram once via `setWebhook`, pointed at
`{SITE_URL}/api/telegram/webhook` (see README) — everything after that is
this route being called by Telegram's own servers.

`DNS-rebinding`-style host checks don't apply here the way they do for MCP:
this route does no more than resolve a short-lived code to a user and store
a chat id, the identical narrow authority an invite link already has.
"""

import logging

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.services import notification_channels as channels_service
from app.services import telegram as telegram_service

logger = logging.getLogger("app.api.routers.telegram_webhook")

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(request: Request, db: DbSession):
    """Always 200s. Telegram retries a webhook call that doesn't, and
    there is nothing here worth retrying — a malformed update or a code that
    doesn't match anything is not a transient failure."""
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not text.startswith("/start") or chat_id is None:
        return {"ok": True}
    code = text.removeprefix("/start").strip()
    if not code:
        return {"ok": True}

    linked = await channels_service.complete_telegram_link(db, code=code, chat_id=str(chat_id))
    reply = (
        "Linked — you'll get notifications here."
        if linked
        else "That link has expired. Start again from your notification settings."
    )
    try:
        await telegram_service.send_message(str(chat_id), reply)
    except Exception as exc:  # pragma: no cover - defensive
        # The link itself already committed. A confirmation that fails to
        # send must not turn that success into a Telegram-visible error.
        logger.warning("could not send the Telegram link confirmation: %s", exc)

    return {"ok": True}
