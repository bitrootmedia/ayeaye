"""The notification email nudge.

Runs in the worker so a slow SMTP server can't hold a request open. The message
carries no detail — just that something happened and where to look.
"""

import logging
import uuid

from sqlalchemy import select

from app.core import mailer
from app.core.config import settings
from app.db import SessionLocal
from app.models import Notification, User
from app.services import notification_channels as channels_service
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.notifications")


@broker.task
async def send_notification_email(notification_id: str) -> None:
    nid = uuid.UUID(notification_id)

    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(Notification, User)
                .join(User, User.id == Notification.user_id)
                .where(Notification.id == nid)
            )
        ).first()
        if row is None:
            # Its subject was deleted between the raise and the send.
            logger.info("notification %s vanished before its email", notification_id)
            return
        notification, user = row
        if notification.emailed:
            # A retry after a partial failure. The flag is the only thing
            # stopping the same nudge going twice.
            return
        if notification.read_at is not None:
            # They already saw it in the app. Don't email about something the
            # person has demonstrably read.
            logger.info("notification %s already read, not emailing", notification_id)
            return
        # Where this organisation's mail goes, which is the account address
        # unless they have said otherwise for this one. Resolved here rather
        # than stamped onto the notification when it was raised: an override
        # changed this morning should apply to a nudge queued last night,
        # and the queue is exactly where a stale copy would sit.
        to = await channels_service.email_for_organisation(
            db, user=user, organisation_id=notification.organisation_id
        )
        title = notification.title
        body = notification.body or ""
        link = f"{settings.site_url}{notification.link_path or ''}"

    if not to:
        # An account with no address at all. Nothing to do, and nothing worth
        # retrying — marking it emailed would be a lie, so it simply isn't.
        logger.info("notification %s has nowhere to go", notification_id)
        return

    paragraphs = [title]
    if body:
        paragraphs.append(body)
    paragraphs.append(f"See it here: {link}")
    text = "\n\n".join(paragraphs) + "\n"

    # Raises on failure so taskiq retries; `emailed` is only set once it has
    # actually gone.
    await mailer.send(to=to or "", subject=f"{settings.brand_name} — {title}", text=text)

    async with SessionLocal() as db:
        notification = (
            await db.execute(select(Notification).where(Notification.id == nid))
        ).scalar_one_or_none()
        if notification is not None:
            notification.emailed = True
            await db.commit()
