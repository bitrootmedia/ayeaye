"""Raising a notification.

**Everything that notifies anyone goes through `notify()`.** One place that
writes the row and queues the email, so there is exactly one answer to "why did
this person get a message" and exactly one place to add rate limiting the day
it's needed.

The email is a *nudge*: it says something happened and where to look, and
carries no detail. Two reasons, and the second is the one that matters — a
task title in an inbox is a task title outside the access model, still sitting
there after the access is revoked.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, User

logger = logging.getLogger("app.services.notifications")


async def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None = None,
    link_path: str | None = None,
) -> Notification | None:
    """Write one notification and queue its email nudge.

    Never raises. A notification is a side effect of something that already
    happened and committed; failing the caller's request because the inbox row
    wouldn't write would undo real work for a cosmetic reason.
    """
    try:
        row = Notification(
            user_id=user_id, kind=kind, title=title, body=body, link_path=link_path
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
        from app.tasks.notifications import send_notification_email

        await send_notification_email.kiq(str(row.id))
    except Exception as exc:
        # The worker being unreachable must not cost the in-app notification,
        # which is the part people actually read.
        logger.warning("could not queue the email for notification %s: %s", row.id, exc)
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
