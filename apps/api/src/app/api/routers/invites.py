"""Taking up an invitation — by link, or from your own pending list.

Not under `/organisations/{id}`, deliberately: you are not a member yet, so
`CurrentOrg` would 404 you out of your own invitation.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import OrganisationMember, User
from app.models.organisation import STATUS_INVITED
from app.schemas.organisations import InvitePreview, OrganisationOut, PendingInviteOut
from app.services import invites as invites_service
from app.services import organisations as orgs_service

router = APIRouter(tags=["invites"])


@router.get("/invites/{token}", response_model=InvitePreview)
async def preview_invite(token: str, db: DbSession):
    """What this link is for — **without requiring a session**.

    Someone following an invitation usually has no account yet, so demanding
    one first would mean signing up for something you can't see. It returns the
    organisation's name and nothing about its contents.
    """
    member, org = await invites_service.by_token(db, token)
    inviter = (
        (
            await db.execute(select(User).where(User.id == member.invited_by_user_id))
        ).scalar_one_or_none()
        if member.invited_by_user_id
        else None
    )
    return InvitePreview(
        organisation_name=org.name,
        invited_email=member.invited_email,
        role=member.role,
        invited_by=(inviter.display_name or inviter.email) if inviter else None,
    )


@router.post("/invites/{token}/accept", response_model=OrganisationOut)
async def accept_invite(token: str, user: CurrentUser, db: DbSession):
    """Join via the link.

    Opening the link *is* the consent, so this activates immediately rather
    than adding another pending row. Note the consequence documented in
    `services/invites.py`: the token is the authority, so whoever holds it
    joins — regardless of the address it was addressed to.
    """
    member = await invites_service.accept_by_token(db, token, user)
    org = (
        await db.execute(
            select(orgs_service.Organisation).where(
                orgs_service.Organisation.id == member.organisation_id
            )
        )
    ).scalar_one()
    return OrganisationOut(
        id=str(org.id), name=org.name, slug=org.slug, role=member.role, created_at=org.created_at
    )


@router.get("/me/invites", response_model=list[PendingInviteOut])
async def my_invites(user: CurrentUser, db: DbSession):
    """Invitations waiting for you.

    This list is why an invitation never joins anyone automatically: being
    added to an organisation without asking is something anyone who knows your
    address could do to you.
    """
    out = []
    for member, org in await invites_service.list_pending_for_user(db, user):
        inviter = (
            (
                await db.execute(select(User).where(User.id == member.invited_by_user_id))
            ).scalar_one_or_none()
            if member.invited_by_user_id
            else None
        )
        out.append(
            PendingInviteOut(
                id=str(member.id),
                organisation_id=str(org.id),
                organisation_name=org.name,
                role=member.role,
                invited_by=(inviter.display_name or inviter.email) if inviter else None,
                created_at=member.created_at,
            )
        )
    return out


async def _my_pending(db, user: User, member_id: uuid.UUID) -> OrganisationMember:
    """One of *your* outstanding invitations, by id.

    Matches on account or on address, the same two ways `list_pending_for_user`
    does, so the row you can see in the list is always the row you can act on.
    """
    member = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.id == member_id,
                OrganisationMember.status == STATUS_INVITED,
                (OrganisationMember.user_id == user.id)
                | (
                    (OrganisationMember.user_id.is_(None))
                    & (OrganisationMember.invited_email == user.email)
                ),
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found"
        )
    return member


@router.post("/me/invites/{member_id}/accept", response_model=OrganisationOut)
async def accept_my_invite(member_id: uuid.UUID, user: CurrentUser, db: DbSession):
    member = await _my_pending(db, user, member_id)
    member = await orgs_service.accept(db, member, user)
    org = (
        await db.execute(
            select(orgs_service.Organisation).where(
                orgs_service.Organisation.id == member.organisation_id
            )
        )
    ).scalar_one()
    return OrganisationOut(
        id=str(org.id), name=org.name, slug=org.slug, role=member.role, created_at=org.created_at
    )


@router.delete("/me/invites/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def decline_my_invite(member_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Turn it down. Deletes the row, so the organisation can invite you again
    later — a decline is not a block."""
    member = await _my_pending(db, user, member_id)
    await orgs_service.decline(db, member)
