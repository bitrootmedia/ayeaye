"""The invitation email.

Runs in the worker so a slow or unreachable SMTP server can't hold a request
open for its full timeout. The invite itself is already committed and its link
already returned to the inviter by the time this runs, which is the point:
**the email is a convenience, never the mechanism.** If it never arrives, the
inviter pastes the link.
"""

import logging
import uuid

from sqlalchemy import select

from app.core import mailer
from app.core.config import settings
from app.db import SessionLocal
from app.models import Organisation, OrganisationMember, User
from app.services.invites import invite_url
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.invites")


@broker.task
async def send_invite_email(member_id: str) -> None:
    nid = uuid.UUID(member_id)

    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(OrganisationMember, Organisation, User)
                .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
                .outerjoin(User, User.id == OrganisationMember.invited_by_user_id)
                .where(OrganisationMember.id == nid)
            )
        ).first()

    if row is None:
        # Revoked between the request and this task. Nothing to send.
        logger.info("invitation %s vanished before its email", member_id)
        return

    member, org, inviter = row
    if not member.invite_token or not member.invited_email:
        # Already accepted. Sending the link now would be sending a dead one.
        logger.info("invitation %s no longer pending, not emailing", member_id)
        return

    who = (inviter.display_name or inviter.email) if inviter else "Someone"
    text = (
        f"{who} invited you to join {org.name} on {settings.brand_name}.\n\n"
        f"{invite_url(member.invite_token)}\n\n"
        "If you don't have an account yet, that link will walk you through "
        "creating one.\n\n"
        "If you weren't expecting this, ignore it — nothing happens until you "
        "open the link.\n"
    )

    # Raises on failure so taskiq retries. The inviter already has the link, so
    # a permanent failure costs a convenience, not the invitation.
    await mailer.send(
        to=member.invited_email,
        subject=f"{who} invited you to {org.name}",
        text=text,
    )
