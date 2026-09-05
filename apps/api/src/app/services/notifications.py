"""Raising a notification.

**Everything that notifies anyone goes through `notify()`.** One place that
writes the row and queues delivery, so there is exactly one answer to "why did
this person get a message" and exactly one place to add rate limiting the day
it's needed.

Every nudge — email, Telegram, webhook — carries no detail beyond a title,
an optional body and where to look. Two reasons, and the second is the one
that matters — a task title in an inbox we don't control is a task title
outside the access model, still sitting there after the access is revoked.

**Delivery fans out to every channel enabled for this `kind`**, not "always
email" — see `services/notification_channels.py`. That module owns the
routing decision entirely; this one just asks it who to tell and queues
whichever jobs come back.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, User
from app.models.notification_channel import CHANNEL_EMAIL, CHANNEL_TELEGRAM, CHANNEL_WEBHOOK

logger = logging.getLogger("app.services.notifications")


async def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None = None,
    link_path: str | None = None,
    organisation_id: uuid.UUID | None = None,
) -> Notification | None:
    """Write one notification and queue its email nudge.

    `organisation_id` is what lets the email go to the address chosen for
    *that* organisation rather than the account's own — see
    `notification_channels.email_for_organisation`. Every caller has it: they
    have just built a `/orgs/{id}/…` link with it. Optional only because
    nothing structurally requires a notification to belong to one, and a
    caller that genuinely doesn't have one should send to the account
    address rather than guess.

    Never raises. A notification is a side effect of something that already
    happened and committed; failing the caller's request because the inbox row
    wouldn't write would undo real work for a cosmetic reason.
    """
    try:
        row = Notification(
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            link_path=link_path,
            organisation_id=organisation_id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    except Exception as exc:  # pragma: no cover - defensive
        await db.rollback()
        logger.warning("could not raise %s notification for %s: %s", kind, user_id, exc)
        return None

    try:
        # Imported here, not at module scope: app.tasks imports handlers which
        # import services, and a top-level import would close that loop.
        from app.services import notification_channels as channels_service
        from app.tasks.notification_channels import (
            send_telegram_message,
            send_webhook_notification,
        )
        from app.tasks.notifications import send_notification_email

        for channel in await channels_service.channels_for(db, user_id, kind=kind):
            if channel.kind == CHANNEL_EMAIL:
                await send_notification_email.kiq(str(row.id))
            elif channel.kind == CHANNEL_TELEGRAM:
                await send_telegram_message.kiq(str(row.id), str(channel.id))
            elif channel.kind == CHANNEL_WEBHOOK:
                await send_webhook_notification.kiq(str(row.id), str(channel.id))
    except Exception as exc:
        # The worker being unreachable must not cost the in-app notification,
        # which is the part people actually read.
        logger.warning("could not queue delivery for notification %s: %s", row.id, exc)
    return row


async def list_for_user(
    db: AsyncSession, user: User, *, unread_only: bool = False, limit: int = 50
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list((await db.execute(stmt)).scalars().all())


async def unread_count(db: AsyncSession, user: User) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
    ).scalar_one()


async def mark_read(db: AsyncSession, user: User, notification_id: uuid.UUID) -> None:
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is not None and row.read_at is None:
        row.read_at = func.now()
        await db.commit()


async def mark_all_read(db: AsyncSession, user: User) -> None:
    rows = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.user_id == user.id, Notification.read_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.read_at = func.now()
    await db.commit()


async def delete(db: AsyncSession, user: User, notification_id: uuid.UUID) -> None:
    """Silently a no-op for a foreign or already-gone id — the same "not
    found is fine" shape `mark_read` already has for this inbox, and DELETE
    is supposed to be idempotent regardless."""
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
