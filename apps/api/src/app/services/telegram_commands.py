"""What a Telegram chat can say to this product, and what it says back.

Four commands, and one kind of button — the two under "still working on
this?" (`services/check_ins.py`), which arrive as a `callback_query` rather
than a message. `/start {code}` is the linking handshake (`services/
notification_channels.py::complete_telegram_link`); `/task`, `/org` and
`/help` are new. Everything else — a plain message, an unrecognised
command — gets a "send /help" reply and creates nothing. That was a
deliberate product call: the ask was a `/task` command, not "every message
becomes a task," because the second one is one accidental tap or stray
reply away from a task nobody meant to file.

`handle_update` never raises for an *expected* failure — not linked, no
organisation, an `/org` query matching nothing — those are replies, not
exceptions. A genuinely unexpected error is left to propagate to the
router's own catch-all, the identical "never worth a Telegram retry" shape
`/start` already had before this module existed.

**No `update_id` de-duplication, on purpose.** Telegram retries a webhook
call that doesn't 200; this one (almost) always does, even on an internal
error, so a retry is already rare. Tracking processed update ids would be
real infrastructure (a table, or a Redis key) for a genuinely rare edge
case on what is, at bottom, a personal capture tool — the identical
trade-off this module's own docstring's sibling, `services/
notification_channels.py`, already makes for webhook and Telegram
delivery not getting the email job's per-notification idempotency flag.
"""

import logging
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import NotificationChannel, User
from app.models.notification_channel import CHANNEL_TELEGRAM
from app.services import check_ins as check_ins_service
from app.services import notification_channels as channels_service
from app.services import organisations as organisations_service
from app.services import tasks as tasks_service
from app.services import telegram as telegram_service

logger = logging.getLogger("app.services.telegram_commands")

HELP_TEXT = (
    "Commands:\n"
    "/task <title> — create a task (add more lines for a description)\n"
    "/org <name> — choose which organisation new tasks go into\n"
    "/org — show your current organisation and the ones you belong to\n"
    "/help — this message"
)


async def handle_update(db: AsyncSession, update: dict) -> None:
    if update.get("callback_query"):
        await _handle_button(db, update["callback_query"])
        return
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not text or chat_id is None:
        return
    chat_id = str(chat_id)

    if text.startswith("/start"):
        await _handle_start(db, chat_id, text.removeprefix("/start").strip())
        return

    resolved = await _channel_and_user(db, chat_id)
    if resolved is None:
        await _reply(
            chat_id,
            "This chat isn't linked to an account yet. Link it from Account → "
            "Notification channels.",
        )
        return
    channel, user = resolved

    if text.startswith("/task"):
        await _handle_task(db, channel, user, text.removeprefix("/task").strip())
    elif text.startswith("/org"):
        await _handle_org(db, channel, user, text.removeprefix("/org").strip())
    elif text.startswith("/help"):
        await _reply(chat_id, HELP_TEXT)
    else:
        await _reply(chat_id, "Didn't understand that — send /help for the commands.")


async def _handle_button(db: AsyncSession, query: dict) -> None:
    """A tap on one of the buttons under "still working on this?".

    The only buttons this bot sends, so anything else is ignored. Resolved
    through the chat the tap came from, exactly like a command — the entry id
    in the button only pins *which* timer, it grants nothing on its own.
    """
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    parsed = check_ins_service.parse_callback(query.get("data") or "")
    if chat_id is None or parsed is None:
        return
    action, entry_id = parsed
    resolved = await _channel_and_user(db, str(chat_id))
    if resolved is None:
        return
    _, user = resolved
    outcome = await check_ins_service.answer(
        db, user, still_working=action == check_ins_service.ANSWER_YES, entry_id=entry_id
    )
    question = (message.get("text") or "").split("\n")[0]
    text = {
        check_ins_service.CONFIRMED: f"{question}\n\n✓ Yes — carrying on.",
        check_ins_service.STOPPED: f"{question}\n\n■ Stopped the timer.",
        check_ins_service.GONE: f"{question}\n\nThat timer isn't running any more.",
    }[outcome]
    await telegram_service.settle_question(
        str(chat_id), message.get("message_id"), query.get("id"), text
    )


async def _handle_start(db: AsyncSession, chat_id: str, code: str) -> None:
    if not code:
        return
    linked = await channels_service.complete_telegram_link(db, code=code, chat_id=chat_id)
    reply = (
        "Linked — you'll get notifications here. Send /help to see what else this bot can do."
        if linked
        else "That link has expired. Start again from your notification settings."
    )
    await _reply(chat_id, reply)


