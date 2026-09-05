"""The "confirm this address" email for a per-organisation override.

In the worker for the same reason the invitation email is: a slow or
unreachable SMTP server must not hold a request open for its full timeout.

**The address is not in use until this is opened**, so a mail that never
arrives costs nothing but the change — notifications keep going to the
account address, which is exactly what they were doing before. With no SMTP
configured the mailer logs the message, link included, so a self-hoster can
still finish the job from `docker compose logs api`.
"""

import logging
import uuid

from sqlalchemy import select

from app.core import mailer
from app.core.config import settings
from app.db import SessionLocal
from app.models import Organisation, OrganisationMember
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.notification_emails")


def confirm_url(token: str) -> str:
    """A page in the SPA, not an API route.

    Same boundary the rest of this product keeps: browser-facing is React,
    the API is JSON. The page posts the token back and says what happened —
    which also means the link can be opened by somebody who is signed out,
    or signed in as somebody else, without either being a special case.
    """
    return f"{settings.site_url}/notification-email/{token}"


def confirm_email_body(*, organisation: str, link: str) -> str:
    return (
        f"Confirm this address to receive {organisation} notifications here.\n\n"
        f"{link}\n\n"
        "Until you do, they keep going to the address on the account.\n\n"
        "If you weren't expecting this, ignore it — nothing has changed, and "
        "nothing will be sent here.\n"
    )


@broker.task
async def send_notification_email_confirmation(member_id: str, token: str) -> None:
    mid = uuid.UUID(member_id)

    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(OrganisationMember, Organisation)
                .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
                .where(OrganisationMember.id == mid)
            )
        ).first()
        if row is None:
            logger.info("membership %s vanished before its confirmation email", member_id)
            return
        membership, organisation = row
        pending = membership.notification_email_pending
        name = organisation.name

    if not pending:
        # Cleared, or confirmed by another route, between the request and
        # this job. Nothing to confirm and nowhere to send it.
        return

    try:
        await mailer.send(
            to=pending,
            subject=f"Confirm this address for {name}",
            text=confirm_email_body(organisation=name, link=confirm_url(token)),
        )
    except Exception as exc:
        # Nothing to undo: the address isn't in use, and the person can ask
        # again from the same screen.
        logger.warning("could not send the confirmation for %s: %s", pending, exc)
