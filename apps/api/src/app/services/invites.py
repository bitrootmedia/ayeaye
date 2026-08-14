"""Inviting people by email — and the link that makes email optional.

Two ways in, one row (see `models/organisation.OrganisationMember`):

**The address.** Invite `sam@example.com` before Sam has an account and the row
waits with `user_id` NULL. When Sam registers, `bind_pending_for_user` attaches
the invitation to their new account in one UPDATE. It does **not** join them —
it appears in their pending list and they accept it. See the model docstring
for why an invitation never joins anyone automatically.

**The link.** Every invitation also mints a token, so the inviter can copy a URL
and paste it into chat. This is what lets the whole product run with no SMTP
configured at all (PLAN.md §2.4), which is the difference between "works after
you set up a mail provider" and "works".

The trade, stated plainly because it is a real one: **the link is the
authority.** Whoever opens it joins, whatever address they signed up with. That
is how every invite link works, and the mitigations are that it is single-use
(cleared on acceptance), revocable (delete the invitation and the token dies
with it), and 256 bits of urandom. If that trade is ever unacceptable, the
change is to require the accepting user's email to match `invited_email` — one
condition in `accept_by_token`, at the cost of the paste-into-Slack flow.
"""

import logging
import secrets

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Organisation, OrganisationMember, User
from app.models.organisation import STATUS_ACTIVE, STATUS_INVITED
from app.services import organisations as orgs_service
from app.services.organisations import OrgContext

logger = logging.getLogger("app.services.invites")


def new_token() -> str:
    """43 urlsafe characters, 256 bits. A guessable invite token is an open
    door to an organisation's entire contents."""
    return secrets.token_urlsafe(32)


def invite_url(token: str) -> str:
    return f"{settings.site_url}/invites/{token}"


async def create(
    db: AsyncSession, ctx: OrgContext, *, email: str, role: str, inviter: User
) -> OrganisationMember:
    """Invite one address at one role."""
    ctx.require(
        orgs_service.can_manage_members(ctx.role),
        "only an admin or owner can invite people",
    )
    ctx.require(
        orgs_service.can_grant_role(ctx.role, role),
        f"you cannot invite someone as {role}",
    )

    email = email.strip().lower()
    if not email:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="an invitation needs an email address",
        )

    # If they already have an account, attach the invitation to it now. That is
    # what puts it in their pending list at next sign-in without waiting for
    # them to click anything.
    existing_user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if existing_user is not None:
        already = (
            await db.execute(
                select(OrganisationMember).where(
                    OrganisationMember.organisation_id == ctx.organisation.id,
                    OrganisationMember.user_id == existing_user.id,
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    "they are already a member"
                    if already.status == STATUS_ACTIVE
                    else "they have already been invited"
                ),
            )

    member = OrganisationMember(
        organisation_id=ctx.organisation.id,
        user_id=existing_user.id if existing_user else None,
        role=role,
        status=STATUS_INVITED,
        invited_email=email,
        invited_by_user_id=inviter.id,
        invite_token=new_token(),
    )
    db.add(member)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # The partial unique index on (organisation, invited_email) WHERE
        # status='invited'. Two people inviting the same address at once.
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="they have already been invited",
        ) from exc
    await db.refresh(member)
    return member


async def by_token(db: AsyncSession, token: str) -> tuple[OrganisationMember, Organisation]:
    """Look an invitation up by its link. Deliberately unauthenticated — the
    recipient has to see what they're being asked to join *before* they create
    an account for it."""
    row = (
        await db.execute(
            select(OrganisationMember, Organisation)
            .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
            .where(
                OrganisationMember.invite_token == token,
                OrganisationMember.status == STATUS_INVITED,
            )
        )
    ).first()
    if row is None:
        # Covers expired, revoked and already-used alike. Distinguishing them
        # would confirm that a token was once valid.
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="that invitation link is no longer valid",
        )
    return row[0], row[1]


async def accept_by_token(db: AsyncSession, token: str, user: User) -> OrganisationMember:
    """Join by link. Opening it is the consent, so this activates immediately."""
    member, _org = await by_token(db, token)

    # They may already be in, through a different invitation or by having
    # created the organisation. Joining twice would violate the (org, user)
    # unique index, so treat it as the no-op it is.
    existing = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.organisation_id == member.organisation_id,
                OrganisationMember.user_id == user.id,
                OrganisationMember.id != member.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(member)
        await db.commit()
        return existing

    return await orgs_service.accept(db, member, user)


async def list_pending_for_user(
    db: AsyncSession, user: User
) -> list[tuple[OrganisationMember, Organisation]]:
    """Invitations waiting for this person, by account or by address.

    Both, because the two can differ: an invitation created before they
    registered is matched on the address until `bind_pending_for_user` attaches
    it, and that binding runs on their first request — this query is what makes
    the list right even if it somehow hasn't.
    """
    rows = (
        await db.execute(
            select(OrganisationMember, Organisation)
            .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
            .where(
                OrganisationMember.status == STATUS_INVITED,
                (OrganisationMember.user_id == user.id)
                | (
                    (OrganisationMember.user_id.is_(None))
                    & (OrganisationMember.invited_email == user.email)
                ),
            )
            .order_by(OrganisationMember.id)
        )
    ).all()
    return [(member, org) for member, org in rows]


async def bind_pending_for_user(db: AsyncSession, user: User) -> int:
    """Attach invitations addressed to this person's email to their new account.

    Runs on the user's first authenticated request (see `services.users`), so
    an invite-then-register lands in their pending list immediately rather than
    looking lost.

    Sets `user_id` only — status stays `invited`. Being invited is not being a
    member; see the model docstring.

    The NOT EXISTS is load-bearing: if they are already in that organisation,
    binding would violate the (organisation, user) partial unique index and
    fail their very first request with a 500.
    """
    if not user.email:
        return 0
    result = await db.execute(
        text(
            """
            UPDATE organisation_members AS m
               SET user_id = :uid
             WHERE m.invited_email = :email
               AND m.user_id IS NULL
               AND m.status = 'invited'
               AND NOT EXISTS (
                     SELECT 1
                       FROM organisation_members AS other
                      WHERE other.organisation_id = m.organisation_id
                        AND other.user_id = :uid
                   )
            """
        ),
        {"uid": user.id, "email": user.email},
    )
    await db.commit()
    return result.rowcount or 0