async def _channel_and_user(
    db: AsyncSession, chat_id: str
) -> tuple[NotificationChannel, User] | None:
    row = (
        await db.execute(
            select(NotificationChannel, User)
            .join(User, User.id == NotificationChannel.user_id)
            .where(
                NotificationChannel.kind == CHANNEL_TELEGRAM,
                NotificationChannel.verified_at.is_not(None),
                NotificationChannel.config["chat_id"].astext == chat_id,
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


# --- /task -------------------------------------------------------------------------


async def _handle_task(
    db: AsyncSession, channel: NotificationChannel, user: User, rest: str
) -> None:
    chat_id = channel.config["chat_id"]
    if not rest:
        await _reply(
            chat_id,
            "Usage: /task <title> — add more lines for a description.",
        )
        return

    org_id = await _resolve_default_organisation(db, channel, user)
    if org_id is None:
        return  # _resolve_default_organisation already replied.

    try:
        ctx = await organisations_service.context_for(db, org_id, user)
    except HTTPException:
        await _reply(
            chat_id,
            "You're no longer a member of your default organisation. "
            "Send /org <name> to choose another.",
        )
        return

    title, _, description = rest.partition("\n")
    task = await tasks_service.create(
        db, ctx, user, title=title.strip()[:300], description=description.strip() or None
    )
    link = f"{settings.site_url}/orgs/{ctx.organisation.id}/tasks/{task.id}"
    await _reply(chat_id, f'✅ Created "{task.title}" in {ctx.organisation.name}\n{link}')


async def _resolve_default_organisation(
    db: AsyncSession, channel: NotificationChannel, user: User
) -> uuid.UUID | None:
    """The org `/task` should file into, or `None` after already replying
    with why it couldn't decide. Auto-picks (and persists) a lone
    organisation rather than making someone run `/org` for a choice that
    doesn't exist yet."""
    chat_id = channel.config["chat_id"]
    stored = channel.config.get("default_organisation_id")
    if stored:
        return uuid.UUID(stored)

    mine = await organisations_service.list_for_user(db, user)
    if len(mine) == 1:
        org = mine[0][0]
        await channels_service.set_telegram_default_organisation(db, channel, org.id)
        return org.id
    if not mine:
        await _reply(chat_id, "You're not a member of any organisation yet.")
        return None
    names = ", ".join(o.name for o, _ in mine)
    await _reply(chat_id, f"Choose an organisation first: /org <name>. You belong to: {names}")
    return None


# --- /org --------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchResult:
    organisation_id: str | None
    organisation_name: str | None
    ambiguous: list[str]


def match_organisation(query: str, choices: list[tuple[str, str]]) -> MatchResult:
    """`choices` is `(id, name)` pairs. Exact (case-insensitive) name match
    wins outright even when it's also a substring of another choice — so
    typing "Acme" for an organisation literally named "Acme" doesn't get
    tangled up with a second one named "Acme Corp". Only when there's no
    exact match does a *unique* substring match get used; more than one
    candidate either way is reported, never guessed at."""
    q = query.strip().lower()
    exact = [(i, n) for i, n in choices if n.lower() == q]
    if len(exact) == 1:
        return MatchResult(exact[0][0], exact[0][1], [])
    if len(exact) > 1:
        return MatchResult(None, None, [n for _, n in exact])

    partial = [(i, n) for i, n in choices if q in n.lower()]
    if len(partial) == 1:
        return MatchResult(partial[0][0], partial[0][1], [])
    return MatchResult(None, None, [n for _, n in partial])


async def _handle_org(
    db: AsyncSession, channel: NotificationChannel, user: User, query: str
) -> None:
    chat_id = channel.config["chat_id"]
    mine = await organisations_service.list_for_user(db, user)

    if not query:
        current_id = channel.config.get("default_organisation_id")
        current = next((o.name for o, _ in mine if str(o.id) == current_id), None)
        names = ", ".join(o.name for o, _ in mine) or "none yet"
        await _reply(
            chat_id,
            f"Current: {current or 'not set'}\nYou belong to: {names}\n"
            "Send /org <name> to switch.",
        )
        return

    result = match_organisation(query, [(str(o.id), o.name) for o, _ in mine])
    if result.organisation_id is None:
        if result.ambiguous:
            await _reply(
                chat_id,
                f'"{query}" matches more than one: {", ".join(result.ambiguous)}. '
                "Be more specific.",
            )
        else:
            names = ", ".join(o.name for o, _ in mine) or "none yet"
            await _reply(chat_id, f'No organisation matches "{query}". You belong to: {names}')
        return

    await channels_service.set_telegram_default_organisation(
        db, channel, uuid.UUID(result.organisation_id)
    )
    await _reply(chat_id, f"New tasks now go to {result.organisation_name}.")


async def _reply(chat_id: str, text: str) -> None:
    try:
        await telegram_service.send_message(chat_id, text)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("could not send a Telegram reply: %s", exc)
